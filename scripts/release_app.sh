#!/usr/bin/env bash
# V7.0 PixCull.app full distribution pipeline.
#
# This script automates everything from a clean checkout to a
# notarized + stapled DMG ready to publish.
#
# Pre-requisites you have to do ONCE manually
# ===========================================
# 1. Apple Developer Program membership — $99/year
#      https://developer.apple.com/programs/enroll/
#
# 2. A "Developer ID Application" certificate in your login keychain.
#    Create via: Xcode → Settings → Accounts → Manage Certificates
#    OR: Apple developer portal → Certificates → "+" → Developer ID Application
#
# 3. An app-specific password for notarytool, stored in keychain:
#      xcrun notarytool store-credentials "pixcull-notary" \
#          --apple-id "your-apple-id@example.com" \
#          --team-id "ABCDE12345" \
#          --password "abcd-efgh-ijkl-mnop"
#    (the password comes from appleid.apple.com → App-Specific Passwords)
#
# 4. Set the two env vars below to match your account, e.g. in ~/.zshrc:
#      export PIXCULL_SIGN_IDENTITY="Developer ID Application: Your Name (ABCDE12345)"
#      export PIXCULL_NOTARY_PROFILE="pixcull-notary"
#
# Then any release is just:
#      ./scripts/release_app.sh
#
# What this does
# ==============
# 1. Build clean (build_app.sh)
# 2. Re-sign with Developer ID + entitlements + hardened runtime
# 3. Build DMG
# 4. Sign DMG
# 5. Submit to Apple notarization (waits ~10-15 min)
# 6. Staple the ticket to the DMG so it works offline
# 7. Verify (spctl + stapler validate)
#
# Output: dist/PixCull.dmg (notarized, stapled, ready to ship)
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -z "${PIXCULL_SIGN_IDENTITY:-}" ]; then
    echo "ERROR: PIXCULL_SIGN_IDENTITY env var not set."
    echo "Set it to e.g. 'Developer ID Application: Your Name (ABCDE12345)'"
    echo "List available identities with: security find-identity -v -p codesigning"
    exit 1
fi
if [ -z "${PIXCULL_NOTARY_PROFILE:-}" ]; then
    echo "ERROR: PIXCULL_NOTARY_PROFILE env var not set."
    echo "Set up notary credentials with:"
    echo "  xcrun notarytool store-credentials pixcull-notary \\"
    echo "      --apple-id YOUR_ID --team-id TEAM_ID --password APP_PASSWORD"
    echo "Then export PIXCULL_NOTARY_PROFILE=pixcull-notary"
    exit 1
fi

VENV=${VENV:-.venv}
APP=dist/PixCull.app
DMG=dist/PixCull.dmg
ENTITLEMENTS=app/entitlements.plist

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  V7 PixCull release pipeline"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  identity: $PIXCULL_SIGN_IDENTITY"
echo "  notary:   $PIXCULL_NOTARY_PROFILE"
echo ""

# Step 1: build (uses ad-hoc sig, we'll replace it)
echo "=== Step 1/7: Build app (~5 min) ==="
./scripts/build_app.sh

# Step 2: replace ad-hoc with real Developer ID
echo ""
echo "=== Step 2/7: Re-sign with Developer ID + hardened runtime ==="
xattr -cr "$APP"
codesign --deep --force --options runtime --timestamp \
    --entitlements "$ENTITLEMENTS" \
    -s "$PIXCULL_SIGN_IDENTITY" "$APP"
echo "Verifying signature…"
codesign --verify --deep --strict --verbose=2 "$APP"
spctl -a -t exec -vv "$APP" || {
    echo "warn: spctl rejected — pre-notarization, this is expected."
}

# Step 3: build the DMG
echo ""
echo "=== Step 3/7: Build DMG ==="
./scripts/make_dmg.sh

# Step 4: sign the DMG
echo ""
echo "=== Step 4/7: Sign DMG ==="
codesign --force --timestamp -s "$PIXCULL_SIGN_IDENTITY" "$DMG"

# Step 5: notarize (this takes 5-15 min)
echo ""
echo "=== Step 5/7: Submit to Apple notarization (5-15 min) ==="
xcrun notarytool submit "$DMG" \
    --keychain-profile "$PIXCULL_NOTARY_PROFILE" \
    --wait

# Step 6: staple the ticket
echo ""
echo "=== Step 6/7: Staple notarization ticket ==="
xcrun stapler staple "$DMG"

# Step 7: final verification
echo ""
echo "=== Step 7/7: Verify ==="
xcrun stapler validate "$DMG"
spctl -a -t open --context context:primary-signature -vv "$DMG"

SZ=$(du -sh "$DMG" | awk '{print $1}')
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✓ Released $DMG  ($SZ)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Distribution:"
echo "  - This DMG runs on any Mac with no warnings."
echo "  - Upload to GitHub Releases / your website / wherever."
echo "  - Users open DMG → drag to Applications → run."
