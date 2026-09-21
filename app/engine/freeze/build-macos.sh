#!/usr/bin/env bash
# IP-322 — freeze the Python sidecar and pinned qwentts native server (macOS arm64).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ENGINE_DIR="$(dirname "$HERE")"
VENV="${ROO_FREEZE_ENV:-$HOME/roo-voice/engine-freeze/env}"
OUT="$ENGINE_DIR/dist/roo-engine"
PBS_VER="3.12.13"; PBS_TAG="20260718"; PBS_DIR="${ROO_PBS_DIR:-$HOME/roo-voice/pbs-python}"
if [ ! -x "$VENV/bin/pyinstaller" ]; then
  if [ ! -x "$PBS_DIR/python/bin/python3.12" ]; then
    mkdir -p "$PBS_DIR"
    curl -sfL -o "$PBS_DIR/pbs.tgz" "https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/cpython-${PBS_VER}+${PBS_TAG}-aarch64-apple-darwin-install_only.tar.gz"
    tar -xzf "$PBS_DIR/pbs.tgz" -C "$PBS_DIR"
  fi
  "$PBS_DIR/python/bin/python3.12" -m venv "$VENV"
  "$VENV/bin/pip" install --quiet -r "$HERE/requirements-freeze.txt"
fi
echo "== [1/3] PyInstaller freeze (NumPy only) =="
cd "$ENGINE_DIR"
"$VENV/bin/pyinstaller" --noconfirm --clean --onedir --name roo-engine --distpath dist --workpath build --specpath build --paths . freeze/freeze_entry.py
test -x "$OUT/roo-engine"
echo "== [2/3] native qwentts (Metal, embedded metallib, macOS ${MACOS_FLOOR:-14.0}) =="
bash "$HERE/build-native.sh" macos "$OUT"
echo "== [3/3] bundled resources =="
"$VENV/bin/python" "$HERE/prepare-assets.py" --output "$OUT"
"$VENV/bin/python" "$HERE/prepare-assets.py" --check --output "$OUT"
"$OUT/roo-engine" --manifest "$OUT/manifest.json" --native-bin "$OUT/tts-server" --data-dir "$ENGINE_DIR/dist/.smoke-data" --help >/dev/null
du -sh "$OUT"
echo "OK: $OUT (Metal embedded; native qwentts + CPU fallback)"
