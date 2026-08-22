# PixCull v2.68 → v2.77 charter — the rule stack is now the weak half

Written 2026-08-21, the day after the evidence A/B (v2.67) closed the
last open question about the judge.

## What changed, and why this plan looks nothing like the last one

Every charter since v2.48 asked the same question: *is the model any
good?*  That question is answered.  On 493 blind-labelled frames,
`vlm_authority=primary` scores macro-F1 0.695 against the rule stack's
0.400, and v2.67 showed the evidence block it is handed earns its place.

Turning that around: **the rule stack is now the worst component in the
product**, and it is the only component an offline user has.  `--vlm-mode
off` is a documented, supported mode, and it is the mode this project
spent two years building.  Measured on its own, without the judge to
overrule it:

| rule stack alone, 493 blind frames | macro-F1 |
|---|---|
| as it ships today | **0.321** |
| stop treating a hard flag as an automatic cull | 0.476 |
| …and recalibrate the two thresholds | 0.565 |

The single worst behaviour is `flag ⇒ cull`.  It is worth −15.5 macro-F1
points on its own, and it is not a surprise: the detector flags measure
**0.9x lift** against this photographer's culls — worse than chance.
The rule stack auto-deletes on a signal that is anti-correlated with the
thing it is deleting for.

## The trap this plan must not fall into

That 0.565 was chosen by sweeping thresholds on the same 493 frames it
is scored on.  It is an upper bound on a fit, not an estimate of
performance, and shipping it as though it were the latter is how this
project produced four circular datasets in a row.

**No threshold ships without cross-validation.**  The honest number is
the held-out one, it will be lower than 0.565, and if it is not
distinguishable from today's 0.321 then nothing ships and that is a
result too.

---

## v2.68 — recalibrate the rule stack, cross-validated

The whole slice, in order:

1. **A CV harness that cannot cheat.** K-fold over the blind frames,
   thresholds fitted on the training folds only, scored on the held-out
   fold, stratum weights travelling with the rows into both. Refuse to
   report if any fold has zero cull positives.
2. **Fit `flag ⇒ cull` as a parameter, not an axiom.** It is currently
   unconditional; it becomes a fitted choice like any threshold.
3. **Report the held-out delta with a bootstrap CI**, and ship only if
   the interval clears zero.
4. **A test that pins the shipped thresholds to the recorded CV result**,
   the same contract v2.67 gave the evidence arm: change one without the
   other and the suite fails.

## v2.69 — hard flags: which of them are evidence at all

v2.68 asks whether the flags should auto-cull.  This asks the prior
question, per flag: does `highlight_clip`, `blur`, `eyes_closed`,
`duplicate` each carry lift against the blind labels, or do some of them
carry none?  A flag with no lift should stop being a flag, not merely
stop auto-culling.  Free — every flag is already in `scores.csv`.

## v2.70 — counterfactual: wire it, or admit it is not there

`counterfactual.py` says in its own docstring that it "surfaces in the
Inspector as `+0.08 if rule-of-thirds`".  Nothing in `pixcull/report/`,
`pixcull/pipeline/` or `cli.py` references it; it is reachable only from
its own tests and from `composition_classifier`, which is equally
unreachable. Two modules, a false claim, and no user-facing path.

The decision is genuinely open, and v2.67 makes it harder rather than
easier: composition metrics handed to the judge made every per-frame
call *worse*. A composition-based "crop this way" chip inherits that
doubt. So: evaluate it against the blind frames, and either wire it up
with evidence or delete both modules and the claim.

## v2.71 — the prompt A/B (v2.59's debt)

Scheduled for v2.59 and displaced by the calibration work, on the
reasoning that the prompt was not the binding constraint while the rule
stack over-culled 4.8x. v2.68 removes that excuse. Same four-arm
framework as v2.67, varying the rubric rather than the evidence.

**Costs API calls against the owner's key, so it does not start without
their go-ahead** — and the estimate goes to them before, not after.

## v2.72 — the `maybe` / recoverable labelling pass

The v2.63 candidate, unchanged in substance: `maybe` may mean
*recoverable after a crop* rather than *borderline*. Two blind passes
measured what it means for the metric (97% of `maybe`s on kept frames
were "worth another look"), but nothing has asked the photographer to
mark *recoverable* directly on frames they would otherwise cull.

Buildable now: the third-button card, the strata, the weights. The
labelling itself is the owner's, and the feature stays unbuilt until the
label exists — building it first is exactly how the four circular
datasets happened.

## v2.73 — `--vlm-mode off` is a supported mode; test it like one

Everything measured since v2.48 measures the cloud path. The offline
path is what the README offers privacy-conscious users, and it has no
end-to-end quality gate at all. Whatever v2.68 and v2.69 establish
becomes that gate.

## v2.74 — the personalisation profile, measured

`~/.pixcull/personal_profile.json` shifts thresholds from a
photographer's corrections. It has never been evaluated against blind
labels, and it was learned partly from the circular datasets. It has to
be measured with the profile removed and re-applied, on held-out data,
or it should be off by default.

## v2.75 — advice quality has never been measured

`m3_advice` replaced 1576 lines of templates on the argument that a
template "cannot say 新娘的手被前景虚化挡住了 because it has never seen
the frame". Reasonable, and unmeasured. Needs a rubric a human can score
blind, on a sample, against the template baseline.

## v2.76 — burst handling against blind labels

Burst collapse picks a peak frame per stack. Whether the picked frame is
the one the photographer keeps has never been checked, and the blind set
contains bursts.

## v2.77 — close the block: re-measure end to end, re-sync, re-audit

Everything above changes decisions. The 493-frame measurement gets
re-run against the shipped configuration, the READMEs get whatever the
numbers actually say, and the claims-match-reality gate runs over the
result.

---

## Sequencing note

v2.68, v2.69, v2.70, v2.73, v2.74 and v2.76 need no API calls and no
labelling: they are measurements against data already collected. v2.71
needs the owner's budget go-ahead. v2.72 and v2.75 need the owner to
label. The unblocked work is deliberately first.

---

## v2.70 — landed, and it changed nothing on purpose

Per-flag lift, on the same 494 blind frames, weighted, with Wilson
intervals on the raw firing counts:

| flag | fired | lift | 95% CI | verdict |
|---|---|---|---|---|
| `no_clear_subject` | 301 | 0.83x | [0.56, 1.22] | inconclusive |
| `shadows_clipped` | 87 | 1.72x | [1.04, 2.72] | **informative** |
| `severely_underexposed` | 63 | 2.32x | [1.41, 3.60] | **informative** |
| `scene_uncertain` | 45 | 0.51x | [0.15, 1.67] | inconclusive |
| `subject_blur` | 15 | 2.35x | [0.86, 5.12] | unmeasured |
| `highlights_clipped` | 6 | 3.98x | [1.22, 7.93] | unmeasured |
| `face_occluded` | 6 | 0.00x | [0.00, 4.29] | unmeasured |
| `severely_blurry` | 4 | 0.00x | [0.00, 5.39] | unmeasured |

**Nothing was dropped, and that is the finding.** The charter said "a
flag with no lift should stop being a flag". No flag in the shipped
attention set has a measured absence of lift: three of the five never
fired once on 494 frames, and the two that did are inconclusive.
Dropping any of them would be acting on the shape of the sample.

**v2.68 overstated its own evidence.** Its commit says the flags carry
"0.9x lift — worse than chance". That was a point estimate with no
interval; `no_clear_subject`'s spans 1.0. The decision v2.68 took stands
on its direct A/B (274 keepers destroyed against 4) rather than on that
number, but the number did not support the sentence built around it.

**Raw lift turned out to be the wrong question.** A flag fires on frames
whose score is already low, and a low score already sends them to MAYBE:
52 of `severely_underexposed`'s 63 firings were non-KEEP before the flag
was consulted. The marginal question — of the frames the flag ALONE
moves off KEEP, how many did the photographer cull — answers differently:

| flag | fired | already non-KEEP | moved by the flag | of those, culls |
|---|---|---|---|---|
| `severely_underexposed` | 63 | 52 | 11 | 2 (18%) |
| `shadows_clipped` | 87 | 65 | 22 | 2 (9.1% — the base rate) |
| `subject_blur` | 15 | 14 | 1 | 1 |

`shadows_clipped` would buy 22 second looks and return nothing.

And macro-F1 cannot referee this at all: it scores MAYBE as KEEP, so
moving a frame between them is invisible. Adding either flag changed it
by 0.0 — the same identifiability trap as v2.68's `keep_min`.

Shipped: `pixcull/scoring/flag_lift.py`, `pixcull flag-lift`, and this
record. Not shipped: any change to the decision logic.
