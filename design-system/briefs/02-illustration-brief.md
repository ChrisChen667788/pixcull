# Brief 02 · PixCull Empty-State Illustration Set

> **Hand this to an editorial illustrator.**
> 2-4 week engagement, RMB 5,000–10,000 for 10 illustrations.
> Deliverable: 10 SVG + PNG illustrations replacing the
> developer-drawn placeholders in
> [pixcull/report/templates/results.html](../../pixcull/report/templates/results.html).

## Project context

PixCull has 10 places in the UI where the photographer sees an
**empty state** — no buckets yet / no peers in the LAN sync session
/ no annotations completed yet / etc.  Each currently shows a
geometric SVG placeholder drawn by the developer, in a two-tone
palette that's recognisable as Heroicons / Lucide-default-style.

**The goal of this brief**: replace all 10 with editorial line-
drawing illustrations that feel personal + on-brand + photographer-
specific.  Inspiration:
[Dropbox Paper empty-states](https://www.dropbox.com/scl/fi/), the
[Notion welcome screens](https://www.notion.so/), or
[Linear's empty-issue-list](https://linear.app/) decorations.

## The 10 illustrations

### Already in the codebase (v0.4 / v0.9 P2-3) — to be REPLACED

Current SVG sources at lines noted in
[pixcull/report/templates/results.html](../../pixcull/report/templates/results.html).
Look + copy-paste current SVG paths into Figma as starting points
ONLY to understand the spec — your job is to redraw with
illustrator's voice.

| # | Symbol id (current) | Surface when shown | Subject suggestion |
|---|---|---|---|
| 01 | `art-empty-inbox` | A run with zero rows (analysis fail) | An empty wooden inbox tray on the photographer's desk, with a tiny golden sparkle suggesting "first photo arriving soon" |
| 02 | `art-no-match` | Filter cleared zero photos from the batch | A magnifier looking at an empty contact sheet — five blank cells in a row |
| 03 | `art-analyzing` | (Future) Loading state for the analyzer | A film canister with pulsing concentric light rings — already loosely-defined; the illustrator decides if it stays or refactors |
| 04 | `art-empty-buckets` | `/buckets` panel before any bucket created | Three nested editorial-style bucket silhouettes on a shelf, the centre one with a soft glow + a small "+" hovering above |
| 05 | `art-empty-history` | `/history` page with zero archived runs | A vintage Leica with no film loaded + a wall clock frozen at 12 — implying "no time line yet" |
| 06 | `art-no-peer` | LAN sync presence panel with no collaborators | One photographer figure in the centre with WiFi-ripple lines extending outward, no second figure at the perimeter |
| 07 | `art-no-annotations` | When 0 rubric-human-labeled rows | An editorial clipboard with a half-drawn pencil sketching the first star of a 5-star rating |
| 08 | `art-no-search` | CLIP semantic search returns no matches | A magnifier examining a film negative, with a tiny floating question mark above |

### New (Phase B additions) — illustrator's invention

| # | Surface concept | Subject suggestion |
|---|---|---|
| 09 | `art-style-train-empty` | When user clicks "Train style model" with < 3 keeps | Three frames pinned to a mood board, two empty + one with a hint of a great photo, with arrow pointing to "+ 2 more selects please" |
| 10 | `art-tether-waiting` | Tether session is live but no photos arrived yet | A camera with USB cable + a hand reaching toward the shutter, hint of a coffee mug nearby (photographer waiting) |

## Style + technical specifications

### Style direction

- **Editorial line drawing** — single-weight strokes (1.5–2 px on
  a 160×120 viewBox), no fills inside the outline EXCEPT…
- ...**ONE accent area per illustration** filled with the brand
  gradient (`url(#brandGrad)` matching tokens.json
  `color.brand.gradient`).  This is the
  "where the photographer's attention should land".
- Black-outlined strokes use `var(--color-fg-muted)` so they
  read as charcoal on dark theme AND as ink on light theme
- **Soft drop-shadow** at the bottom of each illustration —
  `<ellipse cx=80 cy=103 rx=50 ry=5 fill=rgba(99,102,241,0.10)/>`
  pattern is already established and should stay (community
  recognition)

### Technical spec

- **viewBox**: `0 0 160 120` (matches the existing
  `.empty-art { width: 160px; height: 120px }` rule)
- **Format**: SVG primary, with PNG at 320×240 (2x) + 640×480 (4x)
  for Retina + email embedding
- **Filename convention**: `art-<id>.svg` matching the existing
  symbol-id namespace + `art-<id>@2x.png` + `art-<id>@4x.png`
- **CSS variables**: every fill / stroke uses `var(--color-*)` so
  the same SVG works on dark + light theme.  Reference the
  existing v0.4 P1 (3/4) SVGs for the pattern.
- **No raster textures inside the SVG** — the illustrator can use
  raster brushes in their tool but the export must be all vector
  paths.  This is for the executive PDF where data-URI inline of
  a raster would inflate file size.
- **Brand-gradient `<defs>`** — DO NOT include a `<defs>` inside
  each symbol.  Reference the existing
  `<linearGradient id="aiBrandGrad">` defined once at the top of
  results.html.

## Delivery

- 10 × `art-<id>.svg` (clean, single-file, well-commented)
- 30 × PNG renders (10 × 3 resolutions)
- 1 × `style-guide.pdf` showing all 10 side-by-side in a
  consistent grid for review
- All files in `design-system/placeholders/illustrations/`
  (engineer-side then moves them to the proper inline-symbol
  location in `results.html`)

## Acceptance criteria

- Each illustration tells the user **what they should do next**
  in under 5 seconds — emptiness is an invitation, not a defeat
- A blind designer panel of 3 unanimously prefers the new set
  over the placeholders side-by-side
- All 10 SVGs render correctly on both dark + light theme
  (test via the v0.4 light-theme toggle)
- File sizes: each SVG < 2 KB, each PNG @2x < 30 KB
- Both Chinese-script (clipboard text in illustration 07) and
  Latin (camera label in 10) are illustrated without baked-in
  text — use universally-readable forms instead

## Timeline + payment

- Week 1 — kickoff + concept sketches for all 10 (rough pencil)
- Week 2 — selected style refined; 3 finals produced for review
- Week 3 — remaining 7 produced
- Week 4 — revision round + delivery

Payment: 30% at kickoff, 70% at delivery acceptance.

## How to bid

Reply to hello@pixcull.dev with:

1. Portfolio (5-8 example illustrations in the editorial-line style)
2. Rate (per-illustration or fixed-project)
3. Timeline given your current load
4. Tool of choice (Illustrator / Figma / Procreate / iPad app)
5. Specific question about the brief above
