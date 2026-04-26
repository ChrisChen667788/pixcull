"""V2.1 multi-head rescorer: one regression model per rubric axis.

Why this isn't just an extension of rescorer.py
================================================
The V1.1 rescorer (``rescorer.py``) is a binary keep/maybe classifier
trained on a single ``manual_label`` column. That topology hits a
ceiling around AUC 0.67 on small label sets because one bit of signal
per image isn't enough.

The V2.0 rubric annotation system collects 6 stars + rationale per
image. To consume that signal we need a different topology: one
model per axis, each predicting 1-5★ as a regression target.
Six small models share the same feature inputs but each learns a
narrower function. Empirically (e.g. RLHF reward modeling) this
extracts roughly 3-5x more signal than a single classifier on the
same dataset.

Topology choice — regression, not classification
------------------------------------------------
We deliberately use ``HistGradientBoostingRegressor`` instead of
treating stars as a 5-class classifier, because:

* The ★ axis is ordered: 4★ is closer to 5★ than to 1★. A classifier
  doesn't know that and fights itself for no reason.
* MSE is what the user actually wants minimized — a 4★ predicted as
  3★ is annoying; predicted as 1★ is broken.
* Regression handles continuous auto-rubric inputs (e.g. 3.97★ from
  decompose_row) without fake-bucketing them.

Storage layout
--------------
``models/rescorer_axis_<name>.joblib``  one file per axis, each
                                         containing a sklearn Pipeline.
``models/rescorer_axis_meta.json``      training metadata (axes covered,
                                         row counts, CV R², feature list).

A run that has all 6 files trained constitutes a complete V2.1 model.
Partial training (e.g. only ``aesthetic`` after a quick correction
session) is allowed — axes without a model fall through to V1's
existing scoring.

Inference
---------
``load_axis_rescorers(model_dir)``   returns dict[axis_name, AxisModel]
                                      empty dict if nothing's trained.

``score_row_per_axis(models, row)``  one inference call per axis;
                                      returns dict[axis_name, stars].
                                      Failures are silently skipped per
                                      axis — partial output is valid.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from pixcull.scoring.rubric import RUBRIC_AXES


@dataclass
class AxisModel:
    """One axis worth of rescorer state."""
    pipeline: Any                  # sklearn.pipeline.Pipeline
    feature_cols: list[str]        # same schema across all axes
    cv_r2: float                   # 5-fold mean R² on training data
    cv_mae: float                  # 5-fold mean absolute error in stars
    train_rows: int                # rows the model was fit on
    target_axis: str               # redundant but useful for sanity
    n_human_targets: int = 0       # how many were human-rated vs auto

    @property
    def missing_indicator_bases(self) -> list[str]:
        return [c[: -len("__missing")] for c in self.feature_cols
                if c.endswith("__missing")]


def axis_model_path(model_dir: Path | str, axis: str) -> Path:
    """Where one axis's joblib lives. Single source of truth."""
    return Path(model_dir) / f"rescorer_axis_{axis}.joblib"


def axis_meta_path(model_dir: Path | str) -> Path:
    return Path(model_dir) / "rescorer_axis_meta.json"


def load_axis_rescorers(model_dir: Path | str) -> dict[str, AxisModel]:
    """Load every per-axis joblib found under ``model_dir``.

    Returns an empty dict — not None — if nothing's trained yet, so
    callers can do ``if axis_models:`` without a None check. Partial
    training is supported: missing axes just don't appear in the dict.
    Loud on stderr for any failure so silent regressions are obvious.
    """
    out: dict[str, AxisModel] = {}
    md = Path(model_dir)
    if not md.exists():
        return out
    for axis_def in RUBRIC_AXES:
        p = axis_model_path(md, axis_def.name)
        if not p.exists():
            continue
        try:
            import joblib
            obj = joblib.load(p)
        except Exception as exc:  # noqa: BLE001
            print(f"[axis_rescorer] failed to load {p}: "
                  f"{type(exc).__name__}: {exc} — axis '{axis_def.name}' "
                  f"will fall through to auto rubric",
                  file=sys.stderr)
            continue
        try:
            out[axis_def.name] = AxisModel(
                pipeline=obj["pipeline"],
                feature_cols=list(obj["feature_cols"]),
                cv_r2=float(obj.get("cv_r2", 0.0)),
                cv_mae=float(obj.get("cv_mae", 0.0)),
                train_rows=int(obj.get("train_rows", 0)),
                target_axis=str(obj.get("target_axis", axis_def.name)),
                n_human_targets=int(obj.get("n_human_targets", 0)),
            )
        except (KeyError, TypeError) as exc:
            print(f"[axis_rescorer] artifact at {p} malformed: {exc}",
                  file=sys.stderr)
            continue
    return out


def score_row_per_axis(
    models: dict[str, AxisModel],
    row: dict,
) -> dict[str, float]:
    """Score one row against every loaded axis model.

    Returns ``{axis_name: predicted_stars}`` clamped to [1.0, 5.0].
    Axes whose model fails or isn't loaded are simply absent from the
    output — caller should fall back to auto rubric for those.
    """
    out: dict[str, float] = {}
    for name, model in models.items():
        try:
            data: dict[str, Any] = dict(row)
            # Mirror the same __missing indicator handling V1.1 uses
            for base in model.missing_indicator_bases:
                data[f"{base}__missing"] = int(
                    base not in row or _is_nan(row.get(base))
                )
            df = pd.DataFrame([data]).reindex(columns=model.feature_cols)
            stars = float(model.pipeline.predict(df)[0])
            out[name] = max(1.0, min(5.0, stars))
        except Exception as exc:  # noqa: BLE001
            print(f"[axis_rescorer] {name} prediction failed for "
                  f"{row.get('filename', '?')}: {type(exc).__name__}: "
                  f"{exc}", file=sys.stderr)
            continue
    return out


# ---------------------------------------------------------------------------
# Aggregation: 6 axis stars → overall keep/maybe/cull. Kept here (not
# in decision.py) because it's V2.1-specific and will likely evolve as
# we collect more annotation data. The thresholds below are starting
# points the team should tune against eval_findings.md once V2.1 has
# real golden-set numbers.
# ---------------------------------------------------------------------------

def axes_to_overall(
    axes_stars: dict[str, float | None],
    *,
    keep_min_stars: float = 4.0,
    cull_max_stars: float = 2.0,
) -> tuple[str, str]:
    """Reduce per-axis stars to a single keep/maybe/cull verdict.

    Logic (intentionally simple — let humans see the decomposition,
    let the rule be obvious):
      * Any axis ≤ cull_max_stars → cull (a single fatal flaw is
        enough; a 1★ technical kills any photo regardless of light)
      * All axes ≥ keep_min_stars (or unrated) → keep
      * Otherwise → maybe

    Returns ``(decision, rationale)`` where rationale names the
    weakest axis(es), in Chinese for the demo UI's display.
    """
    from pixcull.scoring.rubric import get_axis

    # Filter to only axes that have predictions
    rated = {k: v for k, v in axes_stars.items() if v is not None}
    if not rated:
        return "maybe", "无可用评分"

    # Find weakest
    weakest_axis = min(rated, key=rated.get)  # type: ignore[arg-type]
    weakest_stars = rated[weakest_axis]
    strongest_axis = max(rated, key=rated.get)  # type: ignore[arg-type]

    if weakest_stars <= cull_max_stars:
        return "cull", (
            f"{get_axis(weakest_axis).label_zh} {weakest_stars:.1f}★ "
            f"(致命缺陷)"
        )

    if all(v >= keep_min_stars for v in rated.values()):
        return "keep", (
            f"全轴 ≥ {keep_min_stars}★(最弱"
            f"{get_axis(weakest_axis).label_zh} {weakest_stars:.1f}★)"
        )

    weak = [
        get_axis(name).label_zh
        for name, v in rated.items() if v < 3.0
    ]
    if weak:
        return "maybe", "偏弱: " + " · ".join(weak)
    return "maybe", "中间档(无明显短板也无亮点)"


def _is_nan(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(np.isnan(value))
    except (TypeError, ValueError):
        return False
