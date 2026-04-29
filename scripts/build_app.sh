#!/usr/bin/env bash
# Build PixCull.app via PyInstaller.
#
# Output:
#   dist/PixCull.app           drag to /Applications
#
# Optional steps after this:
#   - Ad-hoc sign:    codesign --deep --force -s - dist/PixCull.app
#   - Notarize:       see app/NOTARIZATION.md (requires Apple Dev account)
#   - Make DMG:       ./scripts/make_dmg.sh
set -euo pipefail

cd "$(dirname "$0")/.."

VENV=${VENV:-.venv}
SPEC=app/pixcull.spec

if [ ! -x "$VENV/bin/pyinstaller" ]; then
    echo "ERROR: pyinstaller not found in $VENV. Run:"
    echo "  $VENV/bin/pip install pyinstaller"
    exit 1
fi

echo "=== Cleaning previous build artefacts ==="
rm -rf build dist

echo "=== Running PyInstaller (~3-8 min on M-series) ==="
"$VENV/bin/pyinstaller" "$SPEC" --noconfirm --clean

if [ ! -d dist/PixCull.app ]; then
    echo "ERROR: build did not produce dist/PixCull.app — check log above."
    exit 1
fi

# Apply ad-hoc signature so Gatekeeper at least lets the user
# right-click → Open. The entitlements file disables library
# validation — required for ad-hoc-signed Python bundles to load
# their own libpython3.12.dylib without team-ID matching errors.
# For full distribution, replace `-s -` with the developer identity
# hash and add notarization (see app/NOTARIZATION.md).
echo "=== Stripping cached signatures + xattrs ==="
xattr -cr dist/PixCull.app
echo ""
echo "=== Ad-hoc code signing with entitlements ==="
codesign --deep --force -s - --entitlements app/entitlements.plist dist/PixCull.app || {
    echo "warn: codesign failed (some bundled .so may have invalid headers — usually still launches OK)"
}

SZ=$(du -sh dist/PixCull.app | awk '{print $1}')
echo ""
echo "✓ Built dist/PixCull.app  (size: $SZ)"
echo ""
echo "Test:    open dist/PixCull.app"
echo "Move to: /Applications"
echo ""
echo "Distribution checklist:"
echo "  [ ] sign with Developer ID  (codesign -s 'Developer ID Application: ...')"
echo "  [ ] notarize  (xcrun notarytool submit --wait)"
echo "  [ ] staple    (xcrun stapler staple)"
echo "  [ ] DMG       (./scripts/make_dmg.sh)"
