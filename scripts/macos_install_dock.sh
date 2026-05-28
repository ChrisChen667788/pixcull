#!/usr/bin/env bash
# v0.11-P2-1 — One-click "Add PixCull to Dock + Login Items".
#
# Photographers open PixCull 3-5 times a day.  After the signed
# .dmg from `scripts/release_macos.sh` lands the .app in
# /Applications, this script promotes it to a 1-click reach:
#
#   1. Adds /Applications/PixCull.app to the Dock (persistent-apps)
#   2. Registers PixCull.app as a Login Item (so it boots with macOS
#      — convenient when the photographer's workflow is "Lightroom
#      → PixCull → Capture One" all morning)
#   3. Skips both steps gracefully if they're already present
#
# Usage:
#   bash scripts/macos_install_dock.sh                  # Dock + login
#   bash scripts/macos_install_dock.sh --dock-only      # skip login
#   bash scripts/macos_install_dock.sh --uninstall      # remove both
#
# Distribution
# ============
# The bundled .pkg installer can run this in its postinstall script;
# for a manual user, double-clicking it (after `chmod +x`) works too.
# We also ship a sibling .workflow bundle (Quick Action) — see
# scripts/PixCull-AddToDock.workflow/ — that wraps this script for
# the "right-click → Quick Actions → Add PixCull to Dock" path.

set -euo pipefail

APP_PATH="/Applications/PixCull.app"
DOCK_ONLY=0
UNINSTALL=0

for arg in "$@"; do
  case "$arg" in
    --dock-only) DOCK_ONLY=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --help|-h)
      sed -n '2,25p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown flag: $arg" >&2
      exit 2
      ;;
  esac
done

if [[ ! -d "$APP_PATH" ]]; then
  echo "[macos-dock] PixCull.app not found at $APP_PATH"
  echo "[macos-dock] Install it first (drag the .app from the .dmg"
  echo "             into /Applications, or run \`brew install --cask pixcull\`)."
  exit 1
fi

# ---------------------------------------------------------------------------
# Dock entry — uses dockutil if available (much more reliable), else
# falls back to `defaults write` + killall Dock (works on every macOS).
# ---------------------------------------------------------------------------

_dock_has_pixcull() {
  defaults read com.apple.dock persistent-apps 2>/dev/null \
    | grep -q "PixCull.app" || return 1
}

_add_to_dock() {
  if _dock_has_pixcull; then
    echo "[macos-dock] already in Dock — skipping"
    return 0
  fi
  if command -v dockutil >/dev/null 2>&1; then
    dockutil --add "$APP_PATH" --no-restart
  else
    # Append a tile dict; killall Dock picks it up
    /usr/bin/defaults write com.apple.dock persistent-apps -array-add \
      "<dict>
        <key>tile-data</key>
        <dict>
          <key>file-data</key>
          <dict>
            <key>_CFURLString</key>
            <string>${APP_PATH}</string>
            <key>_CFURLStringType</key>
            <integer>0</integer>
          </dict>
        </dict>
      </dict>"
  fi
  /usr/bin/killall Dock || true
  echo "[macos-dock] ✓ added to Dock"
}

_remove_from_dock() {
  if ! _dock_has_pixcull; then
    echo "[macos-dock] not in Dock — skipping"
    return 0
  fi
  if command -v dockutil >/dev/null 2>&1; then
    dockutil --remove "PixCull" --no-restart
    /usr/bin/killall Dock || true
    return 0
  fi
  echo "[macos-dock] dockutil not installed — open System Settings → Dock"
  echo "             and remove PixCull manually (or:"
  echo "             \`brew install dockutil; dockutil --remove PixCull\`)"
}

# ---------------------------------------------------------------------------
# Login Items — osascript talks to System Events.
# ---------------------------------------------------------------------------

_add_login_item() {
  /usr/bin/osascript <<EOF
tell application "System Events"
  if not (exists login item "PixCull") then
    make new login item at end with properties \
      {path:"${APP_PATH}", hidden:false, name:"PixCull"}
  end if
end tell
EOF
  echo "[macos-dock] ✓ added to Login Items"
}

_remove_login_item() {
  /usr/bin/osascript <<EOF
tell application "System Events"
  if (exists login item "PixCull") then
    delete login item "PixCull"
  end if
end tell
EOF
  echo "[macos-dock] ✓ removed from Login Items"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if [[ $UNINSTALL -eq 1 ]]; then
  _remove_from_dock
  _remove_login_item
  echo "[macos-dock] done — PixCull removed from Dock + Login Items"
  exit 0
fi

_add_to_dock
if [[ $DOCK_ONLY -eq 0 ]]; then
  _add_login_item
fi
echo "[macos-dock] done — PixCull is now 1-click reachable from the Dock."
