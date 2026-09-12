# What is still open, and who it is waiting on

Written 2026-09-08, before starting the next block. Two blocks of work have
closed since the last time anyone counted, and the open items were spread across
three documents in two different shapes. This page is the count.

**Sixteen versions are nominally open. They are four requests.** Every one of
them is waiting on a person, and the harness for each is built — the work left
is not engineering.

---

## The four asks

### 1. ~~One API spend ceiling~~ — answered 2026-09-12: no ceiling, run to completion

The owner's decision, and v3.79 made it mean what it says.

`plan()` refused only against `ceiling_units`, so an infinite ceiling
never refused — and the block is still behind `llm_budget`'s daily cap,
which carries a default and declines calls one at a time as they happen.
The exact failure this planner exists to prevent, a stop halfway through
leaving half an arm, was reachable by setting no ceiling at all, and it
arrived silently.

It takes `daily_cap_units` now, measures against whichever limit is
smaller, and the refusal names which one bound it and which knob to
turn. A plan given no daily cap records `bound_by=None` rather than
implying nothing bound it.

**Still to do before the block runs:** raise `PIXCULL_LLM_BUDGET_YUAN`
past the block's estimate, or split it across days deliberately. The
estimate depends on the pricing function the caller supplies; at 200
frames the eight measurements come to about 2,400 calls.

---

### 2. ~~A correction set with the shoot type recorded~~ — answered 2026-09-12

**158 blind corrections, two verticals, 79 each against a minimum of 30.**
`readiness()` reports `ready: True` and `corrections_to_unblock: 0`.
Unblocks v2.83, v3.8 and v3.9.

Blind, and that is the point. Every previous label set this project
produced was circular — the model's verdict was on screen while the
person labelled, so `source: "auto"`, the label equalled the decision,
and accuracy computed from it was exactly 100%. These came from
`pixcull m3 label`: photograph, serial number, two buttons, nothing
else. Labelled first, scored second, joined third.

**The first honest number this project has had.** Against the rule stack
on the same 158 frames:

| vertical | frames | agreement |
|---|---|---|
| landscape | 79 | 68% |
| portrait | 79 | 78% |
| both | 158 | **73%** |

And the disagreement is one-directional: **27 frames the machine kept
and the photographer culled, and zero the other way.** The rule stack is
systematically more permissive than the person it is for. That is a
finding about the product, not about the labels.

Artefacts are local and outside the repository:
`~/pixcull_label_run/{blind_2026-09-12/,scored/,corrections_2026-09-12.jsonl}`.

---

### 3. Human judgement — unblocks 4

**v2.80, v2.88, v2.89** need raters who are working photographers and are not
the author. `blind_eval.py` and `ground_truth.py` hold the protocol and the
refusal guard that declines to publish a headline number when inter-rater
agreement falls below threshold. **Never synthesise these labels** — that is the
exact defect v2.88 exists to prevent.

**v3.12** is different in kind: it asks whether the burst face strip changes the
override rate, which is a question about the owner's own behaviour rather than
about a third party's opinion. `strip_effect.py` records it as a side effect of
ordinary use — off unless asked for, written to the run's own directory, never
transmitted, and refusing to report a rate below five observations per side.

### 4. ~~One real Lightroom catalogue~~ — answered 2026-09-12

Every test built its own SQLite fixture in the shape the reader expects,
which proved the reader self-consistent and nothing about Adobe's schema.

Run against the owner's working catalogue — Lightroom Classic v13-3, 137
tables, 7,941 images, opened read-only from a copy:

    ✓ 2 judged frames (2 keep · 0 cull), provenance lr_catalog

**No schema mismatch.** The reader handles the real thing.

The interesting part is the other number. That catalogue holds **zero
flags, zero rejects, and six star ratings across 7,941 images** — this
photographer develops in Lightroom and culls elsewhere. Two frames import
because `decision_for` maps `rating >= 4` to keep and returns None below
it, on the grounds that an unflagged three-star frame is a frame nobody
got round to rather than a judgement. That rule is right and it leaves
almost nothing to import here.

So the feature works and its premise does not hold for this user. Worth
knowing before anything is built on top of it.

**Found while checking:** `import-catalog` answers a file it cannot open
with a raw traceback rather than the clean refusal the section above
describes — the same shape as the `contact-sheet` fault fixed in v3.75,
which that sweep did not reach.

---

## ~~The attribution heatmap has a backend and no front~~ — answered in v3.78: the backend was the wrong shape

Recorded 2026-09-11 as an unfinished feature. Measured a day later,
before wiring it up, and that description was wrong in the direction
that mattered.

**Every axis produced a byte-identical PNG.** `_get_axis_head` looked in
the repo-root `models/`; the per-axis models moved into the package in
v3.44 and live at `pixcull/models/`, so the lookup missed every time and
all six axes silently took an identity fallback that ignores the axis.
Same sha256 for composition, light, subject and technical.

**Fixing the path would not have been enough.** Having found the joblib
it loads the estimator, discards it, and looks for a `.coef.npy`
surrogate nothing has ever exported — identity again.

**And a correct implementation would still have been wrong.** The axis
rescorers are sklearn pipelines over 29 named tabular metrics —
`horizon_tilt_deg`, `rule_of_thirds_offset`, `face_count`,
`laplacian_global`. They never see pixels. Integrated Gradients over a
CNN cannot explain a model that does not consume the CNN; it would point
at image regions the scorer never examined, persuasively, in a product
whose distinguishing claim is that it tells you why.

So it is removed rather than repaired, and
`tests/test_attribution.py` holds the rule.

**What a real version looks like.** Those 29 columns are readable on
their own — a horizon tilt is a number in degrees — and the product
already surfaces them as the cull-reason taxonomy and the per-axis
driver line. Attributing an axis score to the features it actually
consumes is the shape this should take: for a tree model that is a
per-prediction contribution per column, which is exact rather than
approximate. Not scheduled; written down so the next attempt starts
from the right model.

---

## A contiguous stretch of one shoot: 149 frames in, 149 keeps out

v3.81 could not test redundancy because its sample was spread evenly
across each shoot, so near-duplicates were rarely drawn together. Redone
on 149 **consecutive** frames of the Zhangye take:

    ✓ Done. Keep=149 Maybe=0 Cull=0

with **28 near-duplicate clusters covering 127 of the 149 frames**, the
largest holding 30, 82% of frames within 0.97 cosine of another, and
`is_burst_peak` False on 99. The product worked out which frame won each
burst and kept every loser.

**Why, and why it is not an ordering mistake.** The decision is made per
frame inside the scoring loop and is final before any cross-frame column
exists: `df["decision"]` is assigned two lines before `df["score_final"]`,
and `rank_burst_peaks` needs `score_final`, so it runs thirteen lines
after the decision and feeds nothing. A burst is cross-frame by
definition. The architecture decides each frame alone and learns which
were siblings afterwards — which is also why `demote_mediocre_bursts`
rebuilds its own time-bucket grouping instead of reusing the clusters,
and why its scope is still `stilllife` alone.

**What v3.82 changed, and what it deliberately did not.** The run says so
now:

    100 of those keeps are not the best frame of their burst (27 bursts
    found). Nothing removes them: burst ranking happens after the
    decision, and the whole-burst demotion covers still life only.

Whether to cull non-peak members is an owner decision, not an
engineering one, and there is a real argument against: on events and
portraits a photographer often wants several frames of one moment, which
is why the existing demotion stayed narrow. Doing it would mean moving
the decision out of the per-frame loop, which is a change to the hot path
and wants a measured before/after.

**The ask, if it is wanted:** should a frame the tool has already ranked
as not the best of its burst be culled by default, kept, or demoted to
`maybe`? Per vertical, since that is where the argument differs.

---

## Nothing the product measures separates this photographer's keeps from their culls

Measured 2026-09-12 on the first blind correction set, 158 frames, and
the reason the 73% agreement number cannot be improved by moving a
threshold.

The 28 frames the photographer culled and the rule stack kept score
**higher** than the 114 both agreed to keep, on every axis:

| | culled | both kept | diff |
|---|---|---|---|
| composition | 4.83 | 4.63 | +0.20 |
| moment | 3.19 | 2.71 | +0.49 |
| light | 4.42 | 4.25 | +0.17 |
| aesthetic | 3.24 | 3.08 | +0.17 |
| sharpness (laplacian) | 1428 | 873 | +555 |
| `score_final` | 0.783 | 0.778 | +0.006 |

Four hypotheses tested and refuted:

* **A loose threshold.** No — the culled frames are not lower-scoring.
* **Blown skies.** Highlight clipping is *lower* in the culled set
  (2.19% vs 2.89%), and equal at every threshold. Formed by looking at
  the frames and rejected by measuring them.
* **Redundancy, by cluster.** One of 28 sits in a cluster where a
  sibling was kept. (The sample was drawn evenly across each shoot,
  which makes near-duplicates unlikely to be sampled together — so this
  set cannot test redundancy properly. A contiguous sample could.)
* **Redundancy, by embedding.** Cosine similarity to the nearest other
  frame is no higher for culled frames (d = +0.09 overall, negative
  within each vertical).

What is visible in the frames and measured by nothing: tour buses,
walkways and railings in the landscape frames, and a great many
near-identical ridge lines. The product has no feature for "there is a
coach in the shot".

**This is not a threshold problem, and no amount of correction data
fixes it.** A dimension the rubric does not have cannot be weighted.

---

## ~~One burst boundary moved between two runs~~ — answered in v3.84

Recorded 2026-09-12 as "I could not reproduce the split, so I cannot
name the cause". Found 2026-09-13 while trying to reproduce the
pipeline's clustering from its own artefacts, which turned out to be
impossible for two separate reasons.

**The verdicts were not stable.** Two consecutive runs of one 150-frame
folder, no code change: `Keep=97 Maybe=53` and `Keep=95 Maybe=55`.

**Why.** EXIF time is second-resolution and a burst is several frames a
second, so tied timestamps are the normal case rather than an edge.
`cluster_bursts` sorted on time alone with a stable sort, so a tie kept
whatever order the rows arrived in — and they arrive from a parallel
scoring pass, in completion order. Only adjacent rows are compared and
the chain is transitive, so the row that happens to sit at a tie
boundary decides whether two groups merge. On four real frames at
16:25:12/:12/:13/:13, every adjacent pair above threshold, two of the
four possible orderings merge and two split.

Since v3.83 `cluster_id` decides `keep` versus `maybe`, so this reached
the verdict.

**And the evidence was not on disk.** `embeddings.npz` holds 512-d CLIP
vectors for semantic search; clustering groups on the 768-d DINOv2
vector, which was discarded with the dataframe. Reaching for the file on
disk gets the wrong model at the wrong dimensionality, and cosine
similarity does not complain — it returns plausible numbers. I did that,
got 44 singletons where the run had 74, drew a conclusion about a scene
misclassification, and had to withdraw it.

Fixed both: tie-break on the filename, which is the camera's shutter
counter and the only real order on the dataframe; and
`burst_embeddings.npz`, so the grouping can be checked rather than
trusted.

Measured over four contiguous blocks, 599 frames: 11 verdicts moved
(1.8%), `score_final` unchanged on every frame, and two consecutive runs
now produce byte-identical groupings.

---

## ~~Should a burst loser default to `maybe`~~ — answered 2026-09-13: no

Asked in v3.82 as a two-sided question and decided by the owner in
v3.83: demote them. Shipped, then tested, then reverted in v3.85.

The test was the owner blind-labelling the same 149 frames — photograph,
serial number, two buttons, no verdict on screen:

| | frames |
|---|---|
| demoted to `maybe` by v3.83 | 100 |
| the photographer kept | 87 |
| the photographer culled | 13 |

A hundred frames moved into review to catch thirteen. Within bursts the
ranking is 6-3 better than chance over the nine clusters where anything
was culled at all, which from nine is not evidence either way.

**The reasoning was sound and the assumption under it was never tested.**
The product does rank each burst, and it did hand over every loser as a
`keep`. What nobody had checked was whether losing a burst predicts
being unwanted. For this photographer, on this evidence, it does not.

`rank_burst_peaks` stays — the ranking is reported in the review page
and the CSV, and README claim 6 is about it. What is gone is letting it
reach the verdict.

`tests/test_burst_losers_stay_keeps.py` holds the revert structurally —
any function that reads `is_burst_peak` and writes a `decision` fails
it, under any name — and names what new evidence would justify a second
attempt, so the next one starts from more than an argument.

---

## The four-block singleton measurement, and what it did not settle

Recorded 2026-09-13. Four contiguous blocks, blind-labelled by the
owner, testing whether a frame with no near-duplicate is culled more
often:

| block | overall cull | singleton | in-burst | OR |
|---|---|---|---|---|
| landscape, Zhangye | 20.8% | 50.0% | 15.7% | 5.24 |
| event, iron-flower | 60.7% | 67.6% | 41.0% | 2.95 |
| portrait, mid-shoot | 10.0% | 9.5% | 10.5% | 0.90 |
| portrait, opening | 11.4% | 26.7% | 7.6% | 4.39 |

Three of four replicate; heterogeneity I² = 58%, so the exception is not
sampling noise. Two candidate explanations were tested and eliminated:
**genre** (two blocks from the same shoot, same model, disagree) and
**overall cull rate** (10.0% versus 11.4%, effectively identical,
opposite results).

A third — that a scene misclassification widened the clustering window
and diluted the singleton group — is **still open**. The test of it was
invalid, because it fed CLIP vectors to a function that groups on
DINOv2. It can be redone now that the right vectors are on disk.

**Not shipped as a rule.** Three-of-four with an unexplained exception is
a rule that fails when nobody is looking.

---

## Three gaps that are NOT waiting on a person

Recorded because "waiting on the owner" is a comfortable place to put something
that is actually unfinished.

~~**v3.28's fix is construction-tested, not effect-tested.**~~ **Closed by
v3.41 — and it found something.** The test went into CI rather than onto anyone's
machine, following the ffmpeg precedent from v2.45, so no install was needed.

The four assertions that protect the photographer's metadata passed on the first
run: the three exiftool behaviours v3.28 took on trust are correct. The fifth
failed. `preserve_existing=False`, the documented escape hatch, emitted a bare
`-IPTC:Keywords=` and then `-IPTC:Keywords+=ours`, and those two do not net to
"only ours" in one invocation — the photographer's keyword survived a write that
had been explicitly asked to replace everything.

No construction test could have found it. The arguments were exactly what the
docstring described; exiftool simply did not compose them that way.

**v3.29's second half did not run.** The charter asked for `evaluate()` re-run
with and without the non-human rows, so that if the delta is material every
published personalisation figure could be marked as computed over polluted
labels. That needs the same correction set as ask 2. The provenance fix shipped;
the impact measurement did not.

**`24-transcript-edit.png` is still synthetic**, and declared as such. It needs
footage with speech in it; the owner's working copy of the source clip is no
longer on this machine.

---

## Closed since the last count

Six items that had been sitting as "NOT MEASURED" turned out to be perfectly
runnable once someone tried — v3.14, v3.15, v3.19, v3.20, v3.21, v3.27, measured
during the v3.1–v3.27 close. Two of them were only unmeasured because nobody had
attempted the measurement, which is a different and less comfortable reason than
"we are waiting on the owner".

`BLOCK-v3.1-v3.27-CLOSE.md` has those numbers. The lesson is on this page
because it will apply again: before recording something as blocked, try it.

---

### 5. ~~Which palette is canonical~~ — answered, and the question was wrong

Asked 2026-09-09, answered 2026-09-10 in v3.66. Recorded rather than
deleted, because the way it was wrong is the point.

**The three-way choice did not exist.** Measured in HSL, all three ramps
sit in the same hue family (35°–41°, warm gold). They differ by role, not
by opinion:

| where | ramp | what it actually is |
|---|---|---|
| `pixcull/report/templates/results.html` | `#d5b584` `#eaca98` `#93743f` | the **accent**. Its own tokens.css already calls `#d5b584` `--accent` and names it champagne gold |
| `scripts/brand/pixcull-brand.json` | `#f2ead9` `#dfcfae` `#c2a878` | the **wordmark** ramp — keyed `wordmarkStart/Mid/End`, drawn on the dark banner where the accent would sit too close to the ground |
| `design-system/tokens.json` | `#c4b9a9` `#988b78` `#6a6052` | the only one nothing renders: a desaturated mid-flight copy, under the names `indigo` / `violet` / `pink` inherited from the purple palette it replaced |

So there was nothing to choose. The design system adopted the accent
ramp, learned the wordmark ramp as the separate role it is, and **no
pixel a user sees changed** — the reconciliation was a rename.

**v3.71 follow-up — and then the counter was wrong too.** With the
palettes reconciled, the `unmigrated` figure was supposed to be the
remaining mechanical work: a token's value written as a literal where a
`var()` would do. It was neither complete nor correct. It counted
`--accent: #d5b584` — the token being *defined*, which cannot become a
var() reference to itself — and it read only inside `<style>`, one of
the three places a single-file HTML app paints. In `video_review.html`
that was the whole number: three counted, all three definitions, and
seven real usages sitting in JavaScript that assembles SVG as a string,
invisible. The honest figures are 131 undesigned and 81 unmigrated.
Migrating those 81 is mechanical and still open; it is not ratcheted, so
it blocks nothing.

**The stated payoff was false.** This entry used to say "reconcile the
palettes and this falls on its own — the script lowers its own baseline
whenever violations drop". `_load_design_tokens()` in
`scripts/lint_design_tokens.py` was **defined, documented at length, and
never called** (verified by AST). The gate had never once read the design
system it exists to enforce, so the number was "count of inline hex" and
reconciling the palette could not have moved it by one. The same false
consequence was written in `.lint_baseline.json`'s `_why` and in a test
docstring; all three are corrected.

The gate reads the tokens now, and reports two numbers instead of one:

| | v3.46 | v3.66 |
|---|---|---|
| files scanned | 1 | 3 — `video_review.html` and `timeline.html` ship to users and were counted by nothing |
| **undesigned** (a hex in no token — real debt) | 144, all of it | **108** |
| **unmigrated** (a hex that *is* a token, written as a literal) | not distinguished | **68** |

Split rather than short-circuited on purpose: folding `unmigrated` into
the ratchet would let a palette edit erase 55 violations with no line of
CSS improving.

Held by `tests/test_colour_names_are_true.py` — no colour token may be
named for a hue its value is not in, the gate must consult the design
system, and every template with a `<style>` block must be scanned.

---

### 6. ~~What number the next release carries~~ — answered: 3.53.0

Found 2026-09-09, updating the public description.

`pyproject.toml` used to be bumped in lockstep with the iteration
number — v2.73 → `2.73.0`, v2.74 → `2.74.0`, v2.75 → `2.75.0`. The last
bump was commit `0a1f5f7` on 2026-08-22. Since then v2.76 through v2.99
and v3.1 through v3.53 have shipped and the version has not moved.

So two things are stale in a way that feeds each other:

| | says | actually |
|---|---|---|
| `pyproject.toml` | 2.75.0 | 78 iterations later |
| latest GitHub Release | v2.47.0 (2026-08-06) | ditto, plus 28 |

The release badge at the top of the README reads the second one, so the
first thing a visitor sees is a version from a month ago.

**The ask is one number.** The convention says pyproject mirrors the
iteration, and the current iteration is v3.53 — which makes the next
release `3.53.0`, a major bump with the meaning that carries on PyPI.
Continuing in 2.x (`2.99.0`) is the other honest reading. Both are
defensible and neither is an engineering call.

Once it is chosen: bump `pyproject.toml`, push the tag, and
`.github/workflows/release.yml` builds the wheel and sdist, runs
`twine check`, smoke-tests the wheel in a clean venv and creates the
GitHub Release with both attached. PyPI upload stays a separate manual
step, so tagging publishes nothing to PyPI on its own.

**Answered 2026-09-09: `3.53.0`,** following the convention rather than
softening it. v3.1 was already a deliberate major step in the charter
numbering; continuing to publish 2.x would have hidden something that had
already happened.

And a thing worth writing down, because I got it wrong out loud. I told
the owner that tagging would not touch PyPI and that upload was a
separate manual step. It was not: `PYPI_API_TOKEN` is configured, and the
upload step ran on any tag push where the token existed. So an ordinary
reversible act performed an irreversible one — PyPI refuses a version
number twice, and a mistagged release burns it for good.

The release now goes out on GitHub only. Upload is `workflow_dispatch`
with an opt-in that defaults to false, and
`tests/test_release_rail.py` fails if a tag push can reach it again, if
the default flips, if the reversible half gets swept behind the same
gate, or if the packaged version starts trailing the newest release
again. PyPI stays on 2.47.0 until somebody decides to move it
deliberately.

---

## Three gaps the skip ledger now names

v3.51 turned the CI skip census into `tests/ci_skip_dispositions.tsv`,
where a row marked `gap` has to say what closes it. Three do, and each is
the same one-line shape as the fix that closed the face extra:

1. **`zeroconf not installed`** — multi-machine sync discovery, three
   tests, no CI coverage. Closed by adding the `sync` extra to the
   hermetic install.
2. **`shot detection extra not installed`** — README claim 17 says a reel
   candidate never spans a hard cut. Closed by adding `pixcull[shots]`.
3. **`scikit-image unavailable`** — the public-domain astronaut face.
   v3.50 installs it, so this should already be gone; if the reason
   reappears the install did not take.

These are engineering, not owner asks. They are here so the next block
starts from a list rather than from another accident.

---

## Known red, pre-existing and now fixed

`test_visual_smoke::test_grid_and_lightbox_have_no_legacy_palette` had flagged
the disagreement-review button since before v3.20. It stayed hidden because the
local gate convention skips that file — it needs a real browser render. Fixed on
`fix/info-token-runtime-palette-guard`: the button never hard-coded a colour, the
dark-theme `--c-info` value itself sat in the one-step gap between the static
guard (`b >= 190`) and the runtime one (`b > 180`).
