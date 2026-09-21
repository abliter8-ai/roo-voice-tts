#!/usr/bin/env bash
# Build the pinned qwentts.cpp native server for the shipping platform.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ENGINE_DIR="$(dirname "$HERE")"
SRC="${QWENTTS_SRC:-$ENGINE_DIR/build/qwentts-src}"
BUILD_ROOT="${QWENTTS_BUILD_DIR:-$ENGINE_DIR/build/native}"
QWENTTS_REPO="https://github.com/ServeurpersoCom/qwentts.cpp.git"
QWENTTS_COMMIT="0bfb9237c1aae55f6d279fc7e32b3416a6dbb93a"
GGML_COMMIT="e2568d7bd8c773cfd55665d17ddda5d176d51d03"

TARGET="${1:?usage: build-native.sh macos|linux|windows <output-dir>}"
OUT="${2:?usage: build-native.sh macos|linux|windows <output-dir>}"
case "$TARGET" in macos|linux|windows) ;; *) echo "unknown native target: $TARGET" >&2; exit 2 ;; esac

if [ ! -d "$SRC/.git" ]; then
  mkdir -p "$(dirname "$SRC")"
  git clone --quiet --no-checkout "$QWENTTS_REPO" "$SRC"
  git -C "$SRC" checkout --quiet --detach "$QWENTTS_COMMIT"
fi
ACTUAL="$(git -C "$SRC" rev-parse HEAD)"
[ "$ACTUAL" = "$QWENTTS_COMMIT" ] || { echo "FATAL: qwentts.cpp pin mismatch: $ACTUAL" >&2; exit 1; }
git -C "$SRC" submodule update --init --recursive
ACTUAL_GGML="$(git -C "$SRC/ggml" rev-parse HEAD)"
[ "$ACTUAL_GGML" = "$GGML_COMMIT" ] || { echo "FATAL: ggml pin mismatch: $ACTUAL_GGML" >&2; exit 1; }

mkdir -p "$BUILD_ROOT/$TARGET" "$OUT"
CONFIG=(
  -S "$SRC" -B "$BUILD_ROOT/$TARGET" -DCMAKE_BUILD_TYPE=Release
  -DBUILD_SHARED_LIBS=OFF -DGGML_NATIVE=OFF -DGGML_CPU=ON -DGGML_BLAS=OFF
  -DGGML_CUDA=OFF -DGGML_HIP=OFF -DGGML_SYCL=OFF -DGGML_WEBGPU=OFF
  -DGGML_BACKEND_DL=OFF -DGGML_BUILD_TESTS=OFF
)
case "$TARGET" in
  macos) CONFIG+=( -DCMAKE_OSX_DEPLOYMENT_TARGET="${MACOS_FLOOR:-14.0}" -DGGML_METAL=ON -DGGML_METAL_EMBED_LIBRARY=ON -DGGML_METAL_MACOSX_VERSION_MIN="${MACOS_FLOOR:-14.0}" -DGGML_VULKAN=OFF ) ;;
  linux|windows) CONFIG+=( -DGGML_METAL=OFF -DGGML_VULKAN=ON -DGGML_VULKAN_CHECK_RESULTS=OFF ) ;;
esac

echo "== qwentts.cpp $QWENTTS_COMMIT / ggml $GGML_COMMIT ($TARGET) =="
cmake "${CONFIG[@]}"
cmake --build "$BUILD_ROOT/$TARGET" --config Release --target tts-server --parallel "${CMAKE_BUILD_PARALLEL_LEVEL:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)}"
BIN="$BUILD_ROOT/$TARGET/tts-server"
[ "$TARGET" != windows ] || BIN="$BUILD_ROOT/$TARGET/Release/tts-server.exe"
[ -f "$BIN" ] || { echo "FATAL: native server was not produced: $BIN" >&2; exit 1; }
if [ "$TARGET" = windows ]; then cp "$BIN" "$OUT/tts-server.exe"; else cp "$BIN" "$OUT/tts-server"; chmod 755 "$OUT/tts-server"; fi

case "$TARGET" in
  macos)
    otool -L "$OUT/tts-server" | tee "$OUT/tts-server.links.txt"
    if otool -L "$OUT/tts-server" | grep -qE '/opt/homebrew|/usr/local'; then echo "FATAL: native server references a local library" >&2; exit 1; fi
    otool -l "$OUT/tts-server" | grep -A4 LC_BUILD_VERSION | grep -q "minos ${MACOS_FLOOR:-14.0}" || { echo "FATAL: native server is below macOS floor" >&2; exit 1; }
    ;;
  linux)
    if command -v ldd >/dev/null 2>&1; then
      ldd "$OUT/tts-server" | tee "$OUT/tts-server.links.txt"
      grep -q 'libvulkan' "$OUT/tts-server.links.txt" || { echo "FATAL: native server has no Vulkan loader dependency" >&2; exit 1; }
    fi
    ;;
  windows)
    # Ship the Vulkan loader when the SDK provides it. The ICD remains a
    # machine/driver component; the native binary still contains CPU kernels.
    VULKAN_DLL=""
    if [ -n "${VULKAN_SDK:-}" ]; then
      SDK_ROOT="$VULKAN_SDK"
      if command -v cygpath >/dev/null 2>&1; then SDK_ROOT="$(cygpath -u "$VULKAN_SDK")"; fi
      [ -f "$SDK_ROOT/Bin/vulkan-1.dll" ] && VULKAN_DLL="$SDK_ROOT/Bin/vulkan-1.dll"
    fi
    if [ -z "$VULKAN_DLL" ] && command -v cygpath >/dev/null 2>&1 && [ -f "$(cygpath -u 'C:\Windows\System32\vulkan-1.dll')" ]; then
      VULKAN_DLL="$(cygpath -u 'C:\Windows\System32\vulkan-1.dll')"
    fi
    [ -n "$VULKAN_DLL" ] || { echo "FATAL: Vulkan loader vulkan-1.dll is unavailable" >&2; exit 1; }
    cp "$VULKAN_DLL" "$OUT/vulkan-1.dll"
    command -v dumpbin >/dev/null 2>&1 && dumpbin /DEPENDENTS "$OUT/tts-server.exe" | tee "$OUT/tts-server.links.txt" ;;
esac
echo "native backend packaged: $OUT"
