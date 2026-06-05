# Brief 05 · Rive motion · Hero reveal v2 + signature moments

> **Hand to a Rive (or Lottie) motion designer.**
> 4-6 week engagement, RMB 8,000–15,000.  Phase C.  Trigger:
> Brief 04's typeface in production (the motion lands on typefaces).

## Why Rive (vs. Lottie / vs. plain CSS)

v0.9-P0-2 ships a CSS-keyframe hero reveal — the 2-second
stagger / count-up / scale-in.  It works.  But:

- CSS keyframes can't react to user input (e.g. mouse position
  during reveal · scroll during reveal · the "I clicked something
  mid-animation" branch)
- Tuning a CSS-keyframe animation takes 20 dev-iterations to
  feel "designed" — Rive ships in a single iteration with a
  designer-tuned state machine
- Rive runtime is < 100 KB (Lottie ~ 200 KB; vanilla CSS keyframes
  are free but spread across the whole stylesheet)
- Lottie's Adobe lock-in violates PixCull's OSS-first commitment

**The brief replaces the v0.9-P0-2 CSS hero reveal with a Rive
state machine + adds 3 new signature moments.**

## Scope

### Moment 1 — `/results` hero reveal v2 (replace v0.9-P0-2)

Current CSS-keyframe version:
- 0-300ms: workspace bar + sidebar slide in
- 200-1000ms: grid cards stagger fade-up (each +16ms)
- 300-1500ms: workspace stats number count-up
- 500-1200ms: per-card score count-up
- 600-2000ms: decision dot scale 0→1

Rive v2 should:
- Use the **PixCull Sans variable font axis** to animate weight
  during count-up (200 → 700 by end of count)
- React to mouse: if the user hovers a card mid-reveal, that
  card's animation **pauses and waits for them**, then resumes
  when they move on
- Provide a **"skip" interaction** — pressing `Esc` or `Enter`
  during the reveal jumps to end-state cleanly
- Total runtime tunable (current 2s, designer picks final)
- `prefers-reduced-motion` → state machine has a 1-frame final
  state (no animation, just settled UI)

### Moment 2 — Cmd+K open

Current: instant render of the palette.
v2: 200ms entrance with the search input materialising first,
then results list cascading.  Reverse on close.

### Moment 3 — Conflict modal entrance (v0.10-P0-1)

Current: standard `.modal.show` fade-in.
v2: when 2-way sync detects a conflict, the modal **slides in
from the syncBadge** (the click target), drawing visual lineage
from "which UI element fired this state".

### Moment 4 — Score radial fill on every annotation

Current: 280ms CSS transition on dasharray.
v2: when the user labels keep/cull, the score radial does a
brief **ripple outward** from the new fill level — celebration
moment for "you decided!".

## Deliverables

1. **4 × `.riv` files** — one per moment, plus a `_master.riv`
   bundling them
2. **JS integration glue** in `pixcull/report/templates/results.html` —
   `<script src=".../rive.min.js"></script>` + 1 init call per
   moment
3. **state-machine spec docs** — markdown describing each state +
   transition + input
4. **Fallback**: every Rive moment has a CSS-keyframe fallback
   that fires if Rive runtime fails to load.  Existing v0.9-P0-2
   CSS keyframes are the fallback for moment 1.

## Technical constraints

- **Rive runtime size budget**: total page weight including Rive
  + 4 `.riv` files ≤ 500 KB (current results.html is ~600 KB
  uncompressed)
- **No external network requests** — Rive engine + all `.riv`
  files bundled with PixCull
- **The brand gradient must render correctly inside Rive** — the
  CSS `linear-gradient` we use doesn't directly work in Rive;
  designer needs to recreate the gradient as a Rive shape fill
- **Same motion curve** — the `pixcull-overshoot` curve
  (`cubic-bezier(0.34, 1.56, 0.64, 1)`) is the brand signature.
  All Rive easings must match.

## Acceptance criteria

- Side-by-side dev panel: CSS-keyframe v0.9-P0-2 vs Rive v2.
  **A blind viewer prefers v2** in 4 of 5 trials.
- All 4 moments respect `prefers-reduced-motion: reduce`
- Page-weight budget held (< 500 KB)
- Fallback works when Rive runtime is blocked
- All easings match `pixcull-overshoot` brand curve

## Timeline + payment

- Week 1 — moment 1 (hero reveal) prototype + state-machine review
- Week 2 — moment 1 polish + moment 2 (Cmd+K)
- Week 3 — moments 3 + 4
- Week 4 — integration + fallback testing + delivery

Payment: 30% kickoff, 30% at moment 1 acceptance, 40% at delivery.

## How to bid

Reply with portfolio (3-5 prior Rive projects), rate, timeline.

Contact: hello@pixcull.dev
