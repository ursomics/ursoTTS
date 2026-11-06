"""Create a double-click launcher for the source version of the desktop app.

macOS:   ~/Applications/ursoTTS.app (a tiny app that runs `python -m ursotts app`
         in your project folder; drag it to the Dock if you like)
Windows: an "ursoTTS" shortcut on the Desktop and in the Start menu
Linux:   ~/.local/share/applications/ursotts.desktop (appears in the app menu)

The launcher uses the Python that runs this command (your .venv) and the
project folder you run it from, so run it from inside the project folder.
"""
from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from . import __version__

ICONS = Path(__file__).parent / "assets" / "tk" / "icons"


def _project_icon(project: Path, name: str) -> Path | None:
    for p in (project / "packaging" / "icons" / name, ICONS / name.lower()):
        if p.exists():
            return p
    return None


def make_mac_app(project: Path, python: str, dest_dir: Path | None = None) -> Path:
    dest_dir = dest_dir or Path.home() / "Applications"
    app = dest_dir / "ursoTTS.app"
    macos, res = app / "Contents" / "MacOS", app / "Contents" / "Resources"
    if app.exists():
        shutil.rmtree(app)
    macos.mkdir(parents=True)
    res.mkdir(parents=True)
    script = macos / "ursoTTS"
    script.write_text(
        "#!/bin/bash\n"
        "# Opens the ursoTTS desktop app from your project folder (made by `ursotts make-launcher`).\n"
        f"cd {shlex.quote(str(project))} || exit 1\n"
        f"exec {shlex.quote(python)} -m ursotts app\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    icon = _project_icon(project, "ursoTTS.icns")
    if icon:
        shutil.copy2(icon, res / "ursoTTS.icns")
    (app / "Contents" / "Info.plist").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>ursoTTS</string>
  <key>CFBundleDisplayName</key><string>ursoTTS</string>
  <key>CFBundleIdentifier</key><string>com.ursomics.ursotts.launcher</string>
  <key>CFBundleExecutable</key><string>ursoTTS</string>
  <key>CFBundleIconFile</key><string>ursoTTS</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>{__version__}</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
""", encoding="utf-8")
    subprocess.run(["touch", str(app)], check=False)       # refresh Finder's icon cache
    return app


def make_windows_shortcuts(project: Path, python: str) -> list[Path]:
    pythonw = Path(python).with_name("pythonw.exe")
    target = str(pythonw if pythonw.exists() else python)
    icon = _project_icon(project, "ursoTTS.ico")
    places = [Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop",
              Path(os.environ.get("APPDATA", Path.home())) / "Microsoft" / "Windows" / "Start Menu" / "Programs"]
    made = []
    for folder in places:
        if not folder.exists():
            continue
        lnk = folder / "ursoTTS.lnk"
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
              "$s.TargetPath='{target}';$s.Arguments='-m ursotts app';"
              "$s.WorkingDirectory='{wd}';{icon}$s.Save()").format(
            lnk=str(lnk).replace("'", "''"), target=target.replace("'", "''"),
            wd=str(project).replace("'", "''"),
            icon=f"$s.IconLocation='{str(icon).replace(chr(39), chr(39) * 2)}';" if icon else "")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
        made.append(lnk)
    return made


def make_linux_desktop_entry(project: Path, python: str, dest_dir: Path | None = None) -> Path:
    dest_dir = dest_dir or Path.home() / ".local" / "share" / "applications"
    dest_dir.mkdir(parents=True, exist_ok=True)
    icon = _project_icon(project, "icon_256.png") or ICONS / "icon_256.png"
    entry = dest_dir / "ursotts.desktop"
    entry.write_text(
        "[Desktop Entry]\nType=Application\nName=ursoTTS\nComment=Voice cloning text-to-speech\n"
        f"Exec={shlex.quote(python)} -m ursotts app\nPath={project}\nIcon={icon}\n"
        "Terminal=false\nCategories=AudioVideo;Audio;\n", encoding="utf-8")
    entry.chmod(entry.stat().st_mode | stat.S_IXUSR)
    return entry


def make_launcher(project: Path | None = None, python: str | None = None) -> list[Path]:
    project = (project or Path.cwd()).resolve()
    python = python or sys.executable
    if not (project / "config.yaml").exists():
        raise SystemExit(f"{project} doesn't look like the ursoTTS project folder (no config.yaml). "
                         "Run this from inside the project folder.")
    if sys.platform == "darwin":
        return [make_mac_app(project, python)]
    if sys.platform.startswith("win"):
        return make_windows_shortcuts(project, python)
    return [make_linux_desktop_entry(project, python)]
