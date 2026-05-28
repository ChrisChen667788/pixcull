"""v0.13-P2-1 — Per-photographer preferred-axes profile.

Some rubric axes are not universally meaningful:
  * Documentary photographers don't optimise for "composition" the
    same way wedding portrait photographers do
  * Fine-art / street photographers explicitly *reject* the
    "sharpness" axis (movement blur is the point)
  * Astrophotographers don't care about "subject"

This module lets a user mute axes — they continue to be computed
under the hood, but the rescorer's score_final reweights to ignore
them.  Same persistence pattern as ``pixcull/shortcuts.py``:
``~/.pixcull/preferred_axes.json``.

Schema
======

    {
      "version": 1,
      "muted": ["sharpness"],
      "weight_boost": {"moment": 1.4}
    }

* ``muted`` — list of axis IDs treated as if absent
* ``weight_boost`` — multiplicative weight applied during fusion
  (default for every axis is 1.0; clamp to [0.1, 3.0])

Public API
==========

  load() → AxisPrefs
  save(prefs) → None
  reweight(axis_scores: dict[axis, float]) → dict[axis, float]
      Applies mute + boost to a per-axis score dict.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


SCHEMA_VERSION = 1

AXES = (
    "technical", "subject", "composition",
    "light", "moment", "aesthetic",
)

_WEIGHT_MIN = 0.1
_WEIGHT_MAX = 3.0


@dataclass
class AxisPrefs:
    muted: list[str] = field(default_factory=list)
    weight_boost: dict[str, float] = field(default_factory=dict)

    def is_muted(self, axis: str) -> bool:
        return axis in self.muted

    def boost_for(self, axis: str) -> float:
        w = self.weight_boost.get(axis, 1.0)
        return max(_WEIGHT_MIN, min(_WEIGHT_MAX, float(w)))


def prefs_path() -> Path:
    if os.name == "posix":
        base = Path.home() / "Library" / "Application Support" / "PixCull"
    else:
        base = Path.home() / ".pixcull"
    base.mkdir(parents=True, exist_ok=True)
    return base / "preferred_axes.json"


def load() -> AxisPrefs:
    """Read user's saved prefs; return defaults on miss / corruption."""
    p = prefs_path()
    if not p.exists():
        return AxisPrefs()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AxisPrefs()
    if not isinstance(data, dict):
        return AxisPrefs()
    if data.get("version") != SCHEMA_VERSION:
        return AxisPrefs()
    muted_raw = data.get("muted", [])
    muted = [str(x) for x in muted_raw if str(x) in AXES] \
        if isinstance(muted_raw, list) else []
    boost_raw = data.get("weight_boost", {})
    boost: dict[str, float] = {}
    if isinstance(boost_raw, dict):
        for k, v in boost_raw.items():
            try:
                kf = float(v)
            except (TypeError, ValueError):
                continue
            if k in AXES:
                boost[k] = kf
    return AxisPrefs(muted=muted, weight_boost=boost)


def save(prefs: AxisPrefs) -> None:
    """Persist via tmp-file atomic rename."""
    p = prefs_path()
    body = json.dumps({
        "version": SCHEMA_VERSION,
        "muted": list(prefs.muted),
        "weight_boost": dict(prefs.weight_boost),
    }, indent=2, ensure_ascii=False)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(p)


def reweight(axis_scores: dict[str, float],
             prefs: AxisPrefs | None = None) -> dict[str, float]:
    """Apply mute + boost to a per-axis score dict.  Returns a new
    dict; doesn't mutate the input.

    Muted axes are removed.  Surviving axes get their boost factor
    applied.  Caller is responsible for re-normalising downstream
    if the fusion expects unit-sum weights.
    """
    if prefs is None:
        prefs = load()
    out: dict[str, float] = {}
    for ax, sc in axis_scores.items():
        if prefs.is_muted(ax):
            continue
        try:
            sc_f = float(sc)
        except (TypeError, ValueError):
            continue
        out[ax] = sc_f * prefs.boost_for(ax)
    return out


def reset_to_defaults() -> AxisPrefs:
    prefs = AxisPrefs()
    save(prefs)
    return prefs
