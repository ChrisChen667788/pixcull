# design-system/ — single source of truth for PixCull's visual language

> **Phase A** of [docs/DESIGN-SYSTEM-ROADMAP.md](../docs/DESIGN-SYSTEM-ROADMAP.md).
>
> Every brand / surface / typography decision lives in one file (`tokens.json`),
> editable by a designer via Tokens Studio in Figma, consumed by every
> rendering target (web / iOS / PDF) via the compiled outputs below.

## Layout

```
design-system/
├── tokens.json                 ← SOURCE OF TRUTH (edit this)
├── tokens.css                  ← generated · consumed by web (results.html)
├── tokens.python.json          ← generated · consumed by executive_pdf etc.
├── iOS/
│   └── BrandTokens.swift       ← generated · consumed by iOS Companion
├── briefs/                     ← Phase B + C designer briefs (humans write)
│   ├── 01-brand-guide-brief.md
│   ├── 02-illustration-brief.md
│   ├── 03-figma-library-brief.md
│   ├── 04-typeface-brief.md
│   ├── 05-rive-motion-brief.md
│   └── 06-press-kit-brief.md
├── figma/                      ← Phase B Figma deliverables (binary, gitignored)
│   └── .gitkeep
├── placeholders/               ← Phase B asset placeholders (humans replace)
└── README.md                   ← you are here
```

## Workflows

### Designer (Tokens Studio in Figma)

1. Open the PixCull Figma file → Plugins → Tokens Studio
2. Import `design-system/tokens.json` (Tokens Studio honours the
   `$schema` field at the top)
3. Edit colors / spacing / typography in the Figma UI
4. Export → JSON → overwrite `design-system/tokens.json`
5. Commit the JSON; the next CI run rebuilds CSS / Swift / Python

### Engineer (after a JSON edit)

```bash
python scripts/build_design_tokens.py
git diff design-system/   # confirm the diff is minimal + expected
git add design-system/ && git commit
```

### CI

Two gates run on every PR:

1. **`python scripts/build_design_tokens.py --check`** — fails if
   the committed `tokens.css` / `BrandTokens.swift` / `tokens.python.json`
   are out of sync with `tokens.json`.  Run the build locally + commit
   the regenerated files.

2. **`python scripts/lint_design_tokens.py`** — fails if any NEW
   inline hex color landed in `results.html` over the
   [`.lint_baseline.json`](.lint_baseline.json) count.  Use a
   `var(--color-*)` reference from the tokens instead.

## How to consume the tokens

### Web (`results.html` + other server-rendered HTML)

```html
<link rel="stylesheet" href="/static/design-tokens.css">
<style>
  .card { background: var(--color-surface-bg-card); }
  h1    { font-size: var(--font-size-hero); }
</style>
```

(Phase A.1 adds the `/static/design-tokens.css` route to serve_demo;
for now `tokens.css` is inlined into the existing `<style>` block.)

### iOS (`mobile/PixCullCompanion/`)

```swift
import SwiftUI
// BrandTokens.swift is auto-generated from tokens.json
let bg = Color(hex: BrandTokens.color_surface_bg)
```

(See `BrandKit.swift` for the higher-level primitives like
`RadialProgress` and `AISparkline`.  This file is the raw value
layer; `BrandKit` builds on top.)

### Python (executive PDF, cli_audit, share page)

```python
import json
from pathlib import Path

_TOKENS = json.loads(
    (Path(__file__).resolve().parent.parent.parent
     / "design-system" / "tokens.python.json").read_text()
)
BRAND_INDIGO = _TOKENS["color.brand.indigo"]
```

(Phase A.1 lifts this into a `pixcull.design_tokens` helper module
so consumers don't repeat the path resolution.)

## What's NOT in tokens.json

Three things stay out, deliberately:

1. **Per-component CSS** — `.card`, `.chip`, `.modal` etc. live in
   `results.html` because component composition needs media queries,
   pseudo-selectors, animation keyframes — Tokens Studio can't model
   those.
2. **Light theme overrides** — Phase A only ships the dark-theme
   tokens.  The v0.9-P2-1 light theme's sand-cream palette lives in
   `results.html` until Phase A.1 lifts it.
3. **One-off illustration palettes** — colors inside SVG `<symbol>`
   blocks (`art-empty-buckets` etc.) are illustration pixels, not
   theme tokens; the lint script's `_SCAN_SKIP_SYMBOLS` exception
   recognises this.

## Migration runway · "no new visual debt"

The lint baseline (128 inline hex on `results.html` at Phase A
landing) shrinks every release:

| Release  | Lint baseline | Note                                         |
|----------|---------------|----------------------------------------------|
| v0.10    | 128           | Phase A landing — no migration yet           |
| v0.11    | < 80          | Phase A.1 light theme tokens lifted          |
| v0.12    | < 30          | Phase B component library lands              |
| v1.0     | **0**         | Full token compliance, ready for v1 release  |

Every PR is expected to either hold the baseline OR lower it — the
CI gate auto-lowers when violations decrease.  Use
`python scripts/lint_design_tokens.py --list` to find migration
candidates.

## What's coming next (Phase B + C)

- **Phase B** (2 months, RMB 23k-43k) — commissioned designer
  produces `BRAND-GUIDE.pdf` + 10 custom empty-state illustrations
  + Figma component library matching this tokens.json.  Deliverables
  land under `figma/` (binary) + `placeholders/` get replaced with
  real assets.

- **Phase C** (v0.13 window, RMB 50k-100k) — custom `PixCull Sans`
  typeface, Rive-rebuilt hero reveal, full press kit.  See briefs
  04 / 05 / 06.

All four briefs at `design-system/briefs/` are ready to hand to a
designer day one.
