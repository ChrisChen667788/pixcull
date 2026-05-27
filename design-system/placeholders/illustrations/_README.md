# 10 empty-state illustrations · v0.10 AI draft

> **STATUS: AI-AUTHORED FIRST DRAFTS.**  These 10 SVGs are
> Phase B deliverable #2, drafted by AI as a baseline.  A Phase
> B illustrator (see [Brief 02](../../briefs/02-illustration-brief.md))
> should redraw each with hand-tuned curves + the illustrator's
> editorial voice.  Until then, these are dropped into
> `results.html` `<symbol>` blocks as the production version.

## Style discipline

Every illustration in this directory follows the same constraints:

- **viewBox**: `0 0 160 120` (matches `.empty-art` size)
- **Stroke palette**:
  - `var(--color-fg-muted)` (#a8b2c1) — main outlines
  - `var(--color-fg-muted-soft)` (#7a8696) — background elements
  - `var(--color-brand-indigo)` / `url(#brandGrad)` — the *one* accent area
- **Stroke width**: 2.0 px (mid-weight stroke) on outlines,
  1.5 px on background elements
- **Stroke style**: `stroke-linecap="round" stroke-linejoin="round"`
  everywhere
- **Floor shadow**: every illustration has the canonical
  `<ellipse cx="80" cy="103" rx="50" ry="5" fill="rgba(99,102,241,0.10)"/>`
- **No raster textures** — all vector paths
- **One brand-gradient accent per illustration** — the visual
  pulled-eye target

## Why these are still "AI-drafty"

- Hand-drawn curves an illustrator would produce read better than
  geometric SVG paths
- A human illustrator gives each illustration a "voice" (e.g. the
  bucket on illustration 04 should feel like a real desk-side
  prop, not a Lucide icon scaled up)
- The Phase B illustrator can sit with one for 2 hours and find
  the small composition shift that elevates it; I can't

The 10 SVGs below are baseline-quality — better than the v0.9-P2-3
placeholders, but not the Phase B target.

## File list

| File | Surface | Status |
|------|---------|--------|
| 01-art-empty-inbox.svg | Run with zero rows | Refined v0.4 P1 |
| 02-art-no-match.svg | Filter zero match | Refined v0.4 P1 |
| 03-art-analyzing.svg | Loading state | Refined v0.4 P1 |
| 04-art-empty-buckets.svg | No buckets created | Refined v0.9 P2-3 |
| 05-art-empty-history.svg | No archived runs | Refined v0.9 P2-3 |
| 06-art-no-peer.svg | No LAN collaborators | Refined v0.9 P2-3 |
| 07-art-no-annotations.svg | Zero human-labeled | Refined v0.9 P2-3 |
| 08-art-no-search.svg | CLIP search zero match | Refined v0.9 P2-3 |
| 09-art-style-train-empty.svg | Style train < 3 keeps | NEW (Brief 02 #09) |
| 10-art-tether-waiting.svg | Tether session live, no photos yet | NEW (Brief 02 #10) |

## How to wire into the product after Phase B

```bash
# 1. Phase B illustrator delivers polished SVGs into this folder
#    (replacing AI drafts)
# 2. Engineer copies symbol body into results.html:
python scripts/wire_illustrations.py \
    --src design-system/placeholders/illustrations/ \
    --dst pixcull/report/templates/results.html
# (script TBD — Phase B follow-up)
```

For now: copy-paste the contents of each `.svg` (minus the
outer `<svg>` wrapper) into the matching `<symbol id="art-*">`
block in `results.html`.
