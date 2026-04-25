"""Tests for the V0.5 MediaPipe face detector.

Covers three paths:
  1. Pure unit — EAR math, constants, graceful-degradation stub
  2. Light integration — analyze() on noise image emits face_count=0
  3. Opt-in integration — known portraits from fixtures (skipped when images
     aren't present or mediapipe isn't installed)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pixcull.detectors import face as face_mod
from pixcull.detectors.face import (
    BLINK_CLOSED_THRESHOLD,
    EAR_CLOSED_FALLBACK,
    FACE_BLUR_LAP_FLOOR,
    MEANINGFUL_FACE_AREA_FRAC,
    MEANINGFUL_FACE_MIN_CONF,
    FaceDetector,
    _ear,
    _LEFT_EYE_EAR,
    _RIGHT_EYE_EAR,
)


# ---------------------------------------------------------- constants sanity
def test_thresholds_are_in_sane_ranges():
    """Tuned on golden set — any later regression here likely breaks eval."""
    assert 0.70 <= BLINK_CLOSED_THRESHOLD <= 0.95
    assert 0.10 <= EAR_CLOSED_FALLBACK <= 0.22
    assert 0.0 < MEANINGFUL_FACE_AREA_FRAC < 0.10
    assert 0.5 <= MEANINGFUL_FACE_MIN_CONF < 1.0
    assert FACE_BLUR_LAP_FLOOR > 0


def test_eye_landmark_indices_have_six_points():
    assert len(_LEFT_EYE_EAR) == 6
    assert len(_RIGHT_EYE_EAR) == 6
    # MediaPipe face mesh has 478 canonical landmarks (468 + 10 iris)
    assert all(0 <= i < 478 for i in _LEFT_EYE_EAR)
    assert all(0 <= i < 478 for i in _RIGHT_EYE_EAR)


# ---------------------------------------------------------- EAR math
def test_ear_open_eye_is_above_fallback_threshold():
    """Classic open-eye contour: vertical ≈ 0.30 × horizontal → EAR ≈ 0.30."""
    # 6 points in order: outer, upper1, upper2, inner, lower2, lower1
    pts = np.array([
        [0.0, 0.0],   # outer corner
        [0.3, -0.3],  # upper1
        [0.7, -0.3],  # upper2
        [1.0, 0.0],   # inner corner
        [0.7, 0.3],   # lower2
        [0.3, 0.3],   # lower1
    ], dtype=float)
    val = _ear(pts)
    assert val > EAR_CLOSED_FALLBACK * 1.5
    # Back-of-envelope: v1=v2=0.6, h=1.0 → ear = (0.6 + 0.6)/2.0 = 0.6
    assert 0.55 <= val <= 0.65


def test_ear_closed_eye_is_below_fallback_threshold():
    """Squashed eye: vertical ~0 → EAR ~0, < fallback threshold."""
    pts = np.array([
        [0.0, 0.0],
        [0.3, -0.01],
        [0.7, -0.01],
        [1.0, 0.0],
        [0.7, 0.01],
        [0.3, 0.01],
    ], dtype=float)
    val = _ear(pts)
    assert val < EAR_CLOSED_FALLBACK


def test_ear_handles_degenerate_zero_width():
    """Division-by-zero guard: horizontal spread of 0 shouldn't NaN."""
    pts = np.zeros((6, 2), dtype=float)
    val = _ear(pts)  # 0 / (0 + 1e-6) = 0.0
    assert np.isfinite(val)
    assert val == 0.0


# ---------------------------------------------------------- no-MP graceful degradation
def test_no_mediapipe_returns_empty_result(monkeypatch, sample_image):
    """If MediaPipe import fails, analyze() must return an empty DetectionResult."""
    d = FaceDetector()
    # Force the lazy-init to short-circuit as if MP isn't installed.
    d._init_failed = True
    r = d.analyze(sample_image)
    assert r.metrics == {}
    assert r.flags == []


def test_missing_model_weights_no_op(monkeypatch, sample_image, tmp_path):
    """If .task / .tflite files are missing, detector silently no-ops."""
    missing = tmp_path / "does_not_exist.tflite"
    monkeypatch.setattr(face_mod, "FACE_DETECTOR_MODEL", missing)
    monkeypatch.setattr(face_mod, "FACE_LANDMARKER_MODEL", missing)
    d = FaceDetector()
    r = d.analyze(sample_image)
    assert r.metrics == {}
    assert r.flags == []
    assert d._init_failed is True


# ---------------------------------------------------------- integration
def _mediapipe_available() -> bool:
    try:
        import mediapipe  # noqa: F401
    except ImportError:
        return False
    return face_mod.FACE_DETECTOR_MODEL.exists() and face_mod.FACE_LANDMARKER_MODEL.exists()


@pytest.mark.skipif(not _mediapipe_available(), reason="MediaPipe / model weights unavailable")
def test_analyze_on_solid_color_sees_no_face():
    """A flat gray image must produce no cull flags and non-NaN metrics."""
    d = FaceDetector()
    gray = Image.new("RGB", (512, 512), color=(128, 128, 128))
    r = d.analyze(gray)
    # On a featureless image, the detector may hallucinate faces but should
    # not fire cull flags (both area and confidence gates should filter them).
    assert r.metrics.get("face_count", 0.0) == 0.0
    assert "closed_eyes" not in r.flags
    assert "motion_blur_on_face" not in r.flags
    assert "face_occluded" not in r.flags


@pytest.mark.skipif(not _mediapipe_available(), reason="MediaPipe / model weights unavailable")
def test_analyze_on_portrait_detects_open_eyes():
    """3J0A1701.JPG is a golden-set keep portrait — detector should find one
    face with eyes clearly open and emit no cull flags."""
    img_path = Path(__file__).parent / "fixtures" / "images" / "portrait" / "3J0A1701.JPG"
    if not img_path.exists():
        pytest.skip("portrait fixture unavailable")

    from pixcull.io.loader import load_image
    img = load_image(img_path)
    assert img is not None

    d = FaceDetector()
    r = d.analyze(img)
    assert r.metrics.get("face_count", 0.0) >= 1.0
    # Open eyes: blink should be low, EAR high, no cull flags.
    assert r.metrics.get("face_max_blink", 0.0) < BLINK_CLOSED_THRESHOLD
    assert r.metrics.get("face_min_ear", 0.0) > EAR_CLOSED_FALLBACK
    assert "closed_eyes" not in r.flags


@pytest.mark.skipif(not _mediapipe_available(), reason="MediaPipe / model weights unavailable")
def test_meaningful_face_gate_suppresses_tiny_detections():
    """A portrait rendered at 32×32 (faces present but far below 2% of image
    size when scaled up to a large canvas) must not emit cull flags — confirms
    the area gate is doing its job."""
    # Create a 2000×2000 canvas with a tiny 32×32 portrait pasted in a corner.
    img_path = Path(__file__).parent / "fixtures" / "images" / "portrait" / "3J0A1701.JPG"
    if not img_path.exists():
        pytest.skip("portrait fixture unavailable")

    base = Image.open(img_path).convert("RGB")
    tiny = base.resize((40, 40))
    canvas = Image.new("RGB", (2000, 2000), color=(128, 128, 128))
    canvas.paste(tiny, (10, 10))

    d = FaceDetector()
    r = d.analyze(canvas)
    # Even if the detector sees something, cull flags should be gated off.
    assert "closed_eyes" not in r.flags
    assert "motion_blur_on_face" not in r.flags
    assert "face_occluded" not in r.flags
