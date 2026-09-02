# Advice depth — the baseline, 2026-08-31

The owner's assessment of the written critique was that it is "too shallow, does
not show photographic expertise". That was true and it was not measurable, so it
could not be fixed, defended, or regressed against. This is the measurement.

## What was measured

4,318 cached model calls (`~/.pixcull/cache/m3_verdicts.jsonl`), the real output
of real runs. No API spend, no human raters, nothing synthesised.

> **Corrected 2026-08-31 (v2.81).** The first edition of this page reported one
> figure over all 4,318 rows. That was wrong: the file holds calls from two
> different prompts. 4,138 are verdict calls, whose `overall_rationale` is a
> one-line summary by design; 180 are advice calls, whose `reading` is the deep
> critique. Counting them together dragged the advice rows in as "empty" — they
> have no `overall_rationale` because they were never asked for one — and buried
> the finding under a corpus-wide average. The two are separated below, and the
> conclusion changed completely.

### Verdict rationale — 4,138 calls, the one-liner

| signal | value |
|---|---|
| empty | 5.1% (209) |
| median length | 69 characters |
| names something in the picture | 65.8% |
| connects observation to consequence | 67.8% |
| **both** | **47.7%** |
| carries template tells | 3.2% |
| distinct subjects named, mean | 1.16 |

### Advice reading — 180 calls, the deep critique

| signal | value |
|---|---|
| empty | **0%** |
| median length | **238 characters** |
| names something in the picture | **98.3%** |
| connects observation to consequence | **97.8%** |
| **both** | **96.1%** |
| carries template tells | 14.4% |
| distinct subjects named, mean | **4.85** |

**The deep path is already good.** 96.1% against 47.7%, and it never comes back
empty. Nothing about the advice prompt needs rescuing. What needed finding was
who gets it — see below.

**47.7% is the figure for the one-liner, and 96.1% is the figure the deep path
already reaches.** Any change to either has to beat its own number, not the other's.

## Refreshed 2026-09-02 (v3.1), and made reproducible

The numbers above were assembled by hand and had already drifted: the cache has
since grown to 4,324 rows, and the advice calls from 180 to 186. Rebuilt with
`scripts/measure_advice_depth.py --cache ~/.pixcull/cache/m3_verdicts.jsonl`:

| field | n | empty | median | sees | argues | **both** | hedged | subjects |
|---|---|---|---|---|---|---|---|---|
| `verdict.overall_rationale` | 4,138 | 5.1% | 69 | 65.8% | 67.8% | **47.7%** | 3.2% | 1.16 |
| `advice.reading` | 186 | 3.2% | 234 | 95.2% | 94.6% | **93.0%** | 14.0% | 4.69 |
| `advice.alternative` | 186 | 3.2% | 82 | 93.5% | 18.3% | 17.7% | 15.6% | 2.60 |
| `advice.rationale` | 186 | 3.2% | 39 | 69.9% | 78.0% | 57.5% | 1.1% | 1.16 |

The one-liner is unchanged to the decimal. `advice.reading` moved from 96.1% to
93.0% on six new calls — that is small-sample movement, not a regression, and it
is exactly why a baseline nobody can re-run is not a baseline.

`advice.alternative` is reported here for the first time. It names things in the
frame at 93.5% but connects an observation to a consequence only 18.3% of the
time — it is a list of what to try, not an argument. That is arguably correct for
that field, and it is recorded so that a future change which improves `reading`
by moving sentences out of `alternative` cannot read as a win.

**What v3.1 actually changed in the code:** nothing about the measurement.
`summarise()` now requires a `field` keyword and returns it, so the shape of the
v2.81 defect — a table of rates with nothing saying what it was over — can no
longer be produced. A test asserts every section of this page that reports a
median names its field in the heading.

## What these signals cannot see

`sees_the_picture` cannot tell whether the naming is *correct* — a model that
hallucinates a bird scores well. `argues` cannot tell whether the reasoning is
*sound*. Neither can tell whether a photographer would agree. That judgement is
v2.80's blind evaluation and it needs raters who are working photographers and
are not the author. This metric is the floor beneath that, not a substitute: it
catches critique that could not possibly be expert, which is a different and
cheaper question than whether critique *is* expert.

Deliberately not a single score. A composite would let a prompt change claim a
win by moving the cheapest component — length, which padding buys for free.

## Who was getting the shallow one (v2.81)

The deep critique was withheld from every photograph the tool decided to throw
away: the eligibility filter was `decision in ("keep", "maybe")`. For a culling
tool that is backwards. "Why are you discarding this frame" is the question the
product exists to answer, and it was answered by the 47.7% one-liner while the
96.1% critique went to the keepers, who need it least.

Including culls roughly doubles the API calls, which is the owner's money, so
v2.81 does not change the default. It makes the policy visible instead: the
number of frames denied a critique, and the reason, are now recorded in the
fallback ledger and reported. `PIXCULL_ADVISE_CULL=1` includes them.

An implicit rule that nobody can see is indistinguishable from a bug — that is
the whole lesson of v2.68.6, v2.75 and v2.76 in this repository.

## Where the shallowness actually comes from

Two paths produce critique and only one of them can be deep.

**The template path** (`photo_advice.py`, used with `--vlm-mode off`) maps
measurements to pre-written phrases. It structurally cannot show expertise
because it never sees the photograph — no phrase bank fixes that. Measured on
415 labelled frames: `rationale` is null on 95%, which is by design (it is
synthesised only for `maybe`, and `maybe` is 4% of that set), and 1.2% contradict
themselves — the strength "figure-ground contrast is strong, the subject stands
out" beside the weakness "no clear subject, the frame is diffuse", five times.

**The model path** (`m3_advice.py`) has a prompt that already asks for exactly
what is missing: two to four sentences connecting observation to judgement to
consequence, concrete nouns, no hedging between two possibilities, and an
explicit instruction to surface conflicts between the readings and what is
visible. The prompt is not the problem. The 9% that produce nothing and the 54%
that produce half a critique are.

## What must not be concluded from this

That the fix is a bigger model. The competitive refresh recommended one on the
strength of a benchmark result, and the fact-check found that claim overstated —
the paper was a year older than reported and the architecture was
mischaracterised. Model choice is an experiment for v2.79's successor, run
against this baseline, not a conclusion.
