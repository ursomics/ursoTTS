"""Logic shared by the web UI and the desktop app (no Gradio or Tkinter here)."""
from __future__ import annotations

import re
from pathlib import Path

from . import audio
from .text import KO_LETTERS, LETTER_NAMES, number_words


class UserError(Exception):
    """A problem the user can fix; each front end shows it in its own way.

    `message` is the English text and may contain {placeholders} filled from `fmt`;
    str(error) is the finished English sentence. The desktop app translates
    (message, fmt) through i18n.tr_exc."""

    def __init__(self, message: str, **fmt):
        super().__init__(message.format(**fmt) if fmt else message)
        self.key, self.fmt = message, fmt


LANGS = {"Auto (English + Korean)": "auto", "English": "en", "Korean": "ko"}

MAX_CANDIDATES = 6


def letters_notation(letters: str) -> str:
    """'DNA' -> 'dee.en.AY' (syllable notation, stress on the last letter)."""
    names = [LETTER_NAMES[c] for c in letters.upper()]
    names[-1] = names[-1].upper()
    return ".".join(names)


def _dot_letters(t: str) -> str:
    """'PD-L1' -> 'P.D.L. one', 'RNA-seq' -> 'R.N.A. seek', 'TCRs' -> 'T.C.R.s'."""
    t = re.sub(r"(?<=[A-Z])-(?=[A-Z0-9])", "", t)
    t = re.sub(r"\b([A-Z]{1,6})(s?)(\d*)\b",
               lambda m: "".join(c + "." for c in m.group(1)) + m.group(2)
               + (" " + number_words(m.group(3)) if m.group(3) else ""), t)
    return re.sub(r"-seq\b", " seek", t)


def _hangul_letters(t: str) -> str:
    """'PD-L1' -> '피디엘원', 'TCRs' -> '티씨알스': capital letters (and the digits and
    plural s attached to them) as Korean letter names. Ordinary words stay as typed."""
    ko_digits = dict(zip("0123456789", ["제로", "원", "투", "쓰리", "포", "파이브", "식스",
                                        "세븐", "에잇", "나인"]))
    t = re.sub(r"(?<=[A-Z])-(?=[A-Z0-9])", "", t)
    t = re.sub(r"-seq\b", " 시퀀싱", t)

    def conv(m):
        caps, plural, digits = m.group(1), m.group(2), m.group(3)
        return ("".join(KO_LETTERS[c] for c in caps) + ("스" if plural else "")
                + "".join(ko_digits[d] for d in digits))
    return re.sub(r"(?<![A-Za-z])([A-Z]{2,}|[A-Z](?=\d))(s?)(\d*)(?![a-z])", conv, t)


AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}
SKIP_DIRS = {".venv", "venv", ".git", ".cache", "__pycache__", "node_modules", "docs", "ursotts"}


def prepare_sample(path: str, out_dir: Path) -> str:
    """Make any recording or upload safe for the voice model: mono, 24 kHz WAV,
    silence trimmed, volume evened out, at most 20 seconds. Browser recordings and compressed files (m4a, mp3, webm)
    can otherwise make the model stall without an error."""
    import hashlib
    import subprocess
    src = Path(path)
    if not src.exists():
        raise UserError("The voice sample could not be read. Please record or upload it again.")
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(src.read_bytes()).hexdigest()[:12]
    dst = out_dir / f"sample_{digest}_v2.wav"
    if not dst.exists():
        ff = audio.find_ffmpeg()
        if ff:
            try:
                # mono 24 kHz; trim silence at both ends; even out the volume; max 20 s
                clean = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.2,"
                         "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.2,"
                         "areverse,loudnorm=I=-20:TP=-2")
                subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src), "-af", clean,
                                "-ac", "1", "-ar", "24000", "-t", "20", str(dst)],
                               check=True, timeout=60)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                raise UserError("This audio file could not be converted. Try a WAV or MP3 file.")
        elif src.suffix.lower() in {".wav", ".flac"}:
            wav, sr = audio.read_wav(src)
            audio.write_wav(dst, wav[: sr * 30], sr)
        else:
            raise UserError("Install ffmpeg to use this file type, or upload a WAV file.")
    seconds = len(audio.read_wav(dst)[0]) / audio.read_wav(dst)[1]
    if seconds < 3:
        raise UserError("The sample is only {seconds:.1f} s long. Record 10–30 seconds of speech.",
                         seconds=seconds)
    return str(dst)


def list_folders(root: Path, need_scripts: bool = False, depth: int = 3) -> list[str]:
    """Folders under the project (relative paths), skipping hidden and system folders.
    With need_scripts=True, only folders that contain .txt or .md scripts."""
    found = []
    def walk(d: Path, level: int):
        for c in sorted(d.iterdir()) if d.is_dir() else []:
            if not c.is_dir() or c.name.startswith(".") or c.name in SKIP_DIRS:
                continue
            rel = c.relative_to(root).as_posix()
            has = any(f.suffix.lower() in {".txt", ".md"} for f in c.iterdir() if f.is_file())
            if not need_scripts or has:
                found.append(rel)
            if level < depth:
                walk(c, level + 1)
    walk(root, 1)
    return found


def suggest_spellings(term: str, cfg: dict, lang: str = "en") -> list[str]:
    """A few versions worth comparing by ear, starting with the project's default style."""
    t = term.strip()
    if not t:
        return []
    if lang == "ko":
        out = [_hangul_letters(t), t]
    else:
        m = re.fullmatch(r"([A-Z]{2,6})(\d{0,3})", t)
        num = (" " + number_words(m.group(2))) if m and m.group(2) else ""
        if m and len(m.group(1)) >= 3 and m.group(1)[1] in "AEIOU":
            # gene-name rule: 2nd letter a vowel -> try it as a word first, letters second
            out = [m.group(1).capitalize() + num, _dot_letters(t), t]
        else:
            out = [_dot_letters(t), t]
        if m:
            out.append(letters_notation(m.group(1)) + num.upper())
        elif t.isalpha() and t[1:].islower():  # an ordinary word such as Ursomics
            out.append(re.sub(r"(?<=[^aeiou\W])o(?=[^aeiou\W])", ".OH.", t.lower(),
                              count=1).strip("."))
    seen, uniq = set(), []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq[:MAX_CANDIDATES]


YAML_PLAIN = re.compile(r"^[A-Za-z0-9][\w.+\-]*( [\w.+\-]+)*$")


def _yaml_scalar(text: str) -> str:
    return text if YAML_PLAIN.match(text) and text.lower() not in {"yes", "no", "on", "off", "true", "false", "null"} \
        else '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def upsert_pronunciation(path: Path, lang: str, term: str, say: str, like: str = "") -> None:
    """Add or replace one entry in pronunciations.yaml, keeping every comment."""
    value = _yaml_scalar(say)
    if like.strip():
        value = "{say: %s, like: %s}" % (_yaml_scalar(say), '"' + like.strip().replace('"', "'") + '"')
    entry = f"  {_yaml_scalar(term)}: {value}"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    head = next((i for i, l in enumerate(lines) if re.match(rf"^{lang}:\s*(\{{\s*\}})?\s*(#.*)?$", l)), None)
    if head is None:
        lines += ["", f"{lang}:", entry]
    else:
        lines[head] = f"{lang}:"
        end = head + 1
        while end < len(lines) and (lines[end].startswith(" ") or not lines[end].strip()):
            end += 1
        key_re = re.compile(rf"^\s+[\"']?{re.escape(term)}[\"']?\s*:")
        hit = next((i for i in range(head + 1, end) if key_re.match(lines[i])), None)
        if hit is not None:
            lines[hit] = entry
        else:
            last = max((i for i in range(head + 1, end) if lines[i].strip()), default=head)
            lines.insert(last + 1, entry)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_pronunciations(path: Path) -> dict:
    """{'en': {term: (say, like)}, 'ko': {...}} from pronunciations.yaml (empty when missing)."""
    import yaml
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {"en": {}, "ko": {}}
    out = {}
    for lang in ("en", "ko"):
        rows = {}
        for term, v in (raw.get(lang) or {}).items():
            if isinstance(v, dict):
                rows[str(term)] = (str(v.get("say", "")), str(v.get("like", "") or ""))
            else:
                rows[str(term)] = (str(v), "")
        out[lang] = rows
    return out


def remove_pronunciation(path: Path, lang: str, term: str) -> bool:
    """Delete one entry from pronunciations.yaml, keeping every comment. True if a line was removed."""
    path = Path(path)
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    head = next((i for i, l in enumerate(lines) if re.match(rf"^{lang}:\s*(#.*)?$", l)), None)
    if head is None:
        return False
    end = head + 1
    while end < len(lines) and (lines[end].startswith(" ") or not lines[end].strip()):
        end += 1
    key_re = re.compile(rf"^\s+[\"']?{re.escape(term)}[\"']?\s*:")
    hit = next((i for i in range(head + 1, end) if key_re.match(lines[i])), None)
    if hit is None:
        return False
    del lines[hit]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


# ursoTTS brand palette (see docs/brand/color_palette.png)
CORAL, DEEP_CORAL, SOFT_CORAL = "#D97757", "#C4623F", "#F0C9B8"
INK, WHITE, CREAM = "#1B1B1B", "#FFFFFF", "#F6EFE6"
# derived neutrals for borders and secondary text
LINE_LIGHT, MUTED_LIGHT = "#E6D9C8", "#6E6259"
SURFACE_DARK, LINE_DARK, MUTED_DARK = "#262220", "#3A332F", "#BFB3A8"

