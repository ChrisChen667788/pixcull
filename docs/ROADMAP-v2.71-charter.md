# PixCull v2.71 → v2.80 charter — reconciled

Written 2026-08-21, after v2.70. Replaces the forward half of
`ROADMAP-v2.68-charter.md`, whose numbering drifted: the filter-
localisation work the owner asked for mid-block took v2.69, and the
charter's own v2.69 (per-flag lift) shipped as v2.70. Everything below
is renumbered against what actually exists in git.

## What is already done

| shipped | what it was |
|---|---|
| v2.68 | rule stack recalibrated, cross-validated; a flag demotes, never deletes |
| v2.68.1 | MutationObserver feedback loop froze Safari |
| v2.68.2 | de-materialiser read layout while mutating — the jank underneath |
| v2.68.3 | closing the lightbox locked the tab; nav arrows sat on the inspector |
| v2.68.4 | NaN reached the screen; advice never said who wrote it |
| v2.68.5 | advice budget 700 → 3000; a schema with room for an argument |
| v2.68.6 | the advice pass had never run — 17 versions unreachable |
| v2.69 | the filter panel spoke in enum values |
| v2.70 | per-flag lift; nothing could honestly be dropped |

## Ten versions left, in three tiers

**Tier 1 — needs nothing from the owner.** Measurements against data
already collected, or engineering with its own acceptance test.

**Tier 2 — needs the owner's budget.** Cloud calls, estimate first.

**Tier 3 — needs the owner to label.** The feature stays unbuilt until
the label exists; building first is how four circular datasets happened.

---

# Tier 1 — unblocked

## v2.71 — a silent fallback must be counted

The smallest version here and the one with the highest interest rate.

`_m3_advice_pass` returned 0 on every run for seventeen versions and
nothing noticed, because falling back to the template is the CORRECT
behaviour on failure and no counter separated "never failed" from "never
ran". The same shape is still live: the current advice pass falls back
on ~9% of rows and nothing counts that either.

1. A `FallbackLedger` — per pass, per reason: attempted / succeeded /
   fell back, with the reason bucketed (no key, no consent, budget,
   truncated, parse failed, no image).
2. Surfaced where the owner will see it: the run summary line and
   `/api/v1/runs/<id>/status`.
3. **A gate**: a pass whose fallback rate is 100% fails the run's
   self-check rather than reporting success. That single assertion would
   have caught v2.68.6 on the day it shipped.
4. Applied to every best-effort path, not just advice: `m3_advice`,
   `meta_judge`, `caption_gen`, `reel_caption`.

## v2.72 — counterfactual: wire it, or admit it is not there

`counterfactual.py` claims in its own docstring that it "surfaces in the
Inspector as `+0.08 if rule-of-thirds`". Nothing in `report/`,
`pipeline/` or `cli.py` references it; it and `composition_classifier`
are reachable only from their own tests.

v2.67 makes the decision harder rather than easier: composition metrics
handed to the judge made every per-frame call worse (cull precision
0.58 → 0.17). A composition-derived "crop this way" chip inherits that
doubt.

1. Evaluate `best_variant()` against the 493 blind frames: on frames the
   photographer culled, does the proposed crop's score gain exceed the
   gain on frames they kept? If not, the chip is decoration.
2. **Ship one of two things, not neither**: wired into the inspector
   with the number behind it, or both modules deleted along with the
   docstring claim.
3. Either way `tests/test_repo_hygiene.py` gains a check that a module
   claiming a UI surface has a caller.

## v2.73 — `--vlm-mode off` is a supported mode; gate it like one

Everything measured since v2.48 measures the cloud path. The offline
path is what the README offers photographers under NDA, and it has no
end-to-end quality gate.

1. An offline e2e test: fixed input folder → `--vlm-mode off` → assert
   the decision distribution and the per-axis stars against a golden,
   so a silent regression in the local stack fails the suite.
2. Assert no network syscall is attempted in that mode (socket guard),
   which is the actual promise — not "the flag exists".
3. Pin v2.68's calibrated thresholds as the offline quality floor:
   destroyed keepers ≤ 8, culls found ≥ 3 on the blind set.

## v2.74 — the personalisation profile, measured

`~/.pixcull/personal_profile.json` shifts thresholds from corrections.
It has never been evaluated against blind labels, and it was learned
partly from the circular datasets.

1. Held-out evaluation: fit the profile on a training split, score the
   held-out split with and without it.
2. **The profile must be REMOVED before any A/B** — a lesson already
   paid for once; the file survives between runs and silently changes
   the baseline.
3. If the held-out delta's interval spans zero, the profile ships off by
   default and says why.

## v2.75 — burst peak against blind labels

Burst collapse picks a peak per stack and puts a 🏆 on it. Whether the
picked frame is the one the photographer keeps has never been checked,
and the blind set contains bursts.

1. For every cluster with ≥2 frames and ≥1 blind label, ask: is the
   picked peak the frame they kept?
2. Compare against the trivial baselines — highest `score_final`, first
   frame, random — because "better than nothing" is not the bar.
3. Per-component attribution: the picker cites "眼睛睁开 95%" / "簇内最
   锐"; measure which component actually predicts the keeper.

## v2.76 — Scenes: cull in story order

The one competitor capability PixCull lacks outright. Narrative Select
groups a shoot chronologically into its parts so you cull in story order
rather than image by image; reviewers call it unique to Narrative.

EXIF timestamps are already read, and `scene-nav` markup already exists
in `results.src.html` (`id="sceneNav"`, currently `hidden`).

1. Segment a run on capture-time gaps — adaptive threshold, not a fixed
   minute count, because a wedding and a studio session have different
   natural pauses.
2. Name each stretch from what is in it (time span, dominant scene,
   frame count); never invent an event name.
3. Wire the existing `#sceneNav` strip: jump, and filter to one stretch.
4. Acceptance: on a 5,000-frame run, a named stretch is reachable in one
   click from the top of the page.

## v2.77 — the first descent

v2.68.2 removed steady-state jank; the first scroll through an
un-materialised run still blocks ~1.8s across two tasks. Competitors
sell "no delay" as a headline, which makes this table stakes.

1. Chunk the first materialisation across frames rather than doing a
   batch in one IntersectionObserver callback.
2. Acceptance is a measurement, not a feeling: zero long tasks over
   6 s of first-descent scrolling on the 5,069-frame run, same harness
   as v2.68.2.
3. Guard: `tests/test_grid_observer_feedback.py` gains the chunking
   invariant, so the next optimisation cannot quietly un-chunk it.

---

# Tier 2 — needs the owner's budget

## v2.78 — the prompt A/B (v2.59's debt)

Scheduled for v2.59, displaced twice. Same four-arm framework as v2.67,
varying the rubric rather than the evidence: current prompt, a shorter
one, one that asks for a decision before reasons, one that asks for
reasons before a decision.

Estimate goes to the owner BEFORE the run, with the arithmetic shown —
v2.67 came in over its estimate because the estimate assumed a cache
that a key change had invalidated.

---

# Tier 3 — needs the owner to label

## v2.79 — `maybe` means "recoverable", or it does not

Two blind passes measured what `maybe` costs the metric (97% of `maybe`s
on kept frames were "worth another look"). Nothing has asked the
photographer to mark *recoverable* directly on frames they would
otherwise cull.

1. Buildable now: the third-button card, the strata, the weights.
2. The labelling pass is the owner's.
3. The feature — surfacing "there is a keeper inside this frame" —
   stays unbuilt until the label exists.

## v2.80 — advice quality, blind

`m3_advice` replaced 1,576 lines of templates on the argument that a
template cannot say "新娘的手被前景虚化挡住了". Reasonable, and still
unmeasured — v2.68.6 only established that the model's words now
*arrive*.

1. A blind rubric card: paragraph shown, source hidden, owner scores it.
2. Sample both arms on the same frames — template and model.
3. If the model does not beat the template blind, the depth problem is
   not where we think it is, and that is the result.

---

## v2.81 — close the block

Re-measure the 493 frames against the shipped configuration, put
whatever the numbers say into both READMEs, re-sync ModelScope, and run
the claims-match-reality gate over the result.
