"""Rule-based composition heuristics. V0.6 minimal implementation.

The V0.5 golden-set eval flagged 6 architecture photos with a `审美一般`
(mediocre aesthetic) annotation that none of the existing detectors catch —
they score 0.70-0.73 on `score_final` and get routed to `keep`. That rules out
a single-scalar signal (LAION-AES / CLIP-IQA) as sufficient, and the
misclassified set has characteristic compositional issues (off-horizon, cluttered
background, subject glued to frame edges) that a rule-based detector can flag.

What this detector does NOT try to do:
  - Replace a learned aesthetic model. The signal is weak — maybe 2-3 photos
    net on our current golden set, per eval_findings.md §V0.6.
  - Composition "style" (leading lines, vanishing points, golden ratio).
    Research-grade work; out of scope.

What it DOES:
  - `horizon_tilt_deg` — dominant near-horizontal line angle from Hough; 0 when
    the camera is level, positive when tilted. High tilt (> 5°) gets penalized.
  - `rule_of_thirds_offset` — L2 distance from subject mask centroid to the
    nearest rule-of-thirds intersection, normalized by image diagonal.
    0.0 = perfectly on a third-point, ~0.3 = dead center.
  - `composition_score` — blended [0, 1] score wired into fusion.py. Stays at
    0.5 (neutral) when we have no mask and no strong horizon signal so we don't
    push scores around without evidence.

Gracefully degrades when OpenCV Hough fails or the mask is empty.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from pixcull.detectors.base import DetectionResult, Detector


# Tuned on golden set architecture/landscape photos. A professional shoot has
# horizons within ~2° of level; strong tilt reads as "off" to most viewers.
# Bad threshold raised from 8° → 12° after V0.6 eval: a 13.5° landscape keep
# was saturating the penalty despite being photographer-approved (3J0A3370).
HORIZON_TILT_NEUTRAL_DEG = 2.0    # below this: perfect, no penalty
HORIZON_TILT_BAD_DEG = 12.0       # above this: saturated penalty

# Rule-of-thirds: subject centroid within this fraction of image diagonal to a
# third-point counts as "well-placed".
THIRDS_HOT_ZONE_FRAC = 0.08
THIRDS_DEAD_ZONE_FRAC = 0.25

# Blend weights when assembling composition_score. Horizon tilt dominates
# because it's the most reliable signal and the one that most matches what
# the photographer's `构图倾斜` annotations flag.
_HORIZON_WEIGHT = 0.6
_THIRDS_WEIGHT = 0.4

# Scenes where horizon tilt is informative (skyline / building / street scene
# against a level horizon). For stilllife / portrait / event / wildlife,
# deliberate camera tilt is common — firing the tilt penalty hurts 3 stilllife
# keeps in the V0.6 eval (AB4A4641/4829/4831 with -8 to -11° intentional
# angles). Thirds signal stays active for all scenes (subject placement is
# universally relevant).
_TILT_RELEVANT_SCENES = frozenset({"landscape", "street", "architecture"})

# Downscale cap for Hough — full-res analysis is slow and doesn't change tilt.
_HOUGH_MAX_SIDE = 1024


def _detect_horizon_tilt(gray: np.ndarray) -> float | None:
    """Return the dominant near-horizontal line's tilt angle in degrees.

    We threshold Hough lines to the near-horizontal band (|angle| ≤ 15°) and
    return the median tilt. `None` when no usable line is found (happens for
    abstract / high-entropy frames where every line is short).
    """
    h, w = gray.shape[:2]
    # Canny edges with auto-thresholds keyed to the image's median intensity.
    v = float(np.median(gray))
    lo = int(max(0, 0.66 * v))
    hi = int(min(255, 1.33 * v))
    edges = cv2.Canny(gray, lo, hi)

    # Min line length = 1/6 of the image width → skip tiny edges.
    min_len = max(40, w // 6)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 360,      # 0.5° bins
        threshold=80,
        minLineLength=min_len,
        maxLineGap=10,
    )
    if lines is None:
        return None

    angles: list[float] = []
    for seg in lines[:, 0, :]:
        x1, y1, x2, y2 = seg
        if x2 == x1:
            continue
        ang_deg = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        # Collapse to [-90, 90] and only keep near-horizontal.
        if ang_deg > 90:
            ang_deg -= 180
        if ang_deg < -90:
            ang_deg += 180
        if abs(ang_deg) <= 15.0:
            angles.append(ang_deg)

    if not angles:
        return None
    return float(np.median(angles))


def _thirds_offset(mask: np.ndarray | None) -> float | None:
    """Distance from subject mask centroid to nearest rule-of-thirds intersection,
    normalized by image diagonal. Returns None when the mask is empty."""
    if mask is None:
        return None
    if mask.sum() == 0:
        return None
    h, w = mask.shape[:2]
    # Centroid of the mask.
    ys, xs = np.nonzero(mask)
    cy = float(ys.mean())
    cx = float(xs.mean())
    # Four third-points.
    targets = [
        (w / 3, h / 3), (2 * w / 3, h / 3),
        (w / 3, 2 * h / 3), (2 * w / 3, 2 * h / 3),
    ]
    dmin = min(float(np.hypot(cx - tx, cy - ty)) for tx, ty in targets)
    diag = float(np.hypot(w, h))
    return dmin / max(1.0, diag)


def _tilt_score(tilt_deg: float | None) -> float:
    """Map tilt angle → [0, 1]. 1.0 = level, 0.0 = saturated tilt."""
    if tilt_deg is None:
        return 0.5  # no evidence → neutral
    t = abs(tilt_deg)
    if t <= HORIZON_TILT_NEUTRAL_DEG:
        return 1.0
    if t >= HORIZON_TILT_BAD_DEG:
        return 0.0
    # Linear ramp between neutral and bad thresholds.
    return 1.0 - (t - HORIZON_TILT_NEUTRAL_DEG) / (HORIZON_TILT_BAD_DEG - HORIZON_TILT_NEUTRAL_DEG)


def _thirds_score(offset_frac: float | None) -> float:
    """Map thirds offset → [0, 1]. 1.0 = on third-point, 0.0 = dead center."""
    if offset_frac is None:
        return 0.5
    if offset_frac <= THIRDS_HOT_ZONE_FRAC:
        return 1.0
    if offset_frac >= THIRDS_DEAD_ZONE_FRAC:
        return 0.0
    return 1.0 - (offset_frac - THIRDS_HOT_ZONE_FRAC) / (
        THIRDS_DEAD_ZONE_FRAC - THIRDS_HOT_ZONE_FRAC
    )


class CompositionDetector(Detector):
    """Rule-based composition heuristics (horizon tilt + rule of thirds).

    The tilt penalty only contributes to `composition_score` when the scene is
    one where horizons matter (landscape/street/architecture). For stilllife,
    portrait, event, wildlife, we emit the raw `horizon_tilt_deg` metric for
    downstream visibility but fall back to a thirds-only composition_score.

    Emits:
        metrics:
            horizon_tilt_deg       – signed tilt in degrees (None → NaN)
            rule_of_thirds_offset  – distance to nearest third-point / diagonal
            composition_score      – blended [0, 1]; scene-gated tilt;
                                      neutral 0.5 when no signal
    """

    name = "composition"

    def analyze(
        self,
        img: Image.Image,
        mask: np.ndarray | None = None,
        scene: str | None = None,
        **_: object,
    ) -> DetectionResult:
        result = DetectionResult()

        arr = np.array(img.convert("RGB"))
        h, w = arr.shape[:2]
        if max(h, w) > _HOUGH_MAX_SIDE:
            scale = _HOUGH_MAX_SIDE / max(h, w)
            new_size = (int(w * scale), int(h * scale))
            small = cv2.resize(arr, new_size, interpolation=cv2.INTER_AREA)
        else:
            small = arr

        gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)

        tilt = _detect_horizon_tilt(gray)
        offset = _thirds_offset(mask)

        # Scene gate: only fold tilt into composition_score when the scene
        # makes tilt a meaningful signal. For other scenes, we use a
        # thirds-only score (still wired when a mask is available) and fall
        # back to neutral 0.5 when we have nothing to say.
        tilt_relevant = scene is None or scene in _TILT_RELEVANT_SCENES

        thirds_s = _thirds_score(offset)
        if tilt_relevant:
            tilt_s = _tilt_score(tilt)
            comp = _HORIZON_WEIGHT * tilt_s + _THIRDS_WEIGHT * thirds_s
        elif offset is not None:
            # Thirds-only composition score for scenes where tilt is noise.
            comp = thirds_s
        else:
            comp = 0.5  # no reliable signal for this scene/image

        if tilt is not None:
            result.metrics["horizon_tilt_deg"] = tilt
        if offset is not None:
            result.metrics["rule_of_thirds_offset"] = offset
        result.metrics["composition_score"] = comp
        return result
