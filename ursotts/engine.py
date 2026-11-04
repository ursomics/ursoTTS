"""TTS engine backends. Add a new engine by subclassing BaseEngine."""
from __future__ import annotations

import numpy as np


class BaseEngine:
    name = "base"
    sample_rate = 24000

    def synth(self, text: str, lang: str, ref_wav: str | None) -> np.ndarray:
        raise NotImplementedError

    def settings(self) -> dict:
        """Anything that changes the output; used for the cache key."""
        return {}

    def update(self, **generation) -> None:
        """Change generation settings without reloading the model (used by the web UI)."""


class DummyEngine(BaseEngine):
    """Fake engine (soft tone, length ~ text) for testing scripts, pauses and
    subtitles without a GPU or model download."""
    name = "dummy"

    def synth(self, text, lang, ref_wav):
        sr = self.sample_rate
        n = int(sr * max(0.4, 0.06 * len(text)))
        t = np.arange(n) / sr
        f = 220.0 if lang == "en" else 330.0
        env = np.minimum(1.0, np.minimum(t, t[::-1]) * 20)
        return (0.3 * np.sin(2 * np.pi * f * t) * env).astype(np.float32)


class ChatterboxEngine(BaseEngine):
    """Resemble AI Chatterbox (MIT). Multilingual model covers English + Korean."""
    name = "chatterbox"

    def __init__(self, device="auto", multilingual=True, exaggeration=0.5,
                 cfg_weight=0.5, temperature=0.8, seed=None):
        import torch

        if device == "auto":
            device = ("cuda" if torch.cuda.is_available()
                      else "mps" if torch.backends.mps.is_available() else "cpu")
        if device == "mps":  # weights were saved on CUDA; remap them for Apple Silicon
            _load = torch.load
            torch.load = lambda *a, **k: _load(*a, **{"map_location": torch.device("mps"), **k})

        self.torch, self.device, self.multilingual = torch, device, multilingual
        self.params = dict(exaggeration=exaggeration, cfg_weight=cfg_weight,
                           temperature=temperature)
        self.seed = seed

        if multilingual:
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
            self.model = ChatterboxMultilingualTTS.from_pretrained(device=device)
        else:
            from chatterbox.tts import ChatterboxTTS
            self.model = ChatterboxTTS.from_pretrained(device=device)
        self.sample_rate = self.model.sr
        # The voice is analyzed once per sample (and expressiveness) and reused for
        # every chunk; passing the sample on each call made the model re-analyze it
        # for every sentence, which is very slow on Apple Silicon.
        self._default_conds = getattr(self.model, "conds", None)
        self._cond_key = None
        print(f"[ursotts] Chatterbox loaded on {device} "
              f"({'multilingual' if multilingual else 'English'})")

    def _use_voice(self, ref_wav) -> bool:
        """Prepare the voice once and keep it. Returns True when it is ready to reuse."""
        import os
        import time
        if not hasattr(self.model, "prepare_conditionals"):
            return False
        if not ref_wav:
            if self._cond_key is not None and self._default_conds is not None:
                self.model.conds = self._default_conds  # back to the built-in voice
            self._cond_key = None
            return True
        key = (os.path.abspath(ref_wav), os.path.getmtime(ref_wav), self.params["exaggeration"])
        if key != self._cond_key:
            t0 = time.time()
            self.model.prepare_conditionals(ref_wav, exaggeration=self.params["exaggeration"])
            self._cond_key = key
            print(f"[ursotts] voice prepared from {os.path.basename(ref_wav)} "
                  f"in {time.time() - t0:.1f} s")
        return True

    def synth(self, text, lang, ref_wav):
        import time
        if self.seed is not None:
            self.torch.manual_seed(self.seed)
        kwargs = dict(self.params)
        if not self._use_voice(ref_wav) and ref_wav:
            kwargs["audio_prompt_path"] = ref_wav  # older Chatterbox: pass the sample
        if self.multilingual:
            kwargs["language_id"] = lang
        t0 = time.time()
        wav = self.model.generate(text, **kwargs)
        out = wav.squeeze().detach().cpu().numpy().astype(np.float32)
        secs, took = len(out) / self.sample_rate, time.time() - t0
        print(f"[ursotts] {lang}: {len(text)} characters -> {secs:.1f} s of audio in {took:.1f} s")
        if secs > 4 + 0.15 * len(text):
            print("[ursotts] warning: this chunk is unusually long for its text. The voice "
                  "sample may contain silence, music or noise; try a cleaner sample.")
        return out

    def settings(self):
        return {"multilingual": self.multilingual, "seed": self.seed, **self.params}

    def update(self, **generation):
        for k in ("exaggeration", "cfg_weight", "temperature"):
            if k in generation:
                self.params[k] = float(generation[k])
        if "seed" in generation:
            self.seed = generation["seed"]


def make_engine(cfg: dict) -> BaseEngine:
    name = cfg["engine"]
    if name == "dummy":
        return DummyEngine()
    if name == "chatterbox":
        g = cfg["generation"]
        return ChatterboxEngine(device=cfg["device"], multilingual=cfg["multilingual"],
                                exaggeration=g["exaggeration"], cfg_weight=g["cfg_weight"],
                                temperature=g["temperature"], seed=g.get("seed"))
    raise ValueError(f"Unknown engine '{name}' (use 'chatterbox' or 'dummy')")
