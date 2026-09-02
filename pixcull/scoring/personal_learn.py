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
    return {
        "user_id": "local",
        "total_human_annotations": len(exs),
        "scene_decision_counts": {"all": counts},
        "avg_rubric_when": avg,
    }


def learn_profile(examples: Iterable[Example]) -> PersonalProfile:
    """Fit a PersonalProfile from local corrections (reuses the cloud-path
    aggregation math; the input is just gathered locally instead)."""
    return profile_from_preferences(aggregate_prefs(examples))


def axis_weights(profile: PersonalProfile) -> dict:
    """Per-axis weight = how much that axis separates THIS user's keep
    from cull (the keep-mean − cull-mean gap), normalised & non-negative.
    Falls back to equal weights when the gaps are uninformative."""
    gaps = {a: max(0.0, profile.axis_keep_means.get(a, 0.0)
                   - profile.axis_cull_means.get(a, 0.0)) for a in AXES}
    total = sum(gaps.values())
    if total <= 1e-9:
        return {a: 1.0 / len(AXES) for a in AXES}
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
        splits = [(g, [e for k, v in groups.items() if k != key for e in v])
                  for key, g in groups.items()]
        splits = [(t, tr) for t, tr in splits if t and tr]
    else:
        splits = [(exs[k::folds],
                   [e for i, e in enumerate(exs) if i % folds != k])
                  for k in range(folds)]

    if not splits:
        return {"n": len(exs), "folds": 0, "grouped": grouped,
                "refused": "every correction came from a single shoot, so "
                           "there is no unseen shoot to predict"}

    gen, per = [], []
    for test, train in splits:
        prof = learn_profile(train)
        gen.append(_keep_f1(test, lambda a: decide(a, profile=None)))
        per.append(_keep_f1(test, lambda a, p=prof: decide(a, profile=p)))
    g = sum(gen) / len(gen)
    pf = sum(per) / len(per)
    return {"n": len(exs), "folds": len(splits), "grouped": grouped,
            "n_runs": len(groups),
            "generic_f1": round(g, 3), "personal_f1": round(pf, 3),
            "delta": round(pf - g, 3), "refused": None}


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

    pooled_f1, per_f1 = [], []
    for vert, rows in eligible.items():
        if len(rows) < folds * 2:
            continue
        for k in range(folds):
            test = rows[k::folds]
            train_v = [e for i, e in enumerate(rows) if i % folds != k]
            if not test or not train_v:
                continue
            # The pooled arm trains on everything EXCEPT this fold —
            # including the other verticals. That is the comparison that
            # matters: is the other verticals' data helping or diluting.
            train_all = [e for e in exs if e not in test]
            pooled_f1.append(_keep_f1(
                test, lambda a, p=learn_profile(train_all): decide(a, profile=p)))
            per_f1.append(_keep_f1(
                test, lambda a, p=learn_profile(train_v): decide(a, profile=p)))

    if not pooled_f1:
        return {"n": len(exs),
                "verticals_eligible": sorted(eligible),
                "refused": "no vertical had enough corrections to fold"}
    pooled = sum(pooled_f1) / len(pooled_f1)
    per = sum(per_f1) / len(per_f1)
    return {
        "n": len(exs),
        "verticals_eligible": sorted(eligible),
        "folds": len(pooled_f1),
        "pooled_f1": round(pooled, 3),
        "per_vertical_f1": round(per, 3),
        "delta": round(per - pooled, 3),
        "refused": None,
    }


# --------------------------------------------------------------------- #
# Gather from the user's local runs
# --------------------------------------------------------------------- #
def gather_examples_from_runs(runs_root) -> list:
    """Join ``annotations.jsonl`` (the user's keep/maybe/cull) with
    ``scores.csv`` (``rubric_<axis>_stars``) across every run under
    ``runs_root``.  Latest decision per filename wins."""
    out: list[Example] = []
    root = Path(runs_root)
    if not root.exists():
        return out
    for ann in root.rglob("annotations.jsonl"):
        scores = ann.parent / "scores.csv"
        if not scores.exists():
            continue
        axmap: dict[str, dict] = {}
        vmap: dict[str, str] = {}
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
        except OSError:
            continue
        dec: dict[str, str] = {}
        try:
            for line in ann.read_text("utf-8").splitlines():
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                f = r.get("filename")
                d = r.get("overall_label") or r.get("decision")
                if f and d in DECISIONS:
                    dec[f] = d            # latest line wins
        except OSError:
            continue
        for f, d in dec.items():
            if f in axmap:
                # v2.83 — which shoot, so held-out folds can be whole
                # shoots rather than a stride through one afternoon.
                out.append(Example(axes=axmap[f], decision=d,
                                   run_id=str(ann.parent.parent.name),
                                   vertical=vmap.get(f, "")))
    return out
