# homebrew-pixcull — brew tap for PixCull

This directory is the **source-of-truth** for the brew tap that ships
the macOS cask. When v0.8 releases, the contents of this directory get
copied (or git-subtree'd) into the public tap repo at
`https://github.com/ChrisChen667788/homebrew-pixcull`.

## Install (for end users)

Once the tap is published:

```bash
brew tap chrischen667788/pixcull
brew install --cask pixcull
```

That's it. PixCull installs to `/Applications/PixCull.app` and
auto-updates via Sparkle (the brew tap tracks the same appcast).

## Layout

```
homebrew-tap/
├── Casks/
│   └── pixcull.rb           # The cask definition (this is what brew reads)
└── README.md                # You are here
```

When the tap repo is created, the contents above land at the
repo root so `brew tap chrischen667788/pixcull` finds them at the
canonical `Casks/<name>.rb` path.

## Release flow

1. Build + sign + notarize: `bash scripts/release_macos.sh <version>`
2. `gh release upload v<version> dist/PixCull-<version>.dmg dist/appcast.xml`
3. Update `version` + `sha256` in `Casks/pixcull.rb`:
   - `sha256` comes from `shasum -a 256 dist/PixCull-<version>.dmg`
   - `version` from the release tag
4. Push the tap update: `cd homebrew-pixcull && git push`
5. End users: `brew upgrade --cask pixcull` (or wait for Sparkle)

## Why a separate repo for the tap?

Homebrew taps must live in a repo whose name starts with
`homebrew-` and the cask file must be at `Casks/<name>.rb` at the
repo root. We keep the source here so it stays in sync with the
appcast schema + release scripts, then mirror to the canonical
tap repo at release time.
