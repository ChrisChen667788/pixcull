"""v0.11-P1-4 — Hard-example mining for active-learning v2.

Why this exists
===============
The original active-learning queue (see ``_serve_next_to_label`` in
``scripts/serve_demo.py``) ranks unlabeled photos by one signal:
*disagreement among model components* (rule vs rescorer vs prob).
That's a strong signal for the current run, but it ignores a much
richer source: **past runs' annotations**, where we can see which
scenes/verticals the model *thinks it knows but doesn't*.

Hard-example mining adds a second priority dimension by scanning
``~/.pixcull/runs/**/annotations.jsonl`` for rows where the recorded
``model_decision`` (or ``rescorer_pred``) differs from the recorded
human decision AND the model was confident.  We aggregate those by
scene + vertical → "scenes the model gets wrong" → boost any current-
run candidate in those scenes.

This is intentionally local-only: we never upload the history to a
cloud aggregator.  Each photographer's hard-example signal stays
on-box, matching the local-first promise.

Design notes
============
* The scan is cached for ``_CACHE_TTL_SEC`` (default 300s) so the
  next-to-label endpoint stays cheap.
* When ``annotations.jsonl`` doesn't carry model_decision (older
  schemas), we fall back to nothing — better silent miss than wrong
  boost.
* No external deps; pure stdlib + pathlib.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# Cache so repeated calls inside a serving session are cheap.
_CACHE_TTL_SEC = 300
_CACHE: dict[str, "HardExampleStats"] = {}


@dataclass(frozen=True)
class Reversal:
    """One past disagreement row."""
    filename: str
    model_decision: str       # what the model said
    human_decision: str       # what the user picked
    confidence: float         # rescorer_prob_keep (0..1)
    scene: str = ""
    vertical: str = ""


@dataclass
class HardExampleStats:
    """Aggregated reversal stats across all of ``runs_root``."""
    reversals: list[Reversal] = field(default_factory=list)
    scenes_with_reversals: dict[str, int] = field(default_factory=dict)
    verticals_with_reversals: dict[str, int] = field(default_factory=dict)
    timestamp_built: float = 0.0

    def boost_for(self, *, scene: str = "", vertical: str = "") -> float:
        """Return a priority-boost score in [0, 1] for a candidate.

        Higher = more boost.  0.0 means "no past reversals in this
        scene/vertical — no extra signal".
        """
        # Most prominent scene/vertical → 1.0; rest scale linearly.
        max_scene = max(self.scenes_with_reversals.values(), default=0)
        max_vert = max(self.verticals_with_reversals.values(), default=0)
        s_score = (self.scenes_with_reversals.get(scene, 0) / max_scene
                   if max_scene > 0 and scene else 0.0)
        v_score = (self.verticals_with_reversals.get(vertical, 0) / max_vert
                   if max_vert > 0 and vertical else 0.0)
        # Take the max — either signal alone is enough to boost
        return max(s_score, v_score)


def _is_high_confidence(prob: float | None) -> bool:
    """Model is confident when prob_keep is near 0 or near 1."""
    if prob is None:
        return False
    return prob >= 0.85 or prob <= 0.15


def _iter_annotations(runs_root: Path) -> Iterable[dict]:
    """Yield every annotation dict under ``runs_root``."""
    if not runs_root.exists():
        return
    for ann_path in runs_root.rglob("annotations.jsonl"):
        try:
            with ann_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(data, dict):
                        yield data
        except OSError:
            continue


def _extract_reversal(row: dict) -> Reversal | None:
    """If this row is a high-confidence model-vs-user disagreement,
    return a Reversal.  Else None.
    """
    fn = row.get("filename")
    if not isinstance(fn, str) or not fn:
        return None
    # Various keys can carry the model prediction depending on which
    # serve_demo version wrote the jsonl:
    model_dec = (
        row.get("model_decision")
        or row.get("rescorer_pred")
        or row.get("decision_at_save")
        or ""
    )
    human_dec = (
        row.get("decision")
        or row.get("overall_label")
        or row.get("decision_human")
        or ""
    )
    if not model_dec or not human_dec:
        return None
    if model_dec == human_dec:
        return None
    prob = row.get("rescorer_prob_keep")
    try:
        prob_f = float(prob) if prob is not None else None
    except (TypeError, ValueError):
        prob_f = None
    if not _is_high_confidence(prob_f):
        return None
    return Reversal(
        filename=fn,
        model_decision=str(model_dec),
        human_decision=str(human_dec),
        confidence=prob_f or 0.0,
        scene=str(row.get("scene", "")),
        vertical=str(row.get("vertical", "") or row.get("scene", "")),
    )


def build_stats(runs_root: Path) -> HardExampleStats:
    """Walk ``runs_root`` once + aggregate."""
    stats = HardExampleStats(timestamp_built=time.time())
    for row in _iter_annotations(runs_root):
        rv = _extract_reversal(row)
        if rv is None:
            continue
        stats.reversals.append(rv)
        if rv.scene:
            stats.scenes_with_reversals[rv.scene] = (
                stats.scenes_with_reversals.get(rv.scene, 0) + 1
            )
        if rv.vertical:
            stats.verticals_with_reversals[rv.vertical] = (
                stats.verticals_with_reversals.get(rv.vertical, 0) + 1
            )
    return stats


def get_stats(runs_root: Path, ttl_sec: int = _CACHE_TTL_SEC) -> HardExampleStats:
    """Cached entry point.  Returns the per-runs_root stats, building
    them on first call and re-using the result for ``ttl_sec`` seconds.
    """
    key = str(runs_root.resolve())
    cached = _CACHE.get(key)
    if cached is not None and (time.time() - cached.timestamp_built) < ttl_sec:
        return cached
    stats = build_stats(runs_root)
    _CACHE[key] = stats
    return stats


def clear_cache() -> None:
    """Drop the cached stats — tests + admin "rebuild" knob."""
    _CACHE.clear()
