# Linux AppImage signing — setup guide

`scripts/release_linux_appimage.sh` produces a signed, auto-updating
.AppImage for PixCull on Linux x86_64. This guide walks through the
one-time setup.

## What you'll end up with

```
dist/PixCull-0.8.0-x86_64.AppImage         ← chmod +x and run
dist/PixCull-0.8.0-x86_64.AppImage.zsync   ← delta-update feed
dist/PixCull-0.8.0-x86_64.AppImage.sig     ← GPG detached signature
```

Users download, `chmod +x`, run. `AppImageUpdate` finds the
`.zsync` feed via the embedded `UPDATE_INFORMATION` block and
delta-patches in place on each upgrade — no re-download of the
~120 MB bundle, just the changed chunks (~5 MB per minor release).

## 1. `.env` schema

```bash
# Your long-lived GPG key for release signing.  Can be the user-id
# email, the 8-hex short ID, or the full 40-hex fingerprint.  The
# release script passes this straight to `gpg --local-user`.
GPG_SIGNING_KEY=releases@chrischen.studio

# Optional — when set, releases also get a Sparkle EdDSA signature
# so the same appcast.xml serves macOS DMG + Windows MSI + Linux
# AppImage with one consistent signature scheme.
SPARKLE_ED_ACCOUNT=pixcull-default
```

## 2. Prereqs — `linuxdeploy`, `zsyncmake`, `gpg`

Most distros ship `gpg` + `zsync` by default; you'll need to grab
linuxdeploy manually:

```bash
# Ubuntu / Debian
sudo apt install gpg zsync

# Arch
sudo pacman -S gnupg zsync

# Fedora
sudo dnf install gnupg2 zsync

# linuxdeploy (all distros) — single statically-linked AppImage
curl -L https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage \
    -o ~/.local/bin/linuxdeploy
chmod +x ~/.local/bin/linuxdeploy

# Optional but recommended: the Python conf plugin, which handles
# bundling PyInstaller's _internal/ tree cleanly.  Drop alongside
# linuxdeploy and it auto-detects.
curl -L https://github.com/linuxdeploy/linuxdeploy-plugin-conda/releases/download/continuous/linuxdeploy-plugin-conda.sh \
    -o ~/.local/bin/linuxdeploy-plugin-conda
chmod +x ~/.local/bin/linuxdeploy-plugin-conda
```

`zsyncmake` is part of the `zsync` package above.

## 3. Generate the GPG release key (one-time)

If you don't have a release-signing GPG key yet:

```bash
gpg --full-generate-key
# Select:
#   1. RSA and RSA (default)
#   2. 4096 bit
#   3. 2y expiry (renew every 2 years)
#   4. Name: "PixCull Releases"
#      Email: "releases@chrischen.studio"
#      Comment: (leave blank)

# Export the PUBLIC key so users can verify
gpg --armor --export releases@chrischen.studio > docs/pixcull-releases.asc

# Confirm
gpg --list-keys releases@chrischen.studio
```

Commit `docs/pixcull-releases.asc` to the repo so users can pin the
fingerprint:

```bash
# What users will run to verify a release
gpg --import docs/pixcull-releases.asc
gpg --verify PixCull-0.8.0-x86_64.AppImage.sig PixCull-0.8.0-x86_64.AppImage
```

Set `GPG_SIGNING_KEY` in `.env` to either the email or the
fingerprint.

**Backup the private key** to 1Password / a hardware token. Losing
it means downstream Linux users can't verify new releases against
the published public key.

## 4. AppImage update channel (Sparkle-style for Linux)

The script bakes `UPDATE_INFORMATION` into the AppImage header
pointing at the GitHub releases CDN:

```
gh-releases-zsync|ChrisChen667788|pixcull|latest|PixCull-*-x86_64.AppImage.zsync
```

Users install [AppImageUpdate](https://github.com/AppImage/AppImageUpdate),
then run:

```bash
AppImageUpdate ~/Applications/PixCull-0.7.0-x86_64.AppImage
# → checks the zsync feed → delta-patches to 0.8.0
```

If you want to also serve the cross-platform Sparkle appcast feed
(so AppImage + macOS DMG + Windows MSI all read from the same
`appcast.xml`), set `SPARKLE_ED_ACCOUNT` in `.env` — the script
emits an EdDSA signature block you paste into `releases.json`.

## 5. First release

```bash
bash scripts/release_linux_appimage.sh 0.8.0
```

The script prints a size + GPG key id + signature block at the end.
Paste into `dist/releases.json` under the matching version key, then:

```bash
python scripts/build_appcast.py dist/releases.json --out dist/appcast.xml
gh release upload v0.8.0 \
    dist/PixCull-0.8.0-x86_64.AppImage \
    dist/PixCull-0.8.0-x86_64.AppImage.zsync \
    dist/PixCull-0.8.0-x86_64.AppImage.sig \
    dist/appcast.xml
```

## 6. Asking users to verify (recommended docs paragraph)

Add this to `README.md` under the Linux install section once v0.8
ships:

```markdown
### Linux — verify the GPG signature

PixCull ships every Linux release with a detached GPG signature:

    # one-time
    curl -L https://raw.githubusercontent.com/ChrisChen667788/pixcull/main/docs/pixcull-releases.asc \
         | gpg --import

    # every release
    gpg --verify PixCull-0.8.0-x86_64.AppImage.sig \
                 PixCull-0.8.0-x86_64.AppImage

The fingerprint should match: `<paste fingerprint here at release time>`
```

## Troubleshooting

**linuxdeploy: "Could not find any .so files in AppDir"** — Your
PyInstaller build is missing the bundled libpython3.X.so. Add
`hiddenimports=['encodings.idna']` to `app/pixcull.spec` and
rebuild; this is a known PyInstaller-on-Linux quirk.

**zsyncmake: "input file too small"** — Run with `-b 4096` to drop
the block size for small AppImages (<10 MB); irrelevant for our
~120 MB bundle.

**gpg: "skipped 'releases@...': No secret key"** — Your GPG_SIGNING_KEY
references a key whose private half isn't in the local keyring.
Either import it (`gpg --import private.asc`) or update
`GPG_SIGNING_KEY` to point at a key you do have.

**AppImage runs but Sparkle says updates broken** — The bundled
Sparkle public key in the .AppImage doesn't match the private key
you signed the appcast with. Re-bundle the .AppImage with the
right public key.

**AppImageUpdate says "no zsync URL"** — `UPDATE_INFORMATION` env
var wasn't set when linuxdeploy ran. The script exports it
unconditionally; if it's missing, your linuxdeploy is an old
version that doesn't read the env var. Upgrade to a 2022+ build.
