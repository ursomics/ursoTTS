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
from tkinter import filedialog, font as tkfont, messagebox, ttk

import yaml

from . import __version__, audio
from .pipeline import Synthesizer, missing_voices, plan_batch, process_file, run_batch
from .shared import (AUDIO_EXTS, CORAL, DEEP_CORAL, LANGS, MAX_CANDIDATES, UserError,
                     prepare_sample, suggest_spellings, upsert_pronunciation)
from .text import Speech, render_say

# VS Code Dark+ colors, with the ursoTTS coral as the accent
BG = "#1E1E1E"          # editor
SIDEBAR = "#252526"
ACTIVITY = "#333333"
TABBAR = "#252526"
TAB_IDLE = "#2D2D2D"
PANEL = "#1E1E1E"
BORDER = "#3C3C3C"
INPUT = "#3C3C3C"
FG = "#CCCCCC"
FG_DIM = "#8B8B8B"
FG_BRIGHT = "#FFFFFF"
SELECT = "#264F78"
HOVER = "#2A2D2E"

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
                self.q.put(("log", piece + "\n"))

    def flush(self):
        if self.buf.strip():
            self.q.put(("log", self.buf))
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

    def __init__(self, parent, text, variable, value=None, bg=SIDEBAR, font=None, radio=False):
        super().__init__(parent, bg=bg, cursor="hand2")
        self.var, self.value, self.radio = variable, value, radio
        self.size = 16
        self.canvas = tk.Canvas(self, width=self.size + 2, height=self.size + 2, bg=bg,
                                highlightthickness=0, bd=0)
        self.canvas.pack(side="left")
        self.text = tk.Label(self, text=text, bg=bg, fg=FG, font=font, anchor="w")
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
        edge = CORAL if on else ("#9D9D9D" if hover else "#6B6B6B")
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
                              fill=FG_BRIGHT, width=2.2, capstyle="round", joinstyle="round")


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
        sans = ("Poppins", "SF Pro Text", "Segoe UI", "Helvetica Neue", "Helvetica", "DejaVu Sans")
        mono = ("Menlo", "SF Mono", "Consolas", "DejaVu Sans Mono")
        specs = {
            "ui": _font(*sans, size=14),
            "ui_b": _font("Poppins SemiBold", *sans, size=14, weight="bold"),
            "small": _font(*sans, size=12),
            "head": _font("Poppins SemiBold", *sans, size=11, weight="bold"),
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
        self.log(f"ursoTTS {__version__} desktop app. Project folder: {self._short(self.project)}\n")
        self.log("The voice model loads the first time you generate; later runs are quick.\n")

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
            self._icons = [tk.PhotoImage(file=str(ASSETS / "icons" / f"icon_{n}.png")) for n in (32, 64, 128, 256)]
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
                    indicatorforeground=FG_BRIGHT, focuscolor=SIDEBAR)
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
        s.configure("Vertical.TScrollbar", background="#424242", troughcolor=BG, bordercolor=BG,
                    lightcolor="#424242", darkcolor="#424242", gripcount=0, width=10)
        s.map("Vertical.TScrollbar", background=[("active", "#4F4F4F"), ("!active", "#424242")])

    # ------------------------------------------------------------- widgets
    def label(self, parent, text, kind="ui", fg=FG, bg=SIDEBAR, **kw):
        return tk.Label(parent, text=text, font=self.fonts[kind], fg=fg, bg=bg, anchor="w", **kw)

    def button(self, parent, text, command, primary=False, bg=SIDEBAR, **kw):
        color = CORAL if primary else "#3A3D41"
        hover = DEEP_CORAL if primary else "#45494E"
        b = tk.Label(parent, text=text, font=self.fonts["ui_b" if primary else "ui"], fg=FG_BRIGHT,
                     bg=color, padx=14, pady=6, cursor="hand2", **kw)
        b.bind("<Button-1>", lambda e: command() if str(b.cget("state")) != "disabled" else None)
        b.bind("<Enter>", lambda e: b.configure(bg=hover) if str(b.cget("state")) != "disabled" else None)
        b.bind("<Leave>", lambda e: b.configure(bg=color))
        b._color = color
        return b

    def entry(self, parent, var, width=28, bg=SIDEBAR):
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
        self.label(f, title.upper(), "head", fg=FG_DIM).pack(fill="x")
        return f

    def field(self, parent, text):
        self.label(parent, text, "small", fg=FG_DIM).pack(fill="x", padx=14, pady=(8, 2))

    # ------------------------------------------------------------- layout
    def _build(self):
        r = self.root
        self._menu()
        self.status = tk.Frame(r, bg=CORAL, height=24)
        self.status.pack(side="bottom", fill="x")
        self.status_left = tk.Label(self.status, text="", font=self.fonts["small"], fg=FG_BRIGHT, bg=CORAL)
        self.status_left.pack(side="left", padx=10)
        self.status_right = tk.Label(self.status, text="", font=self.fonts["small"], fg=FG_BRIGHT, bg=CORAL)
        self.status_right.pack(side="right", padx=10)
        # a small sliding bar while ursoTTS is working
        ttk.Style(r).configure("Busy.Horizontal.TProgressbar", troughcolor=DEEP_CORAL, background=FG_BRIGHT,
                               bordercolor=CORAL, lightcolor=FG_BRIGHT, darkcolor=FG_BRIGHT, thickness=6)
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
                                        self.status_right.configure(text="Settings (config.yaml)")))
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
        file.add_command(label="Open script…", accelerator=f"{MOD_LABEL}O", command=self.open_script)
        file.add_command(label="Save script", accelerator=f"{MOD_LABEL}S", command=self.save_script)
        file.add_command(label="Save script as…", accelerator=f"⇧{MOD_LABEL}S" if MOD_LABEL == "⌘" else "Ctrl+Shift+S",
                         command=self.save_script_as)
        file.add_separator()
        file.add_command(label="Show output folder", command=lambda: reveal(self.out_root.resolve()))
        if not FROZEN:
            file.add_command(label="Create launcher…", command=self.create_launcher)
        file.add_separator()
        file.add_command(label="Quit", accelerator=f"{MOD_LABEL}Q", command=self.quit)
        m.add_cascade(label="File", menu=file)
        view = tk.Menu(m, tearoff=False)
        for i, v in enumerate(VIEWS, 1):
            view.add_command(label=TITLES[v].title(), accelerator=f"{MOD_LABEL}{i}", command=lambda v=v: self.show(v))
        view.add_separator()
        view.add_command(label="Toggle output panel", accelerator=f"{MOD_LABEL}J", command=self.toggle_panel)
        view.add_separator()
        view.add_command(label="Zoom in", accelerator=f"{MOD_LABEL}+", command=lambda: self.zoom(+1))
        view.add_command(label="Zoom out", accelerator=f"{MOD_LABEL}−", command=lambda: self.zoom(-1))
        view.add_command(label="Actual size", accelerator=f"{MOD_LABEL}0", command=lambda: self.zoom(0))
        m.add_cascade(label="View", menu=view)
        helpm = tk.Menu(m, tearoff=False)
        helpm.add_command(label="ursoTTS manual", command=lambda: webbrowser.open(MANUAL_URL))
        helpm.add_command(label="Open config.yaml", command=self.open_settings)
        helpm.add_separator()
        helpm.add_command(label="About ursoTTS", command=self.about)
        m.add_cascade(label="Help", menu=helpm)
        self.root.configure(menu=m)

    def _shortcuts(self):
        r = self.root
        for i, v in enumerate(VIEWS, 1):
            r.bind_all(f"<{MOD}-Key-{i}>", lambda e, v=v: self.show(v))
        r.bind_all(f"<{MOD}-j>", lambda e: self.toggle_panel())
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
            self._set_status(f"Zoom {round(self._scale() * 100)}%")
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
            self.status_right.configure(text=TITLES[view].title())
        else:
            self._set_status()

    def _tab(self, view):
        for w in self.tabbar.winfo_children():
            w.destroy()
        tab = tk.Frame(self.tabbar, bg=BG)
        tab.pack(side="left", fill="y")
        tk.Frame(tab, bg=CORAL, height=2).pack(fill="x", side="top")
        self.label(tab, f"  {TAB_NAMES[view]}  ", "ui", fg=FG_BRIGHT, bg=BG, pady=6).pack(side="left")

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

    def about(self):
        win = tk.Toplevel(self.root, bg=BG)
        win.title("About ursoTTS")
        win.resizable(False, False)
        win.transient(self.root)
        self._about_img = tk.PhotoImage(file=str(ASSETS / "about_400x400.png"))
        tk.Label(win, image=self._about_img, bg=BG).pack()
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
        clear = tk.Label(head, text="Clear", font=self.fonts["small"], fg=FG_DIM, bg=PANEL, padx=8, cursor="hand2")
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
        self.logbox.tag_configure("error", foreground="#F48771")
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
            text = f"  generating… {tokens} tokens (≈{seconds:.1f} s of speech)"
            if speed:
                text += f" · {float(speed):.1f} tokens/s"
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
        self.lang = tk.StringVar(value="Auto (English + Korean)")
        ttk.Combobox(side, textvariable=self.lang, values=list(LANGS), state="readonly", font=self.fonts["ui"]).pack(fill="x", padx=14)

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
        for key, label, lo, hi, hint in (("exaggeration", "Expressiveness", 0.25, 1.0, "calm … animated"),
                                         ("cfg_weight", "Pacing", 0.0, 1.0, "slower … faster"),
                                         ("temperature", "Variation", 0.3, 1.2, "steady … varied")):
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
        self.gen_btn = self.button(bar, f"Generate narration   {MOD_LABEL}↵", self.generate, primary=True, bg=BG)
        self.gen_btn.pack(side="right")
        self.autoplay = tk.BooleanVar(value=True)
        Choice(bar, "Play when done", self.autoplay, bg=BG, font=self.fonts["small"]).pack(side="right", padx=12)
        ed = tk.Frame(main, bg=BG)
        ed.pack(fill="both", expand=True, padx=(0, 0), pady=(0, 6))
        self.gutter = tk.Canvas(ed, width=48, bg=BG, highlightthickness=0, bd=0)
        self.gutter.pack(side="left", fill="y")
        self.script = tk.Text(ed, bg=BG, fg="#D4D4D4", font=self.fonts["mono"], relief="flat", undo=True,
                              insertbackground="#AEAFAD", selectbackground=SELECT, highlightthickness=0,
                              wrap="word", padx=8, pady=8)
        sb = ttk.Scrollbar(ed, orient="vertical", command=self._scroll_script)
        self.script.configure(yscrollcommand=lambda a, b: (sb.set(a, b), self._sync_gutter()))
        sb.pack(side="right", fill="y")
        self.script.pack(side="left", fill="both", expand=True)
        self.script.tag_configure("comment", foreground="#6A9955")
        self.script.tag_configure("directive", foreground="#C586C0")
        self.script.tag_configure("pause", foreground="#4EC9B0")
        self.script.bind("<<Modified>>", self._on_script_change)
        self.script.bind("<Configure>", lambda e: self.root.after_idle(self._sync_gutter))
        hint = ("# Paste or type your narration here. Lines starting with # are not spoken.\n"
                "@lang auto\nWelcome to Ursomics. Today we analyze scRNA-seq data.\n\n"
                "안녕하세요, Ursomics입니다. [pause 1] 오늘은 DNA 분석을 해 보겠습니다.\n")
        self.script.insert("1.0", self.layout.get("script", hint))
        sp = self.layout.get("script_path")
        if sp and Path(sp).exists():          # the editor still belongs to that file
            self.script_path, self.saved_text = Path(sp), self.layout.get("saved_text") or ""
        self._update_tab_title()
        self._highlight()

    @staticmethod
    def _short(path) -> str:
        """Show paths inside the home folder as ~/…"""
        p, home = str(path), str(Path.home())
        return "~" + p[len(home):] if p == home or p.startswith(home + os.sep) else p

    def _side_header(self, side, view):
        self.label(side, f"  {TITLES[view]}", "head", fg=FG_DIM, pady=10).pack(fill="x")

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
                          fill="#858585", font=self.fonts["mono"])
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
            messagebox.showerror("Voice sample", str(e))
            return
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^\w\-]+", "_", Path(path).stem).strip("_") or "my_voice"
        target = self.voices_dir / f"{name}.wav"
        target.write_bytes(Path(prepared).read_bytes())
        self.refresh_voices()
        self.log(f"Added voice {target.name} (converted to mono 24 kHz, silence trimmed).\n", "accent")

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
            messagebox.showerror("Save script", f"Could not save {path}:\n{e}")
            return False
        self.script_path, self.saved_text = path, text
        self._update_tab_title()
        self.log(f"Saved {self._short(path)}\n")
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
            "Unsaved changes", f"Save changes to {self.script_path.name} before closing it?",
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
        self.pron_lang = tk.StringVar(value="English")
        ttk.Combobox(side, textvariable=self.pron_lang, values=["English", "Korean"], state="readonly", font=self.fonts["ui"]).pack(fill="x", padx=14)
        self.section(side, "Test sentence")
        self.context = tk.StringVar(value="Today we look at {word} in our data.")
        self.entry(side, self.context).pack(fill="x", padx=14)
        self.note(side, "{word} is replaced by each spelling").pack(fill="x", padx=14, pady=(2, 0))
        row = tk.Frame(side, bg=SIDEBAR)
        row.pack(fill="x", padx=14, pady=14)
        self.button(row, "Suggest spellings", self.suggest).pack(side="left")
        tips = ("Letters: each capital followed by a dot (R.N.A.).\n"
                "Word-like sounds: syllables joined by dots (NAN.og).\n"
                "Genes with a vowel 2nd letter: try the word form first.\n"
                "Korean: write the Hangul reading (피디엘원).")
        self.section(side, "Tips")
        self.note(side, tips).pack(fill="x", padx=14)

        main = tk.Frame(self.content, bg=BG)
        self.main_frames["pron"] = main
        self.label(main, "Versions to compare, one per line", "small", fg=FG_DIM, bg=BG).pack(fill="x", padx=16, pady=(12, 4))
        self.cands = tk.Text(main, height=6, bg=BG, fg="#D4D4D4", font=self.fonts["mono"], relief="flat",
                             insertbackground="#AEAFAD", highlightthickness=1, highlightbackground=BORDER,
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
        lang = "ko" if self.pron_lang.get() == "Korean" else "en"
        self.cands.delete("1.0", "end")
        self.cands.insert("1.0", "\n".join(suggest_spellings(term, self.cfg, lang)))

    def listen(self):
        term = self.term.get().strip() or "word"
        cands = [c.strip() for c in self.cands.get("1.0", "end").splitlines() if c.strip()][:MAX_CANDIDATES]
        if not cands:
            messagebox.showinfo("Pronunciation", "Add at least one spelling, or click Suggest spellings.")
            return
        lang = "ko" if self.pron_lang.get() == "Korean" else "en"
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
        lang = "ko" if self.pron_lang.get() == "Korean" else "en"
        path = Path(self.cfg.get("pronunciations_path") or "pronunciations.yaml")
        upsert_pronunciation(path, lang, term, choice, self.like.get())
        self.cfg["pronunciation_table"] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self.log(f"Saved {term} → {choice} (voice reads “{render_say(choice)}”). "
                 "Scripts that use it are re-rendered on the next batch.\n", "accent")

    # ------------------------------------------------------------- batch
    def _build_batch(self):
        side = tk.Frame(self.sidebar, bg=SIDEBAR)
        self.side_frames["batch"] = side
        self._side_header(side, "batch")
        self.src = tk.StringVar(value=str(self.layout.get("batch_src", self.project / "scripts")))
        self.dst = tk.StringVar(value=str(self.layout.get("batch_out", self.project / "output")))
        for title, var, cmd in (("Scripts folder", self.src, self.pick_src), ("Output folder", self.dst, self.pick_dst)):
            self.section(side, title)
            self.entry(side, var).pack(fill="x", padx=14)
            row = tk.Frame(side, bg=SIDEBAR)
            row.pack(fill="x", padx=14, pady=(6, 0))
            self.button(row, "Choose…", cmd).pack(side="left")
            self.button(row, "Show", lambda var=var: reveal(Path(var.get()))).pack(side="left", padx=6)
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
        self.tree.heading("#0", text="SCRIPT", anchor="w")
        self.tree.heading("status", text="STATUS", anchor="w")
        self.tree.heading("length", text="LENGTH", anchor="e")
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
        d = filedialog.askdirectory(title="Choose the scripts folder", initialdir=self.src.get(), mustexist=True)
        if d:
            self.src.set(d)
            self.list_scripts()

    def pick_dst(self):
        d = filedialog.askdirectory(title="Choose or create the output folder", initialdir=self.dst.get())
        if d:
            self.dst.set(d)
            self.list_scripts()

    def list_scripts(self):
        self.tree.delete(*self.tree.get_children())
        src, out = Path(self.src.get()), Path(self.dst.get())
        if not src.is_dir():
            self.batch_note.configure(text="Choose a scripts folder.")
            return
        files, todo, _ = plan_batch(self.cfg, src, out, False)
        changed = {p.name for p in todo}
        for p in files:
            status = "will render" if p.name in changed else "up to date"
            self.tree.insert("", "end", iid=p.name, text=p.name, values=(status, ""))
        self.batch_note.configure(text=f"{len(files)} script(s) in {src} · {len(changed)} to render")

    def _play_batch_row(self, _e=None):
        sel = self.tree.selection()
        if sel:
            stem = Path(sel[0]).stem
            for ext in (".mp3", ".wav"):
                f = Path(self.dst.get()) / f"{stem}{ext}"
                if f.exists():
                    self.player.play(str(f))
                    return

    def render_batch(self):
        src, out, force = Path(self.src.get()), Path(self.dst.get()), self.force.get()
        if not src.is_dir():
            messagebox.showerror("Batch", f"Folder not found:\n{src}")
            return
        files, todo, keys = plan_batch(self.cfg, src, out, force)
        if not todo:
            self.log(f"All {len(files)} scripts are up to date. Tick “Render everything again” to redo them.\n", "accent")
            return
        if missing_voices(self.cfg) and self.cfg["engine"] != "dummy":
            messagebox.showerror("Batch", "Voice sample not found:\n" + "\n".join(missing_voices(self.cfg)))
            return
        for p in todo:
            if self.tree.exists(p.name):
                self.tree.set(p.name, "status", "waiting…")

        def work():
            synth = self._synth()
            synth.voice_override, synth.voice_overrides = None, {}
            results = run_batch(self.cfg, synth, todo, out, keys, log=print)
            self.q.put(("call", lambda: self._batch_done(results, out)))
        self.run(work, f"Rendering {len(todo)} script(s)…")

    def _batch_done(self, results, out):
        ok = 0
        for r in results:
            name = r.get("file")
            if self.tree.exists(name):
                if "error" in r:
                    self.tree.set(name, "status", "error (see OUTPUT)")
                else:
                    ok += 1
                    self.tree.set(name, "status", "done")
                    self.tree.set(name, "length", f"{r.get('seconds', 0)} s")
        self.log(f"Rendered {ok} of {len(results)} scripts. Files are in {out}/.\n", "accent")

    # ------------------------------------------------------------- claude code
    def _build_claude(self):
        side = tk.Frame(self.sidebar, bg=SIDEBAR)
        self.side_frames["claude"] = side
        self._side_header(side, "claude")
        self.section(side, "Mode")
        self.cc_mode = tk.StringVar(value="ask" if FROZEN else "edit")
        modes = (("ask", "Ask (no changes)"),) if FROZEN else (("ask", "Ask (no changes)"), ("edit", "Edit the app"))
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
        ideas = ["Make the sidebar 340 px wide",
                 "Use a blue status bar like VS Code",
                 "Add a Speed slider",
                 "Show each output file's length",
                 "Make the editor font size 14"]
        lb = tk.Listbox(side, bg=SIDEBAR, fg=FG, font=self.fonts["small"], relief="flat", height=len(ideas),
                        highlightthickness=0, selectbackground=SELECT, activestyle="none")
        for i in ideas:
            lb.insert("end", "• " + i)
        lb.pack(fill="x", padx=14)
        lb.bind("<<ListboxSelect>>", lambda e: lb.curselection() and self._use_idea(ideas[lb.curselection()[0]]))

        main = tk.Frame(self.content, bg=BG)
        self.main_frames["claude"] = main
        self.label(main, "Ask Claude Code to change or explain this app", "small", fg=FG_DIM, bg=BG).pack(fill="x", padx=16, pady=(12, 4))
        self.cc_prompt = tk.Text(main, height=4, bg=BG, fg="#D4D4D4", font=self.fonts["mono"], relief="flat",
                                 insertbackground="#AEAFAD", highlightthickness=1, highlightbackground=BORDER,
                                 highlightcolor=CORAL, padx=8, pady=6, wrap="word")
        self.cc_prompt.pack(fill="x", padx=16)
        bar = tk.Frame(main, bg=BG)
        bar.pack(fill="x", padx=16, pady=8)
        self.cc_note = self.label(main, "", "small", fg=FG_DIM, bg=BG, justify="left", wraplength=760)
        self.cc_note.pack(fill="x", padx=16, pady=(0, 2), before=bar)
        self._claude_status()
        self.cc_btn = self.button(bar, f"Send to Claude   {MOD_LABEL}↵", self.run_claude, primary=True, bg=BG)
        self.cc_btn.pack(side="left")
        self.button(bar, "■ Stop", self.stop_claude, bg=BG).pack(side="left", padx=6)
        frame = tk.Frame(main, bg=BG)
        frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self.cc_out = tk.Text(frame, bg="#181818", fg=FG, font=self.fonts["mono"], relief="flat",
                              highlightthickness=0, wrap="word", padx=10, pady=8, state="normal")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.cc_out.yview)
        self.cc_out.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.cc_out.pack(side="left", fill="both", expand=True)
        self.cc_out.tag_configure("you", foreground=CORAL, font=self.fonts["ui_b"])
        self.cc_out.tag_configure("tool", foreground="#4EC9B0")
        self.cc_out.tag_configure("dim", foreground=FG_DIM)
        self.cc_out.tag_configure("err", foreground="#F48771")
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
            self.cc_note.configure(text="In the installed app, Claude can explain things but can't edit the "
                                        "app itself. To change the app, use the source version "
                                        "(pip install) and its Edit mode, or Claude Code in VS Code.")
        elif self.claude_path():
            self.cc_note.configure(text="Uses the Claude Code command line with the same Claude login as "
                                        "VS Code. Edits are limited to reading and editing files; a backup "
                                        "is saved first, so Undo restores the previous version.")
        else:
            self.cc_note.configure(text="The Claude Code command line (claude) isn't installed. Install it "
                                        "from code.claude.com/docs/en/setup, or use “Copy for VS Code” and "
                                        "paste the request into the Claude panel in VS Code.")

    def _cc_context(self) -> str:
        return ("The user is customizing the ursoTTS desktop app from inside the app itself. "
                "The window is ursotts/app.py (Tkinter, VS Code Dark style; colors and fonts are defined near "
                "the top, each view has a _build_* method). Shared logic is in ursotts/shared.py; the web UI "
                "(ursotts/ui.py) and the pipeline must keep working, so don't change them unless asked. "
                "Make focused, working edits, keep the app's style, and finish with a short plain-language "
                "summary of what you changed. Tell the user to click “Restart app” to see the change.")

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
        self.cc_write(f"\n▸ You ({'edit' if edit else 'ask'}): ", "you")
        self.cc_write(prompt + "\n")
        self.cc_btn.configure(state="disabled", bg="#5A3A30")
        self._set_status("Claude Code is working…")
        try:
            self.cc_proc = subprocess.Popen(cmd, cwd=str(self.project), stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, bufsize=1)
        except OSError as e:
            self.cc_write(f"Could not start Claude Code: {e}\n", "err")
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
                yield f"Claude Code reported an error: {ev.get('result', '')}\n", "err"
            secs = (ev.get("duration_ms") or 0) / 1000
            yield f"  done in {secs:.0f} s\n", "dim"

    def _claude_finished(self, edit):
        self.cc_btn.configure(state="normal", bg=self.cc_btn._color)
        self._set_status()
        if edit:
            changed = self._changed_files()
            if changed:
                self.cc_write("  changed: " + ", ".join(changed) + "\n", "tool")
                self.cc_write("  Click “⟳ Restart app” to see the change, or “↶ Undo last change” to go back.\n", "dim")
                self.log("Claude Code changed: " + ", ".join(changed) + "\n", "accent")
            else:
                self.cc_write("  no files were changed\n", "dim")

    def stop_claude(self):
        if self.cc_proc and self.cc_proc.poll() is None:
            self.cc_proc.terminate()
            self.cc_write("  stopped\n", "err")

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
        if not messagebox.askyesno("Undo last change", f"Restore the app files saved before the last Claude edit "
                                   f"({snap.name})? Then restart the app."):
            return
        for f in snap.rglob("*"):
            if f.is_file():
                rel = f.relative_to(snap)
                dst = (Path(__file__).parent / rel.name) if rel.parts[0] == "_pkg" else self.project / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
        shutil.rmtree(snap, ignore_errors=True)
        self.cc_write("  restored the previous version; click “⟳ Restart app”\n", "tool")
        self.log(f"Undo: restored app files from {snap.name}\n", "accent")

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
        prompt = self.cc_prompt.get("1.0", "end").strip() or "(describe your change here)"
        text = (f"{prompt}\n\nContext: this is for the ursoTTS desktop app, @ursotts/app.py "
                "(Tkinter, VS Code Dark style). Keep the web UI (ursotts/ui.py) and the pipeline working.")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.cc_write("  copied: paste it into the Claude panel in VS Code\n", "dim")

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
            print("[ursotts] loading the voice model (first time only)…")
            t0 = time.time()
            self.synth = Synthesizer(self.cfg, make_engine(self.cfg))
            print(f"[ursotts] voice model ready in {time.time() - t0:.1f} s")
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
        run_cfg = {**self.cfg, "lang_mode": LANGS[self.lang.get()]}

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
        self.log(f"Made {r['seconds']} s of audio in {r['render_time']} s → {Path(made[0]).parent}/\n", "accent")
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
        self._set_status(busy_text)
        self.busy_bar.pack(side="right", padx=(0, 4))
        self.busy_bar.start(15)
        for b in (self.gen_btn, self.listen_btn, self.batch_btn):
            b.configure(state="disabled", bg="#5A3A30")
        if not self.panel_visible:
            self.toggle_panel()

        def wrapper():
            writer = QueueWriter(self.q)
            try:
                with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                    work()
            except Exception as e:  # shown in the panel instead of crashing the window
                self.q.put(("error", f"{type(e).__name__}: {e}\n"))
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
        model = "model ready" if self.synth else "model loads on first run"
        self.status_left.configure(text=f"  ursoTTS {__version__}   ·   engine: {engine}   ·   {model}")
        self.status_right.configure(text=busy or f"Ready   ·   {MOD_LABEL}J panel   ·   {MOD_LABEL}↵ run")

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
                    "batch_src": self.src.get(), "batch_out": self.dst.get(), "zoom": self.zoom_level,
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
            messagebox.showerror("Create launcher", str(e))
            return
        where = "\n".join(self._short(p) for p in made)
        tip = {"darwin": "Open it from Applications in your home folder, or drag it to the Dock."}.get(
            sys.platform, "Double-click it to open ursoTTS without a terminal.")
        self.log(f"Created launcher: {where}\n", "accent")
        messagebox.showinfo("Launcher created", f"Created:\n{where}\n\n{tip}")

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
