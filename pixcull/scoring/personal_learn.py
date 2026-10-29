"""v2.4-P0-2 — learn a personal taste profile from the user's OWN
keep/maybe/cull corrections, and prove it beats the generic decision on
held-out corrections.  Fully local, fully resettable.

The generic pipeline scores every photo the same way for everyone; pros
each have a taste (this shooter rewards composition, tolerates soft
technical).  Every correction is already logged to ``annotations.jsonl``;
this closes the loop:

    gather_examples_from_runs(runs_root)   join annotations + scores.csv
    learn_profile(examples)                → scoring.personalized.PersonalProfile
    axis_weights(profile)                  per-axis weight = keep-vs-cull gap
    decide(axes, profile=...)              axis-weighted + threshold-shifted
    evaluate(examples)                     k-fold generic-vs-personal keep-F1

``PersonalProfile`` (threshold shift + axis means + most-cared axis) is
reused as-is from ``scoring.personalized``; this module supplies the
local learning, the axis-weighted decision, and the honest held-out eval.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from pixcull.scoring.personalized import (
    PersonalProfile,
    profile_from_preferences,
)

AXES = ("technical", "subject", "composition", "light", "moment", "aesthetic")
DECISIONS = ("keep", "maybe", "cull")
# Generic decision thresholds on the 0..1 mean-axis score (the personal
# profile shifts these by its calibrated keep_threshold_shift).
KEEP_THR = 0.62
MAYBE_THR = 0.45


@dataclass
class Example:
    axes: dict            # {axis: stars 0..5}
    decision: str         # keep | maybe | cull
    run_id: str = ""      # v2.83 — which shoot this came from
    # v3.8 — which KIND of shoot.  Without it every correction pools into
    # one profile, so a photographer who shoots weddings and wildlife gets
    # the average of two tastes that disagree by design: wedding
    # corrections forgive soft technical for emotion, wildlife
    # corrections do the opposite, and the mean forgives neither.
    vertical: str = ""
    # v3.98 — which photograph, as `filename@datetime`. The filename alone
    # is not one: the shutter counter wraps, so two shoots reuse names.
    key: str = ""
    # v3.99.1 — the machine's own verdict on this photograph, with no
    # profile applied: what a threshold shift is measured against. "" when
    # the run's scores did not allow it to be recomputed.
    machine: str = ""


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------- #
# Learn
# --------------------------------------------------------------------- #
def aggregate_prefs(examples: Iterable[Example]) -> dict:
    """Roll local corrections into the ``prefs`` shape that
    ``personalized.profile_from_preferences`` already consumes."""
    exs = [e for e in examples if e.decision in DECISIONS]
    counts = {"keep": 0, "maybe": 0, "cull": 0}
    sums = {d: {a: 0.0 for a in AXES} for d in DECISIONS}
    nd = {d: 0 for d in DECISIONS}
    for e in exs:
        counts[e.decision] += 1
        nd[e.decision] += 1
        for a in AXES:
            sums[e.decision][a] += _f(e.axes.get(a))
    avg = {d: {a: (sums[d][a] / nd[d] if nd[d] else 0.0) for a in AXES}
           for d in DECISIONS}
    out = {
        "user_id": "local",
        "total_human_annotations": len(exs),
        "scene_decision_counts": {"all": counts},
        "avg_rubric_when": avg,
    }
    # v3.99.1 — what the machine keeps of the same photographs, which the
    # shift is measured against. Every example or none: a rate over the
    # ones that happen to carry a verdict would be over a different set.
    if exs and all(e.machine in DECISIONS for e in exs):
        out["machine_keep_rate"] = sum(e.machine == "keep" for e in exs) / len(exs)
    return out


def machine_verdict(row: dict, config=None) -> str:
    """v3.99.1 — the product's verdict on a scored row with no threshold
    shift: `decision.decide` on `score_final`, as `pixcull calibrate` and
    the measurements compute it. Recomputed rather than read from the
    row's `decision`, which an active profile has already shifted. A run
    made with a profile whose axis weights are unequal has them in
    `score_final` already; that is also the score a re-fitted shift is
    applied to. The run's vertical is not in `scores.csv`, so it is not
    applied. "" when the row has no usable `score_final`."""
    from pixcull.scoring.decision import decide as _product_decide
    from pixcull.scoring.vlm_eval import _flags_of
    try:
        score = float(row.get("score_final"))
    except (TypeError, ValueError):
        return ""
    if config is None:
        from pixcull.config import PixCullConfig
        config = PixCullConfig.load()
    verdict, _ = _product_decide(score, _flags_of(row), config, "standard",
                                 scene=str(row.get("scene") or ""))
    return verdict.value


def learn_profile(examples: Iterable[Example]) -> PersonalProfile:
    """Fit a PersonalProfile from local corrections (reuses the cloud-path
    aggregation math; the input is just gathered locally instead)."""
    return profile_from_preferences(aggregate_prefs(examples))


#: A keep-cull gap smaller than this, in stars out of five, is not worth
#: acting on. Set from the first blind correction set (v3.81): the two
#: axes that survived clamping there were +0.08 and +0.12, and building
#: a profile on those produced a confident, wrong answer.
MIN_MEANINGFUL_GAP = 0.25


def axis_weights(profile: PersonalProfile) -> dict:
    """Per-axis weight = how much that axis separates THIS user's keep
    from cull (the keep-mean − cull-mean gap), normalised & non-negative.
    Equal weights when the gaps do not say anything.

    **v3.81 — `max(0.0, gap)` threw away the evidence that there was no
    signal.** Measured on the first genuinely blind correction set, four
    of six axes had a NEGATIVE gap: the frames the photographer culled
    scored higher on composition, subject, light and aesthetic than the
    ones they kept. Clamping dropped all four to zero, and the whole
    weight landed on the two tiny positives that survived — +0.08 and
    +0.12 stars — producing

        technical 0.4 · moment 0.6 · everything else 0.0

    which is not "learned nothing". It is a confident claim that this
    photographer does not care about composition at all, built from two
    gaps that are noise, and it would have been installed if it happened
    to edge the generic model on a holdout.

    Two rules now, both using only what is already here:

    * a gap under `MIN_MEANINGFUL_GAP` stars is not acted on; and
    * if the largest gap pointing the WRONG way is as large as the
      largest pointing the right way, the ordering is noise and nothing
      is weighted.

    The second is the one that matters. A negative gap is not an absence
    of evidence, it is evidence against — and discarding it silently is
    how no signal becomes a strong opinion.
    """
    raw = {a: profile.axis_keep_means.get(a, 0.0)
              - profile.axis_cull_means.get(a, 0.0) for a in AXES}
    equal = {a: 1.0 / len(AXES) for a in AXES}

    best_right = max(raw.values())
    worst_wrong = -min(raw.values())          # magnitude of the worst negative
    if best_right < MIN_MEANINGFUL_GAP:
        return equal
    if worst_wrong >= best_right:
        return equal

    gaps = {a: max(0.0, g) for a, g in raw.items()}
    total = sum(gaps.values())
    if total <= 1e-9:
        return equal
    return {a: gaps[a] / total for a in AXES}


# --------------------------------------------------------------------- #
# Decide
# --------------------------------------------------------------------- #
def _score(axes: dict, weights: dict) -> float:
    return sum(weights.get(a, 0.0) * _f(axes.get(a)) for a in AXES) / 5.0


def decide(axes: dict, *, profile: Optional[PersonalProfile] = None,
           keep_thr: float = KEEP_THR, maybe_thr: float = MAYBE_THR) -> str:
    """keep / maybe / cull for a photo's axis stars.  ``profile=None`` is
    the generic decision (equal axis weights, base thresholds); a profile
    applies the learned axis weights + calibrated threshold shift."""
    if profile is None:
        weights = {a: 1.0 / len(AXES) for a in AXES}
        kt, mt = keep_thr, maybe_thr
    else:
        weights = axis_weights(profile)
        kt = keep_thr + profile.keep_threshold_shift
        mt = maybe_thr + profile.keep_threshold_shift * 0.5
    s = _score(axes, weights)
    return "keep" if s >= kt else ("maybe" if s >= mt else "cull")


# --------------------------------------------------------------------- #
# Evaluate (the moat proof)
# --------------------------------------------------------------------- #
def _keep_f1(examples: list, decide_fn: Callable[[dict], str]) -> float:
    tp = fp = fn = 0
    for e in examples:
        pred = decide_fn(e.axes) == "keep"
        true = e.decision == "keep"
        tp += pred and true
        fp += pred and not true
        fn += (not pred) and true
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    return 2 * p * r / (p + r) if (p + r) else 0.0


def _cull_recall(examples: list, decide_fn: Callable[[dict], str]) -> Optional[float]:
    """Of the photographer's culls, the share this decision also culls.
    None when the examples hold no cull to find."""
    culls = [e for e in examples if e.decision == "cull"]
    if not culls:
        return None
    return sum(decide_fn(e.axes) == "cull" for e in culls) / len(culls)


def evaluate(examples: Iterable[Example], *, folds: int = 4) -> dict:
    """k-fold: learn on the train split, predict the held-out user
    decisions, compare keep-F1 of generic vs personalised.  This is the
    acceptance metric — personalised should be ≥ generic on the user's
    own taste."""
    # v2.83, two changes, both about not lying by omission.
    #
    # REFUSAL. Too little data used to return `delta: 0.0`, which the CLI
    # printed in the same table cell as a real result. "We could not
    # measure" and "we measured and personalisation makes no difference"
    # are opposite findings and they came out identical.
    #
    # GROUPING. Folds were a stride over the example list, so a fold could
    # be drawn entirely from one shoot — tested on frames beside the ones
    # it learned from, same light, same day. That measures memory, not
    # taste. With run ids and at least two runs, a fold is a whole shoot:
    # learn on some, predict one never seen. Without them the old stride
    # is used and `grouped: False` says so.
    exs = list(examples)
    if len(exs) < folds * 2:
        return {"n": len(exs), "folds": 0, "grouped": False,
                "refused": (f"{len(exs)} corrections is too few for "
                            f"{folds}-fold held-out evaluation; at least "
                            f"{folds * 2} are needed")}

    groups: dict[str, list[Example]] = {}
    for e in exs:
        groups.setdefault(getattr(e, "run_id", "") or "", []).append(e)
    grouped = len(groups) >= 2 and "" not in groups

    if grouped:
        splits = [(g, [e for k, v in groups.items() if k != key for e in v], key)
                  for key, g in groups.items()]
        splits = [(t, tr, key) for t, tr, key in splits if t and tr]
    else:
        splits = [(exs[k::folds],
                   [e for i, e in enumerate(exs) if i % folds != k], None)
                  for k in range(folds)]

    if not splits:
        return {"n": len(exs), "folds": 0, "grouped": grouped,
                "refused": "every correction came from a single shoot, so "
                           "there is no unseen shoot to predict"}

    gen, per, gcr, pcr = [], [], [], []
    for test, train, _key in splits:
        prof = learn_profile(train)
        gen.append(_keep_f1(test, lambda a: decide(a, profile=None)))
        per.append(_keep_f1(test, lambda a, p=prof: decide(a, profile=p)))
        gcr.append(_cull_recall(test, lambda a: decide(a, profile=None)))
        pcr.append(_cull_recall(test, lambda a, p=prof: decide(a, profile=p)))
    g = sum(gen) / len(gen)
    pf = sum(per) / len(per)
    # v3.98 — keep-F1 alone rewards keeping more. On keep-heavy shoots a
    # profile that lowers the bar raises keep-F1 while the culls it was
    # supposed to find slip through: measured across the owner's five
    # shoots, the learned shift raised the product's keep-F1 from 0.743 to
    # 0.777 and halved its cull recall, 7.7% to 3.6%. So the figure the
    # acceptance test was built on is reported beside the one it hides.
    cr = [(a, b) for a, b in zip(gcr, pcr) if a is not None]
    # v3.96 — the mean alone hides how much it moves. The published
    # +0.002 was a four-fold mean; a reader could not tell whether the
    # folds agreed on it or straddled zero, and that is the difference
    # between "no effect" and "no idea".
    return {"n": len(exs), "folds": len(splits), "grouped": grouped,
            "n_runs": len(groups),
            "generic_f1": round(g, 3), "personal_f1": round(pf, 3),
            "delta": round(pf - g, 3),
            "fold_deltas": [round(b - a, 3) for a, b in zip(gen, per)],
            "generic_cull_recall": round(sum(a for a, _ in cr) / len(cr), 3) if cr else None,
            "personal_cull_recall": round(sum(b for _, b in cr) / len(cr), 3) if cr else None,
            # v3.98 — which shoot each fold held out, so a cross-shoot
            # mean can be read per shoot. None for stride folds.
            "fold_groups": [k for _t, _tr, k in splits] if grouped else None,
            "fold_n": [len(t) for t, _tr, _k in splits],
            "refused": None}


# --------------------------------------------------------------------- #
# v3.8 — one taste per kind of shoot
# --------------------------------------------------------------------- #

#: Corrections needed before a vertical gets its own profile.
#:
#: The whole risk of this version is that splitting a small correction
#: set by shoot type produces several profiles each fitted to noise, and
#: every one of them looks exactly like a profile. 30 is not a magic
#: number — it is the point below which the pooled profile is the safer
#: answer, and the guard matters more than the threshold.
MIN_PER_VERTICAL = 30

#: The key the pooled profile lives under. Always present.
POOLED = "_pooled"


def split_by_vertical(examples: Iterable[Example]) -> dict[str, list]:
    """Group corrections by shoot type, dropping the unlabelled ones.

    Examples with no vertical are NOT pooled into a shared "" bucket:
    an unlabelled correction is a correction whose shoot type nobody
    recorded, and treating "unknown" as its own taste would fit a
    profile to a coincidence.
    """
    out: dict[str, list] = {}
    for e in examples:
        v = (getattr(e, "vertical", "") or "").strip()
        if v:
            out.setdefault(v, []).append(e)
    return out


def learn_profiles(examples: Iterable[Example]) -> dict:
    """Pooled profile always; a per-vertical one only where earned.

    Returns ``{POOLED: profile, "<vertical>": profile, ...}``. A vertical
    below :data:`MIN_PER_VERTICAL` gets no entry at all rather than a
    thin one — an absent key makes the caller fall back, a thin profile
    makes it confident.
    """
    exs = list(examples)
    out = {POOLED: learn_profile(exs)}
    for vert, rows in split_by_vertical(exs).items():
        if len(rows) >= MIN_PER_VERTICAL:
            out[vert] = learn_profile(rows)
    return out


def profile_for(profiles: dict, vertical: str | None):
    """The profile to decide with, falling back to pooled."""
    v = (vertical or "").strip()
    if v and v in profiles:
        return profiles[v]
    return profiles.get(POOLED)


def readiness(examples: Iterable[Example]) -> dict:
    """v3.33 — how far off a per-vertical comparison is, in corrections.

    `evaluate_by_vertical` refuses until two verticals clear
    :data:`MIN_PER_VERTICAL`, which is correct and unhelpful on its own:
    "refused" does not tell a photographer whether they are twelve
    corrections away or two hundred.

    Answering that is most of what makes the ask cheap. Nobody labels for
    an afternoon against an unknown target.
    """
    examples = list(examples)
    by_v = split_by_vertical(examples)
    eligible = sorted(v for v, r in by_v.items() if len(r) >= MIN_PER_VERTICAL)
    # v3.99 — corrections are not shoots. The 2026-09 set was 79 and 79,
    # `ready: True`, and one shoot per vertical, so the only comparison it
    # allowed was a fold beside the frames the arm learned from. Same test
    # evaluate_by_vertical uses to decide whether it can hold a shoot out.
    shoots = {v: len({e.run_id for e in r if getattr(e, "run_id", "")})
              for v, r in by_v.items()}
    across = (len(eligible) >= 2
              and all(getattr(e, "run_id", "") for e in examples)
              and any(shoots[v] >= 2 for v in eligible))
    need = {}
    for v, rows in sorted(by_v.items()):
        short = MIN_PER_VERTICAL - len(rows)
        if short > 0:
            need[v] = short
    # The cheapest route to two eligible verticals: finish the two that
    # are closest, not every vertical that exists.
    remaining = sorted(need.values())[:max(0, 2 - len(eligible))]
    return {
        "verticals": {v: len(r) for v, r in sorted(by_v.items())},
        "eligible": eligible,
        "min_per_vertical": MIN_PER_VERTICAL,
        "short_by": need,
        "corrections_to_unblock": sum(remaining),
        "ready": len(eligible) >= 2,
        "shoots": shoots,
        # `ready` says the comparison will run; this says whether it can
        # test a shoot it did not learn from, rather than memory.
        "across_shoots": across,
        # Unlabelled corrections are counted separately. They are not
        # short of anything — nobody recorded which shoot they came from,
        # and labelling more of the same will not help.
        "unlabelled": sum(1 for e in examples
                          if not (getattr(e, "vertical", "") or "").strip()),
    }


def evaluate_by_vertical(examples: Iterable[Example], *,
                         folds: int = 4) -> dict:
    """Does a per-vertical profile beat the pooled one on held-out data?

    Same acceptance shape as :func:`evaluate`, including its refusal: a
    result that cannot be measured says so instead of returning a delta
    of 0.0, because "we could not measure" and "we measured and it makes
    no difference" are opposite findings that used to print identically.

    The refusal here is stricter. Splitting by vertical means each arm
    trains on a fraction of an already-small set, so this declines unless
    at least two verticals clear :data:`MIN_PER_VERTICAL` — with one
    vertical there is nothing to compare, and the pooled profile IS the
    per-vertical profile.
    """
    exs = list(examples)
    by_v = split_by_vertical(exs)
    eligible = {v: r for v, r in by_v.items() if len(r) >= MIN_PER_VERTICAL}
    if len(eligible) < 2:
        return {
            "n": len(exs),
            "verticals_seen": {v: len(r) for v, r in sorted(by_v.items())},
            "verticals_eligible": sorted(eligible),
            "refused": (
                f"need at least two verticals with {MIN_PER_VERTICAL}+ "
                f"corrections each to compare a per-vertical profile "
                f"against the pooled one; got "
                f"{len(eligible)} ({sorted(eligible)})"
            ),
        }

    # v3.99 — whole shoots, as evaluate() has held out since v2.83. The
    # stride below draws a fold from the same afternoon the per-vertical
    # arm learned from, so it measured memory; on the 2026-09 correction
    # set, one shoot per vertical, it could measure nothing else. Grouped
    # when every correction names its shoot and some vertical has two:
    # only those verticals are measured, and the rest are named.
    shoots = {v: {} for v in eligible}
    for v, rows in eligible.items():
        for e in rows:
            shoots[v].setdefault(getattr(e, "run_id", "") or "", []).append(e)
    grouped = (all(e.run_id for e in exs)
               and any(len(s) >= 2 for s in shoots.values()))
    splits = []                              # (vertical, test, train_v, shoot)
    for vert, rows in eligible.items():
        if grouped:
            for key, test in shoots[vert].items():
                train_v = [e for k, g in shoots[vert].items() if k != key for e in g]
                if train_v:
                    splits.append((vert, test, train_v, key))
        elif len(rows) >= folds * 2:
            splits += [(vert, rows[k::folds],
                        [e for i, e in enumerate(rows) if i % folds != k], None)
                       for k in range(folds)]

    pooled_f1, per_f1, pooled_cr, per_cr = [], [], [], []
    for vert, test, train_v, key in splits:
        # The pooled arm trains on everything EXCEPT this fold (the held-out
        # shoot, when grouped) — including the other verticals. That is the
        # comparison that matters: is the other verticals' data helping or
        # diluting. By identity: two corrections with the same stars and
        # verdict compare equal, and `not in` dropped both.
        out_ids = {id(e) for e in test}
        if key is not None:
            out_ids |= {id(e) for e in exs if e.run_id == key}
        pooled = learn_profile([e for e in exs if id(e) not in out_ids])
        # A vertical learned from fewer than MIN_PER_VERTICAL corrections
        # gets no profile of its own (learn_profiles), so it decides with
        # the pooled one, and this arm says so by being identical.
        per = learn_profile(train_v) if len(train_v) >= MIN_PER_VERTICAL else pooled
        for arm, prof, f1s, crs in (("pooled", pooled, pooled_f1, pooled_cr),
                                    ("per", per, per_f1, per_cr)):
            f1s.append(_keep_f1(test, lambda a, p=prof: decide(a, profile=p)))
            crs.append(_cull_recall(test, lambda a, p=prof: decide(a, profile=p)))

    if not pooled_f1:
        return {"n": len(exs),
                "verticals_eligible": sorted(eligible),
                "refused": "no vertical had enough corrections to fold"}
    pooled = sum(pooled_f1) / len(pooled_f1)
    per = sum(per_f1) / len(per_f1)
    cr = [(a, b) for a, b in zip(pooled_cr, per_cr) if a is not None]
    measured = sorted({v for v, *_ in splits})
    return {
        "n": len(exs),
        "verticals_eligible": sorted(eligible),
        "folds": len(pooled_f1),
        "grouped": grouped,
        "pooled_f1": round(pooled, 3),
        "per_vertical_f1": round(per, 3),
        "delta": round(per - pooled, 3),
        # v3.99 — what evaluate() has reported since v3.96 and v3.98: the
        # spread, which shoot each fold held out, and cull recall, because
        # keep-F1 alone rewards a profile that keeps more.
        "fold_deltas": [round(b - a, 3) for a, b in zip(pooled_f1, per_f1)],
        "fold_groups": [(v, k) for v, _t, _tr, k in splits] if grouped else None,
        "fold_n": [len(t) for _v, t, _tr, _k in splits],
        "pooled_cull_recall": round(sum(a for a, _ in cr) / len(cr), 3) if cr else None,
        "per_vertical_cull_recall": round(sum(b for _, b in cr) / len(cr), 3) if cr else None,
        "verticals_measured": measured,
        # Grouped, a vertical shot once has no other shoot of its own kind
        # to learn from, so there is nothing to compare for it.
        "verticals_unmeasured": sorted(set(eligible) - set(measured)),
        "refused": None,
    }


# --------------------------------------------------------------------- #
# Gather from the user's local runs
# --------------------------------------------------------------------- #
def excluded_reason(rec: dict) -> str | None:
    """Why a correction is left out of THIS photographer's taste, or None.

    The one place the rule lives. v3.96 — it used to be inline in
    `gather_examples_from_runs`, which dropped these records without
    counting them, so nothing could say how many there were or measure
    what keeping them would have done.
    """
    # v3.9 — a burst sibling rejected in the compare modal is NOT a
    # photograph the photographer disliked. It is one that lost to a
    # near-identical frame, so its axis stars are nearly the winner's.
    # Averaged into the cull bucket it flattens the very keep-minus-cull
    # gap `axis_weights` is built from, and every use of the compare
    # gesture made the profile slightly worse with nothing saying so.
    #
    # The preference is not discarded — it is kept in its correct form,
    # as a pair, in `pairwise_prefs.jsonl`.
    if rec.get("source") == "compare_rejected":
        return "compare_rejected"
    # v3.29 — a correction another photographer made on their own machine
    # is a real human correction. It is not THIS photographer's taste, and
    # this file exists to learn one person's taste. Multi-shooter sync was
    # pouring a second shooter's judgement into the same profile with
    # nothing marking it, which is v3.9's defect with a different producer.
    if rec.get("synced"):
        return "synced"
    return None


def _fold_records(records, *, include_excluded: bool):
    """filename -> (decision, record), latest line wins; and filename ->
    the reason its latest statement was left out.

    An excluded record still counts as the frame's newest statement:
    a synced record after a local one removes the local label rather
    than leaving it standing (v3.29).
    """
    dec: dict[str, tuple[str, dict]] = {}
    left_out: dict[str, str] = {}
    for r in records:
        if not isinstance(r, dict):
            continue
        f = r.get("filename")
        d = r.get("overall_label") or r.get("decision")
        reason = excluded_reason(r)
        if reason and not include_excluded:
            had = dec.pop(f, None) is not None
            # Left out if it carried a label, or if it removed one: an
            # unlabelled synced record still ends an earlier local label,
            # and that frame is one the "with" half keeps.
            if f and (d in DECISIONS or had):
                left_out[f] = reason
            continue
        if f and d in DECISIONS:
            dec[f] = (d, r)            # latest line wins
            left_out.pop(f, None)
    return dec, left_out


def _count_left_out(excluded, left_out: dict, joined) -> None:
    """Add to the caller's counter the frames the rule left out that would
    otherwise have become examples, so `with = without + left out`."""
    if excluded is not None:
        excluded.update(r for f, r in left_out.items() if f in joined)


def gather_examples_from_runs(runs_root, *, excluded: Counter | None = None,
                              include_excluded: bool = False) -> list:
    """Join ``annotations.jsonl`` (the user's keep/maybe/cull) with
    ``scores.csv`` (``rubric_<axis>_stars``) across every run under
    ``runs_root``.  Latest decision per filename wins.

    ``excluded``, if given, is a Counter that receives one entry per frame
    `excluded_reason` left out, keyed by the reason. ``include_excluded``
    keeps those frames instead, which is the "with" half of the v3.96
    measurement; nothing learns from it by default.
    """
    out: list[Example] = []
    root = Path(runs_root)
    if not root.exists():
        return out
    from pixcull.config import PixCullConfig
    cfg = PixCullConfig.load()
    for ann in root.rglob("annotations.jsonl"):
        scores = ann.parent / "scores.csv"
        if not scores.exists():
            continue
        axmap: dict[str, dict] = {}
        vmap: dict[str, str] = {}
        mmap: dict[str, str] = {}
        try:
            with open(scores, newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    fnk = row.get("filename") or row.get("sha1") or row.get("path")
                    if fnk:
                        axmap[fnk] = {a: _f(row.get(f"rubric_{a}_stars"))
                                      for a in AXES}
                        # v3.8 — the shoot type was already sitting in
                        # this row and was simply not carried across.
                        vmap[fnk] = str(row.get("vertical")
                                        or row.get("scene") or "").strip()
                        mmap[fnk] = machine_verdict(row, cfg)
        except OSError:
            continue
        records = []
        try:
            for line in ann.read_text("utf-8").splitlines():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            continue
        dec, left_out = _fold_records(records, include_excluded=include_excluded)
        _count_left_out(excluded, left_out, axmap)
        for f, (d, _rec) in dec.items():
            if f in axmap:
                # v2.83 — which shoot, so held-out folds can be whole
                # shoots rather than a stride through one afternoon.
                out.append(Example(axes=axmap[f], decision=d,
                                   run_id=str(ann.parent.parent.name),
                                   vertical=vmap.get(f, ""),
                                   machine=mmap.get(f, "")))
    return out


def load_corrections(path, *, excluded: Counter | None = None,
                     include_excluded: bool = False) -> list:
    """Examples from a corrections file: JSONL, one record per photograph,
    each carrying its own ``axes`` (the rubric stars it was scored with)
    beside ``overall_label``, and optionally ``run_id`` and ``vertical``.

    That is the shape of the owner's blind corrections, which were joined
    to their scores by hand and so never lived in an ``annotations.jsonl``
    beside a ``scores.csv``. The same exclusion rule and latest-wins fold
    apply. A labelled record without ``axes`` raises: it is a broken
    join, and dropping it would shrink the sample with nothing saying so.
    """
    records = []
    # utf-8-sig: a file re-saved in a BOM-writing editor still loads.
    with open(path, encoding="utf-8-sig") as fh:
        for no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            if (isinstance(rec, dict)
                    and (rec.get("overall_label") or rec.get("decision"))
                    and not isinstance(rec.get("axes"), dict)):
                raise ValueError(f"{path}:{no}: a labelled record with no axes")
            records.append(rec)
    dec, left_out = _fold_records(records, include_excluded=include_excluded)
    _count_left_out(excluded, left_out, left_out)
    return [Example(axes={a: _f(r["axes"].get(a)) for a in AXES}, decision=d,
                    run_id=str(r.get("run_id") or ""),
                    vertical=str(r.get("vertical") or ""))
            for d, r in dec.values()]


def examples_from_blind_sheet(sheet, scores, *, shoot: str = "") -> list:
    """Examples from a blind sheet (`pixcull m3 label`'s saved verdicts)
    joined to the `scores.csv` of the run that scored those frames.

    v3.98 — the join is within one run on purpose. Filenames are the
    camera's shutter counter, which wraps at 9999, so across shoots the
    same name is often a different photograph: six names in the owner's
    2023 portrait set recur in a 2024 portrait block, different frames a
    year apart. Within one run a name appears once, which is checked.
    Only records the sheet attests as human become examples.
    """
    from pixcull.config import PixCullConfig
    from pixcull.scoring.ground_truth import label_provenance, load_blind_sheet
    cfg = PixCullConfig.load()
    with open(scores, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    names = [r.get("filename") for r in rows]
    if len(set(names)) != len(names):
        raise ValueError(f"{scores} names a file more than once; a blind "
                         f"label cannot be joined to one row of it")
    by_name = {r["filename"]: r for r in rows}
    out = []
    for rec in load_blind_sheet(sheet):
        d = str(rec.get("overall_label") or "").lower()
        row = by_name.get(rec["filename"])
        if row is None or d not in DECISIONS or label_provenance(rec) != "human":
            continue
        out.append(Example(axes={a: _f(row.get(f"rubric_{a}_stars")) for a in AXES},
                           decision=d, run_id=shoot,
                           vertical=str(row.get("vertical") or row.get("scene") or ""),
                           key=f"{rec['filename']}@{row.get('datetime') or ''}",
                           machine=machine_verdict(row, cfg)))
    return out

