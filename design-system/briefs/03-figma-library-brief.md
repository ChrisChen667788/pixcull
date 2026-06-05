# Brief 03 · PixCull Figma Component Library

> **Hand to the same brand designer doing Brief 01**, or a separate
> systems-design specialist if Brief 01's designer doesn't have
> component-library experience.  Bundle pricing:
> if same designer is doing both, +1 week / +RMB 5,000–10,000.
> Standalone: 2 weeks / RMB 10,000–18,000.

## Why this exists

Phase A (already shipped) put every token in `tokens.json` —
designers can edit color / spacing / typography in Figma via the
Tokens Studio plugin.  But there are NO COMPONENTS yet in
Figma — the designer can edit *what* the brand uses but can't
preview *how* it looks on a real card / chip / modal / button.

This brief commissions the **Figma component library** that mirrors
the actual `.card`, `.chip`, `.modal`, `.btn`, `.score-radial`,
and `.ai-sparkline` rendering paths in `results.html`.

## Deliverables

### A. The Figma library file

Location: `design-system/figma/pixcull-components.fig`

Contents (5 component families, each with all states):

#### 1. `.card`

The photo grid card.  States:
- default (decision = none yet)
- decision · keep (green accent left bar)
- decision · maybe (amber accent left bar)
- decision · cull (red accent left bar)
- has-human (4-style chip on top right)
- needs-review (warn-styled bar)
- sync-conflict (amber corner triangle)
- hover (lifted shadow + floating actions visible)
- active (compare mode A / B badges)

24 variants total (decision×4 × has-human×2 × needs-review×2 ×
hover×2 — only the meaningful subset).

#### 2. `.chip`

The unified chip system (decision / scene / style / cull-reason
/ wedding-moment).  States:
- success / warn / danger / info / neutral (5 palettes)
- size · small / regular (2 sizes)
- with-icon / text-only (2 forms)
- active / hover / disabled (3 interaction states)

90 variants total — Figma auto-grid generates these.

#### 3. `.modal`

Four modal types from v0.9-P1-1 (info / action / destructive /
detail).  Each:
- header (title + close + optional badge)
- body (default + scrollable + form fields)
- footer (button pair · reverse-pair on destructive)
- Sizing: small (380px) · medium (560px) · large (760px)

#### 4. `.btn`

Buttons.  Variants:
- primary / secondary / ghost / danger (4 palettes)
- size · sm / md / lg (3 sizes)
- with-icon · leading / trailing / icon-only (4 layouts)
- state · default / hover / active / disabled / loading

24 + state variants.

#### 5. `.score-radial` + `.ai-sparkline`

v0.9-P1-4 AI viz components.  Variants:
- `.score-radial` · score 0.0 / 0.25 / 0.5 / 0.75 / 1.0 / null
- `.score-radial.lg` · same at 36px
- `.ai-sparkline` · balanced / valley / spike / sparse / empty

### B. Page layouts (frames showing components in context)

3 frames that mirror the real product:

1. **/results grid** — using real photo data + 12 cards + all
   chips populated + workspace bar + sidebar
2. **/results lightbox** — single photo open + inspector pane
   populated + sparkline + radial + 4-source axis comparison
3. **/share/<token> portfolio** — the v0.9-P0-5 client deliverable
   page with cover + 3 chapter sections + 12 keep cards

These pages are what stakeholders open when they ask "what does
PixCull look like in 2026 Q4?" — they're the brand's screenshot
generators.

### C. Style auto-export → tokens.json

Set up the Tokens Studio plugin in the Figma file so a designer
editing colors / typography in Figma can:

```
Tokens Studio panel → Export → JSON → overwrite tokens.json
```

The export must round-trip cleanly:

```bash
python scripts/build_design_tokens.py --check
# OK — N tokens, all targets in sync
```

### D. Documentation page (in-Figma)

A `🏠 Cover` page documenting:
- Component naming conventions (matching CSS class names)
- Variant property order (matching the existing CSS modifier chain)
- Constraints / auto-layout settings
- When to use which variant
- "Don't use the Figma file as a sandbox for new components —
  components added here that don't exist in `results.html` are
  technical debt"

## Technical constraints

- **Match real CSS** — every shadow / radius / spacing / motion in
  the Figma file MUST exist in `tokens.json`.  No "designed it nice
  in Figma, doesn't quite render that way in CSS" mismatch.
- **Tokens Studio compatible** — every color / spacing / radius
  reference inside a component should be a Tokens Studio variable,
  not a raw hex.  Otherwise designer edits don't flow to the JSON.
- **Light + dark theme variants** — every component renders in
  both.  Tokens Studio supports theme switching natively.

## Acceptance criteria

- All 5 component families have every state listed above
- All 3 page layouts render cleanly using real PixCull data
- Tokens Studio export → JSON → CSS pipeline round-trips without
  drift
- The cover documentation page is complete
- A non-designer (an engineer) can open the file, find a component
  by name, copy it into a new mockup, and apply a variant without
  outside help

## Timeline + payment

- Week 1 — base components + 5 families · static styling
- Week 2 — interaction states + variants + Tokens Studio wiring +
  3 page layouts + cover doc

Payment: 40% at kickoff, 60% at delivery acceptance.

## How to bid

Reply with:

1. Portfolio: at least 2 prior Figma component libraries you've
   shipped or maintained (links + screenshots)
2. Rate (day rate or fixed-project)
3. Comfort level with Tokens Studio specifically
4. Any change you'd push back on in this spec

Contact: hello@pixcull.dev
