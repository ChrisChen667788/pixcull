# Advice depth — the baseline, 2026-08-31

The owner's assessment of the written critique was that it is "too shallow, does
not show photographic expertise". That was true and it was not measurable, so it
could not be fixed, defended, or regressed against. This is the measurement.

## What was measured

4,318 cached model verdicts (`~/.pixcull/cache/m3_verdicts.jsonl`), the real
output of real runs. No API spend, no human raters, nothing synthesised.

| signal | value | what it means |
|---|---|---|
| empty | **9.0%** (389) | produced no rationale at all |
| median length | **69 characters** | one sentence, against a 3,000-token budget |
| names something in the picture | 63% | the rest could have been written from the readings alone |
| connects observation to consequence | 65% | the rest is a list of assertions |
| **both** | **45.7%** | fewer than half are a critique in both senses |
| carries template tells | 3.1% | "expression *or* movement", "overall speaking" |
| distinct subjects named, mean | 1.1 | when it does look, it looks at one thing |

**45.7% is the number this project now has to beat.**

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
