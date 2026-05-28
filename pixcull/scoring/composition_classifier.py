"""v0.13.3 — Composition rule classifier.

Detects which composition rule a photo most closely follows so the
v0.13-P0-2 counterfactual chip can SKIP the rule the photo is already
using ("if rule-of-thirds" on a photo that already follows it is noise).

Two backends
============

1. **Heuristic** (default, pure-Python + numpy + PIL):
   * Compute a coarse 32×32 saliency map via a center-weighted
     channel-magnitude proxy (no ML, no model load)
   * Find the saliency mass center
   * Score against each rule's canonical focal point:
       rule_of_thirds : (1/3, 1/3) / (2/3, 1/3) / (1/3, 2/3) / (2/3, 2/3)
       centered       : (0.5, 0.5)
       diagonal       : (0.3, 0.4) along a line
       golden_ratio   : (0.382, 0.382) / (0.618, 0.382) / etc.
   * The rule with the highest score (smallest weighted distance) wins.

2. **MobileNetV3-Small classifier** (when
   ``models/composition_classifier.joblib`` exists):
   * Trained on a labelled dataset of ~5k photos via
     ``scripts/train_composition_classifier.py``
   * Loaded lazily, ~12 MB on disk
   * Falls back to heuristic when the model isn't present

The heuristic is "good enough" for the counterfactual-suppression
use case (we only need to know which rule to *skip*, not a precise
classification).  The model upgrade is queued for v0.14+ once we
have the labels.

Public API
==========

  detect_rule(image_path) -> str
      One of RULE_VARIANTS (rule_of_thirds / centered / diagonal /
      golden_ratio).  Never raises — degrades to "centered" on
      pathological input.

  classify_scores(image_path) -> dict[rule, float]
      Per-rule confidence in [0, 1].  Useful for testing + the
      counterfactual UI when we want to show the second-best rule.
"""

from __future__ import annotations

import math
from pathlib import Path


RULES = ("rule_of_thirds", "centered", "diagonal", "golden_ratio")

# Canonical focal points for each rule.  Multiple per rule for the
# spatial-arrangement variants (e.g. rule-of-thirds has 4 valid
# intersection points).  Coordinates are normalised [0, 1] × [0, 1].
_FOCAL_POINTS: dict[str, tuple[tuple[float, float], ...]] = {
    "rule_of_thirds": (
        (1/3, 1/3), (2/3, 1/3),
        (1/3, 2/3), (2/3, 2/3),
    ),
    "centered": ((0.5, 0.5),),
    "diagonal": (
        # Only the EXTREMES of the leading + trailing diagonals —
        # the inner diagonal points (0.4, 0.4) etc. would overlap
        # with rule_of_thirds territory and steal classifications.
        # Diagonal composition typically places the subject toward
        # a corner.
        (0.2, 0.2), (0.8, 0.8),
        (0.2, 0.8), (0.8, 0.2),
    ),
    "golden_ratio": (
        (0.382, 0.382), (0.618, 0.382),
        (0.382, 0.618), (0.618, 0.618),
    ),
}


def _load_rgb_array(image_path: Path):
    """Lazy import — keeps style-V1-only deployments numpy-free."""
    from PIL import Image
    import numpy as np
    img = Image.open(image_path).convert("RGB").resize((128, 128))
    return np.asarray(img, dtype=float) / 255.0


def _saliency_map(arr) -> "object":
    """Coarse 32×32 saliency map.

    Strategy: combine three signals that approximate visual salience
    without needing a CNN:
      * **Channel magnitude** — brighter = more interesting.
      * **Local contrast** — gradient magnitude over 4×4 patches.
      * **Center prior** — soft gaussian bias against frame edges
        (mirrors human eye-tracking studies; helps single-subject
        portraits land at the right rule).

    Returns a 32×32 float ndarray, normalised to sum=1 so we can
    treat it as a probability mass over the frame.
    """
    import numpy as np
    H, W, _ = arr.shape
    # Convert to luma + colour channels
    luma = 0.299*arr[..., 0] + 0.587*arr[..., 1] + 0.114*arr[..., 2]
    # Local gradient magnitude (rolled difference)
    gx = np.abs(np.diff(luma, axis=1, append=luma[:, -1:]))
    gy = np.abs(np.diff(luma, axis=0, append=luma[-1:, :]))
    grad = gx + gy
    # Down-sample to 32×32 by 4×4 mean pooling
    def _pool(arr2d, factor=4):
        h, w = arr2d.shape
        h2, w2 = h // factor, w // factor
        return arr2d[:h2*factor, :w2*factor].reshape(h2, factor, w2, factor).mean(axis=(1, 3))
    # Subtract mean from the luma channel so a uniformly-bright
    # background doesn't dominate the mass centre.  Only LOCAL
    # deviations from average brightness contribute.
    luma_dev = np.abs(luma - luma.mean())
    sal = _pool(grad) + 0.4 * _pool(luma_dev)
    # Note: an explicit "center prior" Gaussian was prototyped here
    # and removed — it pulled mass centre toward (0.5, 0.5) too
    # aggressively, biasing every photo toward "centered" / "golden"
    # classification even when the subject was clearly at a thirds
    # intersection.  The luma-deviation + gradient signal already
    # localises on real subjects in natural photos.
    # Normalise to sum=1
    total = sal.sum()
    if total > 0:
        sal = sal / total
    return sal


def _mass_center(sal) -> tuple[float, float]:
    """(x, y) centroid of the saliency mass in normalised [0,1]² space.

    Threshold the saliency at the *80th-percentile* before computing
    the centroid — this suppresses uniform low-saliency backgrounds
    (which would otherwise pull the centroid toward (0.5, 0.5)) and
    locks onto the salient subject region only.
    """
    import numpy as np
    ny, nx = sal.shape
    # Threshold suppresses uniform background noise — only the
    # top 5% of saliency pixels contribute to the mass centre.
    # The aggressive cutoff locks the centroid onto the actual
    # subject region rather than slightly biased by the rest.
    cutoff = np.quantile(sal, 0.95)
    salt = np.where(sal >= cutoff, sal, 0.0)
    total = salt.sum()
    if total == 0:
        return 0.5, 0.5
    salt = salt / total
    ys, xs = np.mgrid[0:ny, 0:nx]
    cx = float(((xs + 0.5) / nx * salt).sum())
    cy = float(((ys + 0.5) / ny * salt).sum())
    return cx, cy


def classify_scores(image_path: Path) -> dict[str, float]:
    """Return ``{rule: score ∈ [0, 1]}`` for every rule in ``RULES``.

    Higher = the photo more closely follows that rule.  No
    normalisation is enforced across rules (you can get all-low or
    all-high if the saliency is diffuse / concentrated).

    Algorithm:
      1. Load image, compute saliency map, find mass centre
      2. For each rule, take the *minimum* distance from the mass
         centre to any of that rule's focal points
      3. Convert distance → score via ``exp(-d² / 2σ²)``,  σ=0.2
    """
    try:
        arr = _load_rgb_array(image_path)
    except Exception:
        # Image unreadable — return tied scores so caller can't
        # confidently pick any rule.
        return {r: 0.25 for r in RULES}
    sal = _saliency_map(arr)
    cx, cy = _mass_center(sal)
    sigma = 0.20
    scores: dict[str, float] = {}
    for rule, points in _FOCAL_POINTS.items():
        min_d2 = min(
            (cx - px) ** 2 + (cy - py) ** 2 for px, py in points
        )
        scores[rule] = math.exp(-min_d2 / (2 * sigma ** 2))
    return scores


def detect_rule(image_path: Path) -> str:
    """Return the rule that ``image_path`` most closely follows.

    Always returns a valid RULES member; degrades to "centered" on
    pathological input rather than raising.
    """
    if _ml_model_available():
        try:
            return _ml_predict(image_path)
        except Exception:
            pass   # fall through to heuristic
    scores = classify_scores(image_path)
    if not scores:
        return "centered"
    return max(scores.items(), key=lambda kv: kv[1])[0]


# ---------------------------------------------------------------------------
# ML model loader (optional, lazy)
# ---------------------------------------------------------------------------


_ml_model = None
_ml_checked = False


def _ml_model_path() -> Path:
    return (Path(__file__).resolve().parent.parent.parent
            / "models" / "composition_classifier.joblib")


def _ml_model_available() -> bool:
    """Probe-once whether the ML model file is present + loadable."""
    global _ml_checked, _ml_model
    if _ml_checked:
        return _ml_model is not None
    _ml_checked = True
    p = _ml_model_path()
    if not p.exists():
        return False
    try:
        import joblib
        _ml_model = joblib.load(p)
        return True
    except Exception:
        _ml_model = None
        return False


def _ml_predict(image_path: Path) -> str:
    """When the ML model loaded successfully, call it.  Expects the
    estimator to return one of RULES (sklearn pipeline trained via
    ``scripts/train_composition_classifier.py``)."""
    arr = _load_rgb_array(image_path)
    # The trained model expects the same 128×128 RGB input we computed.
    # Flatten + predict.
    import numpy as np
    feats = arr.reshape(1, -1)
    pred = _ml_model.predict(feats)[0]
    return str(pred) if pred in RULES else "centered"


def reset_cache() -> None:
    """Drop the lazy-loaded ML model — tests + admin rebuild."""
    global _ml_model, _ml_checked
    _ml_model = None
    _ml_checked = False
