# Apple Developer Setup — what you need to do (real-world actions)

This is the checklist that **only you** can do. PixCull's release
infrastructure (build_appcast.py, macos-signing.md cookbook,
`release_macos.sh` pipeline script) is all in place — once you
finish these steps, the signed-DMG + Sparkle pipeline will run
end-to-end.

Estimated time: **2–4 hours active work + 1–3 day waits on
Apple's verification queues.** Cost: **$99 USD/year**.

## ✅ Action checklist

### 1. Apple Developer Program enrollment (~1 hour active + 1-3 day wait)

- [ ] Go to <https://developer.apple.com/programs/>
- [ ] Click "Enroll" (top right) — you need an Apple ID first if you don't have one
- [ ] Choose **Individual** (NOT Organization unless you're filing as a business)
- [ ] Pay **$99 USD/year**
- [ ] Wait for the email "Your enrollment has been completed" (usually 1-3 days for identity verification)

> **Note:** China-based Apple IDs can enroll. The billing currency is automatically converted from your local payment method. Avoid the Mac App Store option — we want Developer ID for direct distribution.

### 2. Create Developer ID Application certificate (~15 min)

Once enrolled:

- [ ] Open Xcode (install from App Store if you don't have it — required for certificate signing)
- [ ] Xcode → Settings → Accounts → click "+" → sign in with your Apple ID
- [ ] Select your team → "Manage Certificates" → "+" → **"Developer ID Application"**
- [ ] Xcode generates the cert and installs it in your Keychain
- [ ] Verify:
  ```sh
  security find-identity -v -p codesigning | grep "Developer ID Application"
  ```
  Should print one or more lines like:
  ```
  1) 1234ABCD5678... "Developer ID Application: Your Name (TEAMID)"
  ```

> **Copy the TEAMID (10 chars in parentheses) — you'll need it for env vars.**

### 3. Create an app-specific password for notarytool (~5 min)

`notarytool` needs an app-specific password (NOT your main Apple ID password) for non-interactive use.

- [ ] Sign in at <https://appleid.apple.com>
- [ ] Sign-In and Security → "App-Specific Passwords" → "+"
- [ ] Label: `pixcull-notarytool`
- [ ] Copy the password (16 chars, format `xxxx-xxxx-xxxx-xxxx`)
- [ ] Store it in a `.env` file (gitignored — see `.env.example`)

### 4. Save the credential profile (~5 min)

```sh
xcrun notarytool store-credentials pixcull-notary \
    --apple-id "your-apple-id@example.com" \
    --team-id "TEAMID_FROM_STEP_2" \
    --password "xxxx-xxxx-xxxx-xxxx"   # from step 3
```

The credential lives in your login Keychain after this. `release_macos.sh` references it as `--keychain-profile pixcull-notary`.

### 5. Generate the Sparkle EdDSA key pair (~5 min)

This is the **update signing key** — distinct from the macOS code-signing identity. Protects against MITM attacks on the CDN.

- [ ] Clone Sparkle:
  ```sh
  git clone https://github.com/sparkle-project/Sparkle.git ~/Sparkle
  cd ~/Sparkle && make bin
  ```
- [ ] Generate the key pair (stored in your Keychain):
  ```sh
  ~/Sparkle/bin/generate_keys
  ```
- [ ] Print the public key for the Info.plist:
  ```sh
  ~/Sparkle/bin/generate_keys --account pixcull -p
  ```
- [ ] Save the public key to a place you control (you'll embed it in the `.app` bundle's Info.plist later)

> **The private key MUST stay in your Keychain only. Anyone with it can push malicious "updates" to every PixCull user.**

### 6. Set up the `.env` file (~5 min)

In the repo root:

```sh
cp .env.example .env
chmod 600 .env
# Edit .env with your real values:
#   APPLE_TEAM_ID=...
#   APPLE_SIGNING_IDENTITY="Developer ID Application: Your Name (TEAMID)"
#   APPLE_NOTARY_PROFILE=pixcull-notary
#   SPARKLE_ED_ACCOUNT=pixcull
```

`.env` is in `.gitignore` so secrets never leave your machine.

### 7. Pick a CDN domain (~10 min)

The signed DMG + the appcast.xml need to be hosted somewhere stable. Options:

- **GitHub Releases** (simplest, free) — appcast.xml ships as a release asset, DMG too. The `SUFeedURL` becomes `https://github.com/ChrisChen667788/pixcull/releases/latest/download/appcast.xml`. Limitation: no phased rollout.
- **Cloudflare R2** + custom domain (`pixcull.app`) — recommended for v0.8 phased-rollout work; $0/month for free tier.
- **S3 + CloudFront** — overkill for v0.7 launch.

If you're not sure, start with **GitHub Releases** — it's already wired in this repo (see `gh release upload`) and zero extra cost. Migrate to R2 in v0.8 when you need phased rollout.

### 8. Verify the pipeline (~30 min) — after all of the above

```sh
# Build the .app (requires py2app — see docs/macos-signing.md §2)
make app  # or python setup_app.py py2app

# Run the signed-DMG pipeline:
bash scripts/release_macos.sh 0.7.0
# Expected output:
#   [release] codesign... OK
#   [release] dmg build... OK
#   [release] notarize submission... waiting (usually 5-30 minutes)
#   [release] notarize accepted: OK
#   [release] stapler attach: OK
#   [release] sparkle sign_update: SIG_FROM_SPARKLE
#   [release] dist/PixCull-0.7.0.dmg ready · upload to CDN
```

### 9. Upload + GitHub release (~5 min)

```sh
# Update docs/sparkle/releases.example.json with the real signature
# from step 8 and rename to dist/releases.json:
cp docs/sparkle/releases.example.json dist/releases.json
# Edit dist/releases.json:
#   "ed_signature": "SIG_FROM_SPARKLE"
#   "size_bytes":   <actual DMG size>

# Regenerate appcast
python scripts/build_appcast.py dist/releases.json --out dist/appcast.xml

# Attach to the v0.7.0 GitHub release
gh release upload v0.7.0 dist/PixCull-0.7.0.dmg dist/appcast.xml
```

That's it. Sparkle users now auto-update.

## 🆘 If you hit a wall

- **"My country can't pay $99"** — Apple accepts most international cards. If your card is rejected, use an Apple Gift Card (purchasable at Apple Stores / Authorized Resellers).
- **"Identity verification taking >5 days"** — email <developer-program-support@apple.com> with your enrollment confirmation #.
- **"codesign: no identity found"** — re-run `security find-identity -v -p codesigning`. If it's empty, the Xcode certificate request didn't complete; redo step 2.
- **"notarytool: invalid credentials"** — app-specific password expired. Generate a fresh one (step 3) and re-run `store-credentials`.
- **"sign_update: missing private key"** — `~/Sparkle/bin/generate_keys` writes to *your login Keychain only*. If you've nuked the Keychain, regenerate — but then the NEW public key MUST be re-embedded in the .app, and existing installs need a critical-update push to switch over.

## 📍 Where this fits in the v0.7 plan

This document closes the gap on **v0.7-P2-3 (Sparkle 自更新)**. The
charter committed to "infrastructure ready, actual cert pending".
Everything code-side is shipped; only the real-world prerequisites
above remain.

Once you finish steps 1-9, mark this issue done in the v0.8 task
list and the next release (v0.8) ships with auto-updates out of
the box.
