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

if [ ! -x "$VENV/bin/pyinstaller" ]; then   # CI runners start bare
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet phonemizer onnxruntime numpy pyinstaller
fi

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

echo "== [3/4] llama-server ${LLAMA_TAG} — SOURCE build, static, floor macOS ${MACOS_FLOOR:-14.0} =="
# CI shakedown finding (run 29686559249): the official macos-arm64 release
# binaries carry deployment target macOS 26 and dyld-abort on anything older
# (_OBJC_CLASS_$_MTLResidencySetDescriptor). Building from source with an
# explicit deployment target weak-links the new-OS Metal APIs; static libs +
# embedded metallib give ONE self-contained binary (simpler nested signing).
SRC="${LLAMA_SRC:-$ENGINE_DIR/build/llama.cpp-src}"
if [ ! -d "$SRC/.git" ]; then
  git clone --quiet --depth 1 --branch "$LLAMA_TAG" \
    https://github.com/ggml-org/llama.cpp "$SRC"
fi
cmake -S "$SRC" -B "$SRC/build" -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_OSX_DEPLOYMENT_TARGET="${MACOS_FLOOR:-14.0}" \
  -DBUILD_SHARED_LIBS=OFF -DGGML_METAL=ON -DGGML_METAL_EMBED_LIBRARY=ON \
  -DLLAMA_CURL=OFF -DLLAMA_SERVER_SSL=OFF -DCMAKE_DISABLE_FIND_PACKAGE_OpenSSL=ON \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF \
  -DLLAMA_BUILD_SERVER=ON >/dev/null
cmake --build "$SRC/build" --target llama-server -j >/dev/null
cp "$SRC/build/bin/llama-server" "$OUT/"
chmod +x "$OUT/llama-server"
# LC_BUILD_VERSION block is cmd/cmdsize/platform/minos/sdk — minos is 3 lines in
if ! otool -l "$OUT/llama-server" | grep -A4 LC_BUILD_VERSION | grep -q "minos ${MACOS_FLOOR:-14.0}"; then
  echo "FATAL: llama-server deployment target is not ${MACOS_FLOOR:-14.0}" >&2
  otool -l "$OUT/llama-server" | grep -A4 LC_BUILD_VERSION | head -6 >&2
  exit 1
fi
if otool -L "$OUT/llama-server" | grep -qE '/opt/homebrew|/usr/local'; then
  echo "FATAL: llama-server links non-system libraries:" >&2
  otool -L "$OUT/llama-server" | grep -E '/opt/homebrew|/usr/local' >&2
  exit 1
fi
echo "deployment floor ${MACOS_FLOOR:-14.0} + self-containment verified"

echo "== [4/4] verify =="
"$OUT/roo-engine" --phonemize "The quick brown fox."
"$OUT/llama-server" --version 2>&1 | head -2
du -sh "$OUT"
echo "OK: $OUT"
