# Building the ursoTTS installers

This folder turns the Tkinter desktop app into installers:

| File | What it does |
|---|---|
| `ursotts_app.py` | Entry point of the installed app; creates `~/ursoTTS` (settings, voices, scripts, output) on first launch |
| `ursotts.spec` | PyInstaller recipe (assets, defaults, icons, voice-engine packages) |
| `build_mac.sh` | Builds `ursoTTS.app` and `dist/ursoTTS-<version>-mac-arm64.dmg` on a Mac |
| `build_windows.ps1` + `ursotts.iss` | Builds `dist/ursoTTS-<version>-windows-setup.exe` on Windows (needs Inno Setup 6) |
| `icons/` | `ursoTTS.icns` (macOS) and `ursoTTS.ico` (Windows) from the brand kit |

## Easiest: let GitHub build them

1. Update `__version__` in `ursotts/__init__.py` and `version` in `pyproject.toml`, and push.
2. On GitHub: **Releases → Draft a new release**, create a tag such as `v1.0.0`, write notes, **Publish release**.
3. The **release** workflow (`.github/workflows/release.yml`) builds the `.dmg` on macOS and the setup `.exe` on Windows and attaches both to the release (about 20–40 minutes).

You can also run the workflow by hand from the **Actions** tab; the files are then kept as workflow artifacts.

## Build on your own Mac

```bash
cd ~/Projects/Ursomics/ursotts
bash packaging/build_mac.sh
```

## Notes

- The installers bundle PyTorch and Chatterbox, so they are large (about 1–3 GB). The voice model itself downloads on first use.
- They are not code-signed. Users confirm once on first open (Mac: right-click → Open; Windows: More info → Run anyway). Signing needs an Apple Developer ID (with notarization) and a Windows code-signing certificate.
- The macOS build targets Apple Silicon. The Windows build uses the CPU version of PyTorch from PyPI; an NVIDIA GPU build would need the CUDA wheels.
- MP3 export uses the ffmpeg binary from `imageio-ffmpeg`, which is included.
- In the installed app the Claude Code view is Ask-only (`FROZEN` in `app.py`).
