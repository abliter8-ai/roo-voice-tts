#!/usr/bin/env bash
# IP-178 — freeze roo-engine (Linux x64) into a self-contained onedir bundle.
# DRAFT authored on macOS; validated on CI / ruin-ultra. Mirrors build-macos.sh.
#
# ELF note: the phonemizer temp-copy trick needs no install-name surgery here —
# the engine preloads libpcaudio with RTLD_GLOBAL and the copy's DT_NEEDED
# soname resolves against the already-loaded image natively.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"          # app/engine/freeze
ENGINE_DIR="$(dirname "$HERE")"                # app/engine
VENV="${ROO_FREEZE_ENV:-$ENGINE_DIR/.freeze-venv}"
LLAMA_TAG="${LLAMA_TAG:-b10068}"
OUT="$ENGINE_DIR/dist/roo-engine"

echo "== [1/4] freeze venv =="
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet phonemizer onnxruntime numpy pyinstaller
fi

echo "== [2/4] PyInstaller freeze =="
cd "$ENGINE_DIR"
"$VENV/bin/pyinstaller" --noconfirm --clean --onedir --name roo-engine \
  --distpath dist --workpath build --specpath build \
  --collect-data language_tags --collect-data csvw --collect-data segments \
  --collect-data phonemizer \
  --paths . freeze/freeze_entry.py
test -x "$OUT/roo-engine"

echo "== [3/4] vendor espeak-ng (distro packages) =="
# ubuntu: apt-get install -y espeak-ng-data libespeak-ng1 libpcaudio0
LIBDIR="/usr/lib/x86_64-linux-gnu"
cp "$LIBDIR/libespeak-ng.so.1" "$OUT/libespeak-ng.so.1"
cp "$LIBDIR/libpcaudio.so.0"   "$OUT/libpcaudio.so.0" 2>/dev/null || true
DATA="$LIBDIR/espeak-ng-data"
[ -d "$DATA" ] || DATA="/usr/share/espeak-ng-data"
cp -r "$DATA" "$OUT/espeak-ng-data"
chmod -R u+w "$OUT/espeak-ng-data" "$OUT"/libespeak* "$OUT"/libpcaudio* 2>/dev/null || true

echo "== [4/4] official llama-server (ubuntu-vulkan-x64) =="
TMP="$(mktemp -d)"
curl -sL -o "$TMP/llama.tgz" \
  "https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_TAG}/llama-${LLAMA_TAG}-bin-ubuntu-vulkan-x64.tar.gz"
tar -xzf "$TMP/llama.tgz" -C "$TMP"
LBIN="$(find "$TMP" -name llama-server -type f | head -1)"
LDIR="$(dirname "$LBIN")"
cp "$LBIN" "$OUT/"
find "$LDIR" -maxdepth 1 -name '*.so*' -exec cp {} "$OUT/" \;
chmod +x "$OUT/llama-server"

"$OUT/roo-engine" --phonemize "The quick brown fox."
"$OUT/llama-server" --version 2>&1 | head -2 || true
du -sh "$OUT"
echo "OK: $OUT"
