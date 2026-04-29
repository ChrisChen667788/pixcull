# PixCull.app — Distribution & Notarization

For personal use you can ship the **ad-hoc-signed DMG** that
`scripts/build_app.sh` + `scripts/make_dmg.sh` produces.
On the recipient's Mac, the first launch needs **right-click → Open**
once to bypass Gatekeeper.

For wider distribution (sharing on a website, Mac App Store, etc.) you
need full Apple Developer ID signing + notarization. Below is the
full path.

## Prerequisites

- **Apple Developer Program** membership (US$99/year)
- **Xcode** or `xcode-select` command-line tools
- A **Developer ID Application** certificate
  (Account → Certificates → "+", "Developer ID Application")
- An **app-specific password** for `notarytool`
  (appleid.apple.com → Sign-In and Security → App-Specific Passwords)

Once you have those, save your notary credentials to the keychain so
you don't paste them on every release:

```bash
xcrun notarytool store-credentials "pixcull-notary" \
    --apple-id "your-apple-id@example.com" \
    --team-id "ABCDE12345" \
    --password "abcd-efgh-ijkl-mnop"
```

## Sign

```bash
# 1. Build the app
./scripts/build_app.sh

# 2. Replace the ad-hoc signature with a Developer ID signature.
#    --options runtime turns on the "Hardened Runtime" required for notarization.
codesign --deep --force --options runtime --timestamp \
    -s "Developer ID Application: Your Name (ABCDE12345)" \
    dist/PixCull.app

# 3. Verify
codesign --verify --deep --strict --verbose=2 dist/PixCull.app
spctl -a -t exec -vv dist/PixCull.app   # should NOT say "rejected"
```

## Notarize

Apple's notarization service signs an "I have inspected this binary
and found no malware" stamp. This is what removes the
"PixCull cannot be opened because the developer cannot be verified"
warning.

```bash
# 1. Make the DMG (already signed-via-app)
./scripts/make_dmg.sh

# 2. Submit + wait. Takes ~5-15 min for a 2 GB DMG.
xcrun notarytool submit dist/PixCull.dmg \
    --keychain-profile "pixcull-notary" \
    --wait

# 3. If it succeeded, staple the ticket so the DMG works offline.
xcrun stapler staple dist/PixCull.dmg

# 4. Verify
xcrun stapler validate dist/PixCull.dmg
spctl -a -t open --context context:primary-signature -vv dist/PixCull.dmg
```

## What can go wrong

- **`hardened runtime` issues**: PyInstaller bundles often need
  entitlements for JIT. If notarytool log says
  `com.apple.security.cs.allow-unsigned-executable-memory`,
  pass `--entitlements app/entitlements.plist` to codesign with:
  ```xml
  <?xml version="1.0" encoding="UTF-8"?>
  <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
      "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
  <plist version="1.0">
  <dict>
      <key>com.apple.security.cs.allow-jit</key><true/>
      <key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
      <key>com.apple.security.cs.disable-library-validation</key><true/>
  </dict>
  </plist>
  ```

- **Embedded `.so` files unsigned**: rare, but if notarytool complains
  about a specific `.dylib`, sign it explicitly:
  ```bash
  codesign --force -s "Developer ID Application: …" \
      dist/PixCull.app/Contents/Frameworks/libtorch_cpu.dylib
  ```

- **Apple's malware scanner is slow**: ~15 min for a 2 GB DMG is
  normal. Don't kill `notarytool submit --wait` early.

## Sparkle auto-update (optional, V4.1)

Set up [Sparkle](https://sparkle-project.org/) with an
[appcast.xml](https://sparkle-project.org/documentation/publishing/)
on a web server. Embed the public key in the .app, sign DMG releases
with the matching private key, and the app silently updates itself.

Skip this until V4.1+ — for the first release, manual download +
drag-to-Applications is fine.
