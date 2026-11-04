"""Config loading with defaults; paths are resolved relative to the config file."""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

DEFAULTS = {
    "engine": "chatterbox",
    "device": "auto",
    "multilingual": True,
    "voices": {},
    "default_lang": "en",
    "lang_mode": "auto",
    "max_chars": 250,
    "pauses": {"sentence": 0.25, "paragraph": 0.7},
    "generation": {"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8, "seed": 42},
    "pronunciations": None,
    "spell_acronyms": True,
    "output": {"mp3": True, "srt": True, "normalize_db": -1.0},
    "cache_dir": ".cache",
}


def _merge(base: dict, over: dict) -> dict:
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config(path: str | None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    root = Path.cwd()
    if path:
        p = Path(path)
        cfg = _merge(cfg, yaml.safe_load(p.read_text(encoding="utf-8")) or {})
        root = p.resolve().parent

    def resolve(x):
        return str((root / x).resolve()) if x else None

    cfg["voices"] = {k: resolve(v) for k, v in (cfg["voices"] or {}).items()}
    cfg["cache_dir"] = resolve(cfg["cache_dir"])
    table = {}
    cfg["pronunciations_path"] = resolve(cfg["pronunciations"])
    if cfg["pronunciations_path"]:
        pp = Path(cfg["pronunciations_path"])
        if pp.exists():
            table = yaml.safe_load(pp.read_text(encoding="utf-8")) or {}
    cfg["pronunciation_table"] = table
    return cfg
