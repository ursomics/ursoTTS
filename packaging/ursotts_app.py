"""Entry point for the installed ursoTTS desktop app (.app on macOS, .exe on Windows).

The installed app keeps your own files in a ursoTTS folder in your home folder
(override with the URSOTTS_HOME environment variable): config.yaml,
pronunciations.yaml, voices/, scripts/ and output/. On first launch it is
created and filled with the default settings and example scripts.
"""
import multiprocessing
import os
import shutil
import sys
from pathlib import Path


def bundled() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "defaults"
    return Path(__file__).resolve().parent.parent      # running from the source tree


def prepare_home() -> Path:
    home = Path(os.environ.get("URSOTTS_HOME", Path.home() / "ursoTTS"))
    home.mkdir(parents=True, exist_ok=True)
    src = bundled()
    for name in ("config.yaml", "pronunciations.yaml"):
        if not (home / name).exists() and (src / name).exists():
            shutil.copy2(src / name, home / name)
    for folder in ("scripts", "examples"):
        if not (home / folder).exists() and (src / folder).is_dir():
            shutil.copytree(src / folder, home / folder)
    for folder in ("voices", "output"):
        (home / folder).mkdir(exist_ok=True)
    return home


def main():
    multiprocessing.freeze_support()          # needed on Windows for frozen apps
    os.chdir(prepare_home())
    from ursotts.app import launch
    from ursotts.config import load_config
    launch(load_config("config.yaml"))


if __name__ == "__main__":
    main()
