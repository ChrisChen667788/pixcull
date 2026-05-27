# v0.8-P0-3 — Homebrew cask for PixCull.app.
#
# This file is the source-of-truth for the brew tap at
# https://github.com/ChrisChen667788/homebrew-pixcull (to be created
# once the first signed + notarized DMG ships).  When v0.8 cuts:
#
#   1. Build + sign + notarize: `bash scripts/release_macos.sh 0.8.0`
#   2. Upload dist/PixCull-0.8.0.dmg to a GitHub release
#   3. Copy this file into the homebrew-pixcull repo as Casks/pixcull.rb
#   4. Update `version` + `sha256` + `url` below to match the release
#   5. `brew tap chrischen667788/pixcull && brew install --cask pixcull`
#
# Why a cask, not a formula:
#   PixCull ships as a notarized .app bundle (not a CLI binary),
#   so it lives in the cask namespace.  The .app already contains
#   its own bundled Python + ONNX runtime — no Homebrew Python
#   dependency, no `depends_on python@3.12`.  Drag-into-Applications
#   is the canonical install path; Sparkle handles updates.
#
# Why livecheck pulls from the appcast (not the GH releases page):
#   scripts/build_appcast.py emits dist/appcast.xml as the
#   authoritative version-feed; brew livecheck speaks the same
#   `<enclosure sparkle:shortVersionString="...">` schema, so the
#   tap auto-tracks new versions without us touching the cask on
#   every point release.

cask "pixcull" do
  # Bumped on every release — see scripts/release_macos.sh §5
  # which emits the SIG_OUTPUT + size_bytes block.
  version "0.8.0"
  sha256 "REPLACE_WITH_SHA256_AT_RELEASE_TIME"

  url "https://github.com/ChrisChen667788/pixcull/releases/download/v#{version}/PixCull-#{version}.dmg",
      verified: "github.com/ChrisChen667788/pixcull/"
  name "PixCull"
  desc "Local-first AI photo culling for professional photographers"
  homepage "https://github.com/ChrisChen667788/pixcull"

  # Sparkle appcast — same XML emitted by scripts/build_appcast.py
  # so brew tracks new releases automatically via `brew livecheck`.
  livecheck do
    url "https://github.com/ChrisChen667788/pixcull/releases/latest/download/appcast.xml"
    strategy :sparkle
  end

  # macOS minimum — onnxruntime + Apple Silicon GPU acceleration
  # require Big Sur (11.0) at minimum.  PyInstaller builds for the
  # CURRENT arch by default; we ship universal2 fat bundles via the
  # py2app spec so the same DMG installs on Intel + Apple Silicon.
  depends_on macos: ">= :big_sur"

  app "PixCull.app"

  # Sparkle owns the auto-update channel — telling brew about it
  # via auto_updates true means `brew upgrade pixcull` is a no-op
  # when the app is already-updated by Sparkle (no double-update
  # racing).
  auto_updates true

  # Uninstall hooks — clean up the .app + the user's run cache.
  # User data (~/Library/Application Support/PixCull/runs/) is
  # PRESERVED on uninstall so a `brew install --cask pixcull` after
  # uninstall doesn't lose the user's annotation history.  If
  # they want a full wipe, the cleanup stanza below handles it on
  # `brew uninstall --zap`.
  uninstall quit:   "com.pixcull.app",
            delete: "/Applications/PixCull.app"

  zap trash: [
    "~/Library/Application Support/PixCull",
    "~/Library/Preferences/com.pixcull.app.plist",
    "~/Library/Caches/com.pixcull.app",
    "~/Library/Logs/PixCull",
  ]

  # Caveats: print enough to set expectations on first install.
  # Homebrew renders this AFTER the install succeeds.
  caveats <<~EOS
    PixCull runs everything locally — no photos leave your machine.

    First launch will ask for Full Disk Access (only if you point
    it at a library on an external drive).  System Preferences →
    Privacy & Security → Full Disk Access → toggle PixCull.

    To enable AI advice (rubric phrases via DeepSeek), set
    DEEPSEEK_API_KEY in your shell rc, OR launch PixCull and paste
    your key into Settings → AI.  Without a key, the rubric scores
    still work — only the LLM-generated explanations are skipped.

    Updates: PixCull auto-checks for new versions on launch (Sparkle).
    To disable: launch PixCull → Settings → Updates → uncheck.
  EOS
end
