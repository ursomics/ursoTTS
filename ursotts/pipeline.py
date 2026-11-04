"""Render scripts to narration: chunk cache, pauses, subtitles, WAV/MP3 export,
and batch runs that only redo scripts whose text or settings changed."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np

from . import audio
from .text import Pause, Speech, parse_script

SCRIPT_EXTS = {".txt", ".md"}
STATE_FILE = ".ursotts_state.json"


def _file_hash(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def missing_voices(cfg: dict) -> list[str]:
    """Voice samples listed in the config that don't exist (empty list = all good)."""
    if cfg["engine"] == "dummy":
        return []
    if not cfg["voices"]:
        return ["(no voices configured in config.yaml)"]
    return [v for v in cfg["voices"].values() if not v or not Path(v).exists()]


class Synthesizer:
    def __init__(self, cfg: dict, engine):
        self.cfg, self.engine = cfg, engine
        self.sr = engine.sample_rate
        self.cache = Path(cfg["cache_dir"])
        self.cache.mkdir(parents=True, exist_ok=True)
        self.voice_override: str | None = None  # one sample for every language (web UI)
        self.voice_overrides: dict[str, str] = {}  # per-language samples chosen in the web UI
        self._ref_hashes: dict[str, str] = {}
        self.hits = self.misses = 0

    def reference_for(self, lang: str) -> str | None:
        if self.engine.name == "dummy":
            return None
        if self.voice_override:
            ref = self.voice_override
        elif self.voice_overrides:
            o = self.voice_overrides
            ref = o.get(lang) or next((v for v in o.values() if v), None)
        else:
            v = self.cfg["voices"]
            ref = v.get(lang) or v.get(self.cfg["default_lang"]) or next(iter(v.values()), None)
        if ref and not Path(ref).exists():
            raise FileNotFoundError(f"Voice sample not found: {ref}")
        return ref

    def chunk_audio(self, sp: Speech) -> np.ndarray:
        ref = self.reference_for(sp.lang)
        if ref and ref not in self._ref_hashes:
            self._ref_hashes[ref] = _file_hash(ref)
        key = hashlib.sha256(json.dumps({
            "engine": self.engine.name, "settings": self.engine.settings(),
            "text": sp.text, "lang": sp.lang, "ref": self._ref_hashes.get(ref),
        }, sort_keys=True).encode()).hexdigest()[:24]
        path = self.cache / f"{key}.wav"
        if path.exists():  # unchanged line -> reuse, no GPU time
            self.hits += 1
            return audio.read_wav(path)[0]
        self.misses += 1
        wav = audio.trim(self.engine.synth(sp.text, sp.lang, ref), self.sr)
        audio.write_wav(path, wav, self.sr)
        return wav

    def render(self, items, label="", log=print):
        parts, cues, t = [], [], 0.0
        n = sum(isinstance(i, Speech) for i in items)
        k = 0
        for item in items:
            if isinstance(item, Pause):
                parts.append(audio.silence(item.seconds, self.sr))
                t += item.seconds
                continue
            k += 1
            log(f"  {label} [{k}/{n}] ({item.lang}) {item.text[:60]}")
            wav = self.chunk_audio(item)
            dur = len(wav) / self.sr
            parts.append(wav)
            # one subtitle cue per sentence, timed by share of characters
            total = sum(len(s) for s in item.sentences) or 1
            start = t
            for s in item.sentences:
                end = start + dur * len(s) / total
                cues.append((start, end, s))
                start = end
            t += dur
        wav = np.concatenate(parts) if parts else np.zeros(0, np.float32)
        return wav, cues


def parse_file(path: Path, cfg: dict):
    return parse_script(
        path.read_text(encoding="utf-8"), default_lang=cfg["default_lang"],
        lang_mode=cfg["lang_mode"], max_chars=cfg["max_chars"],
        sentence_pause=cfg["pauses"]["sentence"], paragraph_pause=cfg["pauses"]["paragraph"],
        pronunciations=cfg["pronunciation_table"], spell_acronyms=cfg["spell_acronyms"])


def process_file(path: Path, out_dir: Path, synth: Synthesizer, cfg: dict, log=print) -> dict:
    items, _ = parse_file(path, cfg)
    t0 = time.time()
    wav, cues = synth.render(items, label=path.stem, log=log)
    wav = audio.peak_normalize(wav, cfg["output"]["normalize_db"])
    out_dir.mkdir(parents=True, exist_ok=True)
    wav_path = out_dir / f"{path.stem}.wav"
    audio.write_wav(wav_path, wav, synth.sr)
    if cfg["output"]["srt"]:
        audio.write_srt(out_dir / f"{path.stem}.srt", cues)
    mp3 = False
    if cfg["output"]["mp3"]:
        mp3 = audio.to_mp3(wav_path, out_dir / f"{path.stem}.mp3")
        if not mp3:
            log("  (ffmpeg not found - skipped MP3)")
    return {"file": path.name, "seconds": round(len(wav) / synth.sr, 1),
            "render_time": round(time.time() - t0, 1), "mp3": mp3}


# ---------------------------------------------------------------- batch runs

def settings_fingerprint(cfg: dict) -> str:
    """Everything in the config that changes the audio, plus the voice files' contents."""
    keys = ["engine", "multilingual", "default_lang", "lang_mode", "max_chars",
            "pauses", "generation", "output", "pronunciation_table", "spell_acronyms"]
    data = {k: cfg.get(k) for k in keys}
    data["voices"] = {lang: (_file_hash(p) if p and Path(p).exists() else None)
                      for lang, p in cfg["voices"].items()}
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def plan_batch(cfg: dict, src: Path, out: Path, force: bool = False):
    """Return (all_files, files_to_render, keys). A script is up to date only if its
    text AND the settings are unchanged since its last successful render."""
    files = sorted(p for p in (src.iterdir() if src.is_dir() else [src])
                   if p.suffix.lower() in SCRIPT_EXTS)
    fp = settings_fingerprint(cfg)
    keys = {p.name: hashlib.sha256(p.read_bytes() + fp.encode()).hexdigest() for p in files}
    try:
        state = json.loads((out / STATE_FILE).read_text())
    except (OSError, ValueError):
        state = {}
    todo = [p for p in files if force or state.get(p.name) != keys[p.name]
            or not (out / f"{p.stem}.wav").exists()]
    return files, todo, keys


def run_batch(cfg: dict, synth: Synthesizer, todo: list[Path], out: Path,
              keys: dict, log=print) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / STATE_FILE
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        state = {}
    results = []
    for i, p in enumerate(todo, 1):
        log(f"\n== [{i}/{len(todo)}] {p.name}")
        try:
            r = process_file(p, out, synth, cfg, log=log)
            log(f"  -> {r['seconds']} s of audio in {r['render_time']} s")
            state[p.name] = keys[p.name]
            state_path.write_text(json.dumps(state, indent=2))
        except Exception as e:  # keep the batch going
            r = {"file": p.name, "error": str(e)}
            log(f"  !! failed: {e}")
        results.append(r)
    (out / "batch_report.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    return results
