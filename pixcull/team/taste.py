"""v0.10-P1-1 — team taste profile aggregation.

Each user in a studio accumulates an individual taste profile
via the P-UX-12 per-user-preferences endpoint (stored as
``users/<uid>/preferences.json`` with axis weights + cull-reason
frequencies derived from their personal annotation history).

This module:

  * Loads every user's preferences.json
  * Aggregates them into a "studio baseline" (mean / median /
    stddev per axis)
  * Computes discrepancy — per-user deviation from the team
    baseline, surfaced as "compositional weight: 小李 +0.18 vs
    team mean" so a studio lead can spot drift / specialisation

The output drives the /admin/team_taste page (added in the same
slice) and feeds the conflict-resolution UI's "head-shooter
wisdom" tooltip when two team members diverge.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


# The 6 canonical rubric axes — same ones the rest of the
# pipeline writes to scores.csv / annotations.jsonl.  Pinned here
# so the team baseline stays comparable across releases even if
# the underlying eval pipeline grows new metrics.
PROFILE_AXES = (
    "technical", "subject", "composition",
    "light",     "moment",  "aesthetic",
)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if not math.isnan(x) else default
    except (TypeError, ValueError):
        return default


def load_user_taste(user_pref_path: Path) -> dict[str, float] | None:
    """Load one user's axis-weight vector from their preferences.json.

    Returns None when the file is missing / unreadable / missing
    the ``axis_weights`` block.  Format of axis_weights is per
    P-UX-12: ``{axis_name: float_weight}`` normalised so the
    weights sum to 1.0; we don't re-normalise here — that's the
    caller's job.
    """
    if not user_pref_path.exists():
        return None
    try:
        data = json.loads(user_pref_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    weights = data.get("axis_weights") if isinstance(data, dict) else None
    if not isinstance(weights, dict):
        return None
    out: dict[str, float] = {}
    for axis in PROFILE_AXES:
        if axis in weights:
            out[axis] = _safe_float(weights[axis])
    return out or None


def aggregate_taste(
    user_tastes: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """Roll up per-user axis weights into team-level stats.

    Input: {user_id: {axis: weight, ...}, ...}
    Output: {axis: {mean, median, stddev, n}, ...}

    Empty input → empty output (no NaN propagation).  Axes that
    no user weighted in get omitted from the output entirely.
    """
    if not user_tastes:
        return {}
    per_axis: dict[str, list[float]] = {a: [] for a in PROFILE_AXES}
    for taste in user_tastes.values():
        if not isinstance(taste, dict):
            continue
        for axis in PROFILE_AXES:
            if axis in taste:
                per_axis[axis].append(_safe_float(taste[axis]))
    stats: dict[str, dict[str, float]] = {}
    for axis, vals in per_axis.items():
        if not vals:
            continue
        n = len(vals)
        mean = sum(vals) / n
        sorted_vals = sorted(vals)
        if n % 2 == 1:
            median = sorted_vals[n // 2]
        else:
            median = (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2
        var = sum((v - mean) ** 2 for v in vals) / n
        stats[axis] = {
            "mean":   mean,
            "median": median,
            "stddev": math.sqrt(var),
            "n":      n,
        }
    return stats


def discrepancy_report(
    user_tastes: dict[str, dict[str, float]],
    baseline: dict[str, dict[str, float]] | None = None,
) -> list[dict]:
    """Return a flat list of per-user-per-axis deviations from
    the team baseline.

    Each entry shape:
      {
        "user_id":  str,
        "axis":     str,
        "weight":   float,    # this user's weight
        "team":     float,    # team mean
        "delta":    float,    # weight − team
        "stddev_n": float,    # delta / team stddev (z-score; 0 when no σ)
      }

    Sorted by |stddev_n| descending so the most-discrepant pairs
    bubble to the top — exactly what the studio lead wants to see
    on /admin/team_taste.

    ``baseline`` defaults to ``aggregate_taste(user_tastes)``;
    callers can pass a previously-computed one to avoid recomputing.
    """
    base = baseline if baseline is not None else aggregate_taste(user_tastes)
    if not base:
        return []
    rows: list[dict] = []
    for uid, taste in user_tastes.items():
        if not isinstance(taste, dict):
            continue
        for axis in PROFILE_AXES:
            if axis not in taste or axis not in base:
                continue
            team_mean   = base[axis]["mean"]
            team_stddev = base[axis]["stddev"]
            w = _safe_float(taste[axis])
            delta = w - team_mean
            z = (delta / team_stddev) if team_stddev > 1e-9 else 0.0
            rows.append({
                "user_id":  uid,
                "axis":     axis,
                "weight":   w,
                "team":     team_mean,
                "delta":    delta,
                "stddev_n": z,
            })
    rows.sort(key=lambda r: abs(r["stddev_n"]), reverse=True)
    return rows
