#!/usr/bin/env bash
# Build ursoTTS.app and a styled .dmg on a Mac (Apple Silicon).
# Run from the project folder:  bash packaging/build_mac.sh
set -euo pipefail
VERSION=$(python3 -c "import re;print(re.search(r'__version__ = \"([^\"]+)\"', open('ursotts/__init__.py').read()).group(1))")
python3 -m pip install --upgrade pip
python3 -m pip install ".[chatterbox]" pyinstaller pillow
pyinstaller packaging/ursotts.spec --noconfirm --clean

DMG="dist/ursoTTS-${VERSION}-mac-arm64.dmg"
VOL="ursoTTS ${VERSION}"
STAGE=dist/dmg && rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R dist/ursoTTS.app "$STAGE/"

# Re-sign the whole app consistently (ad-hoc, no Apple account needed). Without this,
# macOS can stall for a very long time when first opening the large PyInstaller bundle.
chmod -R u+w "$STAGE/ursoTTS.app"
codesign --force --deep --sign - "$STAGE/ursoTTS.app"
codesign --verify --deep --strict "$STAGE/ursoTTS.app"

# Installer window background: warm panel with an arrow from the app to Applications.
python3 - <<'PY'
from PIL import Image, ImageDraw, ImageFont

CORAL = (217, 119, 87)
INK = (60, 52, 46)
CREAM = (246, 239, 231)

def font(size):
    for p in ("/System/Library/Fonts/Helvetica.ttc",
              "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()

def draw(scale, path):
    W, H = 660 * scale, 400 * scale
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    d.rectangle([0, H - 8 * scale, W, H], fill=CORAL)
    cy = 190 * scale
    x0, x1 = 285 * scale, 378 * scale
    d.line([(x0, cy), (x1 - 16 * scale, cy)], fill=CORAL, width=7 * scale)
    d.polygon([(x1, cy), (x1 - 26 * scale, cy - 18 * scale),
               (x1 - 26 * scale, cy + 18 * scale)], fill=CORAL)
    f = font(18 * scale)
    text = "Drag ursoTTS into Applications to install"
    w = d.textlength(text, font=f)
    d.text(((W - w) / 2, 328 * scale), text, fill=INK, font=f)
    img.save(path)

draw(1, "dist/dmg-bg.png")
draw(2, "dist/dmg-bg@2x.png")
PY
tiffutil -cathidpicheck dist/dmg-bg.png dist/dmg-bg@2x.png -out dist/dmg-bg.tiff

if ! command -v create-dmg >/dev/null 2>&1; then
  brew install create-dmg || true
fi

rm -f "$DMG"
if command -v create-dmg >/dev/null 2>&1 && create-dmg \
    --volname "$VOL" \
    --background dist/dmg-bg.tiff \
    --window-pos 200 120 \
    --window-size 660 400 \
    --icon-size 128 \
    --text-size 14 \
    --icon "ursoTTS.app" 180 190 \
    --hide-extension "ursoTTS.app" \
    --app-drop-link 480 190 \
    "$DMG" "$STAGE"; then
  echo "Built styled $DMG"
else
  echo "create-dmg was unavailable or failed; building a plain DMG instead."
  hdiutil detach "/Volumes/$VOL" -force >/dev/null 2>&1 || true
  rm -f "$DMG" dist/rw.*.dmg
  ln -s /Applications "$STAGE/Applications"
  hdiutil create -volname "$VOL" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
  echo "Built $DMG"
fi
