#!/usr/bin/env bash
# v0.7-P2-3 — actual macOS release pipeline.
#
# Usage:  bash scripts/release_macos.sh <version>
# Example: bash scripts/release_macos.sh 0.7.0
#
# Reads credentials from .env (which lives ungit-committed in the
# repo root; see .env.example for the schema). Aborts with a
# friendly message if any prerequisite is missing — better than
# half-completing a release and leaving a broken .dmg around.
#
# Pipeline (matches docs/macos-signing.md §2):
#   1. codesign --options runtime + entitlements
#   2. create-dmg → dist/PixCull-<v>.dmg
#   3. notarytool submit --wait
#   4. stapler staple
#   5. sign_update → EdDSA signature for the appcast
#   6. print the signature + size for paste-into releases.json
#
# This script is idempotent: re-running it on the same version
# overwrites the previous .dmg. Apple's notarization is also
# idempotent (the same DMG hash → same submission ID).

set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
    echo "[release] usage: bash scripts/release_macos.sh <version>" >&2
    echo "[release] example: bash scripts/release_macos.sh 0.7.0" >&2
    exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --- prereqs ---------------------------------------------------------------
if [[ ! -f .env ]]; then
    echo "[release] missing .env — copy .env.example to .env and fill in" >&2
    echo "[release] see docs/APPLE-DEVELOPER-SETUP.md for the full setup" >&2
    exit 2
fi
# shellcheck disable=SC1091
set -a; source .env; set +a

: "${APPLE_SIGNING_IDENTITY:?APPLE_SIGNING_IDENTITY missing — see .env.example}"
: "${APPLE_NOTARY_PROFILE:?APPLE_NOTARY_PROFILE missing — see .env.example}"
: "${SPARKLE_ED_ACCOUNT:?SPARKLE_ED_ACCOUNT missing — see .env.example}"

APP_PATH="dist/PixCull.app"
DMG_PATH="dist/PixCull-${VERSION}.dmg"
ENTITLEMENTS_PATH="dist/entitlements.plist"

if [[ ! -d "$APP_PATH" ]]; then
    echo "[release] missing $APP_PATH — run \`make app\` (py2app build) first" >&2
    exit 2
fi
if [[ ! -f "$ENTITLEMENTS_PATH" ]]; then
    echo "[release] missing $ENTITLEMENTS_PATH — see docs/macos-signing.md" >&2
    exit 2
fi
if ! command -v create-dmg >/dev/null 2>&1; then
    echo "[release] create-dmg not on PATH — brew install create-dmg" >&2
    exit 2
fi
if [[ ! -x "${HOME}/Sparkle/bin/sign_update" ]]; then
    echo "[release] missing ~/Sparkle/bin/sign_update" >&2
    echo "[release] see docs/APPLE-DEVELOPER-SETUP.md §5" >&2
    exit 2
fi

# --- 1. codesign -----------------------------------------------------------
echo "[release] [1/5] codesign..."
codesign --deep --force --options runtime \
    --entitlements "$ENTITLEMENTS_PATH" \
    --sign "$APPLE_SIGNING_IDENTITY" \
    "$APP_PATH"
codesign --verify --deep --verbose=2 "$APP_PATH" \
    || { echo "[release] codesign verification failed" >&2; exit 1; }
echo "[release] [1/5] codesign OK"

# --- 2. dmg ---------------------------------------------------------------
echo "[release] [2/5] dmg build..."
rm -f "$DMG_PATH"
create-dmg \
    --volname "PixCull ${VERSION}" \
    --window-size 600 400 \
    --icon-size 128 \
    --app-drop-link 425 200 \
    "$DMG_PATH" \
    "$APP_PATH"
echo "[release] [2/5] dmg OK ($(du -h "$DMG_PATH" | awk '{print $1}'))"

# --- 3. notarize ----------------------------------------------------------
echo "[release] [3/5] notarize submission... (typically 5-30 minutes)"
xcrun notarytool submit "$DMG_PATH" \
    --keychain-profile "$APPLE_NOTARY_PROFILE" \
    --wait
echo "[release] [3/5] notarize accepted"

# --- 4. staple ------------------------------------------------------------
echo "[release] [4/5] stapler staple..."
xcrun stapler staple "$DMG_PATH"
xcrun stapler validate "$DMG_PATH"
echo "[release] [4/5] stapler OK"

# --- 5. sparkle sign_update -----------------------------------------------
echo "[release] [5/5] sparkle sign_update..."
SIG_OUTPUT="$("${HOME}/Sparkle/bin/sign_update" "$DMG_PATH" \
    --account "$SPARKLE_ED_ACCOUNT")"
SIZE_BYTES=$(stat -f %z "$DMG_PATH" 2>/dev/null || stat -c %s "$DMG_PATH")
echo "[release] [5/5] sparkle sign_update OK"

# --- summary --------------------------------------------------------------
cat <<EOF

═════════════════════════════════════════════════════════════════
  $DMG_PATH ready · ${SIZE_BYTES} bytes
═════════════════════════════════════════════════════════════════

Paste into dist/releases.json under the matching version entry:

  "size_bytes":  ${SIZE_BYTES},
  ${SIG_OUTPUT}

Then:

  python scripts/build_appcast.py dist/releases.json --out dist/appcast.xml
  gh release upload v${VERSION} dist/${DMG_PATH##*/} dist/appcast.xml

(or upload both files to your CDN of choice — see
 docs/APPLE-DEVELOPER-SETUP.md §7-§9.)

EOF
