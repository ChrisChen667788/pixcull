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
    exs = list(examples)
    if len(exs) < folds * 2:
        return {"n": len(exs), "folds": 0, "generic_f1": 0.0,
                "personal_f1": 0.0, "delta": 0.0}
    gen, per = [], []
    for k in range(folds):
        test = exs[k::folds]
        train = [e for i, e in enumerate(exs) if i % folds != k]
        prof = learn_profile(train)
        gen.append(_keep_f1(test, lambda a: decide(a, profile=None)))
        per.append(_keep_f1(test, lambda a, p=prof: decide(a, profile=p)))
    g = sum(gen) / len(gen)
    pf = sum(per) / len(per)
    return {"n": len(exs), "folds": folds, "generic_f1": round(g, 3),
            "personal_f1": round(pf, 3), "delta": round(pf - g, 3)}


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
        try:
            with open(scores, newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    fnk = row.get("filename") or row.get("sha1") or row.get("path")
                    if fnk:
                        axmap[fnk] = {a: _f(row.get(f"rubric_{a}_stars"))
                                      for a in AXES}
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
                out.append(Example(axes=axmap[f], decision=d))
    return out
