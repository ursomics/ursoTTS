#!/usr/bin/env python3
"""Check the Korean interface translation (run from the project folder).

  python scripts/check_i18n.py            # exit status 1 when anything is missing or inconsistent

It (a) imports ursotts.i18n, (b) scans ursotts/app.py with `ast` for every tr("...") key and
every literal passed to a widget helper (label, button, note, section, field, Choice, menu
labels, messagebox / filedialog calls, run/_set_status) and verifies a Korean entry exists,
(c) verifies every Korean value has the same {placeholders} as its key, (d) checks the regex
patterns used for engine/pipeline output, and (e) confirms English mode returns every key
unchanged.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ursotts import i18n                                  # noqa: E402
from ursotts.i18n_ko import KO, PATTERNS                  # noqa: E402

APP = ROOT / "ursotts" / "app.py"
SHARED = ROOT / "ursotts" / "shared.py"

HELPERS = {"label": 1, "button": 1, "note": 1, "section": 1, "field": 1}   # method -> index of the text argument
MENU_CALLS = {"add_command", "add_cascade", "add_radiobutton", "add_checkbutton"}
DIALOGS = {"showinfo", "showerror", "askyesno", "askyesnocancel"}
LETTERS = re.compile(r"[A-Za-z]{2,}")
# literals that are the same in every language (brand, symbols, file names, menu title shown in both languages)
# tr() calls whose key is looked up at run time; the possible values are checked elsewhere in this
# script (dialog / widget helpers' literals, TITLES, TAB_NAMES, shared.LANGS, the run() calls)
DYNAMIC_OK = {"title", "message", "text", "name", "busy_text", "kw['title']", "k",
              "TITLES[view].title()", "TITLES[v].title()", "TAB_NAMES[view]"}
# non-literal helper arguments that are known to be translated elsewhere or are not words
DYNAMIC_ARG_OK = {"text", "title", "label", "message", "msg", "name", "tips", "i18n.LANG_NAMES[code]"}   # incl. theme names, language names
LANGUAGE_NEUTRAL = {"Language / 언어", "ursomics.com", "GitHub"}


def const_str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def fstring_has_words(node) -> bool:
    return isinstance(node, ast.JoinedStr) and any(
        isinstance(v, ast.Constant) and LETTERS.search(v.value) for v in node.values)


def scan_app():
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    keys: dict[str, int] = {}          # key -> first line
    problems: list[str] = []

    def add(node, how):
        k = const_str(node)
        if k is not None:
            if k.strip() and k not in LANGUAGE_NEUTRAL:
                keys.setdefault(k, node.lineno)
        elif isinstance(node, (ast.Name, ast.Attribute, ast.Subscript, ast.BinOp, ast.IfExp)):
            src = ast.unparse(node)
            if "tr(" not in src and src not in DYNAMIC_ARG_OK:
                problems.append(f"app.py:{node.lineno}: non-literal text {src!r} passed to {how} (wrap its literals in tr())")
        elif fstring_has_words(node):
            problems.append(f"app.py:{node.lineno}: f-string with text passed to {how}; use tr() with {{placeholders}}")

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
        owner = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else ""
        if isinstance(f, ast.Name) and name == "tr" and node.args:
            k = const_str(node.args[0])
            if k is None:
                if ast.unparse(node.args[0]) not in DYNAMIC_OK:
                    problems.append(f"app.py:{node.lineno}: tr({ast.unparse(node.args[0])}) has a non-literal key (cannot be checked)")
            else:
                keys.setdefault(k, node.lineno)
        elif isinstance(f, ast.Attribute) and name in HELPERS and owner == "self" and len(node.args) > HELPERS[name]:
            add(node.args[HELPERS[name]], f"self.{name}()")
        elif isinstance(f, ast.Name) and name == "Choice" and len(node.args) > 1:
            add(node.args[1], "Choice()")
        elif isinstance(f, ast.Attribute) and name == "button" and owner == "self" and len(node.args) > 1:
            add(node.args[1], "self.button()")
        elif name in MENU_CALLS:
            for kw in node.keywords:
                if kw.arg == "label":
                    add(kw.value, name)
        elif owner == "messagebox" and name in DIALOGS:
            for a in node.args[:2]:
                add(a, f"messagebox.{name}()")
        elif owner == "filedialog":
            for kw in node.keywords:
                if kw.arg == "title":
                    add(kw.value, f"filedialog.{name}() title")
                elif kw.arg == "filetypes" and isinstance(kw.value, ast.List):
                    for item in kw.value.elts:
                        if isinstance(item, ast.Tuple) and item.elts:
                            add(item.elts[0], "filetypes")
        elif isinstance(f, ast.Attribute) and owner == "self" and name == "run" and len(node.args) > 1:
            add(node.args[1], "self.run()")
        elif isinstance(f, ast.Attribute) and name == "_set_status" and node.args:
            add(node.args[0], "_set_status()")
        # direct widget text="..." that bypasses the helpers
        for kw in node.keywords:
            if kw.arg == "text" and const_str(kw.value) and LETTERS.search(const_str(kw.value)):
                if name in {"Label", "heading", "configure"}:
                    problems.append(f"app.py:{node.lineno}: literal text= '{const_str(kw.value)}' is not wrapped in tr()")
    # names shown through lookups: view names / tab names
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id == "TITLES" and isinstance(node.value, ast.Dict):
                for v in node.value.values:
                    keys.setdefault(const_str(v).title(), v.lineno)
                    keys.setdefault(const_str(v), v.lineno)
            if node.targets[0].id == "TAB_NAMES" and isinstance(node.value, ast.Dict):
                for v in node.value.values:
                    if "." not in const_str(v):                  # script.txt is a file name
                        keys.setdefault(const_str(v), v.lineno)
    for node in ast.walk(ast.parse(SHARED.read_text(encoding="utf-8"))):       # LANGS: shown in the Language combobox
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "LANGS" and isinstance(node.value, ast.Dict):
            for k in node.value.keys:
                keys.setdefault(const_str(k), k.lineno)
    return keys, problems


def scan_user_errors():
    keys = {}
    tree = ast.parse(SHARED.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "UserError":
            k = const_str(node.args[0]) if node.args else None
            if k is None:
                keys.setdefault(f"<non-literal at shared.py:{node.lineno}>", node.lineno)
            else:
                keys.setdefault(k, node.lineno)
    return keys


def main() -> int:
    bad = 0
    keys, problems = scan_app()
    for k, line in scan_user_errors().items():
        keys.setdefault(k, line)
    for p in problems:
        print("PROBLEM", p)
        bad += 1
    missing = [(line, k) for k, line in keys.items() if k not in KO]
    for line, k in sorted(missing):
        print(f"MISSING  line {line}: {k!r}")
        bad += 1

    for k, v in KO.items():
        if i18n.placeholders(k) != i18n.placeholders(v):
            print(f"PLACEHOLDERS differ: {k!r} -> {v!r}  ({sorted(i18n.placeholders(k))} vs {sorted(i18n.placeholders(v))})")
            bad += 1
        if not v.strip():
            print(f"EMPTY Korean value for {k!r}")
            bad += 1
        if k.endswith("\n") != v.endswith("\n"):
            print(f"TRAILING newline differs: {k!r}")
            bad += 1

    for rx, template in PATTERNS:
        groups = set(rx.groupindex)
        if i18n.placeholders(template) - groups:
            print(f"PATTERN {rx.pattern!r}: template uses {sorted(i18n.placeholders(template) - groups)} not captured")
            bad += 1

    i18n.set_language("en")
    for k in keys:
        if i18n.tr(k) != k:
            print(f"EN not identity: {k!r}")
            bad += 1
    i18n.set_language("ko")
    for k in keys:
        if k in KO:
            ph = {n: "X" for n in i18n.placeholders(k) if n}
            try:
                i18n.tr(k, **ph)
            except Exception as e:                                     # tr must never raise
                print(f"tr() raised for {k!r}: {e}")
                bad += 1
    unused = sorted(k for k in KO if k not in keys)
    i18n.set_language("en")

    print(f"\n{len(keys)} keys used in app.py/shared.py, {len(KO)} Korean entries, {len(PATTERNS)} output patterns")
    if unused:
        print(f"info: {len(unused)} Korean entries are not referenced directly (fine for table-only or runtime keys)")
    print("OK" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
