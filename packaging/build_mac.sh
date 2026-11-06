#!/usr/bin/env bash
# Build ursoTTS.app and a .dmg on a Mac (Apple Silicon).
# Run from the project folder:  bash packaging/build_mac.sh
set -euo pipefail
VERSION=$(python3 -c "import re;print(re.search(r'__version__ = \"([^\"]+)\"', open('ursotts/__init__.py').read()).group(1))")
python3 -m pip install --upgrade pip
python3 -m pip install ".[chatterbox]" pyinstaller
pyinstaller packaging/ursotts.spec --noconfirm --clean
STAGE=dist/dmg && rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R dist/ursoTTS.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"          # drag-to-install shortcut
DMG="dist/ursoTTS-${VERSION}-mac-arm64.dmg"
hdiutil create -volname "ursoTTS ${VERSION}" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
echo "Built $DMG"
