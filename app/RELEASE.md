# PixCull V7.0 release guide

How to ship a notarized DMG to anyone with a Mac (no warnings,
no right-click-Open dance, just double-click and it runs).

## Day-zero one-time setup

### 1. Apple Developer account ($99/year)
Enroll at <https://developer.apple.com/programs/enroll/>. Wait
~1-3 days for approval.

### 2. Developer ID Application certificate
After approval, create one in Xcode:

```
Xcode → Settings → Accounts → [your Apple ID] → Manage Certificates
  → "+" → Developer ID Application
```

This puts a cert + private key in your login keychain. Verify with:

```bash
security find-identity -v -p codesigning
# Look for a line like:
#   1) AB12CD34... "Developer ID Application: Your Name (TEAM12345)"
```

### 3. App-specific password for notarytool
At <https://appleid.apple.com> → Sign-In and Security →
**App-Specific Passwords** → "+" → name "pixcull-notary".
You get a string like `abcd-efgh-ijkl-mnop`.

Store it once in your keychain so you never paste it again:

```bash
xcrun notarytool store-credentials "pixcull-notary" \
    --apple-id "your-apple-id@example.com" \
    --team-id "TEAM12345" \
    --password "abcd-efgh-ijkl-mnop"
```

### 4. Export the two env vars
Add to `~/.zshrc` (or wherever):

```bash
export PIXCULL_SIGN_IDENTITY="Developer ID Application: Your Name (TEAM12345)"
export PIXCULL_NOTARY_PROFILE="pixcull-notary"
```

## Every release

```bash
# (Optional) regenerate icon if you tweaked make_icon.py
.venv/bin/python scripts/make_icon.py

# One command does the whole pipeline (~20 min wall-clock)
./scripts/release_app.sh
```

The script:
1. Runs `build_app.sh` (clean PyInstaller build, ~5 min)
2. Re-signs with your Developer ID + hardened runtime
3. Builds the DMG
4. Signs the DMG
5. Submits to Apple notary (~10-15 min wait)
6. Staples the ticket to the DMG
7. Verifies via `spctl` + `stapler validate`

Output: `dist/PixCull.dmg` — ready to upload to GitHub Releases /
your website / wherever.

## What "notarized" means for users

| | Ad-hoc signed (V4 build) | Notarized (V7 release) |
|---|---|---|
| First launch | "PixCull cannot be opened — developer cannot be verified" → user has to right-click → Open | Just double-click; runs immediately |
| Gatekeeper status | Quarantine flag tripped | Trusted by macOS |
| Internet required to launch? | No | No (because we **stapled** the ticket) |
| Cost | Free | $99/year for the Developer Program |

## Auto-update (V7.1+)

Add Sparkle once you have a download URL stable:

1. `pip install pyobjc-framework-Cocoa` (already a transitive dep)
2. Drop the [Sparkle.framework](https://sparkle-project.org) into
   `app/Frameworks/`
3. Generate a key pair with `generate_keys`, embed public key in
   `Info.plist` via the spec
4. Host an `appcast.xml` on a fixed URL pointing at successive DMGs
5. Sign each DMG release with the private key

Skip this until you actually have multiple users — for the first
release, manual download + drag-to-Applications is fine.

## Distribution channels

- **GitHub Releases** — free, public, easiest. Upload the DMG, link
  it in the README. Users download via web.
- **Personal/team website** — host the DMG on your S3 / R2 / your
  domain. Same UX as GitHub.
- **Mac App Store** — different signing flow ("Mac App Store"
  cert + sandbox entitlements), 30% fee, weeks of review. Skip
  unless you specifically want Store discoverability.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `notarytool` says `Invalid` | Missing entitlement (often `allow-jit`) | Check `app/entitlements.plist` covers all needed flags |
| Download from web "is damaged" | Quarantine flag tripped because not stapled | Re-run `./scripts/release_app.sh` after Apple approves; check `xcrun stapler validate` succeeds |
| `codesign` fails on a `.dylib` | Inner binary has incompatible team ID | Strip first: `codesign --remove-signature path/to.dylib` then run release script |
| App opens but window doesn't show | Hardened runtime blocking stuff | Check Console.app → search "PixCull"; usually means an entitlement is missing |

## Quick sanity check

To confirm a downloaded DMG is fully notarized + stapled:

```bash
# Should show "accepted" + "source=Notarized Developer ID"
spctl -a -t open --context context:primary-signature -vv ~/Downloads/PixCull.dmg

# Should show "The validate action worked!"
xcrun stapler validate ~/Downloads/PixCull.dmg
```
