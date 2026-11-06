"""Interface language for the desktop app (English or Korean).

English is the source text: `tr("Some text")` returns the key itself in English, and
also when Korean has no entry for it, so a missing translation never raises and never
breaks the window. Dynamic text uses str.format placeholders:

    tr("Folder not found:\\n{path}", path=p)

Which language is used (first match wins):
  1. the choice saved from the View > Language menu (key "ui_lang" in the layout file),
  2. the URSOTTS_LANG environment variable ("en" or "ko"),
  3. the language bundled with the installer (ursotts/assets/default_lang.txt),
  4. English.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

LANGS_UI = ("en", "ko")
LANG_NAMES = {"en": "English", "ko": "한국어"}
DEFAULT_LANG_FILE = Path(__file__).parent / "assets" / "default_lang.txt"

_lang = "en"


def _valid(code) -> str | None:
    code = str(code or "").strip().lower()
    return code if code in LANGS_UI else None


def bundled_default() -> str | None:
    """The language the installer was built for (a one-word text file), or None."""
    try:
        return _valid(DEFAULT_LANG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def resolve_language(explicit: str | None = None) -> str:
    """explicit choice > URSOTTS_LANG > bundled default > English."""
    return (_valid(explicit) or _valid(os.environ.get("URSOTTS_LANG"))
            or bundled_default() or "en")


def set_language(code: str) -> str:
    global _lang
    _lang = _valid(code) or "en"
    return _lang


def get_language() -> str:
    return _lang


def _ko() -> dict:
    from .i18n_ko import KO
    return KO


def tr(s: str, **fmt) -> str:
    """Translate `s` (an English key). Never raises; unknown keys come back unchanged."""
    out = s
    if _lang == "ko":
        out = _ko().get(s, s)
    if fmt:
        try:
            out = out.format(**fmt)
        except (KeyError, IndexError, ValueError):
            try:
                out = s.format(**fmt)
            except (KeyError, IndexError, ValueError):
                out = s
    return out


def both(s: str, **fmt) -> str:
    """English text and its Korean text on two lines (for a dialog that must be
    understood in either language, such as the language switch)."""
    en = s.format(**fmt) if fmt else s
    ko = _ko().get(s, s)
    ko = ko.format(**fmt) if fmt else ko
    return en if en == ko else f"{en}\n{ko}"


def tr_line(line: str) -> str:
    """Translate one line of program output (progress and error messages whose text
    comes from the engine or the pipeline). Exact keys first, then the patterns in
    i18n_ko.PATTERNS. Anything unrecognised is returned unchanged."""
    if _lang != "ko" or not line.strip():
        return line
    ko = _ko()
    if line in ko:
        return ko[line]
    from .i18n_ko import PATTERNS
    for rx, template in PATTERNS:
        m = rx.fullmatch(line)
        if m:
            try:
                values = {k: (tr_line(v) if k == "err" else v) for k, v in m.groupdict().items()}
                return template.format(**values)
            except (KeyError, IndexError, ValueError):
                return line
    return line


def tr_exc(e: BaseException) -> str:
    """The message of an exception for the user. UserError carries its English key and
    values (see shared.UserError), so it translates exactly; others go through tr_line."""
    key = getattr(e, "key", None)
    if key:
        return tr(key, **getattr(e, "fmt", {}))
    return tr_line(str(e))


def placeholders(s: str) -> set[str]:
    """Names of the {placeholders} in a format string (used by scripts/check_i18n.py)."""
    return set(re.findall(r"\{(\w*)(?:[!:][^}]*)?\}", s))
