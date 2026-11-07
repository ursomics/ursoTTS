"""ursoTTS desktop app: a native Tkinter window styled like VS Code Dark.

The same features as the web UI (Speak, Pronunciation, Batch), in a desktop
layout: activity bar, resizable sidebar, editor tabs, a collapsible OUTPUT
panel with the live log, and a status bar. The web UI stays available as
`ursotts ui`; both share their logic through `shared.py` and `pipeline.py`.
"""
from __future__ import annotations

import contextlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog as _filedialog, font as tkfont, messagebox as _messagebox, ttk

import yaml

from . import __version__, audio, i18n
from .pipeline import Synthesizer, missing_voices, plan_batch, process_file, run_batch
from .shared import (AUDIO_EXTS, CORAL, DEEP_CORAL, LANGS, MAX_CANDIDATES, UserError,
                     prepare_sample, suggest_spellings, upsert_pronunciation)
from .i18n import tr, tr_exc, tr_line
from .text import Speech, render_say


class messagebox:
    """tkinter.messagebox whose titles and messages go through tr() (English stays as is)."""

    @staticmethod
    def showinfo(title, message, **kw):
        return _messagebox.showinfo(tr(title), tr(message), **kw)

    @staticmethod
    def showerror(title, message, **kw):
        return _messagebox.showerror(tr(title), tr(message), **kw)

    @staticmethod
    def askyesno(title, message, **kw):
        return _messagebox.askyesno(tr(title), tr(message), **kw)

    @staticmethod
    def askyesnocancel(title, message, **kw):
        return _messagebox.askyesnocancel(tr(title), tr(message), **kw)


class filedialog:
    """tkinter.filedialog with translated titles and file-type names."""

    @staticmethod
    def _kw(kw):
        if "title" in kw:
            kw["title"] = tr(kw["title"])
        if "filetypes" in kw:
            kw["filetypes"] = [(tr(name), pat) for name, pat in kw["filetypes"]]
        return kw

    @staticmethod
    def askopenfilename(**kw):
        return _filedialog.askopenfilename(**filedialog._kw(kw))

    @staticmethod
    def asksaveasfilename(**kw):
        return _filedialog.asksaveasfilename(**filedialog._kw(kw))

    @staticmethod
    def askdirectory(**kw):
        return _filedialog.askdirectory(**filedialog._kw(kw))

# Color themes, VS Code style. The ursoTTS coral (status bar, primary buttons) stays in every theme.
KEYS = ("BG SIDEBAR ACTIVITY TABBAR TAB_IDLE PANEL BORDER INPUT FG FG_DIM FG_BRIGHT SELECT HOVER "
        "EDITOR_FG CARET GUTTER COMMENT DIRECTIVE PAUSE BUTTON BUTTON_HOVER SCROLL SCROLL_HOVER "
        "TRANSCRIPT ERROR CHECK_EDGE CHECK_HOVER ACCENT_OFF").split()
THEMES = {
    "Dark+": dict(BG="#1E1E1E", SIDEBAR="#252526", ACTIVITY="#333333", TABBAR="#252526", TAB_IDLE="#2D2D2D",
                  PANEL="#1E1E1E", BORDER="#3C3C3C", INPUT="#3C3C3C", FG="#CCCCCC", FG_DIM="#8B8B8B",
                  FG_BRIGHT="#FFFFFF", SELECT="#264F78", HOVER="#2A2D2E", EDITOR_FG="#D4D4D4", CARET="#AEAFAD",
                  GUTTER="#858585", COMMENT="#6A9955", DIRECTIVE="#C586C0", PAUSE="#4EC9B0", BUTTON="#3A3D41",
                  BUTTON_HOVER="#45494E", SCROLL="#424242", SCROLL_HOVER="#4F4F4F", TRANSCRIPT="#181818",
                  ERROR="#F48771", CHECK_EDGE="#6B6B6B", CHECK_HOVER="#9D9D9D", ACCENT_OFF="#5A3A30"),
    "Light+": dict(BG="#FFFFFF", SIDEBAR="#F3F3F3", ACTIVITY="#2C2C2C", TABBAR="#F3F3F3", TAB_IDLE="#ECECEC",
                   PANEL="#FFFFFF", BORDER="#D4D4D4", INPUT="#FFFFFF", FG="#333333", FG_DIM="#6F6F6F",
                   FG_BRIGHT="#000000", SELECT="#ADD6FF", HOVER="#E8E8E8", EDITOR_FG="#1E1E1E", CARET="#000000",
                   GUTTER="#237893", COMMENT="#008000", DIRECTIVE="#AF00DB", PAUSE="#098658", BUTTON="#E1E1E1",
                   BUTTON_HOVER="#D0D0D0", SCROLL="#C1C1C1", SCROLL_HOVER="#A8A8A8", TRANSCRIPT="#F8F8F8",
                   ERROR="#CD3131", CHECK_EDGE="#919191", CHECK_HOVER="#6F6F6F", ACCENT_OFF="#EDBFAD"),
    "ursoTTS Cream": dict(BG="#FBF7F1", SIDEBAR="#F6EFE6", ACTIVITY="#1B1B1B", TABBAR="#F6EFE6",
                          TAB_IDLE="#EFE5D8", PANEL="#FBF7F1", BORDER="#E6D9C8", INPUT="#FFFFFF", FG="#1B1B1B",
                          FG_DIM="#6E6259", FG_BRIGHT="#000000", SELECT="#F0C9B8", HOVER="#EFE5D8",
                          EDITOR_FG="#1B1B1B", CARET="#C4623F", GUTTER="#B5A898", COMMENT="#8A7F75",
                          DIRECTIVE="#C4623F", PAUSE="#2E7D6B", BUTTON="#EFE5D8", BUTTON_HOVER="#E6D9C8",
                          SCROLL="#D9CBB8", SCROLL_HOVER="#C9B9A4", TRANSCRIPT="#F6EFE6", ERROR="#B3261E",
                          CHECK_EDGE="#B5A898", CHECK_HOVER="#6E6259", ACCENT_OFF="#EDC4B1"),
    "Monokai": dict(BG="#272822", SIDEBAR="#1E1F1C", ACTIVITY="#272822", TABBAR="#1E1F1C", TAB_IDLE="#34352F",
                    PANEL="#272822", BORDER="#414339", INPUT="#414339", FG="#F8F8F2", FG_DIM="#90908A",
                    FG_BRIGHT="#FFFFFF", SELECT="#49483E", HOVER="#3E3D32", EDITOR_FG="#F8F8F2", CARET="#F8F8F0",
                    GUTTER="#90908A", COMMENT="#88846F", DIRECTIVE="#F92672", PAUSE="#A6E22E", BUTTON="#414339",
                    BUTTON_HOVER="#4E5044", SCROLL="#5A5B52", SCROLL_HOVER="#6A6B61", TRANSCRIPT="#1E1F1C",
                    ERROR="#F92672", CHECK_EDGE="#75715E", CHECK_HOVER="#A59F85", ACCENT_OFF="#5A3A30"),
    "Solarized Dark": dict(BG="#002B36", SIDEBAR="#00212B", ACTIVITY="#003847", TABBAR="#00212B",
                           TAB_IDLE="#004052", PANEL="#002B36", BORDER="#2B4C54", INPUT="#073642", FG="#93A1A1",
                           FG_DIM="#657B83", FG_BRIGHT="#FDF6E3", SELECT="#274642", HOVER="#073642",
                           EDITOR_FG="#93A1A1", CARET="#D30102", GUTTER="#586E75", COMMENT="#586E75",
                           DIRECTIVE="#D33682", PAUSE="#2AA198", BUTTON="#073642", BUTTON_HOVER="#0B4A5A",
                           SCROLL="#2B4C54", SCROLL_HOVER="#3A5F68", TRANSCRIPT="#00212B", ERROR="#DC322F",
                           CHECK_EDGE="#586E75", CHECK_HOVER="#93A1A1", ACCENT_OFF="#4A3A33"),
    "Solarized Light": dict(BG="#FDF6E3", SIDEBAR="#EEE8D5", ACTIVITY="#073642", TABBAR="#EEE8D5",
                            TAB_IDLE="#E6DFCB", PANEL="#FDF6E3", BORDER="#DDD6C1", INPUT="#FFFBEF", FG="#586E75",
                            FG_DIM="#93A1A1", FG_BRIGHT="#073642", SELECT="#D3CBB7", HOVER="#E6DFCB",
                            EDITOR_FG="#586E75", CARET="#657B83", GUTTER="#93A1A1", COMMENT="#93A1A1",
                            DIRECTIVE="#D33682", PAUSE="#2AA198", BUTTON="#E6DFCB", BUTTON_HOVER="#DDD6C1",
                            SCROLL="#C9C2AD", SCROLL_HOVER="#B5AE98", TRANSCRIPT="#F5EFDC", ERROR="#DC322F",
                            CHECK_EDGE="#93A1A1", CHECK_HOVER="#657B83", ACCENT_OFF="#EDC4B1"),
    "High Contrast": dict(BG="#000000", SIDEBAR="#000000", ACTIVITY="#000000", TABBAR="#000000",
                          TAB_IDLE="#000000", PANEL="#000000", BORDER="#6FC3DF", INPUT="#000000", FG="#FFFFFF",
                          FG_DIM="#E0E0E0", FG_BRIGHT="#FFFFFF", SELECT="#0F4A85", HOVER="#1A1A1A",
                          EDITOR_FG="#FFFFFF", CARET="#FFFFFF", GUTTER="#FFFFFF", COMMENT="#7CA668",
                          DIRECTIVE="#C586C0", PAUSE="#4EC9B0", BUTTON="#1A1A1A", BUTTON_HOVER="#333333",
                          SCROLL="#6FC3DF", SCROLL_HOVER="#9AD6EA", TRANSCRIPT="#000000", ERROR="#F48771",
                          CHECK_EDGE="#FFFFFF", CHECK_HOVER="#6FC3DF", ACCENT_OFF="#5A3A30"),
}
DEFAULT_THEME = "Dark+"
(BG, SIDEBAR, ACTIVITY, TABBAR, TAB_IDLE, PANEL, BORDER, INPUT, FG, FG_DIM, FG_BRIGHT, SELECT,
 HOVER, EDITOR_FG, CARET, GUTTER, COMMENT, DIRECTIVE, PAUSE, BUTTON, BUTTON_HOVER, SCROLL,
 SCROLL_HOVER, TRANSCRIPT, ERROR, CHECK_EDGE, CHECK_HOVER, ACCENT_OFF) = (THEMES["Dark+"][k] for k in KEYS)   # named for readers and linters
ON_ACCENT = "#FFFFFF"        # text and marks drawn on coral, in every theme
THEME = DEFAULT_THEME


def apply_theme(name: str) -> str:
    """Make `name` the current theme (module colors). Unknown names fall back to Dark+."""
    global THEME
    THEME = name if name in THEMES else DEFAULT_THEME
    globals().update(THEMES[THEME])
    return THEME


apply_theme(DEFAULT_THEME)

ASSETS = Path(__file__).parent / "assets" / "tk"
LAYOUT_FILE = Path.home() / ".config" / "ursotts" / "app.json"
FROZEN = getattr(sys, "frozen", False)   # True in the installed .app / .exe
MANUAL_URL = "https://github.com/ursomics/ursotts/blob/main/docs/MANUAL.md"
VIEWS = ("speak", "pron", "batch", "claude")
TITLES = {"speak": "SPEAK", "pron": "PRONUNCIATION", "batch": "BATCH", "claude": "CLAUDE CODE"}
TAB_NAMES = {"speak": "script.txt", "pron": "pronunciation", "batch": "batch", "claude": "claude code"}
ICONS = {"speak": "mic", "pron": "text", "batch": "folder", "claude": "log"}   # assets/tk/activity_icons
RESTART_ARGS: list[str] = []   # set by launch() so Restart keeps options like --engine
MOD = "Command" if sys.platform == "darwin" else "Control"
MOD_LABEL = "⌘" if sys.platform == "darwin" else "Ctrl+"
# Korean-capable faces tried first in Korean mode (Hangul glyphs then match the Latin text's metrics).
# macOS: Apple SD Gothic Neo; Windows: Malgun Gothic; Linux: Noto / Nanum. Anything else falls back
# to the system's automatic per-character font substitution.
KO_SANS = ("Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans CJK KR", "Noto Sans KR", "NanumGothic")
KO_MONO = ("D2Coding", "NanumGothicCoding", "Noto Sans Mono CJK KR")


def _title(view: str) -> str:
    """Sidebar / menu name of a view in the current language (Title Case)."""
    return tr(TITLES[view].title())


def _font(*names, size=12, weight="normal"):
    available = set(tkfont.families())
    for n in names:
        if n in available:
            # a dedicated face like "Poppins SemiBold" is already as heavy as intended
            w = "normal" if any(k in n for k in ("SemiBold", "Medium")) else weight
            return (n, size, w)
    return ("TkDefaultFont", size, weight)


PROGRESS_RE = re.compile(r"\|\s*(\d+)/\d+\s*\[[^,\]]*(?:,\s*([\d.]+)\s*it/s)?")


class QueueWriter:
    """Sends print() output from the worker thread to the OUTPUT panel.

    Progress bars (tqdm) redraw one line with "\r"; those redraws become a
    single live line ("live") instead of a flood of new lines."""

    def __init__(self, q: queue.Queue):
        self.q = q
        self.buf = ""

    def write(self, s):
        if not s:
            return
        self.buf += s
        while True:
            cut = min([i for i in (self.buf.find("\r"), self.buf.find("\n")) if i != -1], default=-1)
            if cut == -1:
                break
            piece, sep, self.buf = self.buf[:cut], self.buf[cut], self.buf[cut + 1:]
            if sep == "\r" or PROGRESS_RE.search(piece):
                if piece.strip():
                    self.q.put(("live", piece))
            else:
                self.q.put(("log", tr_line(piece) + "\n"))

    def flush(self):
        if self.buf.strip():
            self.q.put(("log", tr_line(self.buf)))
        self.buf = ""


class Player:
    """Plays audio with the system player (afplay on macOS)."""

    def __init__(self):
        self.proc = None

    def command(self, path: str):
        if sys.platform == "darwin":
            return ["afplay", path]
        for tool, args in (("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]), ("aplay", ["-q"])):
            if shutil.which(tool):
                return [tool, *args, path]
        return None

    def play(self, path: str, wait: bool = False):
        self.stop()
        if sys.platform.startswith("win"):
            wav = Path(path).with_suffix(".wav")   # Windows' built-in player handles WAV and can be stopped
            if wav.exists():
                import winsound
                flags = winsound.SND_FILENAME | (0 if wait else winsound.SND_ASYNC)
                winsound.PlaySound(str(wav), flags)
                self.winsound = True
                return
        cmd = self.command(path)
        if cmd is None:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa: S606 - opens the default player
            return
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if wait:
            self.proc.wait()

    def stop(self):
        if getattr(self, "winsound", False):
            import winsound
            winsound.PlaySound(None, 0)
            self.winsound = False
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None


def reveal(path: Path):
    """Show a file or folder in Finder / Explorer / the file manager."""
    path = Path(path)
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)] if path.is_file() else ["open", str(path)])
    elif sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", str(path)] if path.is_file() else ["explorer", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path if path.is_dir() else path.parent)])


class Choice(tk.Frame):
    """VS Code-style checkbox or radio button drawn on a canvas.

    Checkbox: a rounded square that fills coral with a white check mark.
    Radio: a circle with a coral dot. Click the box or the label to change it."""

    def __init__(self, parent, text, variable, value=None, bg=None, font=None, radio=False):
        bg = SIDEBAR if bg is None else bg           # looked up now, so the current theme applies
        super().__init__(parent, bg=bg, cursor="hand2")
        self.var, self.value, self.radio = variable, value, radio
        self.size = 16
        self.canvas = tk.Canvas(self, width=self.size + 2, height=self.size + 2, bg=bg,
                                highlightthickness=0, bd=0)
        self.canvas.pack(side="left")
        self.text = tk.Label(self, text=tr(text), bg=bg, fg=FG, font=font, anchor="w")
        self.text.pack(side="left", padx=(7, 0))
        for w in (self, self.canvas, self.text):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>", lambda e: self._draw(hover=True))
            w.bind("<Leave>", lambda e: self._draw())
        variable.trace_add("write", lambda *a: self._draw())
        self._draw()

    def selected(self):
        return self.var.get() == self.value if self.radio else bool(self.var.get())

    def _click(self, _e=None):
        if self.radio:
            self.var.set(self.value)
        else:
            self.var.set(not self.var.get())

    def _draw(self, hover=False):
        c, n, on = self.canvas, self.size, self.selected()
        c.delete("all")
        edge = CORAL if on else (CHECK_HOVER if hover else CHECK_EDGE)
        if self.radio:
            c.create_oval(1, 1, n, n, outline=edge, width=1.5, fill=INPUT)
            if on:
                c.create_oval(5, 5, n - 4, n - 4, outline="", fill=CORAL)
        else:
            r = 4
            fill = CORAL if on else INPUT
            pts = [1 + r, 1, n - r, 1, n, 1, n, 1 + r, n, n - r, n, n, n - r, n, 1 + r, n, 1, n, 1, n - r, 1, 1 + r, 1, 1]
            c.create_polygon(pts, smooth=True, fill=fill, outline=edge, width=1.2)
            if on:
                c.create_line(4.5, n / 2 + 0.5, n / 2 - 1, n - 4.5, n - 4, 4.5,
                              fill=ON_ACCENT, width=2.2, capstyle="round", joinstyle="round")


class App:
    def __init__(self, root: tk.Tk, cfg: dict):
        self.root, self.cfg = root, cfg
        self.out_root = Path(cfg.get("ui_output", "output"))
        self.project = Path.cwd()
        configured = cfg["voices"] or {}
        self.voices_dir = (Path(next(iter(configured.values()))).parent if configured
                           else self.project / "voices")
        self.synth: Synthesizer | None = None
        self.script_path: Path | None = None      # the file the editor shows (after Open/Save)
        self.saved_text = ""                       # its contents when last opened or saved
        self.wrapped: list[tk.Label] = []
        self.busy = False
        self.q: queue.Queue = queue.Queue()
        self.player = Player()
        self.layout = self._load_layout()
        self.theme = apply_theme(self.layout.get("theme", DEFAULT_THEME))
        # interface language: saved choice > URSOTTS_LANG > installer default > English
        saved = self.layout.get("ui_lang")
        self.ui_choice = saved if saved in i18n.LANGS_UI else None
        i18n.set_language(i18n.resolve_language(self.ui_choice))
        sans = ("Poppins", "SF Pro Text", "Segoe UI", "Helvetica Neue", "Helvetica", "DejaVu Sans")
        mono = ("Menlo", "SF Mono", "Consolas", "DejaVu Sans Mono")
        semibold = ("Poppins SemiBold",)
        if i18n.get_language() == "ko":
            sans, mono, semibold = KO_SANS + sans, KO_MONO + mono, ()
        specs = {
            "ui": _font(*sans, size=14),
            "ui_b": _font(*semibold, *sans, size=14, weight="bold"),
            "small": _font(*sans, size=12),
            "head": _font(*semibold, *sans, size=11, weight="bold"),
            "mono": _font(*mono, size=14),
            "icon": _font(*sans, size=18, weight="bold"),
        }
        # named fonts: changing their size updates every widget that uses them (zoom)
        self.base_sizes = {k: v[1] for k, v in specs.items()}
        self.fonts = {k: tkfont.Font(root=root, family=v[0], size=v[1], weight=v[2]) for k, v in specs.items()}
        self.zoom_level = int(self.layout.get("zoom", 0))
        self._apply_zoom(announce=False)
        self._style()
        self._build()
        self.show(self.layout.get("view", "speak"))
        self.root.after(80, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        if sys.platform == "darwin":                       # the app menu's Quit and ⌘Q from macOS
            self.root.createcommand("tk::mac::Quit", self.quit)
        self.log(tr("ursoTTS {version} desktop app. Project folder: {path}",
                    version=__version__, path=self._short(self.project)) + "\n")
        self.log(tr("The voice model loads the first time you generate; later runs are quick.") + "\n")

    # ------------------------------------------------------------------ style
    def _style(self):
        r = self.root
        r.title("ursoTTS")
        r.configure(bg=BG)
        r.geometry(self.layout.get("geometry", "1280x820"))
        r.minsize(980, 620)
        try:
            if sys.platform.startswith("win"):
                r.iconbitmap(str(ASSETS / "icons" / "ursotts.ico"))
            # Tk uses the FIRST image for the Dock / taskbar icon, so the largest goes first (a 32 px
            # first image looked pixelated). The installed Mac app keeps the sharp icon from its bundle.
            if not (sys.platform == "darwin" and FROZEN):
                self._icons = [tk.PhotoImage(file=str(ASSETS / "icons" / f"icon_{n}.png"))
                               for n in (512, 256, 128, 64, 32)]
                r.iconphoto(True, *self._icons)
        except tk.TclError:
            pass
        s = ttk.Style(r)
        s.theme_use("clam")
        f = self.fonts["ui"]
        s.configure(".", background=SIDEBAR, foreground=FG, font=f, borderwidth=0)
        s.configure("TCombobox", fieldbackground=INPUT, background=INPUT, foreground=FG, arrowcolor=FG,
                    bordercolor=BORDER, lightcolor=INPUT, darkcolor=INPUT, padding=4)
        s.map("TCombobox", fieldbackground=[("readonly", INPUT)], foreground=[("readonly", FG)],
              selectbackground=[("readonly", INPUT)], selectforeground=[("readonly", FG)],
              bordercolor=[("focus", CORAL)])
        r.option_add("*TCombobox*Listbox.background", SIDEBAR)
        r.option_add("*TCombobox*Listbox.foreground", FG)
        r.option_add("*TCombobox*Listbox.selectBackground", SELECT)
        r.option_add("*TCombobox*Listbox.font", str(f))
        s.configure("Horizontal.TScale", background=SIDEBAR, troughcolor=INPUT, bordercolor=SIDEBAR,
                    lightcolor=CORAL, darkcolor=CORAL)
        s.configure("TCheckbutton", background=SIDEBAR, foreground=FG, indicatorbackground=INPUT,
                    indicatorforeground=ON_ACCENT, focuscolor=SIDEBAR)
        s.map("TCheckbutton", background=[("active", SIDEBAR)], indicatorbackground=[("selected", CORAL)])
        s.configure("TRadiobutton", background=BG, foreground=FG, indicatorbackground=INPUT, focuscolor=BG)
        s.map("TRadiobutton", background=[("active", BG)], indicatorbackground=[("selected", CORAL)])
        s.configure("Treeview", background=BG, fieldbackground=BG, foreground=FG, rowheight=self._row_height(),
                    bordercolor=BORDER, font=f)
        s.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", FG_BRIGHT)])
        s.configure("Treeview.Heading", background=TAB_IDLE, foreground=FG_DIM, relief="flat",
                    font=self.fonts["head"], bordercolor=BORDER)
        s.map("Treeview.Heading", background=[("active", TAB_IDLE)])
        s.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        s.configure("Vertical.TScrollbar", background=SCROLL, troughcolor=BG, bordercolor=BG,
                    lightcolor=SCROLL, darkcolor=SCROLL, gripcount=0, width=10)
        s.map("Vertical.TScrollbar", background=[("active", SCROLL_HOVER), ("!active", SCROLL)])

    # ------------------------------------------------------------- widgets
    def label(self, parent, text, kind="ui", fg=None, bg=None, **kw):
        fg = FG if fg is None else fg
        bg = SIDEBAR if bg is None else bg
        return tk.Label(parent, text=tr(text), font=self.fonts[kind], fg=fg, bg=bg, anchor="w", **kw)

    def button(self, parent, text, command, primary=False, bg=None, **kw):
        color = CORAL if primary else BUTTON
        hover = DEEP_CORAL if primary else BUTTON_HOVER
        b = tk.Label(parent, text=tr(text), font=self.fonts["ui_b" if primary else "ui"], fg=ON_ACCENT if primary else FG_BRIGHT,
                     bg=color, padx=14, pady=6, cursor="hand2", **kw)
        b.bind("<Button-1>", lambda e: command() if str(b.cget("state")) != "disabled" else None)
        b.bind("<Enter>", lambda e: b.configure(bg=hover) if str(b.cget("state")) != "disabled" else None)
        b.bind("<Leave>", lambda e: b.configure(bg=color))
        b._color = color
        return b

    def entry(self, parent, var, width=28, bg=None):
        e = tk.Entry(parent, textvariable=var, width=width, font=self.fonts["ui"], bg=INPUT, fg=FG,
                     insertbackground=FG, relief="flat", highlightthickness=1,
                     highlightbackground=INPUT, highlightcolor=CORAL)
        return e

    def note(self, parent, text):
        """Small gray text in the sidebar that wraps to the sidebar width."""
        lab = self.label(parent, text, "small", fg=FG_DIM, justify="left")
        lab.configure(wraplength=max(self.layout.get("sidebar", 340) - 32, 180))
        self.wrapped.append(lab)
        return lab

    def section(self, parent, title):
        f = tk.Frame(parent, bg=SIDEBAR)
        f.pack(fill="x", padx=14, pady=(14, 2))
        self.label(f, tr(title).upper(), "head", fg=FG_DIM).pack(fill="x")
        return f

    def field(self, parent, text):
        self.label(parent, text, "small", fg=FG_DIM).pack(fill="x", padx=14, pady=(8, 2))

    # ------------------------------------------------------------- layout
    def _build(self):
        r = self.root
        self._menu()
        self.status = tk.Frame(r, bg=CORAL, height=24)
        self.status.pack(side="bottom", fill="x")
        self.status_left = tk.Label(self.status, text="", font=self.fonts["small"], fg=ON_ACCENT, bg=CORAL)
        self.status_left.pack(side="left", padx=10)
        self.status_right = tk.Label(self.status, text="", font=self.fonts["small"], fg=ON_ACCENT, bg=CORAL)
        self.status_right.pack(side="right", padx=10)
        # a small sliding bar while ursoTTS is working
        ttk.Style(r).configure("Busy.Horizontal.TProgressbar", troughcolor=DEEP_CORAL, background=ON_ACCENT,
                               bordercolor=CORAL, lightcolor=ON_ACCENT, darkcolor=ON_ACCENT, thickness=6)
        self.busy_bar = ttk.Progressbar(self.status, mode="indeterminate", length=120,
                                        style="Busy.Horizontal.TProgressbar")
        self._set_status()

        body = tk.Frame(r, bg=BG)
        body.pack(fill="both", expand=True)
        self.activity = tk.Frame(body, bg=ACTIVITY, width=48)
        self.activity.pack(side="left", fill="y")
        self.activity.pack_propagate(False)
        self.act_buttons, self.act_images = {}, {}
        for v in VIEWS:
            self.act_images[v] = self._icon_states(ICONS[v])
            holder = tk.Frame(self.activity, bg=ACTIVITY)
            holder.pack(fill="x")
            bar = tk.Frame(holder, bg=ACTIVITY, width=2)
            bar.pack(side="left", fill="y")
            b = tk.Label(holder, image=self.act_images[v]["inactive"], bg=ACTIVITY, pady=12, cursor="hand2")
            b.pack(side="left", fill="x", expand=True)
            b.bind("<Button-1>", lambda e, v=v: self.show(v))
            b.bind("<Enter>", lambda e, v=v: self._hover(v, True))
            b.bind("<Leave>", lambda e, v=v: self._hover(v, False))
            self.act_buttons[v] = (b, bar)
        self.gear_images = self._icon_states("settings")
        gear = tk.Label(self.activity, image=self.gear_images["inactive"], bg=ACTIVITY, pady=12, cursor="hand2")
        gear.pack(side="bottom", fill="x")
        gear.bind("<Button-1>", lambda e: self.open_settings())
        gear.bind("<Enter>", lambda e: (gear.configure(image=self.gear_images["active"]),
                                        self.status_right.configure(text=tr("Settings (config.yaml)"))))
        gear.bind("<Leave>", lambda e: (gear.configure(image=self.gear_images["inactive"]), self._set_status()))

        self.hpane = tk.PanedWindow(body, orient="horizontal", sashwidth=4, bg=BORDER, bd=0, sashrelief="flat")
        self.hpane.pack(side="left", fill="both", expand=True)
        self.sidebar = tk.Frame(self.hpane, bg=SIDEBAR)
        self.sidebar.bind("<Configure>", lambda e: [w.configure(wraplength=max(e.width - 32, 120))
                                                     for w in self.wrapped])
        self.vpane = tk.PanedWindow(self.hpane, orient="vertical", sashwidth=4, bg=BORDER, bd=0, sashrelief="flat")
        self.hpane.add(self.sidebar, minsize=260, width=max(self.layout.get("sidebar", 340), 340))
        self.hpane.add(self.vpane, minsize=480)

        self.editor = tk.Frame(self.vpane, bg=BG)
        self.panel = tk.Frame(self.vpane, bg=PANEL)
        self.vpane.add(self.editor, minsize=260)
        self.panel_visible = self.layout.get("panel", True)
        if self.panel_visible:
            self.vpane.add(self.panel, minsize=90, height=self.layout.get("panel_height", 210))

        self.tabbar = tk.Frame(self.editor, bg=TABBAR, height=35)
        self.tabbar.pack(fill="x")
        self.tabbar.pack_propagate(False)
        self.content = tk.Frame(self.editor, bg=BG)
        self.content.pack(fill="both", expand=True)

        self._build_panel()
        self.side_frames, self.main_frames = {}, {}
        self._build_speak()
        self._build_pron()
        self._build_batch()
        self._build_claude()
        self._shortcuts()

    def _menu(self):
        m = tk.Menu(self.root)
        file = tk.Menu(m, tearoff=False)
        file.add_command(label=tr("Open script…"), accelerator=f"{MOD_LABEL}O", command=self.open_script)
        file.add_command(label=tr("Save script"), accelerator=f"{MOD_LABEL}S", command=self.save_script)
        file.add_command(label=tr("Save script as…"), accelerator=f"⇧{MOD_LABEL}S" if MOD_LABEL == "⌘" else "Ctrl+Shift+S",
                         command=self.save_script_as)
        file.add_separator()
        file.add_command(label=tr("Show output folder"), command=lambda: reveal(self.out_root.resolve()))
        if not FROZEN:
            file.add_command(label=tr("Create launcher…"), command=self.create_launcher)
        file.add_separator()
        file.add_command(label=tr("Quit"), accelerator=f"{MOD_LABEL}Q", command=self.quit)
        m.add_cascade(label=tr("File"), menu=file)
        view = tk.Menu(m, tearoff=False)
        for i, v in enumerate(VIEWS, 1):
            view.add_command(label=_title(v), accelerator=f"{MOD_LABEL}{i}", command=lambda v=v: self.show(v))
        view.add_separator()
        view.add_command(label=tr("Toggle output panel"), accelerator=f"{MOD_LABEL}J", command=self.toggle_panel)
        view.add_separator()
        themes = tk.Menu(view, tearoff=False)
        self.theme_var = tk.StringVar(value=self.theme)
        for name in THEMES:
            themes.add_radiobutton(label=name, value=name, variable=self.theme_var,
                                   command=lambda n=name: self.set_theme(n))
        view.add_cascade(label=tr("Color Theme"), menu=themes)
        view.add_command(label=tr("Choose color theme…"), accelerator=f"{MOD_LABEL}K {MOD_LABEL}T",
                         command=self.pick_theme)
        view.add_separator()
        view.add_separator()
        langs = tk.Menu(view, tearoff=False)
        self.lang_var = tk.StringVar(value=i18n.get_language())
        for code in i18n.LANGS_UI:
            langs.add_radiobutton(label=i18n.LANG_NAMES[code], value=code, variable=self.lang_var,
                                  command=lambda c=code: self.set_ui_language(c))
        view.add_cascade(label="Language / 언어", menu=langs)
        view.add_separator()
        view.add_command(label=tr("Zoom in"), accelerator=f"{MOD_LABEL}+", command=lambda: self.zoom(+1))
        view.add_command(label=tr("Zoom out"), accelerator=f"{MOD_LABEL}−", command=lambda: self.zoom(-1))
        view.add_command(label=tr("Actual size"), accelerator=f"{MOD_LABEL}0", command=lambda: self.zoom(0))
        m.add_cascade(label=tr("View"), menu=view)
        helpm = tk.Menu(m, tearoff=False)
        helpm.add_command(label=tr("ursoTTS manual"), command=self.open_manual)
        helpm.add_command(label=tr("Open config.yaml"), command=self.open_settings)
        helpm.add_separator()
        helpm.add_command(label=tr("About ursoTTS"), command=self.about)
        m.add_cascade(label=tr("Help"), menu=helpm)
        self.root.configure(menu=m)

    def _shortcuts(self):
        r = self.root
        for i, v in enumerate(VIEWS, 1):
            r.bind_all(f"<{MOD}-Key-{i}>", lambda e, v=v: self.show(v))
        r.bind_all(f"<{MOD}-j>", lambda e: self.toggle_panel())
        self._chord = False                      # ⌘K then ⌘T opens the theme picker, as in VS Code
        def chord_start(_e):
            self._chord = True
            self.root.after(1500, lambda: setattr(self, "_chord", False))
            return "break"
        def chord_t(_e):
            if self._chord:
                self._chord = False
                self.pick_theme()
                return "break"
        r.bind_all(f"<{MOD}-k>", chord_start)
        r.bind_all(f"<{MOD}-t>", chord_t)
        for key in ("equal", "plus", "KP_Add"):          # Cmd/Ctrl + (with or without Shift)
            r.bind_all(f"<{MOD}-{key}>", lambda e: self.zoom(+1))
        for key in ("minus", "underscore", "KP_Subtract"):
            r.bind_all(f"<{MOD}-{key}>", lambda e: self.zoom(-1))
        r.bind_all(f"<{MOD}-Key-0>", lambda e: self.zoom(0))
        r.bind_all(f"<{MOD}-o>", lambda e: self.open_script())
        r.bind_all(f"<{MOD}-s>", lambda e: self.save_script())
        r.bind_all(f"<{MOD}-S>", lambda e: self.save_script_as())          # Shift held
        r.bind_all(f"<{MOD}-Shift-s>", lambda e: self.save_script_as())
        r.bind_all(f"<{MOD}-q>", lambda e: self.quit())
        r.bind_all(f"<{MOD}-Return>", lambda e: self.run_current())

    ZOOM_MIN, ZOOM_MAX = -3, 6           # 70% … 160%

    def _scale(self) -> float:
        return 1 + 0.1 * self.zoom_level

    def _row_height(self) -> int:
        return round(32 * self._scale())

    def _apply_zoom(self, announce=True):
        for k, f in self.fonts.items():
            f.configure(size=max(8, round(self.base_sizes[k] * self._scale())))
        if announce:
            ttk.Style(self.root).configure("Treeview", rowheight=self._row_height())
            for w in self.wrapped:
                w.configure(wraplength=max(self.sidebar.winfo_width() - 32, 120))
            self._sync_gutter()
            self._set_status(tr("Zoom {percent}%", percent=round(self._scale() * 100)))
            self.root.after(1500, lambda: (not self.busy) and self._set_status())

    def zoom(self, step: int):
        """step +1 zooms in, -1 zooms out, 0 returns to 100%."""
        self.zoom_level = 0 if step == 0 else max(self.ZOOM_MIN, min(self.ZOOM_MAX, self.zoom_level + step))
        self._apply_zoom()
        return "break"

    def _icon_states(self, name):
        folder = ASSETS / "activity_icons"
        return {state: tk.PhotoImage(file=str(folder / f"{name}_{state}_24.png"))
                for state in ("inactive", "active", "accent")}

    def _hover(self, view, inside):
        b, _bar = self.act_buttons[view]
        if view != getattr(self, "view", None):
            b.configure(image=self.act_images[view]["active" if inside else "inactive"])
        if inside:
            self.status_right.configure(text=_title(view))
        else:
            self._set_status()

    def _tab(self, view):
        for w in self.tabbar.winfo_children():
            w.destroy()
        tab = tk.Frame(self.tabbar, bg=BG)
        tab.pack(side="left", fill="y")
        tk.Frame(tab, bg=CORAL, height=2).pack(fill="x", side="top")
        self.label(tab, f"  {tr(TAB_NAMES[view])}  ", "ui", fg=FG_BRIGHT, bg=BG, pady=6).pack(side="left")

    def show(self, view):
        if view not in VIEWS:
            view = "speak"
        self.view = view
        for v, (b, bar) in self.act_buttons.items():
            b.configure(image=self.act_images[v]["accent" if v == view else "inactive"])
            bar.configure(bg=CORAL if v == view else ACTIVITY)
        for v in VIEWS:
            self.side_frames[v].pack_forget()
            self.main_frames[v].pack_forget()
        self.side_frames[view].pack(fill="both", expand=True)
        self.main_frames[view].pack(fill="both", expand=True)
        self._tab(view)

    def open_manual(self):
        """The manual on GitHub, in Korean when the interface is Korean."""
        webbrowser.open(MANUAL_URL.replace("MANUAL.md", "MANUAL.ko.md") if i18n.get_language() == "ko" else MANUAL_URL)

    def about(self):
        win = tk.Toplevel(self.root, bg=BG)
        win.title(tr("About ursoTTS"))
        win.resizable(False, False)
        win.transient(self.root)
        self._about_img = tk.PhotoImage(file=str(ASSETS / "about_400x400.png"))
        tk.Label(win, image=self._about_img, bg=BG).pack()
        if i18n.get_language() == "ko":
            self.label(win, tr("ursoTTS {version} Korean edition", version=__version__), "ui_b",
                       fg=FG_BRIGHT, bg=BG).pack(pady=(10, 0))
        row = tk.Frame(win, bg=BG)
        row.pack(pady=12)
        self.button(row, "GitHub", lambda: webbrowser.open("https://github.com/ursomics/ursotts"), bg=BG).pack(side="left")
        self.button(row, "ursomics.com", lambda: webbrowser.open("https://ursomics.com"), bg=BG).pack(side="left", padx=6)
        self.button(row, "Close", win.destroy, primary=True, bg=BG).pack(side="left")
        win.bind("<Escape>", lambda e: win.destroy())

    # ------------------------------------------------------------- panel
    def _build_panel(self):
        head = tk.Frame(self.panel, bg=PANEL)
        head.pack(fill="x")
        title = tk.Frame(head, bg=PANEL)
        title.pack(side="left", padx=12)
        self.label(title, "OUTPUT", "head", fg=FG_BRIGHT, bg=PANEL, pady=6).pack()
        tk.Frame(title, bg=CORAL, height=1).pack(fill="x")
        close = tk.Label(head, text="✕", font=self.fonts["ui"], fg=FG_DIM, bg=PANEL, padx=10, cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.toggle_panel())
        clear = tk.Label(head, text=tr("Clear"), font=self.fonts["small"], fg=FG_DIM, bg=PANEL, padx=8, cursor="hand2")
        clear.pack(side="right")
        clear.bind("<Button-1>", lambda e: self.logbox.delete("1.0", "end"))
        frame = tk.Frame(self.panel, bg=PANEL)
        frame.pack(fill="both", expand=True, padx=(12, 0))
        self.logbox = tk.Text(frame, bg=PANEL, fg=FG, font=self.fonts["mono"], relief="flat",
                              insertbackground=FG, highlightthickness=0, wrap="word", padx=4, pady=4)
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.logbox.pack(side="left", fill="both", expand=True)
        self.logbox.tag_configure("accent", foreground=CORAL)
        self.logbox.tag_configure("error", foreground=ERROR)
        self.logbox.tag_configure("dim", foreground=FG_DIM)

    def toggle_panel(self):
        if self.panel_visible:
            self.layout["panel_height"] = self.panel.winfo_height()
            self.vpane.forget(self.panel)
        else:
            self.vpane.add(self.panel, minsize=90, height=self.layout.get("panel_height", 210))
        self.panel_visible = not self.panel_visible

    def log(self, text, tag=None):
        self._end_live()
        self.logbox.insert("end", text, tag)
        self.logbox.see("end")

    def live(self, raw):
        """Show generation progress on one line that updates in place."""
        m = PROGRESS_RE.search(raw)
        if m:
            tokens, speed = int(m.group(1)), m.group(2)
            seconds = tokens / 25            # Chatterbox makes about 25 tokens per second of speech
            text = tr("  generating… {tokens} tokens (≈{seconds:.1f} s of speech)", tokens=tokens, seconds=seconds)
            if speed:
                text += tr(" · {speed:.1f} tokens/s", speed=float(speed))
        else:
            text = "  " + raw.strip()[:120]
        if "live_start" in self.logbox.mark_names():
            self.logbox.delete("live_start", "end-1c")
        else:
            if not self.logbox.get("end-2c", "end-1c") in ("\n", ""):
                self.logbox.insert("end", "\n")
            self.logbox.mark_set("live_start", "end-1c")
            self.logbox.mark_gravity("live_start", "left")
        self.logbox.insert("end", text, "dim")
        self.logbox.see("end")

    def _end_live(self):
        if "live_start" in self.logbox.mark_names():
            self.logbox.mark_unset("live_start")
            self.logbox.insert("end", "\n")

    # ------------------------------------------------------------- speak
    def _build_speak(self):
        side = tk.Frame(self.sidebar, bg=SIDEBAR)
        self.side_frames["speak"] = side
        self._side_header(side, "speak")
        self.section(side, "Language")
        self.lang_codes = {tr(k): v for k, v in LANGS.items()}      # shown name -> "auto" / "en" / "ko"
        self.lang = tk.StringVar(value=tr("Auto (English + Korean)"))
        ttk.Combobox(side, textvariable=self.lang, values=list(self.lang_codes), state="readonly", font=self.fonts["ui"]).pack(fill="x", padx=14)

        self.section(side, "Voices")
        self.voice_en, self.voice_ko = tk.StringVar(), tk.StringVar()
        self.field(side, "English voice")
        self.cb_en = ttk.Combobox(side, textvariable=self.voice_en, state="readonly", font=self.fonts["ui"])
        self.cb_en.pack(fill="x", padx=14)
        self.field(side, "Korean voice")
        self.cb_ko = ttk.Combobox(side, textvariable=self.voice_ko, state="readonly", font=self.fonts["ui"])
        self.cb_ko.pack(fill="x", padx=14)
        self.button(side, "+ Add voice file…", self.add_voice).pack(fill="x", padx=14, pady=(10, 0))
        self.button(side, "↻ Refresh list", self.refresh_voices).pack(fill="x", padx=14, pady=(6, 0))
        self.refresh_voices()

        self.section(side, "Speaking style")
        g = self.cfg["generation"]
        self.style_vars = {}
        for key, label, lo, hi, hint in (("exaggeration", tr("Expressiveness"), 0.25, 1.0, tr("calm … animated")),
                                         ("cfg_weight", tr("Pacing"), 0.0, 1.0, tr("slower … faster")),
                                         ("temperature", tr("Variation"), 0.3, 1.2, tr("steady … varied"))):
            var = tk.DoubleVar(value=float(g.get(key, 0.5)))
            self.style_vars[key] = var
            top = tk.Frame(side, bg=SIDEBAR)
            top.pack(fill="x", padx=14, pady=(8, 0))
            self.label(top, label, "small", fg=FG_DIM).pack(side="left")
            val = self.label(top, f"{var.get():.2f}", "small", fg=FG)
            val.pack(side="right")
            ttk.Scale(side, from_=lo, to=hi, variable=var, orient="horizontal",
                      command=lambda x, v=val, var=var: v.configure(text=f"{var.get():.2f}")).pack(fill="x", padx=14)
        self.seed = tk.StringVar(value="" if g.get("seed") is None else str(g.get("seed")))
        self.field(side, "Seed (same seed = same take)")
        self.entry(side, self.seed, width=10).pack(anchor="w", padx=14)

        self.section(side, "Output files")
        self.files = tk.Listbox(side, bg=SIDEBAR, fg=FG, font=self.fonts["small"], relief="flat",
                                highlightthickness=0, selectbackground=SELECT, activestyle="none", height=6)
        self.files.pack(fill="both", expand=True, padx=14)
        self.files.bind("<Double-Button-1>", lambda e: self.play_selected())
        self.file_paths: list[str] = []
        row = tk.Frame(side, bg=SIDEBAR)
        row.pack(fill="x", padx=14, pady=(6, 12))
        self.button(row, "▶ Play", self.play_selected).pack(side="left")
        self.button(row, "■ Stop", self.player.stop).pack(side="left", padx=6)
        self.button(row, "Show", self.reveal_selected).pack(side="left")

        main = tk.Frame(self.content, bg=BG)
        self.main_frames["speak"] = main
        bar = tk.Frame(main, bg=BG)
        bar.pack(fill="x", padx=16, pady=(10, 6))
        self.button(bar, "Open…", self.open_script, bg=BG).pack(side="left")
        self.button(bar, "Save as…", self.save_script, bg=BG).pack(side="left", padx=6)
        self.button(bar, "Clear", lambda: self.script.delete("1.0", "end"), bg=BG).pack(side="left")
        self.gen_btn = self.button(bar, tr("Generate narration") + f"   {MOD_LABEL}↵", self.generate, primary=True, bg=BG)
        self.gen_btn.pack(side="right")
        self.autoplay = tk.BooleanVar(value=True)
        Choice(bar, "Play when done", self.autoplay, bg=BG, font=self.fonts["small"]).pack(side="right", padx=12)
        ed = tk.Frame(main, bg=BG)
        ed.pack(fill="both", expand=True, padx=(0, 0), pady=(0, 6))
        self.gutter = tk.Canvas(ed, width=48, bg=BG, highlightthickness=0, bd=0)
        self.gutter.pack(side="left", fill="y")
        self.script = tk.Text(ed, bg=BG, fg=EDITOR_FG, font=self.fonts["mono"], relief="flat", undo=True,
                              insertbackground=CARET, selectbackground=SELECT, highlightthickness=0,
                              wrap="word", padx=8, pady=8)
        sb = ttk.Scrollbar(ed, orient="vertical", command=self._scroll_script)
        self.script.configure(yscrollcommand=lambda a, b: (sb.set(a, b), self._sync_gutter()))
        sb.pack(side="right", fill="y")
        self.script.pack(side="left", fill="both", expand=True)
        self.script.tag_configure("comment", foreground=COMMENT)
        self.script.tag_configure("directive", foreground=DIRECTIVE)
        self.script.tag_configure("pause", foreground=PAUSE)
        self.script.bind("<<Modified>>", self._on_script_change)
        self.script.bind("<Configure>", lambda e: self.root.after_idle(self._sync_gutter))
        hint = ("# " + tr("Paste or type your narration here. Lines starting with # are not spoken.") + "\n"
                "@lang auto\nWelcome to Ursomics. Today we analyze scRNA-seq data.\n\n"
                "안녕하세요, Ursomics입니다. [pause 1] 오늘은 DNA 분석을 해 보겠습니다.\n")
        self.script.insert("1.0", self.layout.get("script", hint))
        sp = self.layout.get("script_path")
        if sp and Path(sp).exists():          # the editor still belongs to that file
            self.script_path, self.saved_text = Path(sp), self.layout.get("saved_text") or ""
        self._update_tab_title()
        self._highlight()

    @staticmethod
    def _path(var) -> Path:
        """A folder typed or shown as ~/… → a real path."""
        return Path(var.get().strip()).expanduser()

    @staticmethod
    def _short(path) -> str:
        """Show paths inside the home folder as ~/…"""
        p, home = str(path), str(Path.home())
        return "~" + p[len(home):] if p == home or p.startswith(home + os.sep) else p

    def _side_header(self, side, view):
        self.label(side, "  " + tr(TITLES[view].title()).upper(), "head", fg=FG_DIM, pady=10).pack(fill="x")

    def _scroll_script(self, *args):
        self.script.yview(*args)
        self._sync_gutter()

    def _on_script_change(self, _e=None):
        if self.script.edit_modified():
            self._highlight()
            self.script.edit_modified(False)
            if self.script_path is not None:
                self._update_tab_title()

    def _sync_gutter(self):
        """Draw each line number at the y position where that line starts,
        so numbers stay correct when long lines wrap."""
        g = self.gutter
        g.delete("all")
        width = int(g.cget("width"))
        idx = self.script.index("@0,0")
        while True:
            info = self.script.dlineinfo(idx)
            if info is None:
                break
            line = int(idx.split(".")[0])
            g.create_text(width - 8, info[1], anchor="ne", text=str(line),
                          fill=GUTTER, font=self.fonts["mono"])
            nxt = self.script.index(f"{line + 1}.0")
            if nxt == idx or int(nxt.split(".")[0]) == line:
                break
            idx = nxt

    def _highlight(self):
        t = self.script
        for tag in ("comment", "directive", "pause"):
            t.tag_remove(tag, "1.0", "end")
        for i, line in enumerate(t.get("1.0", "end-1c").split("\n"), 1):
            s = line.lstrip()
            if s.startswith("#"):
                t.tag_add("comment", f"{i}.0", f"{i}.end")
            elif s.startswith("@lang"):
                t.tag_add("directive", f"{i}.0", f"{i}.end")
            for m in re.finditer(r"\[pause[^\]]*\]", line):
                t.tag_add("pause", f"{i}.{m.start()}", f"{i}.{m.end()}")
        self._sync_gutter()

    def refresh_voices(self):
        files = sorted(f for f in self.voices_dir.glob("*") if f.suffix.lower() in AUDIO_EXTS) \
            if self.voices_dir.is_dir() else []
        self.voice_files = {f.name: str(f) for f in files}
        names = list(self.voice_files)
        for cb, var, lang in ((self.cb_en, self.voice_en, "en"), (self.cb_ko, self.voice_ko, "ko")):
            cb.configure(values=names)
            if var.get() not in names:
                default = Path(self.cfg["voices"].get(lang, "")).name if self.cfg["voices"] else ""
                var.set(default if default in names else (names[0] if names else ""))

    def add_voice(self):
        path = filedialog.askopenfilename(title="Choose a voice sample (10–30 s of clear speech)",
                                          filetypes=[("Audio", "*.wav *.mp3 *.m4a *.flac *.ogg *.aac")])
        if not path:
            return
        try:
            prepared = prepare_sample(path, self.out_root / "app" / "samples")
        except UserError as e:
            messagebox.showerror("Voice sample", tr_exc(e))
            return
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^\w\-]+", "_", Path(path).stem).strip("_") or "my_voice"
        target = self.voices_dir / f"{name}.wav"
        target.write_bytes(Path(prepared).read_bytes())
        self.refresh_voices()
        self.log(tr("Added voice {name} (converted to mono 24 kHz, silence trimmed).", name=target.name) + "\n", "accent")

    def open_script(self):
        if not self.confirm_unsaved():
            return
        path = filedialog.askopenfilename(title="Open a script", initialdir=str(self.project / "scripts"),
                                          filetypes=[("Scripts", "*.txt *.md"), ("All files", "*.*")])
        if path:
            self.show("speak")
            text = Path(path).read_text(encoding="utf-8")
            self.script.delete("1.0", "end")
            self.script.insert("1.0", text)
            self.script_path, self.saved_text = Path(path), self.script.get("1.0", "end-1c")
            self._update_tab_title()

    def save_script(self) -> bool:
        """Save to the open file; ask for a name if there is none. True when saved."""
        if self.script_path is None:
            return self.save_script_as()
        return self._write_script(self.script_path)

    def save_script_as(self) -> bool:
        path = filedialog.asksaveasfilename(title="Save script as", defaultextension=".txt",
                                            initialdir=str(self.project / "scripts"),
                                            filetypes=[("Text", "*.txt"), ("Markdown", "*.md")])
        return self._write_script(Path(path)) if path else False

    def _write_script(self, path: Path) -> bool:
        text = self.script.get("1.0", "end-1c")
        try:
            path.write_text(text + ("" if text.endswith("\n") else "\n"), encoding="utf-8")
        except OSError as e:
            messagebox.showerror("Save script", tr("Could not save {path}:\n{error}", path=path, error=e))
            return False
        self.script_path, self.saved_text = path, text
        self._update_tab_title()
        self.log(tr("Saved {path}", path=self._short(path)) + "\n")
        return True

    def script_dirty(self) -> bool:
        """Unsaved changes in a script that belongs to a file."""
        return self.script_path is not None and self.script.get("1.0", "end-1c") != self.saved_text

    def _update_tab_title(self):
        name = self.script_path.name if self.script_path else "script.txt"
        TAB_NAMES["speak"] = ("● " if self.script_dirty() else "") + name
        if getattr(self, "view", None) == "speak":
            self._tab("speak")

    def confirm_unsaved(self) -> bool:
        """Ask about unsaved changes. True means it is fine to go on."""
        if not self.script_dirty():
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved changes", tr("Save changes to {name} before closing it?", name=self.script_path.name),
            icon="warning", default="yes")
        if answer is None:            # Cancel
            return False
        return self.save_script() if answer else True

    def selected_file(self):
        sel = self.files.curselection()
        if sel:
            return self.file_paths[sel[0]]
        return self.file_paths[0] if self.file_paths else None

    def play_selected(self):
        f = self.selected_file()
        if f:
            self.player.play(f)

    def reveal_selected(self):
        f = self.selected_file()
        reveal(Path(f) if f else self.out_root.resolve())

    # ------------------------------------------------------- pronunciation
    def _build_pron(self):
        side = tk.Frame(self.sidebar, bg=SIDEBAR)
        self.side_frames["pron"] = side
        self._side_header(side, "pron")
        self.section(side, "Word or abbreviation")
        self.term = tk.StringVar()
        self.entry(side, self.term).pack(fill="x", padx=14)
        self.section(side, "Language")
        self.pron_lang = tk.StringVar(value=tr("English"))
        ttk.Combobox(side, textvariable=self.pron_lang, values=[tr("English"), tr("Korean")], state="readonly", font=self.fonts["ui"]).pack(fill="x", padx=14)
        self.section(side, "Test sentence")
        self.context = tk.StringVar(value="Today we look at {word} in our data.")
        self.entry(side, self.context).pack(fill="x", padx=14)
        self.note(side, "{word} is replaced by each spelling").pack(fill="x", padx=14, pady=(2, 0))
        row = tk.Frame(side, bg=SIDEBAR)
        row.pack(fill="x", padx=14, pady=14)
        self.button(row, "Suggest spellings", self.suggest).pack(side="left")
        tips = tr("Letters: each capital followed by a dot (R.N.A.).\n"
                  "Word-like sounds: syllables joined by dots (NAN.og).\n"
                  "Genes with a vowel 2nd letter: try the word form first.\n"
                  "Korean: write the Hangul reading (피디엘원).")
        self.section(side, "Tips")
        self.note(side, tips).pack(fill="x", padx=14)

        main = tk.Frame(self.content, bg=BG)
        self.main_frames["pron"] = main
        self.label(main, "Versions to compare, one per line", "small", fg=FG_DIM, bg=BG).pack(fill="x", padx=16, pady=(12, 4))
        self.cands = tk.Text(main, height=6, bg=BG, fg=EDITOR_FG, font=self.fonts["mono"], relief="flat",
                             insertbackground=CARET, highlightthickness=1, highlightbackground=BORDER,
                             highlightcolor=CORAL, padx=8, pady=6)
        self.cands.pack(fill="x", padx=16)
        bar = tk.Frame(main, bg=BG)
        bar.pack(fill="x", padx=16, pady=10)
        self.listen_btn = self.button(bar, "Listen to all", self.listen, primary=True, bg=BG)
        self.listen_btn.pack(side="left")
        self.button(bar, "■ Stop", self.player.stop, bg=BG).pack(side="left", padx=6)
        self.results = tk.Frame(main, bg=BG)
        self.results.pack(fill="x", padx=16)
        self.best = tk.StringVar()
        bottom = tk.Frame(main, bg=BG)
        bottom.pack(fill="x", padx=16, pady=(12, 8))
        self.label(bottom, "Sounds like (optional note)", "small", fg=FG_DIM, bg=BG).pack(fill="x")
        self.like = tk.StringVar()
        self.entry(bottom, self.like, width=60, bg=BG).pack(fill="x", pady=(2, 10))
        self.button(bottom, "Save to pronunciation rules", self.save_pron, primary=True, bg=BG).pack(anchor="w")

    def suggest(self):
        term = self.term.get().strip()
        if not term:
            messagebox.showinfo("Pronunciation", "Type a word first, for example DNA or NANOG.")
            return
        lang = "ko" if self.pron_lang.get() == tr("Korean") else "en"
        self.cands.delete("1.0", "end")
        self.cands.insert("1.0", "\n".join(suggest_spellings(term, self.cfg, lang)))

    def listen(self):
        term = self.term.get().strip() or "word"
        cands = [c.strip() for c in self.cands.get("1.0", "end").splitlines() if c.strip()][:MAX_CANDIDATES]
        if not cands:
            messagebox.showinfo("Pronunciation", "Add at least one spelling, or click Suggest spellings.")
            return
        lang = "ko" if self.pron_lang.get() == tr("Korean") else "en"
        context = self.context.get() if "{word}" in self.context.get() else "{word}"
        overrides = self._voice_overrides()

        def work():
            synth = self._synth()
            synth.voice_override, synth.voice_overrides = None, overrides
            lab = self.out_root / "app" / "pronunciation"
            lab.mkdir(parents=True, exist_ok=True)
            slug = re.sub(r"\W+", "_", term) or "word"
            paths = []
            for i, c in enumerate(cands, 1):
                sentence = context.replace("{word}", render_say(c))
                print(f"[{i}/{len(cands)}] {c}  →  {sentence}")
                wav = audio.peak_normalize(synth.chunk_audio(Speech(sentence, lang, [sentence])))
                p = lab / f"{slug}_{i}.wav"
                audio.write_wav(p, wav, synth.sr)
                paths.append(str(p))
            synth.voice_overrides = {}
            self.q.put(("call", lambda: self._show_results(cands, paths)))
            for p in paths:  # play every version in order
                self.player.play(p, wait=True)
                time.sleep(0.25)
        self.run(work, "Generating versions…")

    def _show_results(self, cands, paths):
        for w in self.results.winfo_children():
            w.destroy()
        self.best.set("")
        for i, (c, p) in enumerate(zip(cands, paths), 1):
            row = tk.Frame(self.results, bg=BG)
            row.pack(fill="x", pady=2)
            Choice(row, f"{i}.  {c}", self.best, value=c, bg=BG, font=self.fonts["ui"], radio=True).pack(side="left")
            self.button(row, "▶", lambda p=p: self.player.play(p), bg=BG).pack(side="right")

    def save_pron(self):
        term, choice = self.term.get().strip(), self.best.get()
        if not term or not choice:
            messagebox.showinfo("Pronunciation", "Listen to the versions and choose the best one first.")
            return
        lang = "ko" if self.pron_lang.get() == tr("Korean") else "en"
        path = Path(self.cfg.get("pronunciations_path") or "pronunciations.yaml")
        upsert_pronunciation(path, lang, term, choice, self.like.get())
        self.cfg["pronunciation_table"] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self.log(tr("Saved {term} → {choice} (voice reads “{spoken}”). "
                    "Scripts that use it are re-rendered on the next batch.",
                    term=term, choice=choice, spoken=render_say(choice)) + "\n", "accent")

    # ------------------------------------------------------------- batch
    def _build_batch(self):
        side = tk.Frame(self.sidebar, bg=SIDEBAR)
        self.side_frames["batch"] = side
        self._side_header(side, "batch")
        self.src = tk.StringVar(value=self._short(self.layout.get("batch_src", self.project / "scripts")))
        self.dst = tk.StringVar(value=self._short(self.layout.get("batch_out", self.project / "output")))
        for title, var, cmd in ((tr("Scripts folder"), self.src, self.pick_src), (tr("Output folder"), self.dst, self.pick_dst)):
            self.section(side, title)
            self.entry(side, var).pack(fill="x", padx=14)
            row = tk.Frame(side, bg=SIDEBAR)
            row.pack(fill="x", padx=14, pady=(6, 0))
            self.button(row, "Choose…", cmd).pack(side="left")
            self.button(row, "Show", lambda var=var: reveal(self._path(var))).pack(side="left", padx=6)
        self.note(side, "To make a new folder, use the New Folder button in the folder dialog.").pack(fill="x", padx=14, pady=(6, 0))
        self.force = tk.BooleanVar(value=False)
        self.section(side, "Options")
        Choice(side, "Render everything again", self.force, font=self.fonts["ui"]).pack(anchor="w", padx=14)
        self.batch_btn = self.button(side, "Render all scripts", self.render_batch, primary=True)
        self.batch_btn.pack(fill="x", padx=14, pady=16)

        main = tk.Frame(self.content, bg=BG)
        self.main_frames["batch"] = main
        self.batch_note = self.label(main, "", "small", fg=FG_DIM, bg=BG)
        self.batch_note.pack(fill="x", padx=16, pady=(12, 6))
        frame = tk.Frame(main, bg=BG)
        frame.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        self.tree = ttk.Treeview(frame, columns=("status", "length"), show="tree headings")
        self.tree.heading("#0", text=tr("SCRIPT"), anchor="w")
        self.tree.heading("status", text=tr("STATUS"), anchor="w")
        self.tree.heading("length", text=tr("LENGTH"), anchor="e")
        self.tree.column("#0", width=320)
        self.tree.column("status", width=220)
        self.tree.column("length", width=90, anchor="e")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-Button-1>", self._play_batch_row)
        self.list_scripts()

    def pick_src(self):
        d = filedialog.askdirectory(title="Choose the scripts folder", initialdir=str(self._path(self.src)), mustexist=True)
        if d:
            self.src.set(self._short(d))
            self.list_scripts()

    def pick_dst(self):
        d = filedialog.askdirectory(title="Choose or create the output folder", initialdir=str(self._path(self.dst)))
        if d:
            self.dst.set(self._short(d))
            self.list_scripts()

    def list_scripts(self):
        self.tree.delete(*self.tree.get_children())
        src, out = self._path(self.src), self._path(self.dst)
        if not src.is_dir():
            self.batch_note.configure(text=tr("Choose a scripts folder."))
            return
        files, todo, _ = plan_batch(self.cfg, src, out, False)
        changed = {p.name for p in todo}
        for p in files:
            status = tr("will render") if p.name in changed else tr("up to date")
            self.tree.insert("", "end", iid=p.name, text=p.name, values=(status, ""))
        self.batch_note.configure(text=tr("{count} script(s) in {path} · {todo} to render",
                                          count=len(files), path=self._short(src), todo=len(changed)))

    def _play_batch_row(self, _e=None):
        sel = self.tree.selection()
        if sel:
            stem = Path(sel[0]).stem
            for ext in (".mp3", ".wav"):
                f = self._path(self.dst) / f"{stem}{ext}"
                if f.exists():
                    self.player.play(str(f))
                    return

    def render_batch(self):
        src, out, force = self._path(self.src), self._path(self.dst), self.force.get()
        if not src.is_dir():
            messagebox.showerror("Batch", tr("Folder not found:\n{path}", path=src))
            return
        files, todo, keys = plan_batch(self.cfg, src, out, force)
        if not todo:
            self.log(tr("All {count} scripts are up to date. Tick “Render everything again” to redo them.",
                        count=len(files)) + "\n", "accent")
            return
        if missing_voices(self.cfg) and self.cfg["engine"] != "dummy":
            messagebox.showerror("Batch", tr("Voice sample not found:\n{paths}", paths="\n".join(missing_voices(self.cfg))))
            return
        for p in todo:
            if self.tree.exists(p.name):
                self.tree.set(p.name, "status", tr("waiting…"))

        def work():
            synth = self._synth()
            synth.voice_override, synth.voice_overrides = None, {}
            results = run_batch(self.cfg, synth, todo, out, keys, log=print)
            self.q.put(("call", lambda: self._batch_done(results, out)))
        self.run(work, tr("Rendering {count} script(s)…", count=len(todo)))

    def _batch_done(self, results, out):
        ok = 0
        for r in results:
            name = r.get("file")
            if self.tree.exists(name):
                if "error" in r:
                    self.tree.set(name, "status", tr("error (see OUTPUT)"))
                else:
                    ok += 1
                    self.tree.set(name, "status", tr("done"))
                    self.tree.set(name, "length", tr("{seconds} s", seconds=r.get("seconds", 0)))
        self.log(tr("Rendered {ok} of {total} scripts. Files are in {path}/.",
                    ok=ok, total=len(results), path=self._short(out)) + "\n", "accent")

    # ------------------------------------------------------------- claude code
    def _build_claude(self):
        side = tk.Frame(self.sidebar, bg=SIDEBAR)
        self.side_frames["claude"] = side
        self._side_header(side, "claude")
        self.section(side, "Mode")
        self.cc_mode = tk.StringVar(value="ask" if FROZEN else "edit")
        modes = ((("ask", tr("Ask (no changes)")),) if FROZEN
                 else (("ask", tr("Ask (no changes)")), ("edit", tr("Edit the app"))))
        for value, text in modes:
            Choice(side, text, self.cc_mode, value=value, font=self.fonts["ui"], radio=True).pack(fill="x", padx=14, pady=2)
        self.cc_continue = tk.BooleanVar(value=True)
        Choice(side, "Continue conversation", self.cc_continue, font=self.fonts["ui"]).pack(anchor="w", padx=14, pady=(8, 0))
        self.section(side, "After a change")
        self.button(side, "⟳ Restart app", self.restart).pack(fill="x", padx=14, pady=(0, 6))
        self.button(side, "↶ Undo last change", self.undo_claude).pack(fill="x", padx=14)
        self.section(side, "VS Code")
        self.button(side, "Open in VS Code", self.open_vscode).pack(fill="x", padx=14, pady=(0, 6))
        self.button(side, "Copy request for VS Code", self.copy_for_vscode).pack(fill="x", padx=14)
        self.section(side, "Ideas")
        ideas = [tr("Make the sidebar 340 px wide"),
                 tr("Use a blue status bar like VS Code"),
                 tr("Add a Speed slider"),
                 tr("Show each output file's length"),
                 tr("Make the editor font size 14")]
        lb = tk.Listbox(side, bg=SIDEBAR, fg=FG, font=self.fonts["small"], relief="flat", height=len(ideas),
                        highlightthickness=0, selectbackground=SELECT, activestyle="none")
        for i in ideas:
            lb.insert("end", "• " + i)
        lb.pack(fill="x", padx=14)
        lb.bind("<<ListboxSelect>>", lambda e: lb.curselection() and self._use_idea(ideas[lb.curselection()[0]]))

        main = tk.Frame(self.content, bg=BG)
        self.main_frames["claude"] = main
        self.label(main, "Ask Claude Code to change or explain this app", "small", fg=FG_DIM, bg=BG).pack(fill="x", padx=16, pady=(12, 4))
        self.cc_prompt = tk.Text(main, height=4, bg=BG, fg=EDITOR_FG, font=self.fonts["mono"], relief="flat",
                                 insertbackground=CARET, highlightthickness=1, highlightbackground=BORDER,
                                 highlightcolor=CORAL, padx=8, pady=6, wrap="word")
        self.cc_prompt.pack(fill="x", padx=16)
        bar = tk.Frame(main, bg=BG)
        bar.pack(fill="x", padx=16, pady=8)
        self.cc_note = self.label(main, "", "small", fg=FG_DIM, bg=BG, justify="left", wraplength=760)
        self.cc_note.pack(fill="x", padx=16, pady=(0, 2), before=bar)
        self._claude_status()
        self.cc_btn = self.button(bar, tr("Send to Claude") + f"   {MOD_LABEL}↵", self.run_claude, primary=True, bg=BG)
        self.cc_btn.pack(side="left")
        self.button(bar, "■ Stop", self.stop_claude, bg=BG).pack(side="left", padx=6)
        frame = tk.Frame(main, bg=BG)
        frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self.cc_out = tk.Text(frame, bg=TRANSCRIPT, fg=FG, font=self.fonts["mono"], relief="flat",
                              highlightthickness=0, wrap="word", padx=10, pady=8, state="normal")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.cc_out.yview)
        self.cc_out.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.cc_out.pack(side="left", fill="both", expand=True)
        self.cc_out.tag_configure("you", foreground=CORAL, font=self.fonts["ui_b"])
        self.cc_out.tag_configure("tool", foreground=PAUSE)
        self.cc_out.tag_configure("dim", foreground=FG_DIM)
        self.cc_out.tag_configure("err", foreground=ERROR)
        self.cc_proc = None

    def _use_idea(self, text):
        self.cc_prompt.delete("1.0", "end")
        self.cc_prompt.insert("1.0", text)

    def claude_path(self):
        found = shutil.which("claude")
        if found:
            return found
        for p in (Path.home() / ".claude" / "local" / "claude", Path.home() / ".local" / "bin" / "claude",
                  Path("/opt/homebrew/bin/claude"), Path("/usr/local/bin/claude")):
            if p.exists():
                return str(p)
        return None

    def _claude_status(self):
        if FROZEN:
            self.cc_note.configure(text=tr("In the installed app, Claude can explain things but can't edit the "
                                           "app itself. To change the app, use the source version "
                                           "(pip install) and its Edit mode, or Claude Code in VS Code."))
        elif self.claude_path():
            self.cc_note.configure(text=tr("Uses the Claude Code command line with the same Claude login as "
                                           "VS Code. Edits are limited to reading and editing files; a backup "
                                           "is saved first, so Undo restores the previous version."))
        else:
            self.cc_note.configure(text=tr("The Claude Code command line (claude) isn't installed. Install it "
                                           "from code.claude.com/docs/en/setup, or use “Copy request for VS Code” and "
                                           "paste the request into the Claude panel in VS Code."))

    def _cc_context(self) -> str:
        return ("The user is customizing the ursoTTS desktop app from inside the app itself. "
                "The window is ursotts/app.py (Tkinter, VS Code Dark style; colors and fonts are defined near "
                "the top, each view has a _build_* method). Shared logic is in ursotts/shared.py; the web UI "
                "(ursotts/ui.py) and the pipeline must keep working, so don't change them unless asked. "
                "Make focused, working edits, keep the app's style, and finish with a short plain-language "
                "summary of what you changed. Tell the user to click “Restart app” to see the change."
                + (" The app is in Korean: reply to the user in Korean (the button is “⟳ 앱 다시 시작”)."
                   if i18n.get_language() == "ko" else ""))

    def cc_write(self, text, tag=None):
        self.cc_out.insert("end", text, tag)
        self.cc_out.see("end")

    def run_claude(self):
        prompt = self.cc_prompt.get("1.0", "end").strip()
        if not prompt:
            messagebox.showinfo("Claude Code", "Type what you'd like to change, or pick one of the ideas.")
            return
        exe = self.claude_path()
        if not exe:
            self._claude_status()
            if messagebox.askyesno("Claude Code", "The Claude Code command line isn't installed.\n\n"
                                   "Copy the request so you can paste it into Claude Code in VS Code?"):
                self.copy_for_vscode()
            return
        if self.cc_proc and self.cc_proc.poll() is None:
            messagebox.showinfo("Claude Code", "Claude is still working on the previous request.")
            return
        edit = self.cc_mode.get() == "edit"
        cmd = [exe, "-p", prompt, "--output-format", "stream-json", "--verbose",
               "--append-system-prompt", self._cc_context()]
        if edit:
            cmd += ["--permission-mode", "acceptEdits", "--allowedTools", "Read,Edit,Write,Glob,Grep"]
            self._snapshot()
        else:
            cmd += ["--permission-mode", "plan", "--allowedTools", "Read,Glob,Grep"]
        if self.cc_continue.get():
            cmd.append("--continue")
        self.cc_write(tr("\n▸ You ({mode}): ", mode=tr("edit") if edit else tr("ask")), "you")
        self.cc_write(prompt + "\n")
        self.cc_btn.configure(state="disabled", bg=ACCENT_OFF)
        self._set_status(tr("Claude Code is working…"))
        try:
            self.cc_proc = subprocess.Popen(cmd, cwd=str(self.project), stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, bufsize=1)
        except OSError as e:
            self.cc_write(tr("Could not start Claude Code: {error}", error=e) + "\n", "err")
            self._claude_finished(edit)
            return
        threading.Thread(target=self._read_claude, args=(self.cc_proc, edit), daemon=True).start()

    def _read_claude(self, proc, edit):
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                self.q.put(("cc", (line + "\n", "dim")))
                continue
            for text, tag in self._describe(ev):
                self.q.put(("cc", (text, tag)))
        proc.wait()
        self.q.put(("call", lambda: self._claude_finished(edit)))

    @staticmethod
    def _describe(ev):
        kind = ev.get("type")
        if kind == "assistant":
            for part in (ev.get("message") or {}).get("content") or []:
                if part.get("type") == "text" and part.get("text", "").strip():
                    yield part["text"].strip() + "\n", None
                elif part.get("type") == "tool_use":
                    inp = part.get("input") or {}
                    target = inp.get("file_path") or inp.get("path") or inp.get("pattern") or ""
                    yield f"  ⚙ {part.get('name')} {Path(target).name if '/' in str(target) else target}\n", "tool"
        elif kind == "result":
            if ev.get("is_error"):
                yield tr("Claude Code reported an error: {error}", error=ev.get("result", "")) + "\n", "err"
            secs = (ev.get("duration_ms") or 0) / 1000
            yield tr("  done in {seconds:.0f} s", seconds=secs) + "\n", "dim"

    def _claude_finished(self, edit):
        self.cc_btn.configure(state="normal", bg=self.cc_btn._color)
        self._set_status()
        if edit:
            changed = self._changed_files()
            if changed:
                self.cc_write(tr("  changed: {files}", files=", ".join(changed)) + "\n", "tool")
                self.cc_write(tr("  Click “⟳ Restart app” to see the change, or “↶ Undo last change” to go back.") + "\n", "dim")
                self.log(tr("Claude Code changed: {files}", files=", ".join(changed)) + "\n", "accent")
            else:
                self.cc_write(tr("  no files were changed") + "\n", "dim")

    def stop_claude(self):
        if self.cc_proc and self.cc_proc.poll() is None:
            self.cc_proc.terminate()
            self.cc_write(tr("  stopped") + "\n", "err")

    # snapshots for Undo: the app's own files only
    def _tracked(self):
        pkg = Path(__file__).parent
        files = [p for p in pkg.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        files += [self.project / n for n in ("config.yaml", "pronunciations.yaml", "CLAUDE.md") if (self.project / n).exists()]
        return files

    def _snapshot(self):
        root = self.project / ".cache" / "claude_undo" / time.strftime("%Y%m%d_%H%M%S")
        for f in self._tracked():
            dst = root / f.resolve().relative_to(self.project.resolve()) if self._inside(f) else root / "_pkg" / f.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
        self.last_snapshot = root
        olds = sorted((self.project / ".cache" / "claude_undo").iterdir())
        for old in olds[:-5]:  # keep the last five
            shutil.rmtree(old, ignore_errors=True)

    def _inside(self, f):
        try:
            f.resolve().relative_to(self.project.resolve())
            return True
        except ValueError:
            return False

    def _changed_files(self):
        snap = getattr(self, "last_snapshot", None)
        if not snap:
            return []
        out = []
        for f in self._tracked():
            old = snap / f.resolve().relative_to(self.project.resolve()) if self._inside(f) else snap / "_pkg" / f.name
            if not old.exists() or old.read_bytes() != f.read_bytes():
                out.append(f.name)
        return out

    def undo_claude(self):
        base = self.project / ".cache" / "claude_undo"
        snaps = sorted(base.iterdir()) if base.is_dir() else []
        if not snaps:
            messagebox.showinfo("Undo", "There's no saved version to go back to yet.")
            return
        snap = snaps[-1]
        if not messagebox.askyesno("Undo last change", tr("Restore the app files saved before the last Claude edit "
                                                          "({name})? Then restart the app.", name=snap.name)):
            return
        for f in snap.rglob("*"):
            if f.is_file():
                rel = f.relative_to(snap)
                dst = (Path(__file__).parent / rel.name) if rel.parts[0] == "_pkg" else self.project / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
        shutil.rmtree(snap, ignore_errors=True)
        self.cc_write(tr("  restored the previous version; click “⟳ Restart app”") + "\n", "tool")
        self.log(tr("Undo: restored app files from {name}", name=snap.name) + "\n", "accent")

    def open_vscode(self):
        code = shutil.which("code") or ("/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
                                        if Path("/Applications/Visual Studio Code.app").exists() else None)
        if code:
            subprocess.Popen([code, str(self.project), str(Path(__file__))])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-a", "Visual Studio Code", str(self.project)])
        else:
            messagebox.showinfo("VS Code", "VS Code wasn't found. Open the project folder in VS Code yourself.")

    def copy_for_vscode(self):
        prompt = self.cc_prompt.get("1.0", "end").strip() or tr("(describe your change here)")
        text = (f"{prompt}\n\nContext: this is for the ursoTTS desktop app, @ursotts/app.py "
                "(Tkinter, VS Code Dark style). Keep the web UI (ursotts/ui.py) and the pipeline working.")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.cc_write(tr("  copied: paste it into the Claude panel in VS Code") + "\n", "dim")

    def restart(self):
        if not self.ok_to_close():
            return
        self._save_layout()
        self.player.stop()
        self.root.destroy()
        os.execv(sys.executable, [sys.executable, "-m", "ursotts", "app", *RESTART_ARGS])

    # ------------------------------------------------------------- engine
    def _synth(self) -> Synthesizer:
        g = {k: round(v.get(), 2) for k, v in self.style_vars.items()}
        seed = self.seed.get().strip()
        g["seed"] = int(seed) if seed.lstrip("-").isdigit() else None
        self.cfg["generation"].update(g)
        if self.synth is None:
            from .engine import make_engine
            print(tr("[ursotts] loading the voice model (first time only)…"))
            t0 = time.time()
            self.synth = Synthesizer(self.cfg, make_engine(self.cfg))
            print(tr("[ursotts] voice model ready in {seconds:.1f} s", seconds=time.time() - t0))
            self.q.put(("call", self._set_status))
        self.synth.engine.update(**g)
        return self.synth

    def _voice_overrides(self):
        return {k: self.voice_files[v.get()] for k, v in (("en", self.voice_en), ("ko", self.voice_ko))
                if v.get() in self.voice_files}

    def generate(self):
        text = self.script.get("1.0", "end-1c")
        if not text.strip():
            messagebox.showinfo("Speak", "Type or paste some text first.")
            return
        overrides = self._voice_overrides()
        if not overrides and self.cfg["engine"] != "dummy":
            messagebox.showerror("Speak", "No voice found. Use “+ Add voice file…” to add a WAV or MP3 sample.")
            return
        run_cfg = {**self.cfg, "lang_mode": self.lang_codes.get(self.lang.get(), "auto")}

        def work():
            synth = self._synth()
            synth.voice_override, synth.voice_overrides = None, overrides
            out_dir = self.out_root / "app"
            out_dir.mkdir(parents=True, exist_ok=True)
            stem = time.strftime("app_%Y%m%d_%H%M%S")
            src = out_dir / f"{stem}.txt"
            src.write_text(text, encoding="utf-8")
            try:
                r = process_file(src, out_dir, synth, run_cfg, log=print)
            finally:
                synth.voice_overrides = {}
            made = [str(out_dir / f"{stem}{e}") for e in (".mp3", ".wav", ".srt") if (out_dir / f"{stem}{e}").exists()]
            self.q.put(("call", lambda: self._speak_done(r, made)))
        self.run(work, "Generating narration…")

    def _speak_done(self, r, made):
        for f in reversed(made):
            if f.endswith((".mp3", ".wav")):
                self.file_paths.insert(0, f)
                self.files.insert(0, Path(f).name)
        self.log(tr("Made {seconds} s of audio in {took} s → {path}/",
                    seconds=r["seconds"], took=r["render_time"], path=Path(made[0]).parent) + "\n", "accent")
        if self.autoplay.get() and made:
            self.player.play(made[0])

    def run_current(self):
        {"speak": self.generate, "pron": self.listen, "batch": self.render_batch,
         "claude": self.run_claude}[self.view]()

    # ------------------------------------------------------------- tasks
    def run(self, work, busy_text):
        if self.busy:
            messagebox.showinfo("ursoTTS", "Please wait: another task is still running.")
            return
        self.busy = True
        self._set_status(tr(busy_text))
        self.busy_bar.pack(side="right", padx=(0, 4))
        self.busy_bar.start(15)
        for b in (self.gen_btn, self.listen_btn, self.batch_btn):
            b.configure(state="disabled", bg=ACCENT_OFF)
        if not self.panel_visible:
            self.toggle_panel()

        def wrapper():
            writer = QueueWriter(self.q)
            try:
                with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                    work()
            except Exception as e:  # shown in the panel instead of crashing the window
                self.q.put(("error", f"{type(e).__name__}: {tr_exc(e)}\n"))
            finally:
                writer.flush()
                self.q.put(("done", None))
        threading.Thread(target=wrapper, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "live":
                    self.live(payload)
                elif kind == "error":
                    self.log(payload, "error")
                elif kind == "cc":
                    self.cc_write(*payload)
                elif kind == "call":
                    payload()
                elif kind == "done":
                    self.busy = False
                    self._end_live()
                    self.busy_bar.stop()
                    self.busy_bar.pack_forget()
                    for b in (self.gen_btn, self.listen_btn, self.batch_btn):
                        b.configure(state="normal", bg=b._color)
                    self._set_status()
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _set_status(self, busy: str | None = None):
        engine = self.cfg.get("engine", "chatterbox")
        model = tr("model ready") if self.synth else tr("model loads on first run")
        self.status_left.configure(text=tr("  ursoTTS {version}   ·   engine: {engine}   ·   {model}",
                                           version=__version__, engine=engine, model=model))
        self.status_right.configure(text=busy or tr("Ready   ·   {mod}J panel   ·   {mod}↵ run", mod=MOD_LABEL))

    def open_settings(self):
        path = (self.project / "config.yaml").resolve()
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-t", str(path)])
        elif sys.platform.startswith("win"):
            os.startfile(str(path))  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(path)])

    # ------------------------------------------------------------- layout memory
    def _load_layout(self) -> dict:
        try:
            return json.loads(LAYOUT_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_layout(self):
        try:
            data = {"geometry": self.root.geometry(), "view": self.view, "panel": self.panel_visible,
                    "sidebar": self.sidebar.winfo_width(),
                    "panel_height": self.panel.winfo_height() if self.panel_visible else self.layout.get("panel_height", 210),
                    "batch_src": str(self._path(self.src)), "batch_out": str(self._path(self.dst)), "zoom": self.zoom_level,
                    "theme": self.theme,
                    **({"ui_lang": self.ui_choice} if self.ui_choice else {}),
                    "script": self.script.get("1.0", "end-1c"),
                    "script_path": str(self.script_path) if self.script_path else None,
                    "saved_text": self.saved_text if self.script_path else None}
            LAYOUT_FILE.parent.mkdir(parents=True, exist_ok=True)
            LAYOUT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    def create_launcher(self):
        from .launcher import make_launcher
        try:
            made = make_launcher(self.project)
        except (SystemExit, Exception) as e:
            messagebox.showerror("Create launcher", tr_line(str(e)))
            return
        where = "\n".join(self._short(p) for p in made)
        tip = {"darwin": tr("Open it from Applications in your home folder, or drag it to the Dock.")}.get(
            sys.platform, tr("Double-click it to open ursoTTS without a terminal."))
        self.log(tr("Created launcher: {where}", where=where) + "\n", "accent")
        messagebox.showinfo("Launcher created", tr("Created:\n{where}", where=where) + "\n\n" + tip)

    def set_theme(self, name: str):
        """Switch theme: saved, then the window restarts (script, folders and layout are kept)."""
        if name == self.theme:
            return
        previous, self.theme = self.theme, name
        self.theme_var.set(name)
        self.restart()                           # asks first about unsaved changes or running work
        self.theme = previous                    # only reached when the restart was cancelled
        self.theme_var.set(previous)

    def set_ui_language(self, code: str):
        """View > Language: save the choice, then restart so every label is rebuilt."""
        self.ui_choice = code
        self.lang_var.set(code)
        if code == i18n.get_language():          # already showing it: just remember the choice
            self._save_layout()
            return
        # the question is shown in both languages so it reads right whichever one is active now
        if messagebox.askyesno("Language / 언어", i18n.both("Restart ursoTTS to apply."), icon="question", default="yes"):
            self.restart()                       # asks about unsaved changes or running work first
        self._save_layout()                      # not restarted: the choice applies at the next launch

    def pick_theme(self):
        """A small VS Code–style quick pick: arrow keys to choose, Enter to apply, Esc to close."""
        win = tk.Toplevel(self.root, bg=BORDER, padx=1, pady=1)
        win.title(tr("Color Theme"))
        win.transient(self.root)
        win.resizable(False, False)
        inner = tk.Frame(win, bg=SIDEBAR)
        inner.pack(fill="both", expand=True)
        self.label(inner, "  " + tr("Select Color Theme"), "head", fg=FG_DIM, pady=8).pack(fill="x")
        names = list(THEMES)
        lb = tk.Listbox(inner, height=len(names), bg=SIDEBAR, fg=FG, font=self.fonts["ui"], relief="flat",
                        highlightthickness=0, selectbackground=SELECT, selectforeground=FG_BRIGHT,
                        activestyle="none", width=26)
        for n in names:
            lb.insert("end", f"  {n}" + (tr("   (current)") if n == self.theme else ""))
        lb.pack(fill="both", padx=6, pady=(0, 8))
        i = names.index(self.theme)
        lb.selection_set(i)
        lb.activate(i)
        lb.focus_set()
        def choose(_e=None):
            sel = lb.curselection()
            win.destroy()
            if sel:
                self.set_theme(names[sel[0]])
        lb.bind("<Return>", choose)
        lb.bind("<Double-Button-1>", choose)
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        win.geometry(f"+{x}+{self.root.winfo_rooty() + 80}")

    def ok_to_close(self) -> bool:
        if self.busy and not messagebox.askyesno(
                "ursoTTS is still working", "Narration is still being made. Quit anyway and stop it?",
                icon="warning", default="no"):
            return False
        return self.confirm_unsaved()

    def quit(self):
        if not self.ok_to_close():
            return
        self._save_layout()
        self.stop_claude()
        self.player.stop()
        self.root.destroy()


FONTS_DIR = Path(__file__).parent / "assets" / "fonts"


def register_brand_fonts() -> None:
    """Make the bundled Poppins fonts available to this app only (no install).
    macOS: CoreText, process scope. Windows: GDI private fonts. Linux: fontconfig.
    If anything fails, the app falls back to the system's sans-serif font."""
    files = sorted(FONTS_DIR.glob("*.ttf"))
    if not files:
        return
    try:
        import ctypes
        import ctypes.util
        if sys.platform == "darwin":
            cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
            ct = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreText"))
            cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
            cf.CFURLCreateFromFileSystemRepresentation.argtypes = [
                ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool]
            ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
            ct.CTFontManagerRegisterFontsForURL.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
            for f in files:
                raw = str(f).encode("utf-8")
                url = cf.CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), False)
                if url:
                    ct.CTFontManagerRegisterFontsForURL(url, 1, None)   # 1 = this process only
        elif sys.platform.startswith("win"):
            for f in files:
                ctypes.windll.gdi32.AddFontResourceExW(str(f), 0x10, 0)  # 0x10 = FR_PRIVATE
        else:
            fc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("fontconfig"))
            fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            for f in files:
                fc.FcConfigAppFontAddFile(None, str(f).encode("utf-8"))
    except Exception:
        pass


def set_macos_app_name(name: str = "ursoTTS") -> None:
    """Show `name` instead of "python3.x" in the macOS menu bar (and the Dock's
    app menu) when the app runs from Python rather than from the installed .app.

    macOS reads the name from the running program's bundle info, so we set
    CFBundleName there before Tk creates the window, using the Objective-C
    runtime through ctypes (no extra package needed). Harmless if it fails."""
    if sys.platform != "darwin" or FROZEN:
        return
    try:
        import ctypes
        import ctypes.util
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        ctypes.cdll.LoadLibrary(ctypes.util.find_library("Foundation"))
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        def send(obj, selector, *args, argtypes=()):
            # objc_msgSend must be called through the exact prototype (required on Apple Silicon)
            proto = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, *argtypes)
            fn = ctypes.cast(objc.objc_msgSend, proto)
            return fn(obj, objc.sel_registerName(selector), *args)

        def nsstring(text):
            return send(objc.objc_getClass(b"NSString"), b"stringWithUTF8String:",
                        text.encode("utf-8"), argtypes=(ctypes.c_char_p,))

        # Python as a plain program (e.g. Homebrew): macOS shows the process name
        pinfo = send(objc.objc_getClass(b"NSProcessInfo"), b"processInfo")
        if pinfo:
            send(pinfo, b"setProcessName:", nsstring(name), argtypes=(ctypes.c_void_p,))
        # Python as an app bundle (python.org): macOS shows the bundle name
        bundle = send(objc.objc_getClass(b"NSBundle"), b"mainBundle")
        info = send(bundle, b"infoDictionary")
        # only write if the dictionary accepts changes (writing to a read-only one would crash)
        responds = ctypes.cast(objc.objc_msgSend, ctypes.CFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p))
        if info and responds(info, objc.sel_registerName(b"respondsToSelector:"),
                             objc.sel_registerName(b"setObject:forKey:")):
            send(info, b"setObject:forKey:", nsstring(name), nsstring("CFBundleName"),
                 argtypes=(ctypes.c_void_p, ctypes.c_void_p))
    except Exception:
        pass


def launch(cfg: dict, restart_args: list[str] | None = None):
    RESTART_ARGS[:] = restart_args or []
    set_macos_app_name("ursoTTS")          # menu bar shows "ursoTTS", not "python3.x"
    register_brand_fonts()                 # Poppins, bundled with ursoTTS
    try:
        root = tk.Tk(className="ursoTTS")
    except tk.TclError as e:
        raise SystemExit(f"Could not open a window ({e}). The desktop app needs a display; "
                         "use `ursotts ui` for the web UI instead.")
    root.withdraw()
    splash = None
    try:  # a short splash while the window is being built
        splash = tk.Toplevel(root)
        splash.overrideredirect(True)
        img = tk.PhotoImage(file=str(ASSETS / "splash_960x540.png"))
        splash._img = img
        tk.Label(splash, image=img, bd=0).pack()
        x = (splash.winfo_screenwidth() - 960) // 2
        y = (splash.winfo_screenheight() - 540) // 3
        splash.geometry(f"960x540+{x}+{y}")
        splash.update()
    except tk.TclError:
        splash = None
    App(root, cfg)

    def reveal_main():
        if splash is not None:
            splash.destroy()
        root.deiconify()
        root.lift()
    root.after(1200, reveal_main)
    root.mainloop()
