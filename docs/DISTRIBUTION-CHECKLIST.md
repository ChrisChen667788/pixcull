# Real-distribution checklist (v0.11-P0-2)

> **Why this exists:** the three `scripts/release_*.sh` scripts have
> been production-ready for ~6 months, but the v0.7 / v0.8 / v0.9 charter
> windows came and went without ever running them — every gate is
> external (Apple Developer enrolment, SignPath OSS approval, GPG key
> ceremony) and the maintainer hasn't completed any of the three.
> This file is the one-shot "Monday morning, I'm doing it" checklist.

## How to use this doc

1. Work through the three platforms in any order.  Each is independent.
2. The `scripts/release_<platform>.sh` scripts gate-check their own
   prereqs and abort cleanly — no need to remember every flag.
3. The chain ends with **one** v0.11 release tag carrying 3 signed
   artefacts + a single merged appcast.xml.

Below: per-platform "what to do today", "what's already in repo",
and "where you can get stuck".

---

## macOS — Apple Developer + Sparkle + brew tap

### What to do today

1. **Apple Developer enrolment**
   - URL: https://developer.apple.com/programs/enroll/
   - Cost: USD 99/yr
   - Approval window: 24-72h (24h for individual, longer for org)
   - Required: a registered Apple ID with two-factor auth on, a debit
     card, and a phone number matching the Apple ID country
2. After approval:
   - Generate a Developer ID Application certificate at
     https://developer.apple.com/account/resources/certificates/list
     → "+" → "Developer ID Application" → download `.cer` → install
     into the login keychain by double-click
   - Generate an "App-specific password" at https://appleid.apple.com →
     Sign-In → App-Specific Passwords (Sparkle's `notarytool` needs
     this; it can't use your account password)
   - Save into `.env`:
     ```
     SIGNING_IDENTITY="Developer ID Application: Your Name (TEAMID)"
     APPLE_ID="you@example.com"
     APPLE_APP_PASSWORD="xxxx-xxxx-xxxx-xxxx"
     APPLE_TEAM_ID="ABCD1234EF"
     ```
3. Run the release script:
   ```bash
   bash scripts/release_macos.sh 0.11.0
   ```
   This:
   - codesigns `dist/PixCull.app`
   - builds `dist/PixCull-0.11.0.dmg`
   - submits to Apple notary (5-30 min wait)
   - staples the notarization ticket
   - runs Sparkle's `sign_update` for the appcast EdDSA signature
4. **Create the homebrew tap:**
   ```bash
   # One-time setup
   gh repo create ChrisChen667788/homebrew-pixcull --public
   git clone https://github.com/ChrisChen667788/homebrew-pixcull.git
   cd homebrew-pixcull
   cp ~/Downloads/zero-basics-python/2/pixcull-restored/dist/pixcull.rb .
   git add pixcull.rb && git commit -m "Initial v0.11.0 cask"
   git push
   ```
   `scripts/release_macos.sh` already produces `dist/pixcull.rb` with
   the SHA256 + URL plugged in.
5. **Verify** on a clean macOS machine:
   ```bash
   brew tap ChrisChen667788/pixcull
   brew install --cask pixcull
   open -a PixCull
   ```

### Stuck?

- `notarytool` says "invalid credentials" → app-specific password
  expired (they last 1 yr); regenerate
- `staple` errors with "no notarization found" → submission still
  in progress; wait + retry (5-30 min)
- `brew install --cask pixcull` errors with "SHA256 mismatch" → the
  cask was committed before the upload finished re-uploading; pull
  + retry

---

## Windows — SignPath OSS approval + WiX MSI

### What to do today

1. **Apply for SignPath OSS sponsorship**
   - URL: https://about.signpath.io/product/open-source
   - Cost: free for OSS projects with a public GitHub repo
   - Approval window: 1-2 weeks
   - Required: GitHub repo URL, project description, MIT/Apache
     license badge visible in README
2. After approval, SignPath issues:
   - A project token (save into `.env`: `SIGNPATH_API_TOKEN=...`)
   - A signing policy ID (save: `SIGNPATH_POLICY_ID=...`)
3. Run the release script on a Windows host (or via WSL):
   ```bash
   bash scripts/release_windows.sh 0.11.0
   ```
   This:
   - PyInstaller-builds `dist/PixCull/PixCull.exe`
   - WiX-builds `dist/PixCull-0.11.0.msi`
   - signs both via SignPath CLI (chain-signs with our OSS sponsorship cert)
   - uploads the signed MSI to GitHub Release
4. **Verify** on a clean Windows 11 host:
   - download from GitHub Release
   - double-click .msi — SmartScreen should NOT show "Publisher unknown"
   - install + run

### Stuck?

- SignPath rejects: usually wants a public LICENSE file in the repo
  root + a README "Contributors" section. Both present.
- `signtool` errors "Certificate not found": the SignPath cert lives
  in their cloud, not your local store. Use the SignPath GitHub Action
  for CI signing instead of running locally.
- SmartScreen still flags: takes a couple of weeks of "reputation
  building" via downloads. There's no shortcut — first 100 users see
  the yellow.

---

## Linux — GPG key + AppImage + AppImageUpdate

### What to do today

1. **Generate a release-signing GPG key** (offline ceremony):
   ```bash
   gpg --full-generate-key
   # → ed25519, never expires, "PixCull Release <release@pixcull.dev>"
   gpg --list-secret-keys --keyid-format LONG
   # → note the long key ID, e.g. F1234567890ABCDE
   gpg --armor --export F1234567890ABCDE > release.pub
   # Upload release.pub to keys.openpgp.org + GitHub
   ```
   Save the key ID into `.env`:
   ```
   GPG_RELEASE_KEY_ID=F1234567890ABCDE
   ```
2. Run the release script:
   ```bash
   bash scripts/release_linux_appimage.sh 0.11.0
   ```
   This:
   - PyInstaller-builds the AppImage with `appimagetool`
   - GPG-signs it with `--detach-sign`
   - generates the AppImage updateinformation embedded in the binary
3. Upload to GitHub Release alongside the .dmg and .msi.
4. **Verify** on a clean Ubuntu 22.04 host:
   ```bash
   chmod +x PixCull-0.11.0-x86_64.AppImage
   ./PixCull-0.11.0-x86_64.AppImage
   # Then trigger an update via:
   ./PixCull-0.11.0-x86_64.AppImage --self-update
   ```
   AppImageUpdate should pull the next-version AppImage (the
   updateinformation we embedded points at the GitHub Release).

### Stuck?

- `appimagetool: command not found` → fetch from
  https://github.com/AppImage/AppImageKit/releases (~1.5 MB binary)
- GPG signature fails on the AppImage → key probably has a passphrase
  and `gpg-agent` isn't running; `gpgconf --launch gpg-agent` first
- AppImageUpdate finds nothing → check the embedded updateinformation
  with `./PixCull*.AppImage --appimage-updateinformation`

---

## Final step — single merged appcast.xml + GitHub Release

After all three release_*.sh runs have produced their artefacts:

```bash
# Aggregates the three platform manifests into a single appcast.xml
# that Sparkle (macOS), AppImageUpdate, and any future Windows
# auto-updater can all read.
python scripts/build_appcast.py dist/releases.json --out dist/appcast.xml

# Bundle everything into the release tag
gh release create v0.11.0 \
    dist/PixCull-0.11.0.dmg \
    dist/PixCull-0.11.0.msi \
    dist/PixCull-0.11.0-x86_64.AppImage \
    dist/PixCull-0.11.0-x86_64.AppImage.sig \
    dist/appcast.xml \
    --notes-file docs/release-notes-v0.11.0.md
```

`docs/release-notes-v0.11.0.md` should be generated from the v0.11 charter
acceptance checklist + the actual list of commits since v0.10.0.

## README update after release

After v0.11.0 ships, replace the "soon" placeholders in README's
install section with the three real commands:

```
brew install --cask pixcull                          # macOS
winget install ChrisChen667788.PixCull               # Windows (after WinGet PR lands)
./PixCull-0.11.0-x86_64.AppImage                     # Linux
```

Also add the GPG fingerprint:
```
Release GPG: F123 4567 8901 ABCD EFG1  2345 6789 ABCD EFG1 2345
```

## Predecessor docs

- `docs/macos-signing.md` — Apple-side notary + Sparkle EdDSA detail
- `scripts/release_macos.sh`, `release_windows.sh`,
  `release_linux_appimage.sh` — the actual pipelines (already
  production-ready)
- `docs/ROADMAP-v0.11-charter.md` § P0-2 — this slice's spec
