#!/usr/bin/env bash
# IP-178 — freeze roo-engine into a self-contained onedir bundle (macOS arm64).
#
# Output: app/engine/dist/roo-engine/
#   roo-engine           frozen binary (python + phonemizer + onnxruntime + numpy)
#   libespeak-ng.dylib   vendored, install-names retargeted to @loader_path
#   libpcaudio.0.dylib   espeak's one non-system dep
#   espeak-ng-data/      voice data (en-gb) — engine probe finds both beside binary
#   llama-server + *.dylib / *.metallib   OFFICIAL ggml-org release (self-contained;
#                        the Homebrew build is NOT shippable — @rpath ggml + openssl)
#
# The Tauri bundler ships this dir as resources; sign_and_notarize handles the
# nested Mach-O signing (IP-176 pipeline).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"          # app/engine/freeze
ENGINE_DIR="$(dirname "$HERE")"                # app/engine
VENV="${ROO_FREEZE_ENV:-$HOME/roo-voice/engine-freeze/env}"
LLAMA_TAG="${LLAMA_TAG:-b10068}"
OUT="$ENGINE_DIR/dist/roo-engine"

echo "== [1/4] PyInstaller freeze =="
cd "$ENGINE_DIR"
"$VENV/bin/pyinstaller" --noconfirm --clean --onedir --name roo-engine \
  --distpath dist --workpath build --specpath build \
  --collect-data language_tags --collect-data csvw --collect-data segments \
  --collect-data phonemizer \
  --paths . freeze/freeze_entry.py
test -x "$OUT/roo-engine"

echo "== [2/4] vendor espeak-ng =="
EBREW="$(brew --prefix espeak-ng)"
PBREW="$(brew --prefix pcaudiolib)"
cp "$EBREW/lib/libespeak-ng.1.dylib" "$OUT/libespeak-ng.dylib"
cp "$PBREW/lib/libpcaudio.0.dylib"   "$OUT/libpcaudio.0.dylib"
chmod u+w "$OUT/libespeak-ng.dylib" "$OUT/libpcaudio.0.dylib"
rm -rf "$OUT/espeak-ng-data"
cp -R "$EBREW/share/espeak-ng-data" "$OUT/espeak-ng-data"
# Cellar files are mode 444; user-writable copies or the NEXT bundler run
# cannot overwrite its previous output (os error 13).
chmod -R u+w "$OUT/espeak-ng-data"
# Bare-name dep + engine-side preload: phonemizer loads a TEMP COPY of the
# espeak dylib, so @loader_path would resolve to the temp dir and fail. With a
# bare install name, dyld satisfies the copy's dependency from the pcaudio image
# the engine preloads by absolute path (engine.Phonemizer._locate_espeak).
install_name_tool -id @loader_path/libespeak-ng.dylib "$OUT/libespeak-ng.dylib"
install_name_tool -id libpcaudio.0.dylib "$OUT/libpcaudio.0.dylib"
PCA_DEP="$(otool -L "$OUT/libespeak-ng.dylib" | awk '/libpcaudio/{print $1}')"
install_name_tool -change "$PCA_DEP" libpcaudio.0.dylib "$OUT/libespeak-ng.dylib"
codesign --force -s - "$OUT/libespeak-ng.dylib" "$OUT/libpcaudio.0.dylib"
if otool -L "$OUT/libespeak-ng.dylib" | grep -q /opt/homebrew; then
  echo "FATAL: homebrew paths still referenced in vendored espeak" >&2; exit 1
fi

echo "== [3/4] official llama-server ${LLAMA_TAG} =="
TMP="$(mktemp -d)"
curl -sL -o "$TMP/llama.tgz" \
  "https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_TAG}/llama-${LLAMA_TAG}-bin-macos-arm64.tar.gz"
tar -xzf "$TMP/llama.tgz" -C "$TMP"
LBIN="$(find "$TMP" -name llama-server -type f | head -1)"
LDIR="$(dirname "$LBIN")"
cp "$LBIN" "$OUT/"
find "$LDIR" -maxdepth 1 \( -name '*.dylib' -o -name '*.metallib' \) -exec cp {} "$OUT/" \;
chmod +x "$OUT/llama-server"

echo "== [4/4] verify =="
"$OUT/roo-engine" --phonemize "The quick brown fox."
"$OUT/llama-server" --version 2>&1 | head -2
du -sh "$OUT"
echo "OK: $OUT"
