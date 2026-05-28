"""v0.13-P0-2 — Counterfactual chip ("would this score higher if…").

Given a photo + the rescorer that scored it, generate a small set of
*virtual variants* (perturbations of the original framing) and report
the largest score delta we'd expect.  Surfaces in the Inspector as
"+0.08 if rule-of-thirds" — answering the photographer's "why?" with
a concrete actionable alternative.

Design
======
* **Composition rules:** rule-of-thirds, centered, diagonal, golden-ratio.
  Each is a *crop strategy* that produces a virtual variant of the
  original frame.  All variants are synthetic (no new pixels — pure
  re-framing) so we never need to fabricate content.
* **Scoring stub:** the existing axis rescorers score variants the
  same way they score the original.  No model retraining needed; we
  just feed perturbed pixels through the existing pipeline.
* **Delta:** report the variant with the highest ``new_score -
  original_score``, with the rule name + the delta.

We deliberately don't ship the classifier from the v0.13 charter
("MobileNetV3-Small … 4 classes, 5k labels") because that requires a
labelled dataset we don't have.  Instead this module ships the
*perturbation + delta scoring* framework that the classifier would
sit on top of.  Adding the classifier later is a drop-in:

  from pixcull.scoring.composition_classifier import detect_rule
  cur_rule = detect_rule(image_path)
  candidates = [r for r in RULE_VARIANTS if r != cur_rule]

For now, ``candidates = RULE_VARIANTS`` and we always score against
all of them (cheaper to over-explore than to miss the right cf).

Public API
==========

  generate_variants(image_path) -> dict[rule_name, image_array]
      Pure-image perturbations.

  best_counterfactual(image_path, score_fn) -> Counterfactual | None
      Highest delta variant + its score.

  ``score_fn`` is any callable taking an image array and returning a
  float in 0..1.  In production it's a partial application of the
  rescorer pipeline; in tests it's a mock.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Counterfactual:
    """One winning counterfactual."""
    rule: str            # "rule_of_thirds" / "centered" / "diagonal" / "golden"
    delta: float         # new_score - original_score; positive = improvement
    new_score: float
    original_score: float

    @property
    def label(self) -> str:
        """Human-readable label suitable for the Inspector chip."""
        sign = "+" if self.delta >= 0 else "−"
        return f"{sign}{abs(self.delta):.2f} if {self.rule.replace('_', ' ')}"


RULE_VARIANTS = ("rule_of_thirds", "centered", "diagonal", "golden_ratio")


# ---------------------------------------------------------------------------
# Perturbation strategies — each returns a numpy ndarray (H, W, 3).
# ---------------------------------------------------------------------------


def _load_rgb(image_path: Path):
    """Lazy import + read into a numpy array (H, W, 3, uint8)."""
    from PIL import Image
    import numpy as np
    img = Image.open(image_path).convert("RGB")
    return np.asarray(img)


def _crop_to_aspect(arr, *, focal_x: float, focal_y: float,
                   aspect: float = None):
    """Crop ``arr`` (H,W,3) around a focal point (normalised 0..1 in
    each dim) preserving aspect.  Returns the cropped ndarray.

    ``aspect`` = w / h (defaults to the input aspect).
    """
    h, w = arr.shape[:2]
    if aspect is None:
        aspect = w / h
    # Choose the largest crop centred on focal point that fits.
    cx = int(focal_x * w)
    cy = int(focal_y * h)
    # Target dims = 90% of the original (10% trim to make room for re-frame)
    target_w = int(w * 0.9)
    target_h = int(target_w / aspect)
    if target_h > h * 0.9:
        target_h = int(h * 0.9)
        target_w = int(target_h * aspect)
    left = max(0, min(w - target_w, cx - target_w // 2))
    top = max(0, min(h - target_h, cy - target_h // 2))
    return arr[top:top+target_h, left:left+target_w]


def _variant_rule_of_thirds(arr):
    """Place the subject at the 1/3 point (focal at (0.333, 0.333))."""
    return _crop_to_aspect(arr, focal_x=1/3, focal_y=1/3)


def _variant_centered(arr):
    """Subject centred in frame."""
    return _crop_to_aspect(arr, focal_x=0.5, focal_y=0.5)


def _variant_diagonal(arr):
    """Subject on the leading diagonal (offset toward top-left)."""
    return _crop_to_aspect(arr, focal_x=0.3, focal_y=0.4)


def _variant_golden_ratio(arr):
    """Subject at the golden-ratio intersection (0.382, 0.382)."""
    return _crop_to_aspect(arr, focal_x=0.382, focal_y=0.382)


VARIANT_FNS = {
    "rule_of_thirds": _variant_rule_of_thirds,
    "centered":       _variant_centered,
    "diagonal":       _variant_diagonal,
    "golden_ratio":   _variant_golden_ratio,
}


def generate_variants(image_path: Path) -> dict[str, "object"]:
    """Pure-image perturbations of ``image_path``.  Returns
    ``{rule: ndarray}``.  Each ndarray is a re-cropped variant
    of the same original pixels."""
    arr = _load_rgb(image_path)
    return {name: fn(arr) for name, fn in VARIANT_FNS.items()}


# ---------------------------------------------------------------------------
# Counterfactual selection
# ---------------------------------------------------------------------------


def best_counterfactual(
    image_path: Path,
    score_fn: Callable[["object"], float],
    *,
    skip_current_rule: str | None = None,
) -> Counterfactual | None:
    """Score the original + every variant + return the highest-delta one.

    ``score_fn(arr)`` is any callable that takes an ndarray and returns
    a float in 0..1.  In production it's wired to the existing
    rescorer pipeline; tests substitute a mock.

    ``skip_current_rule`` (optional): if you know the photo already
    follows one of the rules (e.g. detected via composition
    classifier), pass its name to skip it from candidate variants.

    Returns None when no variant improves the score by ≥ 0.01
    (the chip only surfaces actionable suggestions).
    """
    arr = _load_rgb(image_path)
    original_score = float(score_fn(arr))
    best: Counterfactual | None = None
    for rule, fn in VARIANT_FNS.items():
        if rule == skip_current_rule:
            continue
        variant = fn(arr)
        new_score = float(score_fn(variant))
        delta = new_score - original_score
        if best is None or delta > best.delta:
            best = Counterfactual(
                rule=rule, delta=delta,
                new_score=new_score, original_score=original_score,
            )
    if best is None or best.delta < 0.01:
        return None
    return best
