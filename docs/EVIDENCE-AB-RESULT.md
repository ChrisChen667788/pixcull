# What the evidence block is worth — the v2.66 A/B, run

Written 2026-08-20.  v2.66 shipped the four-arm framework and said, in
its own commit message, **"not yet run"**.  This is the run.

The question it answers has been open since v2.48 shipped the evidence
block: the judge is handed a set of local detector numbers before it
looks at the photograph, and nobody had ever measured whether that helps.
"Advertised but unreachable" is this repo's recurring defect; an
untested design decision at the centre of every run is the same defect
wearing a lab coat.

MEASURED-WINNER: technical

## Design

Four arms, identical in every respect but the evidence block sent with
the image:

| arm | fields sent |
|---|---|
| `technical` | sharpness, highlight clipping, faces, burst — what ships today |
| `composition` | thirds offset, lead room, figure/ground, balance, diagonal energy, symmetry, subject fraction |
| `both` | all of the above |
| `none` | nothing — the control nobody had run |

Scored against **493 blind-labelled frames**: judged before scoring, on
a card carrying the photograph, a serial number and two buttons.  The
100-frame stratified batch travels with its inverse-probability weights.
`vlm_authority=primary` throughout, so the arms differ only in evidence.

Every frame is scored under all four arms or under none of them: a frame
whose call failed on any arm is dropped from all four, because a paired
comparison must be paired.  1 frame of 494 was dropped (0.2%).

## Result

| arm | macro-F1 | vs rule | 95% CI | keepers destroyed | culls found |
|---|---|---|---|---|---|
| `technical` | **0.695** | **+29.5** | [+14.0, +43.0] | **21** | **28** |
| `composition` | 0.666 | +26.6 | [+12.2, +40.4] | 40 | 29 |
| `both` | 0.525 | +12.5 | [+6.6, +19.4] | 34 | 7 |
| `none` | 0.544 | +14.4 | [+8.3, +22.8] | 12 | 7 |
| rule stack | 0.400 | — | — | 274 | 8 |

Paired bootstrap against the shipped arm — the decision-relevant number,
because the question is whether to *change* anything:

| arm | vs `technical` | 95% CI | |
|---|---|---|---|
| `composition` | −2.9 | [−9.3, +3.3] | no significant difference |
| `both` | −17.0 | [−30.8, −1.5] | **significantly worse** |
| `none` | −15.1 | [−28.9, −0.4] | **significantly worse** |

## What it means

**The evidence block earns its place.**  `none` is 15.1 macro-F1 points
worse than `technical`, and the interval excludes zero.  This is the
first evidence that the v2.48 design does anything at all, and it is
positive.

**Nothing should change.**  `technical` ships, `technical` wins.

**`composition` ties on macro-F1 and loses where it counts.**  Same cull
recall (0.36 vs 0.35), much worse cull precision (0.42 vs 0.58) — it
destroys **40 keepers against 21** to find one extra cull.  macro-F1 is
symmetric; a photographer is not.  A tie on the metric is a loss in the
darkroom, and the arm is refused on that ground rather than on its
interval.

**More evidence is not better evidence.**  `both` is worse than either
half and worse than sending nothing.  It is not that the judge goes
timid: `both` still culls 5.5% of frames and its verdict distribution
tracks `technical` (agreement 69%, against 56% with `none`).  It culls
about as *often* and far less *accurately* — cull precision collapses
from 0.58 to 0.17.  Twelve numeric fields do not make a better-informed
judge; they make a confidently wrong one.  The dominance guard refuses
the arm outright: fewer culls found **and** more false positives, on
both classes.

**A population-level discriminator is not a per-frame signal.**  The
earlier finding stands — composition separates this photographer's culls
from their keeps by −0.82σ, and the detector flags manage 0.9× lift,
worse than chance.  It does not follow that handing the composition
numbers to the judge improves any individual call, and measured, it
does not.  That distinction is worth more than the A/B result itself.

## Cost and honesty

1,976 calls, ¥38.56 over the day's budget ledger, against a ¥31
estimate.  The estimate assumed the `technical` arm was already cached;
v2.66 had folded the arm into the cache key, which correctly invalidated
every pre-v2.66 verdict.  404 of them were recovered by back-filling
under the new key — the `technical` block is byte-identical to the
pre-v2.66 default and `PROMPT_VERSION` has not moved since v2.48, so
those verdicts are the same answers to the same prompt, and the
`technical` arm here is literally the same set of verdicts behind the
published 493-frame result.  Its +29.5 against the published +28.9 is
therefore a consistency check, not an independent replication.

Two failures worth recording, both in the harness rather than the
product:

- A first pass fell back to the rule's verdict whenever a call failed,
  which quietly pulls a failing arm toward the baseline and manufactures
  "no difference".  It reported +0.4 to +1.8 across all four arms.  The
  fix is exclusion, not substitution.
- A second pass hit the daily spend cap 54 frames from the end and
  excluded 10.9% of the sample.  The guard held and refused to report;
  the frames were the tail of the task list, not the hard ones, and
  filling them cost ¥3.

## Follow-up

`max_tokens` is not folded into the cache key.  It changes only how much
room the judge has to finish thinking, not the question asked, so cached
verdicts stay valid — but the cache cannot be used to reproduce "what
would this run do at a smaller budget".  Worth folding in the next time
something else already invalidates the cache; not worth invalidating it
on its own.
