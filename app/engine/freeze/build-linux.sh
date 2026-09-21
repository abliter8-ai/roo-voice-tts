#!/usr/bin/env bash
# IP-322 — freeze roo-engine and pinned qwentts native server (Linux x64).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ENGINE_DIR="$(dirname "$HERE")"
VENV="${ROO_FREEZE_ENV:-$ENGINE_DIR/.freeze-venv}"; OUT="$ENGINE_DIR/dist/roo-engine"
if [ ! -x "$VENV/bin/pyinstaller" ]; then python3 -m venv "$VENV"; "$VENV/bin/pip" install --quiet -r "$HERE/requirements-freeze.txt"; fi
echo "== [1/3] PyInstaller freeze (NumPy only) =="
cd "$ENGINE_DIR"
"$VENV/bin/pyinstaller" --noconfirm --clean --onedir --name roo-engine --distpath dist --workpath build --specpath build --paths . freeze/freeze_entry.py
test -x "$OUT/roo-engine"
echo "== [2/3] native qwentts (Vulkan + portable CPU fallback) =="
bash "$HERE/build-native.sh" linux "$OUT"
# The Vulkan loader/ICD is a host prerequisite for Linux AppImage installs;
# the image carries qwentts and its CPU fallback but does not replace GPU drivers.
echo "Linux runtime prerequisite: libvulkan.so.1 plus a Vulkan 1.2+ ICD for acceleration; CPU fallback remains available."
echo "== [3/3] bundled resources =="
"$VENV/bin/python" "$HERE/prepare-assets.py" --output "$OUT"
"$VENV/bin/python" "$HERE/prepare-assets.py" --check --output "$OUT"
"$OUT/roo-engine" --manifest "$OUT/manifest.json" --native-bin "$OUT/tts-server" --data-dir "$ENGINE_DIR/dist/.smoke-data" --help >/dev/null
du -sh "$OUT"
echo "OK: $OUT (Vulkan linked; portable CPU fallback)"
