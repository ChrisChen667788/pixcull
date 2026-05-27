#!/usr/bin/env bash
# v0.8-P1-2 — Windows MSI build + Authenticode signing pipeline.
#
# Usage:  bash scripts/release_windows.sh <version>
# Example: bash scripts/release_windows.sh 0.8.0
#
# Runs on Windows via WSL / Git Bash, OR on macOS / Linux when
# cross-compiling under MinGW.  PyInstaller already produces a
# Windows .exe via the same app/pixcull.spec; this script:
#
#   1. PyInstaller → dist/PixCull/PixCull.exe (+ accompanying dist tree)
#   2. WiX Toolset (`heat` + `candle` + `light`) → dist/PixCull-<v>.msi
#   3. signtool / SignPath CLI → Authenticode signature on both the
#      .exe and the .msi (chain-signed so the user's Windows
#      Defender SmartScreen doesn't flag "publisher unknown")
#   4. Sparkle.NET sign_update → EdDSA signature for the appcast
#
# Reads credentials from .env at the repo root.  See
# docs/WINDOWS-SIGNING-SETUP.md §1 for the .env schema (which
# choice of signing path:  local cert vs SignPath cloud).
#
# This script is idempotent.  Re-running it on the same version
# overwrites the previous MSI.

set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
    echo "[release-win] usage: bash scripts/release_windows.sh <version>" >&2
    echo "[release-win] example: bash scripts/release_windows.sh 0.8.0" >&2
    exit 2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --- prereqs ---------------------------------------------------------------

if [[ ! -f .env ]]; then
    echo "[release-win] missing .env — copy .env.example to .env and fill in" >&2
    echo "[release-win] see docs/WINDOWS-SIGNING-SETUP.md" >&2
    exit 2
fi
# shellcheck disable=SC1091
set -a; source .env; set +a

# Two signing modes are supported — pick whichever you have.
#   1. SIGNPATH_API_TOKEN     →  cloud signing via SignPath (free for OSS)
#   2. WIN_SIGNING_CERT_PATH  →  local signtool with a .pfx
# Setting both is fine — SignPath wins (it's the recommended path
# for distributing publicly).
if [[ -z "${SIGNPATH_API_TOKEN:-}" && -z "${WIN_SIGNING_CERT_PATH:-}" ]]; then
    echo "[release-win] need EITHER SIGNPATH_API_TOKEN or WIN_SIGNING_CERT_PATH" >&2
    echo "[release-win] see docs/WINDOWS-SIGNING-SETUP.md §2 (SignPath, recommended)" >&2
    echo "[release-win]                                §3 (local .pfx, fallback)" >&2
    exit 2
fi

EXE_DIR="dist/PixCull"
EXE_PATH="$EXE_DIR/PixCull.exe"
MSI_PATH="dist/PixCull-${VERSION}.msi"
WIX_DIR="packaging/wix"

if [[ ! -d "$WIX_DIR" ]]; then
    echo "[release-win] missing $WIX_DIR/ — see docs/WINDOWS-SIGNING-SETUP.md §4" >&2
    exit 2
fi

# --- 1. PyInstaller --------------------------------------------------------
echo "[release-win] [1/4] PyInstaller..."
if [[ ! -x ".venv/bin/pyinstaller" && ! -x ".venv/Scripts/pyinstaller.exe" ]]; then
    echo "[release-win] pyinstaller not found in .venv — pip install pyinstaller" >&2
    exit 2
fi
PYINST_BIN=".venv/bin/pyinstaller"
[[ -x ".venv/Scripts/pyinstaller.exe" ]] && PYINST_BIN=".venv/Scripts/pyinstaller.exe"

rm -rf "$EXE_DIR" "build/"
"$PYINST_BIN" app/pixcull.spec --noconfirm --clean

if [[ ! -f "$EXE_PATH" ]]; then
    echo "[release-win] PyInstaller did not produce $EXE_PATH" >&2
    exit 1
fi
echo "[release-win] [1/4] PyInstaller OK ($(du -h "$EXE_DIR" | tail -1 | awk '{print $1}'))"

# --- 2. WiX MSI build -----------------------------------------------------
echo "[release-win] [2/4] WiX MSI build..."
if ! command -v candle >/dev/null 2>&1 || ! command -v light >/dev/null 2>&1; then
    echo "[release-win] WiX Toolset not on PATH (candle/light missing)" >&2
    echo "[release-win] install: choco install wixtoolset OR dotnet tool install --global wix" >&2
    exit 2
fi

# heat = harvest the file tree under dist/PixCull/ into a fragment
heat dir "$EXE_DIR" -srd -dr INSTALLFOLDER -cg PixCullComponents \
     -ag -sfrag -suid -var var.SourceDir -out "$WIX_DIR/_files.wxs"
candle -arch x64 -dSourceDir="$EXE_DIR" -dVersion="$VERSION" \
       -out "build/wix/" "$WIX_DIR/_files.wxs" "$WIX_DIR/pixcull.wxs"
light -ext WixUIExtension -cultures:en-us \
      -out "$MSI_PATH" \
      "build/wix/_files.wixobj" "build/wix/pixcull.wixobj"
echo "[release-win] [2/4] MSI build OK ($(du -h "$MSI_PATH" | awk '{print $1}'))"

# --- 3. Authenticode signing ----------------------------------------------
echo "[release-win] [3/4] Authenticode signing..."

if [[ -n "${SIGNPATH_API_TOKEN:-}" ]]; then
    # SignPath cloud path — recommended for OSS releases.
    # Uses signpath-cli (https://about.signpath.io/documentation/build-system-integration/cli)
    # which uploads the artifact, signs it with the org's HSM, and
    # downloads the signed version in place.
    if ! command -v signpath >/dev/null 2>&1; then
        echo "[release-win] signpath CLI missing — pipx install signpath-cli" >&2
        exit 2
    fi
    : "${SIGNPATH_ORG_ID:?SIGNPATH_ORG_ID missing — see docs/WINDOWS-SIGNING-SETUP.md §2}"
    : "${SIGNPATH_PROJECT_SLUG:?SIGNPATH_PROJECT_SLUG missing}"
    : "${SIGNPATH_POLICY_SLUG:?SIGNPATH_POLICY_SLUG missing}"
    # Sign the EXE first, THEN the MSI — order matters because the
    # MSI bundles the EXE; signing the EXE post-MSI would invalidate
    # the MSI signature.
    for target in "$EXE_PATH" "$MSI_PATH"; do
        echo "[release-win]   signing $target via SignPath..."
        signpath sign \
            --organization-id "$SIGNPATH_ORG_ID" \
            --project-slug "$SIGNPATH_PROJECT_SLUG" \
            --signing-policy-slug "$SIGNPATH_POLICY_SLUG" \
            --input-artifact-path "$target" \
            --output-artifact-path "$target.signed"
        mv "$target.signed" "$target"
    done
else
    # Local .pfx path — fallback when not eligible for SignPath
    # (e.g. closed-source / internal builds).  Requires signtool.exe
    # from the Windows SDK on PATH.
    if ! command -v signtool >/dev/null 2>&1 && ! command -v signtool.exe >/dev/null 2>&1; then
        echo "[release-win] signtool missing — install Windows SDK" >&2
        exit 2
    fi
    : "${WIN_SIGNING_CERT_PATH:?WIN_SIGNING_CERT_PATH missing}"
    : "${WIN_SIGNING_CERT_PASSWORD:?WIN_SIGNING_CERT_PASSWORD missing}"
    SIGNTOOL=signtool
    command -v signtool.exe >/dev/null && SIGNTOOL=signtool.exe
    # Use RFC 3161 timestamping so the signature stays valid after
    # the cert expires.  digicert / sectigo timestamp servers are
    # both free + lenient on rate limits.
    TS_URL="${WIN_TIMESTAMP_URL:-http://timestamp.digicert.com}"
    for target in "$EXE_PATH" "$MSI_PATH"; do
        echo "[release-win]   signing $target via local .pfx..."
        "$SIGNTOOL" sign \
            /f "$WIN_SIGNING_CERT_PATH" \
            /p "$WIN_SIGNING_CERT_PASSWORD" \
            /fd sha256 \
            /tr "$TS_URL" \
            /td sha256 \
            "$target"
        "$SIGNTOOL" verify /pa "$target"
    done
fi
echo "[release-win] [3/4] Authenticode signing OK"

# --- 4. Sparkle.NET sign_update -------------------------------------------
echo "[release-win] [4/4] Sparkle.NET appcast signature..."
SPARKLE_NET_SIGN="${SPARKLE_NET_SIGN_BIN:-${HOME}/SparkleNET/NetSparkleGenerator}"
if [[ ! -x "$SPARKLE_NET_SIGN" ]]; then
    echo "[release-win] $SPARKLE_NET_SIGN missing — see docs/WINDOWS-SIGNING-SETUP.md §5" >&2
    exit 2
fi
: "${SPARKLE_NET_PRIVATE_KEY:?SPARKLE_NET_PRIVATE_KEY missing}"

SIG_OUTPUT="$("$SPARKLE_NET_SIGN" sign --file "$MSI_PATH" \
              --private-key "$SPARKLE_NET_PRIVATE_KEY")"
SIZE_BYTES=$(stat -c %s "$MSI_PATH" 2>/dev/null || stat -f %z "$MSI_PATH")
echo "[release-win] [4/4] Sparkle.NET signature OK"

cat <<EOF

═════════════════════════════════════════════════════════════════
  $MSI_PATH ready · ${SIZE_BYTES} bytes
═════════════════════════════════════════════════════════════════

Paste into dist/releases.json under "windows" key for v${VERSION}:

  "size_bytes":  ${SIZE_BYTES},
  "platform":    "windows-x64",
  ${SIG_OUTPUT}

Then:

  python scripts/build_appcast.py dist/releases.json --out dist/appcast.xml
  gh release upload v${VERSION} ${MSI_PATH} dist/appcast.xml

EOF
