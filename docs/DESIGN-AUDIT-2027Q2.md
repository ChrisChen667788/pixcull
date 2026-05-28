# Design audit — 2027 Q2 (post-v0.12)

## Method

Same scoring rubric as 2026 Q3 / Q4 / 2027 Q1.  Reference set still:
Lightroom Classic, Capture One, Photo Mechanic, DaVinci Resolve,
Pixelmator Pro, Affinity Photo, Raycast.

## Scorecard — where v0.12 lands

| Surface                              | depth | craft | hero | notes |
|--------------------------------------|:----:|:----:|:----:|------|
| Keyboard customisation (Raycast-level)|  5   |  4   |  4   | catalogue + per-scope conflict + JSON persistence in place; full GUI panel scoped for v0.13 polish |
| Multi-monitor lightbox companion     |  5   |  4   |  5   | BroadcastChannel sync feels seamless; the *Lightroom Second Window* moment |
| Inspector → V3 training loop         |  5   |  4   |  3   | invisible to user; closes the v0.11-P1-4 loop |
| Payment channel (Stripe + WeChat)    |  4   |  4   |  3   | webhook scaffold + signed-license delivery; no dashboard (intentional) |
| Drag-reorder (buckets + portfolio)   |  4   |  5   |  4   | HTML5 drag API + touch parity for iPad |
| Compare-with-neighbor `\` hotkey     |  4   |  5   |  3   | one-keystroke into burst cluster compare |
| EXIF / histogram / focus overlay     |  4   |  4   |  4   | `H` toggle in lightbox; Canvas histogram, ~30ms draw |
| iOS haptic feedback                  |  4   |  4   |  3   | swipe-nav + dismiss + zoom-toggle, per Apple HIG |
| Annotation modal 3D card flip        |  4   |  5   |  5   | first-time only, dismissable, reduced-motion safe |
| Vision Pro spike documented          |  3   |  3   |  4   | research-only; ships when hardware lands |
| 5 new locales (pt/nl/tr/ru/ar)       |  4   |  4   |  3   | brings us to 13 languages; AR is RTL-prepared |

**Average:** 4.3 / 5 (held steady from 2027 Q1; the bar moved up but
v0.12 met it).

## Where the audit still finds gaps

### Gap 1 — Every AI score is opaque
v0.4 → v0.12 built the *machinery* (rule stack, rescorer V3,
6-axis rubric, hard-example mining) but never the *explanation
surface*.  When a card says `score_final = 0.74` the user has no
in-app path to "why?".  Every competitor that scores photos has this
problem; nobody solves it.  v0.13 is the explanation release.

### Gap 2 — Bias detection is post-hoc
We can detect "scenes the model gets wrong" (hard-example mining)
but only from accumulated reversals.  No proactive surface for
"this 6-month run shows the rescorer over-firing on night-portrait."
v0.13 P0-4 introduces `/admin/bias`.

### Gap 3 — Counterfactuals are speculation
"This would score 0.08 lower if rule-of-thirds" is currently
guesswork on the photographer's part.  v0.13 P0-2 trains a
composition-rule classifier and emits the counterfactual chip in
the Inspector.

### Gap 4 — Style-ref distance is single-number
Inspector shows "🔭 视觉: 0.234" without saying which references
contribute.  v0.13 P1-2 visualises distance-per-ref so the
photographer sees their own style profile shape.

## What v0.12 explicitly punted

- **Stripe Connect / Tax Identifier flow** — webhook delivers, but
  invoicing + tax IDs live in Stripe Dashboard for now
- **Visualised keymap GUI** — backend ready, frontend panel queued
  for v0.13 P2-1
- **Vision Pro full ship** — spike documented; hardware-blocked

## v0.13 scoping

Thesis A (Studio infra) shipped in v0.11.  Thesis B (Pro motion +
interaction depth) shipped in v0.12.  v0.13 instantiates **Thesis C
— AI judgement transparency**, drafted in `docs/DESIGN-AUDIT-2026Q4.md`.

Slices fully expanded in `docs/ROADMAP-v0.13-charter.md`.  Headline
beats:

- Per-axis attribution heatmap (Integrated Gradients on the timm backbone)
- Counterfactual chip (composition-rule classifier + perturbation)
- Confidence-weighted decision modal (60% maybe rows surface
  explanation modal)
- Bias audit dashboard (`/admin/bias`)
- Plus the v0.12 follow-throughs: NL explainer, style-ref viz,
  goldenset auto-augmentation closing the active-learning loop

## Timestamp + provenance

- Audit timestamp: 2027 Q2 (notional)
- Predecessor: `docs/DESIGN-AUDIT-2027Q1.md` (charter for v0.12)
- v0.13 charter: `docs/ROADMAP-v0.13-charter.md`
- Reference product set: same as 2027 Q1 + Raycast
- Pixel-level evidence: not collected this round (every gap above
  was felt during v0.12 dogfooding)
