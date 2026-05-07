"""Runtime inference for the V1.1 learned keep/maybe rescorer.

This is the library-layer counterpart to ``scripts/train_rescorer.py``.
The trainer is a standalone script — it produces a joblib artifact with
the fitted sklearn pipeline + the feature column list. This module only
knows how to *load* that artifact and score one row at a time, so it can
be called from inside ``pipeline/orchestrator.py`` without pulling sklearn
into the critical path until the user actually flips the mode on.

Design constraints:

* **Schema derived from the artifact**, not duplicated here. The artifact
  stores ``feature_cols`` (numeric + ``__missing`` indicators + categorical),
  which means adding a new feature to the trainer doesn't require a matching
  edit here — as long as the row dict carries the raw column, we'll find it.

* **Graceful failure**: if the artifact can't be loaded (file missing, numpy
  version drift, sklearn version drift), ``load_rescorer`` returns ``None``
  and the pipeline runs rule-only. Loud on startup (stderr warning), silent
  at inference time.

* **No cull scoring**: the rescorer is a keep/maybe binary head. Rows that
  the rule stack already called CULL are never sent through — that guarantee
  is ``decide()``'s job; this module just refuses to predict on them if
  asked, and returns ``None``.

Shadow-mode workflow (V1.2 staging):

    artifact = load_rescorer(config.rescorer.model_path)
    for row in rows:
        decision, reasons = decide(row.score_final, row.flags, config, ...)
        if decision is not Decision.CULL and artifact is not None:
            pred = score_row(artifact, row.to_dict())  # dict | None
            row["rescorer_pred"] = pred["pred"]
            row["rescorer_prob_keep"] = pred["prob_keep"]

When mode flips to "adjudicate", ``decide()`` itself reads these fields and
may override a rule-maybe → keep when ``prob_keep`` is high enough.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class RescorerArtifact:
    """Lightweight wrapper over the joblib dict — lets callers rely on types
    instead of ``artifact["pipeline"]`` everywhere."""

    pipeline: Any  # sklearn.pipeline.Pipeline
    feature_cols: list[str]
    model_name: str
    train_rows: int
    cv_metrics: dict
    source_path: Path

    # Cached list of base columns that need a ``__missing`` indicator sibling
    # at inference — derived from feature_cols so it auto-tracks new missing
    # indicators the trainer adds.
    @property
    def missing_indicator_bases(self) -> list[str]:
        return [c[: -len("__missing")] for c in self.feature_cols
                if c.endswith("__missing")]


# V14.1 — process-local cache for the binary rescorer too. Same idea
# as the axis cache: keyed by (path, mtime) so retraining transparently
# busts old entries. Saves the joblib.load() round-trip on every
# pipeline call (~50-200 ms depending on model size).
_RESCORER_CACHE: dict[tuple, "RescorerArtifact"] = {}


def load_rescorer(path: Path | str | None) -> RescorerArtifact | None:
    """Load the joblib artifact; return ``None`` on any failure.

    Failures are logged to stderr so a pipeline run with a broken rescorer
    clearly says *why* it fell back to rule-only — silent regressions are
    the worst thing that can happen to a learned-head integration.

    V14.1: cached by (path, mtime). Retraining bumps mtime, evicting.
    """
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        print(f"[rescorer] model file not found: {p} — running rule-only",
              file=sys.stderr)
        return None
    try:
        mtime = p.stat().st_mtime_ns
    except OSError:
        mtime = 0
    key = (str(p), mtime)
    cached = _RESCORER_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        import joblib  # noqa: WPS433 — lazy to keep cold-start light
        obj = joblib.load(p)
    except Exception as exc:  # noqa: BLE001
        # joblib/numpy/sklearn version drift most commonly lands here; we
        # want the full class to help the user diagnose, not a generic msg.
        print(f"[rescorer] failed to load {p}: {type(exc).__name__}: {exc} "
              f"— running rule-only", file=sys.stderr)
        return None

    try:
        artifact = RescorerArtifact(
            pipeline=obj["pipeline"],
            feature_cols=list(obj["feature_cols"]),
            model_name=str(obj.get("model_name", "unknown")),
            train_rows=int(obj.get("train_rows", 0)),
            cv_metrics=dict(obj.get("cv_metrics", {})),
            source_path=p,
        )
    except (KeyError, TypeError) as exc:
        print(f"[rescorer] artifact at {p} is malformed "
              f"(expected a dict with 'pipeline', 'feature_cols', ...): {exc}",
              file=sys.stderr)
        return None

    # Evict any older entries for this same path
    for k in list(_RESCORER_CACHE.keys()):
        if k[0] == str(p) and k != key:
            _RESCORER_CACHE.pop(k, None)
    _RESCORER_CACHE[key] = artifact
    return artifact


def score_row(
    artifact: RescorerArtifact,
    row: dict,
    *,
    maybe_upper: float = 0.5,
) -> dict | None:
    """Predict keep/maybe + P(keep) for one per-image record.

    ``row`` is the dict built by ``pipeline.worker.analyze_one`` plus the
    fusion scores attached by the orchestrator — i.e. every field the rule
    stack sees. We don't require every column; missing features are handled
    by the pipeline's imputer at fit time.

    Returns ``{"pred": "keep"|"maybe", "prob_keep": float}``, or ``None`` on
    any exception (malformed row, pipeline transform failure, etc.). Callers
    treat ``None`` as "rescorer had no opinion, keep the rule's decision."

    ``maybe_upper`` is the decision threshold on ``P(keep)``: strictly above
    → keep, at-or-below → maybe. 0.5 matches the trainer's default; callers
    in adjudicate-mode can use asymmetric thresholds via ``prob_keep``
    directly without going through ``pred``.
    """
    try:
        # Build a single-row DataFrame with __missing indicators derived
        # straight from the artifact's column list. Reindex() fills any
        # absent column with NaN — the trainer's imputer handles those.
        data: dict[str, Any] = dict(row)
        for base in artifact.missing_indicator_bases:
            data[f"{base}__missing"] = int(base not in row
                                           or _is_nan(row.get(base)))
        df = pd.DataFrame([data]).reindex(columns=artifact.feature_cols)
        prob_keep = float(artifact.pipeline.predict_proba(df)[0, 1])
    except Exception as exc:  # noqa: BLE001
        # Don't let a single weird row take down the whole pipeline run —
        # log once and let the caller fall back to rule-only.
        print(f"[rescorer] scoring failed for "
              f"{row.get('filename', '<unknown>')}: {type(exc).__name__}: "
              f"{exc}", file=sys.stderr)
        return None

    return {
        "pred": "keep" if prob_keep > maybe_upper else "maybe",
        "prob_keep": prob_keep,
    }


def _is_nan(value: Any) -> bool:
    """Robust NaN check — ``np.isnan`` raises on strings/None."""
    if value is None:
        return True
    try:
        return bool(np.isnan(value))
    except (TypeError, ValueError):
        return False
