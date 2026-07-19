#!/usr/bin/env bash
# IP-178/179 — deep-sign the frozen engine so notarization accepts the bundle.
#
# Apple's notarization rejected the .app because every Mach-O inside
# Resources/roo-engine/_internal (Python framework, numpy .so, openssl dylibs)
# was unsigned: "not signed with a valid Developer ID", "no hardened runtime",
# "no secure timestamp" (CI run 29689401809). The Tauri bundler signs the app
# wrapper, NOT resource Mach-Os — so we sign them all BEFORE bundling.
#
# Usage: presign-macos.sh <engine-dist-dir> <signing-identity> [entitlements]
set -euo pipefail

DIR="${1:?engine dist dir}"
IDENT="${2:?signing identity}"
ENT="${3:-}"

sign() {
  # shellcheck disable=SC2086
  codesign --force --timestamp --options runtime -s "$IDENT" "$@"
}

COUNT=0
while IFS= read -r -d '' f; do
  case "$(file -b "$f")" in
    Mach-O*)
      case "$f" in
        */roo-engine|*/llama-server)
          if [ -n "$ENT" ]; then sign --entitlements "$ENT" "$f"; else sign "$f"; fi
          ;;
        *) sign "$f" ;;
      esac
      COUNT=$((COUNT + 1))
      ;;
  esac
done < <(find "$DIR" -type f -print0)

# Seal the Python framework bundle AFTER its contents are signed.
FW="$DIR/_internal/Python.framework"
if [ -d "$FW" ]; then
  sign "$FW"
fi

echo "presigned $COUNT Mach-O files"
BAD=0
while IFS= read -r -d '' f; do
  case "$(file -b "$f")" in
    Mach-O*)
      codesign --verify --strict "$f" 2>/dev/null || { echo "UNVERIFIED: $f" >&2; BAD=1; }
      ;;
  esac
done < <(find "$DIR" -type f -print0)
[ "$BAD" = "0" ] && echo "verification: all Mach-O signatures valid" || exit 1
