#!/usr/bin/env bash
# Build "Roo Voice.app" (bundled Python + app + launcher) and package Roo-Voice.dmg.
# Apple-Silicon only (MLX requires it). Unsigned — Gatekeeper: right-click → Open.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BUILD="$HERE/build"
APPNAME="Roo Voice"
APP="$BUILD/$APPNAME.app"
# Single-source the version from the app code so Info.plist can't drift (IP-176 §9.1).
VERSION="$(sed -n 's/^ROO_VOICE_VERSION = "\(.*\)"/\1/p' "$REPO/installers/common/bootstrap.py" | head -1)"
[ -n "$VERSION" ] || { echo "could not read ROO_VOICE_VERSION from bootstrap.py"; exit 1; }
echo "==> building Roo Voice $VERSION"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20260623/cpython-3.12.13%2B20260623-aarch64-apple-darwin-install_only.tar.gz"
PY_TGZ="$HERE/_py/python-mac.tar.gz"

echo "==> clean build dir"
rm -rf "$BUILD"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

echo "==> fetch standalone Python (cached)"
mkdir -p "$HERE/_py"
[ -f "$PY_TGZ" ] || curl -L --fail -o "$PY_TGZ" "$PY_URL"
mkdir -p "$APP/Contents/Resources/python"
tar -xzf "$PY_TGZ" -C "$APP/Contents/Resources/python" --strip-components=1

echo "==> stage app files"
APPFILES="$APP/Contents/Resources/app"
mkdir -p "$APPFILES"
rsync -a \
  --exclude '.git' --exclude '.venv' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude 'installers/*/build' --exclude 'installers/*/_py' --exclude 'installers/*/dist' \
  --exclude 'roo-gen.jsonl' --exclude '*.dmg' \
  "$REPO/server" "$REPO/web" "$REPO/assets" "$REPO/reference.wav" "$REPO/README.md" \
  "$APPFILES/"
mkdir -p "$APPFILES/installers/common"
cp "$REPO/installers/common/bootstrap.py" "$APPFILES/installers/common/bootstrap.py"

echo "==> launcher"
cat > "$APP/Contents/MacOS/roo-voice" <<'LAUNCH'
#!/bin/bash
DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"
export ROO_APP_DIR="$DIR/app"
exec "$DIR/python/bin/python3" "$DIR/app/installers/common/bootstrap.py" "$@"
LAUNCH
chmod +x "$APP/Contents/MacOS/roo-voice"

echo "==> icon"
ICONSET="$BUILD/icon.iconset"; mkdir -p "$ICONSET"
# Prefer a purpose-built square icon; fall back to the (landscape) cover art.
if [ -f "$REPO/assets/app-icon.png" ]; then SRC="$REPO/assets/app-icon.png"
elif [ -f "$HERE/icon.png" ]; then SRC="$HERE/icon.png"
else SRC="$REPO/assets/roo-voice-mlx.png"; fi
echo "    icon source: $SRC"
if [ -f "$SRC" ]; then
  for s in 16 32 64 128 256 512; do
    sips -z $s $s "$SRC" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null 2>&1 || true
    d=$((s*2)); sips -z $d $d "$SRC" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null 2>&1 || true
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/icon.icns" 2>/dev/null || true
fi

echo "==> Info.plist"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Roo Voice</string>
  <key>CFBundleDisplayName</key><string>Roo Voice</string>
  <key>CFBundleIdentifier</key><string>ai.abliter8.roo-voice</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleExecutable</key><string>roo-voice</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSArchitecturePriority</key><array><string>arm64</string></array>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

echo "==> package DMG"
STAGE="$BUILD/dmg"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
DMG="$BUILD/Roo-Voice.dmg"
hdiutil create -volname "$APPNAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null

SIZE=$(du -sh "$DMG" | cut -f1)
echo "==> DONE"
echo "    app: $APP"
echo "    dmg: $DMG ($SIZE)"
