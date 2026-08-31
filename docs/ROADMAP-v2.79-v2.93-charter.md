# PixCull v2.79 → v2.93 charter — fifteen versions, reconciled with the market

Written 2026-08-31, after v2.78. Supersedes the forward half of
`ROADMAP-v2.71-charter.md`. Three inputs are merged here:

1. **The competitive refresh** (`COMPETITIVE-2026Q3.md`, same date) — 46 products
   and models scanned, every fact-checked headline claim overstated.
2. **The measured backlog** — defects this repo found and left standing because
   they were a different version's problem, each with a number attached.
3. **The unfinished charter items** from v2.68 and v2.71.

## What the numbering already settled

The competitive refresh proposed grid performance as its v2.82. It shipped first,
as **v2.78**: the placeholder shimmer animated 4,969 off-screen elements forever,
costing 856 ms of style recalc per load and 2,420 ms per six seconds of idle —
roughly 40% of a core held for as long as the tab was open. Style recalc is now
114 ms on load and 30 ms idle. The refresh's target for that item was "below
100 ms for a visible viewport"; measured against its own criterion the item is
closed, and it does not reappear below.

## The honest constraint on five of these

Five versions below **cannot be completed by an agent working alone**. Blind
evaluation needs raters who are working photographers and are not the author;
prompt A/B needs an API budget the owner controls; the recoverable-label pass
needs the owner's own judgement on their own photographs. For each, the version
is split: the harness, the protocol and the refusal guard are buildable now, and
the version does not close until real human input has run through it. A harness
with fabricated raters would be worse than no harness, because it would produce a
number this project would then cite.

Marked **[owner]** below.

---

## The fifteen

### v2.79 — Advice depth: a critique that shows photographic expertise
The live complaint, and the gap that most undercuts what PixCull is structurally
good at. Replace the rubric-driven rationale with per-axis depth from a vision
model, keeping the six axes as structure. The competitive refresh proposes an
Apache-2.0 8B VLM that fits a 16 GB Mac; the fact-check found the benchmark claim
behind that recommendation overstated, so the model choice is an experiment in
this version, not a conclusion.
**Measure:** side-by-side against the current output on the same frames, rated
blind. **Ships only if** the new output wins on a pre-registered margin.
**Wrong, not late:** image-quality benchmarks reward technical judgement; wedding
emotion and sports peak-moment need narrative context a single-frame inference may
not have. The evaluation must include those verticals or it measures the easy half.

### v2.80 — Advice quality baseline, published **[owner]**
Build the blind-evaluation harness for v2.79: pre-registered rubric, rater
assignment, inter-rater agreement computed and *reported*, and a refusal guard that
declines to publish a headline number when agreement falls below threshold.
**Measure:** the evaluation is the deliverable. **Wrong, not late:** agreement on
"expertise" in written critique is historically low; publishing a low-agreement
number as a result would be worse than publishing nothing.

### v2.81 — The 9% advice parse failure, counted by reason
Advice generation fails to parse about 9% of the time and the aggregate reporting
does not say why. A rate without a cause is not actionable, and a silent 9% is how
a systematic failure hides inside an average.
**Measure:** per-reason counts in the run summary; the ledger already exists from
v2.71. **Wrong, not late:** if the failures cluster on one vertical or one image
shape, the fix is upstream of parsing and this version only reveals it.

### v2.82 — Wire the remaining passes into the fallback ledger
`meta_judge`, `caption_gen` and `reel_caption` still fall back silently. v2.71
built the ledger and connected one pass. Until they are all in, "the run went
fine" cannot be distinguished from "three passes quietly did nothing".
**Measure:** a structural-failure count that is zero on a healthy run and non-zero
on a deliberately broken one. **Wrong, not late:** a ledger that over-reports
teaches people to ignore it.

### v2.83 — Personalisation, demonstrated rather than asserted **[owner]**
Active learning from corrections is shipped and unmeasured. A photographer who has
corrected PixCull for six months has no evidence it learned anything.
**Measure:** held-out drift — after a correction batch, the fraction of held-out
frames whose verdict moved in the intended direction, shown as a trend, not a
score. A flat or negative trend blocks the update.
**Wrong, not late:** a held-out set drawn from the same shoot is too similar to
detect generalisation; it must span lighting and location or it measures memory.

### v2.84 — Warm first-screen: the remaining 918 ms
v2.77 took cold first-screen from 3386 ms to 2204 ms and left warm untouched at
918 ms, correctly, because both fixes were cold-path. v2.78 removed 875 ms of
main-thread work. This version re-measures warm from scratch and either finds the
next real cost or reports that the remainder is image fetch and stops.
**Measure:** first-screen ready, cold and warm, the harness from v2.77.
**Wrong, not late:** shipping a change whose saving sits inside the noise band,
which the v2.77 warm arm already came within 53 ms of doing.

### v2.85 — The hydration double-render
Every image URL is requested exactly twice — 172 requests, 86 unique — because
hydration rebuilds the whole grid. The duplicates are memory-cache hits and land
after first-screen, which is why v2.77 declined to touch it. It is still a full
grid teardown and rebuild for rows the user is already looking at.
**Measure:** duplicate request count to zero for rows already materialised;
first-screen must not regress. **Wrong, not late:** the rebuild may be load-bearing
for state the incremental path does not restore — selection, focus, scroll anchor.

### v2.86 — Thumbnails at the size they are displayed, DPR-aware
420 px is served where 278 CSS px is displayed. Shrinking to 280 is wrong: on the
Retina displays photographers actually use, DPR 2 wants 556 px, and a naive
"optimisation" measured at DPR 1 would ship blur to every real user.
**Measure:** bytes and decode time per viewport at DPR 1 and DPR 2, plus a visual
check at 1:1. **Wrong, not late:** trading image quality for milliseconds in a tool
whose entire job is judging image quality.

### v2.87 — Client proof sheet, deliberately minimal
The largest product gap for the Chinese studio market: there is no client-facing
output at all. Watermarked derivatives plus a static gallery the photographer can
host anywhere, with approve/comment through a mailto or a configurable webhook.
No database, no payments, no account.
**Measure:** a 300-frame proof set shared in under two minutes with no third-party
account. **Wrong, not late:** photographers already on a delivery platform will not
move, so this must not grow into one. See "declined" below.

### v2.88 — Accuracy baseline with a disclosed methodology **[owner]**
Rivals quote self-reported accuracy figures; the fact-check found none of them
independently benchmarked. PixCull has better method and no number. Publish one —
with test-set size, rater count, adjudication rule, pre-registered threshold and
confidence interval, and an explicit statement of what the test set does *not*
cover.
**Wrong, not late:** the 608-row correction set may skew to one vertical; an
unscoped headline figure would mislead exactly the photographer it is meant to
inform.

### v2.89 — The keep↔maybe boundary, made visible **[owner]**
`keep_min_score` is unidentifiable to the current metric because `maybe` counts as
`keep`. The parameter cannot be tuned because nothing can see it. Needs a labelling
pass that produces real keep↔maybe reclassifications.
**Measure:** the boundary becomes identifiable — the metric responds to the
parameter. **Wrong, not late:** if reclassifications are rare, the honest outcome
is to delete the parameter rather than tune it.

### v2.90 — Burst peak against blind labels
Burst-peak selection ships and has never been checked against labels produced
before the algorithm's answer was known. Every rival claims burst grouping; this
is the one where a real number is cheap to get.
**Measure:** agreement with blind peak choice, with an interval.
**Wrong, not late:** if humans disagree with each other as much as they disagree
with the algorithm, the metric is measuring the task's difficulty, not the code.

### v2.91 — Prompt A/B on the advice path **[owner]**
Blocked on an API budget the owner controls. The harness, the cost ceiling and the
refusal guard are buildable now; the run is not.
**Wrong, not late:** an A/B whose arms differ in more than the prompt measures
nothing, and cache keys must include the arm — v2.66 already taught this repo that
lesson the expensive way.

### v2.92 — Remote access: the payload that does not matter locally
The page compresses 7.6x and localhost hides it entirely. v2.77 correctly refused
to ship gzip as a first-screen fix. For anyone reaching the review page over a
network — the LAN feature already exists — it is the whole story.
**Measure:** first-screen ready over a throttled connection, before and after.
**Wrong, not late:** compressing on the fly costs server CPU, which on a cold first
open is exactly the resource v2.77 was fighting for.

### v2.93 — Close the block: re-measure everything, then sync
Re-run the acceptance harnesses from v2.77, v2.78 and v2.84 together, confirm no
version undid another, refresh screenshots from a real run, and re-sync GitHub and
ModelScope. **Wrong, not late:** `--sync` deletes remote-only files and the model
card must be re-uploaded afterwards; a "successful" sync that silently removed the
model card has happened before.

---

## Deliberately declined

**A full client-selection commerce platform.** WeChat mini-program, payments,
revision tracking. That is studio-management SaaS against incumbents with years of
production and regulatory experience. v2.87 covers the minimum gap; the rest should
be an integration, not a build.

**An AI retouching engine.** Different dataset, different team, different market
motion. The XMP sidecar is the correct seam; deepening it is tractable, and
building a retouching engine is not.

**Per-genre trained models.** Nine-plus separately trained and maintained models
against a vertical-weighted rubric that is auditable by a small team. Deepen the
rubric (v2.79) instead of competing on model count.

---

## How this charter can fail

Every previous charter in this repo drifted: work the owner asked for mid-block
took a number, and the charter's own item shipped later under a different one.
That is fine and it will happen again. What is not fine is a version closing
because its code landed rather than because its measurement passed. Five of these
fifteen cannot close without a human, and they are marked. If one of them is
reported closed without that human, the report is wrong.
