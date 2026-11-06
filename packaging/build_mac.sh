#!/usr/bin/env bash
# Build ursoTTS.app and a styled .dmg on a Mac (Apple Silicon).
# Run from the project folder:  bash packaging/build_mac.sh
# Korean edition (한국어 버전):  bash packaging/build_mac.sh --ko    (or URSOTTS_BUILD_LANG=ko)
set -euo pipefail

# Which language the app opens in: --ko (or URSOTTS_BUILD_LANG=ko) builds the Korean edition.
BUILD_LANG="${URSOTTS_BUILD_LANG:-en}"
for arg in "$@"; do
  case "$arg" in
    --ko) BUILD_LANG=ko ;;
    --en) BUILD_LANG=en ;;
    *) echo "Unknown option: $arg (use --ko for the Korean edition)" >&2; exit 2 ;;
  esac
done
case "$BUILD_LANG" in en|ko) ;; *) echo "URSOTTS_BUILD_LANG must be en or ko, not '$BUILD_LANG'" >&2; exit 2 ;; esac
export BUILD_LANG

# The installer's default language is the text file ursotts/assets/default_lang.txt (bundled by
# ursotts.spec with the rest of assets/). Write it only for the build, then put things back, so an
# English build after a Korean build is English again.
LANG_FILE=ursotts/assets/default_lang.txt
LANG_BACKUP=$(mktemp)
HAD_LANG_FILE=0
if [ -f "$LANG_FILE" ]; then cp "$LANG_FILE" "$LANG_BACKUP"; HAD_LANG_FILE=1; fi
restore_lang_file() {
  if [ "$HAD_LANG_FILE" = 1 ]; then cp "$LANG_BACKUP" "$LANG_FILE"; else rm -f "$LANG_FILE"; fi
  rm -f "$LANG_BACKUP"
}
trap restore_lang_file EXIT
if [ "$BUILD_LANG" = ko ]; then echo ko > "$LANG_FILE"; else rm -f "$LANG_FILE"; fi
echo "Building the ${BUILD_LANG} edition"

VERSION=$(python3 -c "import re;print(re.search(r'__version__ = \"([^\"]+)\"', open('ursotts/__init__.py').read()).group(1))")
python3 -m pip install --upgrade pip
python3 -m pip install ".[chatterbox]" pyinstaller pillow
pyinstaller packaging/ursotts.spec --noconfirm --clean

DMG="dist/ursoTTS-${VERSION}-mac-arm64.dmg"
VOL="ursoTTS ${VERSION}"
if [ "$BUILD_LANG" = ko ]; then
  DMG="dist/ursoTTS-${VERSION}-mac-arm64_ko.dmg"
  VOL="ursoTTS ${VERSION} 한국어"
fi
STAGE=dist/dmg && rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R dist/ursoTTS.app "$STAGE/"

# Re-sign the whole app consistently (ad-hoc, no Apple account needed). Without this,
# macOS can stall for a very long time when first opening the large PyInstaller bundle.
chmod -R u+w "$STAGE/ursoTTS.app"
codesign --force --deep --sign - "$STAGE/ursoTTS.app"
codesign --verify --deep --strict "$STAGE/ursoTTS.app"

# Installer window background: warm panel with an arrow from the app to Applications.
python3 - <<'PY'
import os
from PIL import Image, ImageDraw, ImageFont

CORAL = (217, 119, 87)
INK = (60, 52, 46)
CREAM = (246, 239, 231)

KOREAN = os.environ.get("BUILD_LANG") == "ko"
CAPTION_EN = "Drag ursoTTS into Applications to install"
CAPTION_KO = "ursoTTS를 응용 프로그램으로 드래그하세요"

def font(size, paths=("/System/Library/Fonts/Helvetica.ttc",
                      "/System/Library/Fonts/Supplemental/Arial.ttf")):
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return None

def caption_font(size):
    """(font, caption). Korean needs a Hangul font; if none loads, fall back to the English caption."""
    if KOREAN:
        f = font(size, (os.environ.get("URSOTTS_KO_FONT", ""),          # optional override (testing)
                        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
                        "/System/Library/Fonts/Supplemental/AppleGothic.ttf"))
        if f is not None:
            return f, CAPTION_KO
        print("warning: no Korean font found for the DMG caption; using the English caption")
    return font(size) or ImageFont.load_default(), CAPTION_EN

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
    f, text = caption_font(18 * scale)
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
