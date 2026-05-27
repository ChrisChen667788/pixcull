# Brief 01 · PixCull Brand Guide

> **Hand this to a mid-level brand designer (自由职业者 / 工作室).**
> 1-month engagement, RMB 15,000–25,000.  Deliverable: a complete
> `BRAND-GUIDE.pdf` PixCull can publish + reference forever.

## Project context

PixCull is a **local-first AI photo culling tool** for professional
photographers (wedding / sports / wildlife / landscape).  Free,
open-source (MIT), single-developer project that's at v0.10 with
mature engineering (614 tests, 7 charters shipped) but
visually still "developer + AI" rather than "designer-curated".

What we have visually right now:

- Brand mark — 5-circle "spotlight on one in a crowd" SVG.  See
  [docs/brand/](../../docs/brand/).  **Concept is good, execution
  is a placeholder.**
- Brand gradient — `#6E56CF → #A855F7 → #EC4899` (indigo → violet →
  pink).  Currently borrowed-feeling from Linear / Stripe.
  **The brief is to evolve this into our own.**
- Typography — system stacks (Inter / Charter / SF Mono).  No
  custom typeface.  **Phase B keeps system; Phase C commissions a
  custom one if budget allows.**
- 8 reference products: Linear / Stripe / Notion / Apple Photos /
  Raycast / Pixelmator Pro / Affinity Photo / Figma — see
  [docs/DESIGN-SYSTEM-ROADMAP.md §2](../../docs/DESIGN-SYSTEM-ROADMAP.md#2--借鉴对象七个被精心设计的对照产品)

## What we're paying for

A **brand guide PDF (60-100 pages)** covering:

1. **Brand mark + logomark + wordmark variants**
   - Primary mark on dark / on light / monochrome / single-color
   - Minimum size, clear-space rules
   - When-not-to-use examples (3-4 anti-patterns)
   - Optional: animated brand-mark concepts for the v0.13 Rive
     hero reveal (Phase C tie-in)

2. **Color system**
   - Three full palettes (dark / light / a11y high-contrast)
   - Each palette: surfaces (4 elevations) · text (4 levels) ·
     accent (3 saturations) · semantic (success / warn / danger /
     info / neutral × tint + border + base)
   - **Brand gradient** — refined from the current
     `#6E56CF → #A855F7 → #EC4899` to a custom-mixed alternative.
     Goal: identifiable as PixCull within 3 seconds vs. Linear /
     Stripe / Apple Music
   - WCAG AA compliance documented for every text / surface pair

3. **Typography ramp**
   - Display / body / serif / mono — 4 typefaces total
   - **Five scripts**: Latin, Simplified Chinese, Japanese, Korean,
     Spanish/Latin extended.  Photo communities are global; one
     PixCull product should read native in all five.
   - 6-level size scale + 3-level line-height scale + 2-3 weight
     pairings
   - **Numerals** — special section on `tabular-nums` for the AI
     scoring numbers (every score is a number; consistent
     numerals are part of the brand voice)
   - Recommended fonts: must be either OSS-licensed (Inter,
     Noto Serif, JetBrains Mono) or properly licensed (Adobe
     Fonts / Fontshare commercial use).  **No SIL-OFL ambiguity.**

4. **Motion identity**
   - Document the existing `pixcull-overshoot` curve
     (`cubic-bezier(0.34, 1.56, 0.64, 1)` — see
     [design-system/tokens.json §motion.ease.out](../tokens.json))
     with **name + use cases + anti-use cases**
   - Specify **3 signature moments** (hero reveal / Cmd+K open /
     conflict modal entrance) at frame-accurate timing
   - Define the principle for "when to add motion vs. when to
     hold still" — Linear's lesson is the only motion that earns
     screen time is purposeful motion

5. **Voice + tone**
   - 5-7 examples of "how PixCull speaks" — error messages, tooltip
     copy, onboarding hints, empty-state encouragement
   - Photographer-voice anchoring — every line should sound like
     a peer working photographer talking, not a software product
     introducing itself
   - Documented vs anti-patterns ("upload 1500 photos in 30s" ≠
     "we save your evening")

6. **Photography**
   - The brand uses real photographer work; spec the lighting /
     color / framing aesthetic the brand favours
   - 5-shot Press Kit reference set (Phase C ties in)

7. **Iconography principle**
   - Adoption of [Phosphor Icons](https://phosphoricons.com/) — confirm
     stroke weight + size scale
   - List the 5 icons that warrant **custom** rather than Phosphor:
     brand mark, score radial dial, share-link icon, sparkline
     glyph, portfolio arrow

8. **Layout grid + spacing**
   - 8px base grid matching existing spacing.{1..8} tokens
   - Edge / inset / gap recommendations for cards / chips / modals

9. **Component preview gallery**
   - Render `.card`, `.chip`, `.modal-{info,action,destructive,detail}`,
     `.btn`, `.score-radial`, `.ai-sparkline` in the proposed
     palette + typography so the brand guide visualises what the
     v0.12 release will look like

## Source files we will provide

- **All current screenshots** under `docs/screenshots/`
- **The brand mark SVG sources** under `docs/brand/`
- **Sample data** to render (one wedding run · 1500 rows of real
  data with hashed filenames)
- **Existing token JSON** as the starting palette baseline:
  `design-system/tokens.json`
- **Three competitor screenshots** for reference: Linear, Apple
  Photos, Lightroom Library

## Source files we expect back

- `design-system/figma/pixcull-brand.fig` — the master Figma file
  (binary; gitignored but lives in the team's Figma org)
- `design-system/figma/brand-guide.pdf` — exported readable PDF
  (committed to the repo)
- `design-system/tokens.json` — updated with the refined palette
  + type ramp (we'll regenerate `tokens.css` etc. from it)
- 3 hi-res brand mark renders (transparent PNG + SVG):
  `docs/brand/pixcull-mark-{light,dark,mono}.{svg,png}`

## Timeline + payment

- Week 1 — kickoff call (1h) + competitive audit + initial mood
  board.  Engineer-side deliverable: rendered version of every
  PixCull surface for review.
- Week 2 — color palette + typography proposals (2-3 options each,
  with rationale)
- Week 3 — brand mark + iconography + motion identity
- Week 4 — voice / tone / layout grid + integration into Figma
  file + final brand-guide.pdf

Payment: 50% at week 1, 50% at deliverable acceptance.

## Acceptance criteria

- Brand guide PDF is **complete to all 9 sections above** — not
  "minimum viable", thorough enough that any future contributor
  can use it as the source of truth
- A blind designer panel of 3 holds PixCull screenshots against
  the 8 reference products and **rates PixCull ≥ 4.0/5 on
  "craft + identity"** (current estimate: 2.5/5)
- The refined Figma file is in our Figma org with edit access
  granted to the PixCull team
- Updated `tokens.json` passes
  `python scripts/build_design_tokens.py --check` and
  `python scripts/lint_design_tokens.py` after the engineer
  re-builds outputs

## How to bid for this work

Please reply with:

1. 3-5 examples of prior brand-system work for software / tech
   products (links are fine)
2. Your rate (day rate or fixed-project)
3. Timeline given your current bandwidth
4. Any specific tools you don't use (Figma vs Sketch vs
   Penpot vs Adobe XD — we prefer Figma but can adapt)
5. Any clarification questions on the brief above

Contact: chenhaorui667788@gmail.com · GitHub
[@ChrisChen667788](https://github.com/ChrisChen667788)
