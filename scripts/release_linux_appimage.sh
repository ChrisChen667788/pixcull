#!/usr/bin/env bash
# v0.8-P1-2 — Linux AppImage build + GPG detached-signature pipeline.
#
# Usage:  bash scripts/release_linux_appimage.sh <version>
# Example: bash scripts/release_linux_appimage.sh 0.8.0
#
# AppImage is the canonical "double-clickable" Linux distribution
# format — one file containing the .app's whole tree + a tiny
# loader.  We use linuxdeploy + python-conf-plugin to bundle our
# PyInstaller output, then zsync for delta-update support so
# downstream AppImageUpdate clients can patch in place.
#
# Pipeline:
#   1. PyInstaller → dist/PixCull/PixCull (Linux ELF)
#   2. AppDir layout under build/PixCull.AppDir/
#   3. linuxdeploy → dist/PixCull-<v>-x86_64.AppImage
#   4. zsyncmake  → dist/PixCull-<v>-x86_64.AppImage.zsync (delta feed)
#   5. gpg --detach-sign → .AppImage.sig
#   6. Sparkle-friendly EdDSA signature (so the same appcast.xml
#      serves macOS + Windows + Linux clients)
#
# Reads creds from .env.  See docs/LINUX-SIGNING-SETUP.md for setup.

set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
    echo "[release-linux] usage: bash scripts/release_linux_appimage.sh <version>" >&2
    exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --- prereqs --------------------------------------------------------------
if [[ ! -f .env ]]; then
    echo "[release-linux] missing .env — copy .env.example to .env and fill in" >&2
    exit 2
fi
# shellcheck disable=SC1091
set -a; source .env; set +a

: "${GPG_SIGNING_KEY:?GPG_SIGNING_KEY missing — see docs/LINUX-SIGNING-SETUP.md §1}"

for tool in linuxdeploy zsyncmake gpg; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "[release-linux] $tool not on PATH — see docs/LINUX-SIGNING-SETUP.md §2" >&2
        exit 2
    fi
done

PYINST_BIN=".venv/bin/pyinstaller"
[[ -x "$PYINST_BIN" ]] || {
    echo "[release-linux] $PYINST_BIN missing — pip install pyinstaller" >&2
    exit 2
}

APPDIR="build/PixCull.AppDir"
APPIMAGE_OUT="dist/PixCull-${VERSION}-x86_64.AppImage"

# --- 1. PyInstaller -------------------------------------------------------
echo "[release-linux] [1/5] PyInstaller..."
rm -rf "dist/PixCull" build/
"$PYINST_BIN" app/pixcull.spec --noconfirm --clean
[[ -f "dist/PixCull/PixCull" ]] || {
    echo "[release-linux] PyInstaller produced no dist/PixCull/PixCull" >&2
    exit 1
}
echo "[release-linux] [1/5] PyInstaller OK"

# --- 2. AppDir layout -----------------------------------------------------
echo "[release-linux] [2/5] AppDir staging..."
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Copy the PyInstaller tree
cp -R dist/PixCull/. "$APPDIR/usr/bin/"

# .desktop file — what shows up in app launchers
cat > "$APPDIR/pixcull.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PixCull
GenericName=Photo Culling
Comment=Local-first AI photo culling for professional photographers
Exec=PixCull %F
Icon=pixcull
Categories=Graphics;Photography;
StartupNotify=true
MimeType=image/jpeg;image/png;image/x-canon-cr2;image/x-nikon-nef;image/x-sony-arw;
EOF
cp "$APPDIR/pixcull.desktop" "$APPDIR/usr/share/applications/"

# Icon — 256x256 PNG.  The brand kit emits this at
# docs/brand/pixcull-icon-256.png; fall back to a generic one if
# the brand file isn't checked in yet.
ICON_SRC="docs/brand/pixcull-icon-256.png"
[[ -f "$ICON_SRC" ]] || ICON_SRC="docs/brand/pixcull-mark.png"
[[ -f "$ICON_SRC" ]] || {
    echo "[release-linux] no PixCull icon found — emit one to docs/brand/" >&2
    exit 2
}
cp "$ICON_SRC" "$APPDIR/pixcull.png"
cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/256x256/apps/pixcull.png"

# AppRun stub — what AppImage executes on launch
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="$HERE/usr/bin:$PATH"
export LD_LIBRARY_PATH="$HERE/usr/bin:${LD_LIBRARY_PATH:-}"
exec "$HERE/usr/bin/PixCull" "$@"
EOF
chmod +x "$APPDIR/AppRun"
echo "[release-linux] [2/5] AppDir OK"

# --- 3. linuxdeploy -> .AppImage -----------------------------------------
echo "[release-linux] [3/5] linuxdeploy..."
rm -f "$APPIMAGE_OUT"
# UPDATE_INFORMATION lets AppImageUpdate find the delta zsync feed
# on each launch.  The placeholder URL points to the GH releases
# CDN; build_appcast.py emits the matching XML so the same appcast
# serves macOS DMG + Windows MSI + Linux AppImage.
export UPDATE_INFORMATION="gh-releases-zsync|ChrisChen667788|pixcull|latest|PixCull-*-x86_64.AppImage.zsync"

linuxdeploy --appdir "$APPDIR" \
            --desktop-file "$APPDIR/pixcull.desktop" \
            --icon-file "$APPDIR/pixcull.png" \
            --output appimage

# linuxdeploy emits the AppImage at the repo root with a default
# name — relocate to our versioned path.
DEFAULT_NAME="$(ls -1 PixCull*.AppImage 2>/dev/null | head -1 || true)"
if [[ -n "$DEFAULT_NAME" ]]; then
    mv "$DEFAULT_NAME" "$APPIMAGE_OUT"
fi
[[ -f "$APPIMAGE_OUT" ]] || {
    echo "[release-linux] linuxdeploy did not emit an AppImage" >&2
    exit 1
}
chmod +x "$APPIMAGE_OUT"
echo "[release-linux] [3/5] linuxdeploy OK ($(du -h "$APPIMAGE_OUT" | awk '{print $1}'))"

# --- 4. zsyncmake (delta-update feed) -------------------------------------
echo "[release-linux] [4/5] zsyncmake..."
ZSYNC_PATH="${APPIMAGE_OUT}.zsync"
rm -f "$ZSYNC_PATH"
zsyncmake -u "PixCull-${VERSION}-x86_64.AppImage" -o "$ZSYNC_PATH" "$APPIMAGE_OUT"
echo "[release-linux] [4/5] zsyncmake OK"

# --- 5. GPG detached signature --------------------------------------------
echo "[release-linux] [5/5] GPG sign..."
SIG_PATH="${APPIMAGE_OUT}.sig"
rm -f "$SIG_PATH"
gpg --batch --yes --detach-sign \
    --local-user "$GPG_SIGNING_KEY" \
    --output "$SIG_PATH" \
    "$APPIMAGE_OUT"
gpg --verify "$SIG_PATH" "$APPIMAGE_OUT" \
    || { echo "[release-linux] GPG verification failed" >&2; exit 1; }
echo "[release-linux] [5/5] GPG sign OK"

# --- Optional: Sparkle EdDSA signature for cross-platform appcast --------
SPARKLE_LINUX_SIG=""
if [[ -x "${HOME}/Sparkle/bin/sign_update" ]]; then
    echo "[release-linux] (bonus) Sparkle EdDSA signature..."
    SPARKLE_LINUX_SIG="$("${HOME}/Sparkle/bin/sign_update" "$APPIMAGE_OUT" \
                       --account "${SPARKLE_ED_ACCOUNT:-default}")"
fi

SIZE_BYTES=$(stat -c %s "$APPIMAGE_OUT" 2>/dev/null || stat -f %z "$APPIMAGE_OUT")
GPG_KEYID="$(gpg --list-keys --with-colons "$GPG_SIGNING_KEY" 2>/dev/null \
             | awk -F: '/^pub/{print $5; exit}')"

cat <<EOF

═════════════════════════════════════════════════════════════════
  $APPIMAGE_OUT ready · ${SIZE_BYTES} bytes
═════════════════════════════════════════════════════════════════

GPG key:        $GPG_KEYID
Zsync feed:     $ZSYNC_PATH
Detached sig:   $SIG_PATH
$([ -n "$SPARKLE_LINUX_SIG" ] && echo "Sparkle EdDSA: $SPARKLE_LINUX_SIG")

Paste into dist/releases.json under "linux" key for v${VERSION}:

  "size_bytes":  ${SIZE_BYTES},
  "platform":    "linux-x86_64",
  "gpg_keyid":   "${GPG_KEYID}",
  $([ -n "$SPARKLE_LINUX_SIG" ] && echo "${SPARKLE_LINUX_SIG}")

Then:

  python scripts/build_appcast.py dist/releases.json --out dist/appcast.xml
  gh release upload v${VERSION} ${APPIMAGE_OUT} ${ZSYNC_PATH} ${SIG_PATH}

End-users verify:
  gpg --verify PixCull-${VERSION}-x86_64.AppImage.sig PixCull-${VERSION}-x86_64.AppImage

EOF
