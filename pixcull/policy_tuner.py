"""V17.4 — automated per-vertical policy tuning.

The user collects ~25-30 good + 25-30 bad reference shots per vertical
via the V17.0/1 sample bank. This module:

  1. Runs the (rule-stack only) analysis on those samples once.
  2. Treats good→keep / bad→cull as binary truth.
  3. Grid-searches keep_min_delta + cull_max_delta to maximise F1
     (positive class = "kept": photographer wants to see this image
     again, i.e. pipeline didn't auto-cull it).
  4. Returns suggested deltas + before-vs-after metrics + the full
     grid so callers can render a heat-map / let users see the
     trade-off curve.
  5. The serve_demo endpoint persists the suggestion to
     ``policy_override.json`` next to the sample dirs; ``decide()``
     reads from there via ``get_effective_policy``.

Design choices
--------------
* Rule-stack only — we run analyze_one + fuse_score, then call the
  inline ``_apply_thresholds`` instead of the full ``decide()``.
  This is deliberate: V17.4 tunes the THRESHOLD layer; the rescorer /
  VLM / meta-judge layers add noise that would obscure the signal
  here. They get re-tuned in V17.5+.
* "Kept" = pred ∈ {keep, maybe} — maybe shouldn't auto-cull a good
  candidate, so it counts as kept for the F1 calculation. This
  reflects how photographers use the tool: they review maybe; they
  don't review cull.
* Search range: ±0.10 in 0.02 steps = 11 values per axis = 121
  combinations. Cheap once samples are pre-analyzed (~1 ms / combo).
* Tolerated_flags grid is NOT searched — the curated defaults from
  V17.2 encode genre intent, swapping them programmatically risks
  losing semantic correctness. V17.5 may do that.

Output: ``TuneResult`` dataclass — JSON-serialisable via dataclasses.asdict.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pixcull import verticals as vmod
from pixcull.config import PixCullConfig
from pixcull.scoring.decision import Decision


# ---------------------------------------------------------------------------
# Grid + decision helpers
# ---------------------------------------------------------------------------

# Search range for the deltas, in score-space units (0..1).
# ±0.10 covers "very lenient" ↔ "very strict"; outside this band we'd
# be redesigning the rule stack, not tuning.
_DELTA_GRID: tuple[float, ...] = tuple(round(-0.10 + i * 0.02, 4)
                                         for i in range(11))


# Same hard-cull set as ``decide()`` — kept here so tuner is
# self-contained and won't break if decide() is refactored. Tests
# pin this against decide()'s set so they don't drift apart.
_HARD_CULL_FLAGS: frozenset[str] = frozenset({
    "closed_eyes",
    "motion_blur_on_face",
    "severely_overexposed",
    "no_clear_subject",
    "severely_blurry",
})

# Mirror of decide()'s scene-tolerant exemptions.
_TINY_SUBJECT_TOLERANT: frozenset[str] = frozenset({"landscape", "street",
                                                     "architecture"})
_BLUR_TOLERANT: frozenset[str] = frozenset({"landscape"})


def _apply_thresholds(
    final_score: float,
    flags: list[str],
    scene: str | None,
    *,
    keep_min: float,
    cull_max: float,
    tolerated_flags: frozenset[str] = frozenset(),
) -> Decision:
    """Threshold-only decision logic — minimal mirror of ``decide()``.

    Same hard-cull behavior + scene exemptions, but accepts explicit
    keep_min / cull_max / tolerated_flags so the grid-search can
    iterate them without monkey-patching the registry.
    """
    hard_cull = _HARD_CULL_FLAGS - frozenset(tolerated_flags)
    if scene in _TINY_SUBJECT_TOLERANT:
        hard_cull = hard_cull - {"no_clear_subject"}
    if scene in _BLUR_TOLERANT:
        hard_cull = hard_cull - {"severely_blurry"}
    if set(flags) & hard_cull:
        return Decision.CULL
    if final_score >= keep_min:
        return Decision.KEEP
    if final_score <= cull_max:
        return Decision.CULL
    return Decision.MAYBE


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def binary_metrics(predictions: list[Decision], truths: list[str]) -> dict:
    """F1 + precision + recall for the "kept" class.

    Conventions:
      * ``truth == "good"`` → photographer's reference of a worth-keeping shot
      * ``truth == "bad"``  → reference of a clearly-cull shot
      * ``pred ∈ {KEEP, MAYBE}`` → pipeline did NOT auto-cull (= "kept")
      * ``pred == CULL`` → auto-culled

    F1 calculated on the "kept" positive class — the metric a
    photographer cares about: how often does the pipeline agree this
    is worth a second look?
    """
    if len(predictions) != len(truths):
        raise ValueError("predictions / truths length mismatch")
    tp = fp = tn = fn = 0
    for pred, truth in zip(predictions, truths):
        kept = pred is not Decision.CULL
        is_good = (truth == "good")
        if kept and is_good:
            tp += 1
        elif kept and not is_good:
            fp += 1
        elif (not kept) and is_good:
            fn += 1
        else:
            tn += 1
    n = tp + fp + tn + fn
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) else 0.0)
    return {
        "f1":         round(f1, 4),
        "precision":  round(precision, 4),
        "recall":     round(recall, 4),
        "accuracy":   round((tp + tn) / max(1, n), 4),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "n": n,
    }


# ---------------------------------------------------------------------------
# Sample analysis — runs the rule stack on each good/bad sample
# ---------------------------------------------------------------------------

@dataclass
class SamplePoint:
    """One analyzed sample: stable enough to grid-search over without
    re-running the (slow) detector pipeline for each candidate delta."""
    filename:    str
    bucket:      str       # "good" or "bad"
    final_score: float     # rule-stack fused final, 0..1
    flags:       list[str]
    scene:       str | None


def analyze_samples(key: str, *,
                     progress_cb=None) -> list[SamplePoint]:
    """Run analyze_one + fuse_score on every sample of a vertical.

    Skips the orchestrator's clustering / rescorer / VLM / meta-judge
    layers — V17.4 tunes the threshold rule stack only.
    """
    if vmod.get_vertical(key) is None:
        raise ValueError(f"unknown vertical: {key}")
    from pixcull.pipeline.worker import analyze_one
    from pixcull.scoring.fusion import fuse_score

    config = PixCullConfig.load()
    out: list[SamplePoint] = []
    for bucket in ("good", "bad"):
        bdir = vmod.vertical_root(key) / bucket
        files = sorted(bdir.iterdir(), key=lambda p: p.name)
        for i, p in enumerate(files):
            if not p.is_file():
                continue
            try:
                row = analyze_one(p)
            except Exception:  # noqa: BLE001
                # A single corrupt sample shouldn't sink the whole
                # tuning run. Skip + report via progress_cb.
                row = None
            if row is None:
                if progress_cb:
                    progress_cb(len(out), -1,
                                  f"skip {p.name}: analyze failed")
                continue
            scene = str(row.get("scene") or "")
            flags = list(row.get("flags") or [])
            try:
                dims = fuse_score(row, flags, scene, config)
            except Exception:  # noqa: BLE001
                continue
            out.append(SamplePoint(
                filename=p.name, bucket=bucket,
                final_score=float(dims.get("final", 0.0)),
                flags=flags, scene=scene or None,
            ))
            if progress_cb:
                progress_cb(len(out), -1, f"分析 {bucket}/{p.name}")
    return out


# ---------------------------------------------------------------------------
# Grid search
# ---------------------------------------------------------------------------

@dataclass
class TuneResult:
    """JSON-friendly bundle. dataclasses.asdict serialises straight."""
    vertical:                 str
    n_good:                   int
    n_bad:                    int
    base_keep_min:            float    # the configured default (0..1)
    base_cull_max:            float
    baseline_delta_keep:      float
    baseline_delta_cull:      float
    baseline:                 dict     # binary_metrics() snapshot
    tuned_delta_keep:         float
    tuned_delta_cull:         float
    tuned:                    dict
    grid:                     list[dict] = field(default_factory=list)
    n_samples_analyzed:       int = 0
    elapsed_s:                float = 0.0
    timestamp:                float = field(default_factory=time.time)


def _baseline_thresholds(config: PixCullConfig) -> tuple[float, float]:
    """Pull the default keep_min / cull_max from config (in 0..1).

    Mirrors how decide() does it for ``strictness="standard"``.
    """
    presets = config.fusion.get("strictness_presets", {})
    thr = presets.get("standard") or config.fusion.get("decision", {})
    return (float(thr.get("keep_min_score", 6.5)) / 10.0,
            float(thr.get("cull_max_score", 4.0)) / 10.0)


def grid_search(
    samples: list[SamplePoint],
    base_keep_min: float,
    base_cull_max: float,
    *,
    tolerated_flags: frozenset[str] = frozenset(),
    delta_grid: tuple[float, ...] = _DELTA_GRID,
) -> tuple[tuple[float, float], dict, list[dict]]:
    """Find the (keep_delta, cull_delta) that maximises F1 on ``samples``.

    Returns (best_deltas, best_metrics, full_grid).
    Ties broken by: higher F1 → higher accuracy → smaller |keep_delta|
    (prefer not to move thresholds when not needed).
    """
    truths = [s.bucket for s in samples]
    best_score = (-1.0, -1.0, float("inf"))
    best = ((0.0, 0.0), None, [])
    grid_out: list[dict] = []
    for kd in delta_grid:
        for cd in delta_grid:
            kmin = max(0.0, min(1.0, base_keep_min + kd))
            cmax = max(0.0, min(1.0, base_cull_max + cd))
            if cmax > kmin:
                # Inverted thresholds = nonsense; skip.
                continue
            preds = [_apply_thresholds(
                s.final_score, s.flags, s.scene,
                keep_min=kmin, cull_max=cmax,
                tolerated_flags=tolerated_flags,
            ) for s in samples]
            m = binary_metrics(preds, truths)
            grid_out.append({
                "keep_delta": kd, "cull_delta": cd,
                "f1":        m["f1"],
                "precision": m["precision"],
                "recall":    m["recall"],
                "accuracy":  m["accuracy"],
            })
            score = (m["f1"], m["accuracy"], -abs(kd))
            if score > best_score:
                best_score = score
                best = ((kd, cd), m, grid_out)
    return best[0], best[1], grid_out


def tune_vertical(key: str, *, progress_cb=None) -> TuneResult:
    """End-to-end: analyze samples → grid search → return TuneResult.

    Raises ``ValueError`` for unknown vertical or empty sample bank.
    """
    v = vmod.get_vertical(key)
    if v is None:
        raise ValueError(f"unknown vertical: {key}")
    counts = vmod.count_samples(key)
    if counts["good"] < 1 or counts["bad"] < 1:
        raise ValueError(
            f"need at least 1 good + 1 bad sample for {key} "
            f"(have good={counts['good']} bad={counts['bad']})"
        )

    t0 = time.time()
    samples = analyze_samples(key, progress_cb=progress_cb)
    n_good = sum(1 for s in samples if s.bucket == "good")
    n_bad  = sum(1 for s in samples if s.bucket == "bad")
    if n_good < 1 or n_bad < 1:
        raise ValueError(
            f"after analysis, need ≥1 good + ≥1 bad ({n_good} / {n_bad})"
        )

    config = PixCullConfig.load()
    base_keep, base_cull = _baseline_thresholds(config)

    # Score the baseline (current registry policy) for before/after
    # comparison. Use the vertical's policy from the registry.
    pol = v.policy
    tol = frozenset(pol.tolerated_flags)
    baseline_preds = [_apply_thresholds(
        s.final_score, s.flags, s.scene,
        keep_min=max(0.0, min(1.0, base_keep + pol.keep_min_delta)),
        cull_max=max(0.0, min(1.0, base_cull + pol.cull_max_delta)),
        tolerated_flags=tol,
    ) for s in samples]
    truths = [s.bucket for s in samples]
    baseline_metrics = binary_metrics(baseline_preds, truths)

    # Search — keep tolerated_flags fixed at the curated default.
    (best_kd, best_cd), tuned_metrics, grid = grid_search(
        samples, base_keep, base_cull,
        tolerated_flags=tol,
    )

    return TuneResult(
        vertical=key,
        n_good=counts["good"], n_bad=counts["bad"],
        base_keep_min=base_keep, base_cull_max=base_cull,
        baseline_delta_keep=pol.keep_min_delta,
        baseline_delta_cull=pol.cull_max_delta,
        baseline=baseline_metrics,
        tuned_delta_keep=best_kd,
        tuned_delta_cull=best_cd,
        tuned=tuned_metrics,
        grid=grid,
        n_samples_analyzed=len(samples),
        elapsed_s=round(time.time() - t0, 2),
    )


# ---------------------------------------------------------------------------
# Override persistence — applied by ``get_effective_policy`` in verticals.py
# ---------------------------------------------------------------------------

def override_path(key: str) -> Path:
    return vmod.vertical_root(key) / "policy_override.json"


def save_override(key: str, result: TuneResult) -> None:
    """Persist the tuned suggestion. Schema:

        {schema, vertical, generated_at, n_good, n_bad,
         keep_min_delta, cull_max_delta, tolerated_flags,
         baseline_f1, tuned_f1, notes}
    """
    pol = vmod.get_vertical(key).policy
    payload = {
        "schema":          "pixcull.policy_override.v1",
        "vertical":        key,
        "generated_at":    result.timestamp,
        "n_good":          result.n_good,
        "n_bad":           result.n_bad,
        "keep_min_delta":  result.tuned_delta_keep,
        "cull_max_delta":  result.tuned_delta_cull,
        "tolerated_flags": sorted(pol.tolerated_flags),
        "baseline_f1":     result.baseline["f1"],
        "tuned_f1":        result.tuned["f1"],
        "notes": (
            f"auto-tuned {time.strftime('%Y-%m-%d', time.localtime(result.timestamp))}"
            f" from {result.n_good}+{result.n_bad} samples"
            f" · F1 {result.baseline['f1']:.3f} → {result.tuned['f1']:.3f}"
        ),
    }
    override_path(key).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_override(key: str) -> dict | None:
    p = override_path(key)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def delete_override(key: str) -> bool:
    p = override_path(key)
    if not p.exists():
        return False
    try:
        p.unlink()
        return True
    except OSError:
        return False


__all__ = [
    "TuneResult",
    "SamplePoint",
    "_DELTA_GRID",
    "_HARD_CULL_FLAGS",
    "binary_metrics",
    "_apply_thresholds",
    "analyze_samples",
    "grid_search",
    "tune_vertical",
    "override_path",
    "save_override",
    "load_override",
    "delete_override",
]
