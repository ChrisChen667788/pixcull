# Windows MSI signing — setup guide

`scripts/release_windows.sh` produces a signed, auto-updating .msi for
PixCull on Windows. This guide walks you through the one-time setup.

## What you'll end up with

```
dist/PixCull-0.8.0.msi    ← Authenticode-signed, ready to ship
dist/appcast.xml          ← updated with the Windows enclosure
```

Users double-click the .msi, Windows trusts the publisher (no
SmartScreen yellow flag), and the in-app Sparkle.NET update channel
auto-pulls future versions from the appcast.

## 1. `.env` schema

The release script reads creds from `.env` at the repo root. Copy
`.env.example` and fill in the section below:

```bash
# Pick ONE of these two signing paths — see §2 + §3 below.

# Option A: SignPath cloud (recommended for OSS)
SIGNPATH_API_TOKEN=path-************************************
SIGNPATH_ORG_ID=path-org-abc123
SIGNPATH_PROJECT_SLUG=pixcull
SIGNPATH_POLICY_SLUG=release-signing

# Option B: local .pfx (fallback / internal builds)
WIN_SIGNING_CERT_PATH=C:/secure/pixcull-codesign.pfx
WIN_SIGNING_CERT_PASSWORD=your-cert-password-here
WIN_TIMESTAMP_URL=http://timestamp.digicert.com   # optional

# Sparkle.NET update channel (always required)
SPARKLE_NET_PRIVATE_KEY=/path/to/sparkle_net_ed25519_private.pem
SPARKLE_NET_SIGN_BIN=/path/to/NetSparkleGenerator
```

## 2. SignPath cloud signing (recommended path)

**Why SignPath**: free for open-source projects (PixCull qualifies),
their HSM stores the cert so your laptop never sees it, and their
GitHub Action integrates cleanly with the release flow.

1. Apply at <https://about.signpath.io/open-source>. Tell them the
   PixCull GitHub URL — they typically approve OSS within 1–2
   business days.
2. After approval, log in and create a project named `pixcull`.
3. Under *Signing Policies*, create one called `release-signing`
   with these settings:
   - Cert: their EV code-signing cert
   - Pre-signing: `Microsoft Authenticode`
   - Allowed artifact types: `.exe`, `.msi`
4. Generate an API token under *User Profile → API Tokens* with
   the `signing.submit` + `signing.upload` scopes.
5. Drop the token + org id + slugs into `.env` per §1 above.

The `signpath` CLI install (one-time):

```bash
pipx install signpath-cli
signpath --version  # sanity check
```

## 3. Local .pfx (fallback)

Use this path when SignPath isn't available — internal builds,
unapproved projects, or air-gapped signing.

1. Buy a code-signing cert (Sectigo / DigiCert / SSL.com). EV
   (Extended Validation) certs cost ~$300/yr and unlock instant
   SmartScreen trust; standard OV certs are ~$80/yr and need ~3
   months of telemetry before SmartScreen stops complaining.
2. Export from your Personal store as a `.pfx`:
   ```powershell
   certutil -exportPFX -p "your-password" My <thumbprint> pixcull-codesign.pfx
   ```
3. Store the `.pfx` somewhere outside the repo (`C:\secure\` or a
   USB key); set `WIN_SIGNING_CERT_PATH` + `WIN_SIGNING_CERT_PASSWORD`
   in `.env`.
4. signtool comes with the Windows SDK; install via the Visual
   Studio installer's "Windows SDK" component, then make sure
   `signtool.exe` is on PATH (`where signtool`).

## 4. WiX Toolset (MSI builder)

```powershell
# Option A — via Chocolatey
choco install wixtoolset

# Option B — via dotnet tool (cross-platform)
dotnet tool install --global wix
```

After install, both `candle` and `light` (WiX 3.x) or `wix`
(WiX 4.x) should be on PATH. The script uses 3.x's `candle/light`
flow; for 4.x you'll want to adjust the script's heat/candle/light
calls to the new `wix build` command.

The `packaging/wix/pixcull.wxs` template + `packaging/wix/pixcull.ico`
(which you need to drop in yourself from `docs/brand/`) are
already committed.

## 5. Sparkle.NET (auto-update channel)

PixCull's Windows app shells out to NetSparkle to check
appcast.xml on every launch. Two pieces you need:

### 5a. The signer binary

```powershell
# Clone NetSparkleUpdater
git clone https://github.com/NetSparkleUpdater/NetSparkle.git ~/NetSparkle
cd ~/NetSparkle/src/NetSparkle.Tools.AppCastGenerator
dotnet build -c Release
# Copy to a convenient path
cp bin/Release/net8.0/NetSparkleGenerator $SPARKLE_NET_SIGN_BIN
```

### 5b. Generate + persist the signing key

```powershell
"$SPARKLE_NET_SIGN_BIN" generate-keys --output ~/.sparkle-net/
# This emits ed25519_private.pem + ed25519_public.pem.
# Drop the public key into the bundled Windows .exe via the
# NetSparkle config (the spec file references it as
# NetSparkleAppCastSignatureKey).  Keep the PRIVATE key offline
# in 1Password / a hardware token — losing it means re-shipping
# the whole app with a new key.
```

Set `SPARKLE_NET_PRIVATE_KEY` in `.env` to the absolute path of
`ed25519_private.pem`.

## 6. First release

```powershell
# From the repo root, in a Windows shell (or WSL Ubuntu)
bash scripts/release_windows.sh 0.8.0
```

The script prints the size + signature block at the end — paste it
into `dist/releases.json` then regenerate the appcast:

```powershell
python scripts/build_appcast.py dist/releases.json --out dist/appcast.xml
gh release upload v0.8.0 dist/PixCull-0.8.0.msi dist/appcast.xml
```

## Troubleshooting

**SmartScreen still flags my signed .exe** — Even with a valid cert,
Windows Defender Microsoft SmartScreen needs a few weeks of telemetry
before it trusts a new publisher. EV certs skip this; OV certs don't.
Reportedly ~5,000 successful "Run anyway" clicks unlock it.

**signtool: "No certificates were found that met all the given
criteria"** — Either the .pfx path is wrong or the password is wrong.
Run `signtool sign /debug ...` to see which.

**linuxdeploy / zsync errors on the Linux script** — see
`docs/LINUX-SIGNING-SETUP.md`.

**Sparkle.NET says "appcast signature invalid"** — the public key
bundled inside the .exe doesn't match the private key that signed
the appcast. Either re-build the .exe with the matching public key,
or re-sign with the matching private key. Don't ship without
matching keys — Sparkle.NET refuses to install unsigned updates
once a key has been bundled.
