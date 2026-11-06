"""Command line: ursotts batch | say | preview | check | ui"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from . import __version__
from .config import load_config
from .text import Pause


def _engine(cfg, args):
    if getattr(args, "engine", None):
        cfg["engine"] = args.engine
    from .engine import make_engine
    from .pipeline import Synthesizer
    return Synthesizer(cfg, make_engine(cfg))


def cmd_batch(args):
    from .pipeline import missing_voices, plan_batch, run_batch
    cfg = load_config(args.config)
    if args.engine:
        cfg["engine"] = args.engine
    src, out = Path(args.input), Path(args.output)
    files, todo, keys = plan_batch(cfg, src, out, args.force)
    if len(todo) < len(files):
        print(f"Skipping {len(files) - len(todo)} up-to-date script(s) "
              "(text and settings unchanged; use --force to redo)")
    if not todo:
        print("Nothing to do.")
        return
    missing = missing_voices(cfg)
    if missing:
        sys.exit("Voice sample(s) missing: " + ", ".join(missing)
                 + "\nAdd your recordings to voices/ or edit config.yaml.")
    synth = _engine(cfg, args)
    results = run_batch(cfg, synth, todo, out, keys)
    ok = sum("error" not in r for r in results)
    print(f"\nDone: {ok}/{len(results)} scripts. Chunks rendered: {synth.misses}, "
          f"reused from cache: {synth.hits}. Report: {out / 'batch_report.json'}")


def cmd_say(args):
    from .pipeline import process_file
    cfg = load_config(args.config)
    if args.lang:
        cfg["lang_mode"] = args.lang
    if args.engine:
        cfg["engine"] = args.engine
    from .pipeline import missing_voices
    missing = missing_voices(cfg)
    if missing:
        sys.exit("Voice sample(s) missing: " + ", ".join(missing)
                 + "\nAdd your recordings to voices/ or edit config.yaml.")
    synth = _engine(cfg, args)
    out = Path(args.output)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"{out.stem}.txt"
        src.write_text(args.text, encoding="utf-8")
        process_file(src, Path(tmp), synth, cfg)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(Path(tmp) / f"{out.stem}.wav", out)
    print(f"Saved {out}")


def cmd_preview(args):
    cfg = load_config(args.config)
    from .pipeline import parse_file
    items, directives = parse_file(Path(args.file), cfg)
    if directives:
        print(f"directives: {directives}")
    for it in items:
        if isinstance(it, Pause):
            print(f"   ... pause {it.seconds}s")
        else:
            print(f"[{it.lang}] {it.text}")


def cmd_check(args):
    cfg = load_config(args.config)
    print(f"ursotts {__version__}\nengine: {cfg['engine']}")
    try:
        import torch
        dev = ("cuda" if torch.cuda.is_available()
               else "mps" if torch.backends.mps.is_available() else "cpu")
        print(f"torch {torch.__version__} | best device: {dev}")
    except ImportError:
        print("torch: not installed")
    try:
        import chatterbox  # noqa: F401
        print("chatterbox: installed")
    except ImportError:
        print("chatterbox: NOT installed  ->  pip install -e \".[all]\"")
    from .audio import find_ffmpeg
    print(f"ffmpeg: {find_ffmpeg() or 'not found (MP3 export disabled)'}")
    for lang, ref in cfg["voices"].items():
        print(f"voice[{lang}]: {ref} {'OK' if ref and Path(ref).exists() else 'MISSING'}")


def cmd_ui(args):
    try:
        from .ui import launch
    except ImportError:
        sys.exit("The web UI needs Gradio:  pip install -e \".[ui]\"")
    cfg = load_config(args.config)
    if args.engine:
        cfg["engine"] = args.engine
    launch(cfg, port=args.port, share=args.share, open_browser=not args.no_browser)


def cmd_app(args):
    try:
        import tkinter  # noqa: F401
    except ImportError:
        sys.exit("The desktop app needs Tkinter. On a Mac, use Python from python.org, or run:\n"
                 "  brew install python-tk@3.13   (match your Python version)\nThe web UI works without it:  ursotts ui")
    restart = ["-c", args.config] + (["--engine", args.engine] if args.engine else [])
    if args.detach:
        # start a separate app process that doesn't depend on this terminal
        import subprocess
        from pathlib import Path
        log = Path.home() / ".config" / "ursotts" / "app.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        python = sys.executable
        kw = {}
        if sys.platform.startswith("win"):
            pythonw = Path(python).with_name("pythonw.exe")
            python = str(pythonw) if pythonw.exists() else python
            kw["creationflags"] = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True                           # survives closing the terminal
        with open(log, "w", encoding="utf-8") as fh:
            proc = subprocess.Popen([python, "-m", "ursotts", "app", *restart], stdin=subprocess.DEVNULL,
                                    stdout=fh, stderr=subprocess.STDOUT, **kw)
        print(f"ursoTTS desktop app started (process {proc.pid}). You can close this terminal.")
        print(f"Its log is in {log}")
        return
    from .app import launch
    cfg = load_config(args.config)
    if args.engine:
        cfg["engine"] = args.engine
    launch(cfg, restart_args=restart)


def cmd_make_launcher(args):
    from .launcher import make_launcher
    made = make_launcher()
    for path in made:
        print(f"Created {path}")
    if sys.platform == "darwin":
        print("Open it from Applications (your home folder's Applications), or drag it to the Dock.")
    elif sys.platform.startswith("win"):
        print("Double-click ursoTTS on the Desktop, or find it in the Start menu.")
    else:
        print("ursoTTS now appears in your applications menu.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ursotts", description="Batch voice-cloned narration.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("batch", help="render every .txt/.md script in a folder")
    b.add_argument("input")
    b.add_argument("output")
    b.add_argument("-c", "--config", default="config.yaml")
    b.add_argument("--engine", choices=["chatterbox", "dummy"])
    b.add_argument("--force", action="store_true", help="re-render up-to-date files")
    b.set_defaults(func=cmd_batch)

    s = sub.add_parser("say", help="render one line of text")
    s.add_argument("text")
    s.add_argument("-o", "--output", default="say.wav")
    s.add_argument("-c", "--config", default="config.yaml")
    s.add_argument("--lang", help="force language, e.g. en or ko")
    s.add_argument("--engine", choices=["chatterbox", "dummy"])
    s.set_defaults(func=cmd_say)

    p = sub.add_parser("preview", help="show chunks/languages/pauses without rendering")
    p.add_argument("file")
    p.add_argument("-c", "--config", default="config.yaml")
    p.set_defaults(func=cmd_preview)

    k = sub.add_parser("check", help="check GPU, ffmpeg and voice samples")
    k.add_argument("-c", "--config", default="config.yaml")
    k.set_defaults(func=cmd_check)

    u = sub.add_parser("ui", help="open the web interface in your browser")
    u.add_argument("-c", "--config", default="config.yaml")
    u.add_argument("--engine", choices=["chatterbox", "dummy"])
    u.add_argument("--port", type=int, default=7860)
    u.add_argument("--share", action="store_true", help="temporary public link (careful!)")
    u.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    u.set_defaults(func=cmd_ui)

    a = sub.add_parser("app", help="open the desktop app (VS Code-style window)")
    a.add_argument("-c", "--config", default="config.yaml")
    a.add_argument("--engine", choices=["chatterbox", "dummy"], help="override the engine in config.yaml")
    a.add_argument("--detach", action="store_true", help="start in the background, so you can close the terminal")
    a.set_defaults(func=cmd_app)

    m = sub.add_parser("make-launcher", help="create a double-click launcher for the desktop app")
    m.set_defaults(func=cmd_make_launcher)

    args = ap.parse_args(argv)
    if hasattr(args, "config") and not Path(args.config).exists():
        args.config = None
    args.func(args)


if __name__ == "__main__":
    main()
