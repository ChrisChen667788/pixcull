#!/usr/bin/env bash
# PixCull · V13.0 release pipeline (Apple Developer ID signed + notarized)
#
# Prerequisites
# -------------
# * Apple Developer ID Application certificate installed in Keychain.
#     security find-identity -v -p codesigning  # to verify
# * notarytool keychain profile already set up (see app/NOTARIZATION.md):
#     xcrun notarytool store-credentials "pixcull-notary" \
#       --apple-id "you@example.com" \
#       --team-id "ABCDE12345" \
#       --password "app-specific-password"
# * sparkle CLI: brew install --cask sparkle
#     (only needed for the optional sparkle signature step)
#
# Environment overrides
# ---------------------
# DEV_ID_NAME      Developer ID Application: ... full name in Keychain
# NOTARY_PROFILE   keychain profile name (default: pixcull-notary)
# RELEASE_VERSION  bumped version string (e.g., 13.0.1)
# UPLOAD_URL       optional URL to scp / aws s3 cp the DMG to
#
# Usage
# -----
#   RELEASE_VERSION=13.0.0 ./scripts/release.sh
#
# Output
# ------
#   dist/PixCull-13.0.0.dmg                signed + notarized DMG
#   dist/PixCull-13.0.0.dmg.asc            (optional) sparkle signature
#   dist/PixCull-13.0.0.appcast-fragment.xml  paste into appcast.xml

set -euo pipefail

cd "$(dirname "$0")/.."

DEV_ID_NAME="${DEV_ID_NAME:-Developer ID Application: REPLACE_WITH_YOUR_NAME (TEAMID12345)}"
NOTARY_PROFILE="${NOTARY_PROFILE:-pixcull-notary}"
RELEASE_VERSION="${RELEASE_VERSION:-$(date +%Y.%m.%d)}"

echo "============================================================"
echo "  PixCull V13 release · v${RELEASE_VERSION}"
echo "============================================================"

# --- 1. Clean build ------------------------------------------------
echo ""
echo "=== [1/6] PyInstaller build (~5 min) ==="
./scripts/build_app.sh

# --- 2. Replace ad-hoc signature with Developer ID ----------------
echo ""
echo "=== [2/6] Re-signing with Developer ID + Hardened Runtime ==="
xattr -cr dist/PixCull.app
codesign --deep --force --options runtime --timestamp \
    --entitlements app/entitlements.plist \
    -s "$DEV_ID_NAME" \
    dist/PixCull.app

echo ""
echo "  Verifying signature..."
codesign --verify --deep --strict --verbose=2 dist/PixCull.app
spctl -a -t exec -vv dist/PixCull.app

# --- 3. Make the DMG ----------------------------------------------
echo ""
echo "=== [3/6] Building DMG ==="
DMG_NAME="PixCull-${RELEASE_VERSION}.dmg"
mv dist/PixCull.dmg "dist/_old.dmg" 2>/dev/null || true
./scripts/make_dmg.sh
mv dist/PixCull.dmg "dist/${DMG_NAME}"
codesign --force --timestamp -s "$DEV_ID_NAME" "dist/${DMG_NAME}"

# --- 4. Notarize ---------------------------------------------------
echo ""
echo "=== [4/6] Notarizing (~5-15 min) ==="
xcrun notarytool submit "dist/${DMG_NAME}" \
    --keychain-profile "$NOTARY_PROFILE" \
    --wait

echo ""
echo "  Stapling notarization ticket..."
xcrun stapler staple "dist/${DMG_NAME}"
xcrun stapler validate "dist/${DMG_NAME}"

# --- 5. Optional: Sparkle EdDSA signature for appcast --------------
echo ""
echo "=== [5/6] Sparkle signature ==="
if command -v sign_update &>/dev/null; then
    SIG=$(sign_update "dist/${DMG_NAME}")
    echo "  Sparkle signature: $SIG"
    SIZE=$(stat -f%z "dist/${DMG_NAME}")
    PUB_DATE=$(date -R)
    cat > "dist/PixCull-${RELEASE_VERSION}.appcast-fragment.xml" <<EOF
    <item>
      <title>v${RELEASE_VERSION}</title>
      <pubDate>${PUB_DATE}</pubDate>
      <sparkle:minimumSystemVersion>12.0</sparkle:minimumSystemVersion>
      <description><![CDATA[
        <ul><li>Release v${RELEASE_VERSION}</li></ul>
      ]]></description>
      <enclosure
        url="https://pixcull.dev/releases/${DMG_NAME}"
        sparkle:version="${RELEASE_VERSION}"
        sparkle:shortVersionString="${RELEASE_VERSION}"
        sparkle:edSignature="${SIG}"
        length="${SIZE}"
        type="application/octet-stream" />
    </item>
EOF
    echo "  Appcast fragment: dist/PixCull-${RELEASE_VERSION}.appcast-fragment.xml"
else
    echo "  WARN: sign_update CLI not found; skipping Sparkle signature."
    echo "  Install Sparkle: brew install --cask sparkle"
fi

# --- 6. Optional: upload to release host --------------------------
if [ -n "${UPLOAD_URL:-}" ]; then
    echo ""
    echo "=== [6/6] Uploading to ${UPLOAD_URL} ==="
    if [[ "$UPLOAD_URL" == s3://* ]]; then
        aws s3 cp "dist/${DMG_NAME}" "${UPLOAD_URL}/${DMG_NAME}" --acl public-read
    else
        scp "dist/${DMG_NAME}" "${UPLOAD_URL}/"
    fi
fi

echo ""
echo "============================================================"
echo "  ✓ Release v${RELEASE_VERSION} ready: dist/${DMG_NAME}"
echo "============================================================"
echo ""
echo "Next steps:"
echo "  1. (if you skipped it) upload dist/${DMG_NAME} to your host"
echo "  2. Paste the appcast fragment into app/sparkle_appcast.xml"
echo "  3. Push the updated appcast.xml to https://pixcull.dev/"
echo "  4. Existing users will see the update offer within 24h"
