# PyInstaller recipe for the ursoTTS desktop app.
# Build from the project folder:  pyinstaller packaging/ursotts.spec --noconfirm
# (packaging/build_mac.sh and packaging/build_windows.ps1 do this for you.)
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "ursotts" / "__init__.py").read_text()).group(1)
MAC, WIN = sys.platform == "darwin", sys.platform.startswith("win")

datas = [
    (str(ROOT / "ursotts" / "assets"), "ursotts/assets"),
    (str(ROOT / "config.yaml"), "defaults"),
    (str(ROOT / "pronunciations.yaml"), "defaults"),
    (str(ROOT / "scripts"), "defaults/scripts"),
    (str(ROOT / "examples"), "defaults/examples"),
]
binaries, hiddenimports = [], ["ursotts.app", "ursotts.engine", "tkinter"]
# ursotts/assets/ is bundled whole, including default_lang.txt when the build script wrote it
# ("ko" for the Korean edition; absent = English). It sets the installed app's default language.
_lang_file = ROOT / "ursotts" / "assets" / "default_lang.txt"
print("ursoTTS build language:", _lang_file.read_text(encoding="utf-8").strip() if _lang_file.exists() else "en (no default_lang.txt)")

# The voice engine and its helpers ship data files and lazily imported modules,
# so collect them whole. Packages that aren't installed are skipped.
for pkg in ("chatterbox", "perth", "s3tokenizer", "librosa", "conformer", "diffusers",
            "transformers", "safetensors", "huggingface_hub", "tokenizers", "imageio_ffmpeg",
            "pkuseg", "spacy_pkuseg"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

# transformers/diffusers/etc. check their dependencies at import time through importlib.metadata
# (e.g. "The 'requests' distribution was not found"), so the installed package metadata
# (.dist-info) must ship inside the app too. recursive=True also pulls in their dependencies.
for dist in ("chatterbox-tts", "transformers", "diffusers", "huggingface-hub", "tokenizers", "safetensors",
             "requests", "tqdm", "regex", "packaging", "filelock", "numpy", "pyyaml", "torch", "torchaudio",
             "librosa", "resemble-perth", "s3tokenizer", "conformer", "accelerate"):
    try:
        datas += copy_metadata(dist, recursive=True)
    except Exception:
        pass

a = Analysis(
    [str(ROOT / "packaging" / "ursotts_app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["gradio", "gradio_client", "matplotlib", "IPython", "jupyter"],  # the web UI isn't part of the app
    noarchive=False,
)
pyz = PYZ(a.pure)
icon = str(ROOT / "packaging" / "icons" / ("ursoTTS.icns" if MAC else "ursoTTS.ico"))
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ursoTTS", console=False,
          icon=icon, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="ursoTTS", upx=False)

if MAC:
    app = BUNDLE(
        coll,
        name="ursoTTS.app",
        icon=icon,
        bundle_identifier="com.ursomics.ursotts",
        version=VERSION,
        info_plist={
            "CFBundleName": "ursoTTS",
            "CFBundleDisplayName": "ursoTTS",
            "CFBundleShortVersionString": VERSION,
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "© 2026 Ursus (@ursomics). MIT license.",
        },
    )
