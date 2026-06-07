# Design Audit — 2029 Q2  ·  **4.3 / 5**

> Closes v2.2 (slice v2.2-P2-2).  Honest self-audit through the
> `taste-skill` lens (redesign-skill master protocol + the three dials:
> DESIGN_VARIANCE 4 / MOTION_INTENSITY 5 / VISUAL_DENSITY 4), on the live
> 200-photo Xiapu run + the `pixcull video` surfaces.  Trend: 2027Q3 3.6
> → 2028Q2 4.4 → 2028Q4 4.1 → **2029Q2 4.3**.

## Score by dimension

| dimension | score | note |
|---|---|---|
| Brand / colour | **4.5** | editorial-warm (espresso/stone/brass) is coherent + distinctive; the v2.3 "AI-purple" is gone. Docked because a **leaked-palette regression** (pink rubric bars, blue/violet accents in ~45 + 1 hex-ramp sites) *shipped* in v2.3 and lived in the public screenshots until v2.3.1-A/B/F fixed it. |
| Typography | **4.5** | Geist Variable (vendored, OFL) + codified scale + tabular-nums; now `unicode-range`-scoped so CJK never tofus (v2.3.1-E). |
| Layout / craft | **4.3** | Double-Bezel cards, max-width container, calm density. Toolbar got cramped mid-width (fixed bounded in D; the full overflow-menu declutter is still owed). |
| Motion | **4.4** | scroll-stagger blur-fade, magnetic CTAs, spring lightbox, the flowing-SVG diagrams. Tasteful, reduced-motion-honoured. |
| Detail / polish | **3.8** | the drag on the score: onboarding coachmarks **overlapped** the lightbox (fixed C); the heatmap shot doesn't show its overlay; no automated visual guard meant the colour leak shipped silently. |
| Explainability UX | **4.4** | 6-axis rubric + 4-source bars + attribution heatmap + NL explainer remain a genuine differentiator. |

## What improved since 2028Q4

- **Editorial-warm rebrand (v2.3)** — tokens, Geist, Double-Bezel, motion.
- **v2.3.1 consistency sweep** — purged three *forms* of leaked old
  palette (decimal `rgba()`, separate hexes, and a **JS hex-arithmetic
  colour ramp** that only a live-DOM probe could find), warmed the
  attribution heatmap, fixed the coachmark overlap, regenerated the
  gallery, CJK-hardened the fonts.
- **Capability** — learned YAMNet audio tagger (macro-F1 0.629 vs DSP
  0.075), GPS travel-map, `pixcull models` manager, animated
  architecture / sequence / data-flow diagrams on both product pages.

## Remaining gaps → tracked in `ROADMAP-v2.4-charter.md`

1. **No visual-regression guard** — the colour leak shipped because
   nothing asserts "no `#ec4899`/`#3b82f6` in computed styles". This is
   the highest-leverage fix (v2.5-P0-2, Playwright e2e smoke). **Pull it
   forward.**
2. **Single-file frontend** (`results.html` ~14k / `serve_demo.py` ~12k)
   makes every change leak-prone — v2.5-P0-1 split.
3. **Toolbar declutter** (full overflow menu) + **heatmap overlay shot**
   (v2.3.1 leftover).
4. **Under-personalised intelligence** — the tool scores generically;
   v2.4-P0-2 (learn from the user's own keep/cull) is the real moat.

## Verdict

The product looks **consistently premium now** — the brand is mature and
the explainability is a moat.  The 0.1 above 2028Q4 (not more) is
deliberate: shipping a palette regression *and* having no guard against
it is a process gap, not just a pixel one.  **v2.4's first move should be
the visual-regression smoke test**, so consistency stops depending on a
manual screenshot review.

**v2.2 is closed** (its one remaining slice, VLM best-frame caption
P0-3, carries to v2.4-P0-1).  Next: v2.4 (intelligence + workflow) per
`docs/ROADMAP-v2.4-charter.md`.
