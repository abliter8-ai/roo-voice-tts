#!/usr/bin/env bash
# Sign + notarize + staple "Roo Voice.app" and package a signed DMG.
#
# Run it from anywhere — including over SSH. It re-execs itself into the GUI
# session when needed (see PREFERENCE DOMAIN below).
#
#   bash installers/macos/sign_and_notarize.sh [path/to/Roo Voice.app]
#
# ---------------------------------------------------------------------------
# PREFERENCE DOMAIN (IP-176 §9.3) — why this script re-execs itself
# ---------------------------------------------------------------------------
# macOS resolves the keychain preference domain PER PROCESS. Any SSH / VS Code
# Remote-SSH / agent shell gets domain=system, which reads the *system* keychain
# search list ("System.keychain", listed twice) and never the user domain. The
# Developer ID identity lives in login.keychain-db, so codesign reports
#     "Developer ID Application: ...: no identity found"
# even though the identity is present, valid, and its chain verifies. Nothing is
# wrong with the certificate — the process is just looking in the wrong place.
#
# Fix: run inside the user's GUI session via `launchctl asuser`.
#
# ---------------------------------------------------------------------------
# The security CLI lies on macOS 26 (Tahoe)
# ---------------------------------------------------------------------------
# Tahoe has documented `security` CLI regressions (hangs, spurious "incorrect
# passphrase", wrong exit codes). During IP-176 every diagnosis that trusted the
# CLI was wrong; only direct Security-framework calls were truthful. So we verify
# the preference domain via ctypes, and we prove signing works with a CANARY SIGN
# before touching the real bundle. If the environment is not what we assume, we
# abort — an unsigned release that looks fine is worse than a failed build.
# NOTE: `set -o pipefail` + `grep -q` is a trap. grep -q exits on first match and
# closes the pipe; the upstream command takes SIGPIPE and dies non-zero; pipefail
# then reports the whole pipeline as FAILED *because it matched*. Every content
# check below therefore captures output to a variable first and uses a pipe-free
# `case` test. (Hit for real: the canary reported "TeamIdentifier != ..." against
# a signature that was perfectly correct.)
set -euo pipefail

IDENTITY="${ROO_SIGN_IDENTITY:-Developer ID Application: David Wallace (486MQ2RRK3)}"
TEAM_ID="${ROO_TEAM_ID:-486MQ2RRK3}"
KEYCHAIN_PROFILE="${ROO_NOTARY_PROFILE:-roo-notary}"

HERE="$(cd "$(dirname "$0")" && pwd)"
ENTITLEMENTS="$HERE/entitlements.plist"
APP="${1:-$HERE/build/Roo Voice.app}"
DMG_OUT="$HERE/build/Roo-Voice.dmg"

say() { printf "\n\033[1m==> %s\033[0m\n" "$*"; }
die() { printf "\n\033[31m✗ %s\033[0m\n\n" "$*" >&2; exit 1; }

# ---- 0. get ourselves into a user-domain session --------------------------- #
domain() {
  /usr/bin/python3 - <<'PY'
import ctypes, ctypes.util
S = ctypes.CDLL(ctypes.util.find_library("Security"))
d = ctypes.c_uint32(); S.SecKeychainGetPreferenceDomain(ctypes.byref(d))
print(d.value)   # 0=user 1=system 2=common 3=dynamic
PY
}

if [ "${ROO_REEXEC:-0}" != "1" ] && [ "$(domain)" != "0" ]; then
  say "keychain preference domain is $(domain) (not user) — re-execing into the GUI session"
  echo "    This is why codesign says 'no identity found' over SSH. sudo will prompt once."
  UID_N="$(id -u)"; USER_N="$(id -un)"
  exec sudo launchctl asuser "$UID_N" sudo -u "$USER_N" \
       env ROO_REEXEC=1 ROO_SIGN_IDENTITY="$IDENTITY" ROO_TEAM_ID="$TEAM_ID" \
           ROO_NOTARY_PROFILE="$KEYCHAIN_PROFILE" \
       bash "$0" "$@"
fi

# --dmg-only: the .app is already signed+notarized+stapled; just (re)build,
# notarize and staple the DMG. Skips the ~1869-file inside-out signing pass.
DMG_ONLY=0
for a in "$@"; do [ "$a" = "--dmg-only" ] && DMG_ONLY=1; done
[ "$DMG_ONLY" = "1" ] && APP="$HERE/build/Roo Voice.app"

[ "$(domain)" = "0" ] || die "still not in a user-domain session (domain=$(domain)). Run this from Terminal.app on the Mac itself."
[ -d "$APP" ] || die "app bundle not found: $APP  (build it first: bash installers/macos/build_dmg.sh)"
[ -f "$ENTITLEMENTS" ] || die "entitlements not found: $ENTITLEMENTS"

if [ "$DMG_ONLY" = "1" ]; then
  say "--dmg-only: skipping app signing; packaging + notarizing the DMG"
fi

# ---- 1. preconditions: identity present, and signing actually works -------- #
say "checking signing identity"
security find-identity -v -p codesigning | grep -F "$IDENTITY" \
  || die "identity not found: $IDENTITY"
echo "    found: $IDENTITY"

# The canary must FAIL FAST, not block. Two traps, both hit for real during IP-176:
#
#  1. If the signing key's partition list lacks apple-tool:/apple:/codesign:,
#     codesign raises a GUI keychain prompt. Run remotely, that dialog sits on the
#     Mac's physical screen where nobody sees it, and codesign blocks forever — a
#     "canary" that hangs proves nothing. `security import -A` is NOT sufficient.
#  2. --timestamp needs a network round-trip to Apple's TSA (port 80). Keep it out
#     of the canary: the canary is proving KEY ACCESS, not timestamping.
say "granting codesign standing access to the key (avoids an invisible GUI prompt)"
if [ -n "${ROO_KEYCHAIN_PASSWORD:-}" ] && security set-key-partition-list \
     -S apple-tool:,apple:,codesign: -s -k "$ROO_KEYCHAIN_PASSWORD" \
     "$HOME/Library/Keychains/login.keychain-db" >/dev/null 2>&1; then
  echo "    partition list set (from ROO_KEYCHAIN_PASSWORD)"
elif security set-key-partition-list -S apple-tool:,apple:,codesign: -s \
     "$HOME/Library/Keychains/login.keychain-db" >/dev/null 2>&1; then
  echo "    partition list set"
else
  echo "    could not set it non-interactively (no ROO_KEYCHAIN_PASSWORD)."
  echo "    If the canary below stalls, a keychain dialog is waiting on the Mac's"
  echo "    screen — click Always Allow, or run:"
  echo "      security set-key-partition-list -S apple-tool:,apple:,codesign: -s \\"
  echo "        -k <login-password> ~/Library/Keychains/login.keychain-db"
fi

say "canary sign (prove key access before touching the real bundle)"
CANARY="$(mktemp -d)/canary"; cp /usr/bin/true "$CANARY"
# no --timestamp here, and a hard timeout: a blocked canary must fail, not hang.
if ! perl -e 'alarm shift; exec @ARGV' 60 \
      codesign --force --options runtime --timestamp=none \
               --sign "$IDENTITY" "$CANARY" 2>/dev/null; then
  die "canary sign failed or timed out after 60s.

If it TIMED OUT, a keychain permission dialog is almost certainly waiting on this
Mac's physical screen (SecurityAgent), invisible over SSH. Either click Always
Allow on the Mac, or grant standing access first:

  security set-key-partition-list -S apple-tool:,apple:,codesign: -s \\
    -k <login-password> ~/Library/Keychains/login.keychain-db

Do NOT ship until the canary passes — the release would be silently unsigned."
fi
CANARY_INFO="$(codesign -dv --verbose=2 "$CANARY" 2>&1 || true)"
case "$CANARY_INFO" in
  *"TeamIdentifier=$TEAM_ID"*) : ;;
  *)
  printf '\n\033[31m✗ canary signed but TeamIdentifier != %s\033[0m\n\n' "$TEAM_ID" >&2
  echo "What codesign actually reports for the canary:" >&2
  printf '%s\n' "$CANARY_INFO" | sed 's/^/    /' >&2
  echo "" >&2
  die "aborting — the signature is not what we expect; do NOT ship" ;;
esac
echo "    canary OK — the key is usable without prompting"
printf '%s\n' "$CANARY_INFO" | grep -E "Authority=|TeamIdentifier=" | head -3 | sed 's/^/    /' 

say "checking Apple's timestamp server is reachable (--timestamp needs it)"
if nc -z -G 8 timestamp.apple.com 80 2>/dev/null; then
  echo "    timestamp.apple.com:80 reachable"
else
  die "cannot reach timestamp.apple.com:80 — signing with --timestamp would stall.
Notarization requires a secure timestamp, so fix connectivity before shipping."
fi

if [ "$DMG_ONLY" != "1" ]; then
# ---- 2. sign inside-out ---------------------------------------------------- #
# Every nested Mach-O must be signed before the bundle that contains it.
say "signing nested code (inside-out)"
# A swallowed failure here yields a bundle that notarizes and then fails at
# launch — exactly the "looks fine but isn't" outcome this script exists to stop.
COUNT=0; FAILED=0; FAILED_LIST=""
while IFS= read -r -d '' f; do
  case "$f" in *.py|*.txt|*.json|*.md|*.png|*.wav|*.ttf|*.gif) continue;; esac
  FTYPE="$(file -b "$f" 2>/dev/null || true)"
  case "$FTYPE" in *Mach-O*) ;; *) continue;; esac
  if true; then
    if codesign --force --options runtime --timestamp \
                --entitlements "$ENTITLEMENTS" --sign "$IDENTITY" "$f" 2>/dev/null; then
      COUNT=$((COUNT+1))
    else
      FAILED=$((FAILED+1)); FAILED_LIST="$FAILED_LIST\n    $f"
    fi
  fi
done < <(find "$APP/Contents/Resources" -type f -print0)
echo "    signed $COUNT nested Mach-O files"
[ "$FAILED" -eq 0 ] || die "$FAILED nested binaries failed to sign:$(printf "$FAILED_LIST")"

say "signing the launcher + bundle"
codesign --force --options runtime --timestamp \
         --entitlements "$ENTITLEMENTS" --sign "$IDENTITY" "$APP/Contents/MacOS/roo-voice"
codesign --force --options runtime --timestamp \
         --entitlements "$ENTITLEMENTS" --sign "$IDENTITY" "$APP"

say "verifying the signature"
codesign --verify --deep --strict --verbose=2 "$APP" 2>&1 | tail -2
codesign -dv --verbose=2 "$APP" 2>&1 | grep -E "Authority|TeamIdentifier|Timestamp=" | sed 's/^/    /'

# ---- 3. notarize ----------------------------------------------------------- #
# The credential must live in the keychain of the session that USES it. A
# store-credentials run from an SSH shell lands in the system default keychain
# and is invisible here — so provision it in-session when missing.
if ! xcrun notarytool history --keychain-profile "$KEYCHAIN_PROFILE" >/dev/null 2>&1; then
  say "no usable notary credential in this session — provisioning it"
  ENV_FILE="${ROO_ENV_FILE:-/Users/roo/Developer/ruin-inference-setup/.env}"
  # Pull only the two keys we need; never source the whole .env wholesale.
  KEY_ID="${APPSTORE_CONNECT_KEY_ID:-$(sed -n 's/^APPSTORE_CONNECT_KEY_ID=//p' "$ENV_FILE" 2>/dev/null | tr -d "\"'" | head -1)}"
  ISSUER="${APPSTORE_ISSUER_ID:-$(sed -n 's/^APPSTORE_ISSUER_ID=//p' "$ENV_FILE" 2>/dev/null | tr -d "\"'" | head -1)}"
  KEYFILE="$HOME/.apple-signing/AuthKey_${KEY_ID}.p8"
  [ -n "$KEY_ID" ] && [ -n "$ISSUER" ] || die "APPSTORE_CONNECT_KEY_ID / APPSTORE_ISSUER_ID not found in $ENV_FILE"
  [ -f "$KEYFILE" ] || die "notary key not found: $KEYFILE"
  xcrun notarytool store-credentials "$KEYCHAIN_PROFILE" \
    --key "$KEYFILE" --key-id "$KEY_ID" --issuer "$ISSUER" \
    || die "could not store the notary credential"
  xcrun notarytool history --keychain-profile "$KEYCHAIN_PROFILE" >/dev/null 2>&1 \
    || die "credential stored but still not readable in this session"
  echo "    credential provisioned in-session"
fi

say "notarizing (uploads to Apple; typically 1-5 min)"
ZIP="$(mktemp -d)/RooVoice.zip"
ditto -c -k --keepParent "$APP" "$ZIP"
xcrun notarytool submit "$ZIP" --keychain-profile "$KEYCHAIN_PROFILE" --wait 2>&1 | tee /tmp/roo-notary.log
NOTARY_OUT="$(cat /tmp/roo-notary.log 2>/dev/null || true)"
case "$NOTARY_OUT" in *"status: Accepted"*) ;; *)
  ID=$(grep -m1 "id:" /tmp/roo-notary.log | awk '{print $2}')
  echo ""
  echo "Notarization did not succeed. Full log:"
  xcrun notarytool log "$ID" --keychain-profile "$KEYCHAIN_PROFILE" 2>&1 | head -40
  die "notarization failed" ;;
esac

say "stapling the ticket"
xcrun stapler staple "$APP"
xcrun stapler validate "$APP" || die "staple validation failed"

# ---- 4. the gate that matters ---------------------------------------------- #
say "Gatekeeper verdict (this is the whole point)"
SPCTL_OUT="$(spctl -a -vv "$APP" 2>&1 || true)"
printf '%s\n' "$SPCTL_OUT" | sed 's/^/    /'
case "$SPCTL_OUT" in
  *accepted*) ;;
  *) die "spctl still rejects the app — do not ship" ;;
esac

fi   # end of app-signing path (skipped by --dmg-only)

# ---- 5. repackage the DMG, signed + stapled -------------------------------- #
say "packaging signed DMG"
STAGE="$(mktemp -d)/dmg"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Roo Voice" -srcfolder "$STAGE" -ov -format UDZO "$DMG_OUT" >/dev/null
codesign --force --timestamp --sign "$IDENTITY" "$DMG_OUT"

# The DMG needs notarizing IN ITS OWN RIGHT. Notarizing the .app and stapling the
# .app is not enough: the DMG is the artifact users download, and Gatekeeper
# checks it on mount. A stapled .app inside an unnotarized DMG still gets the DMG
# flagged (observed: spctl "rejected / source=Unnotarized Developer ID").
say "notarizing the DMG (uploads to Apple; typically 1-5 min)"
xcrun notarytool submit "$DMG_OUT" --keychain-profile "$KEYCHAIN_PROFILE" --wait 2>&1 | tee /tmp/roo-notary-dmg.log
DMG_OUT_LOG="$(cat /tmp/roo-notary-dmg.log 2>/dev/null || true)"
case "$DMG_OUT_LOG" in
  *"status: Accepted"*) ;;
  *) die "DMG notarization failed — see /tmp/roo-notary-dmg.log" ;;
esac

say "stapling the DMG"
xcrun stapler staple "$DMG_OUT" || die "DMG staple failed"
xcrun stapler validate "$DMG_OUT" || die "DMG staple validation failed"

say "Gatekeeper verdict on the DMG (what users actually download)"
DMG_SPCTL="$(spctl -a -vv -t open --context context:primary-signature "$DMG_OUT" 2>&1 || true)"
printf '%s\n' "$DMG_SPCTL" | sed 's/^/    /'
case "$DMG_SPCTL" in
  *accepted*) ;;
  *) die "spctl still rejects the DMG — do not ship" ;;
esac

printf "\n\033[32m✓ DONE\033[0m\n"
echo "    app: $APP"
echo "    dmg: $DMG_OUT  ($(du -sh "$DMG_OUT" | cut -f1))"
echo "    spctl: accepted · notarized · stapled"
