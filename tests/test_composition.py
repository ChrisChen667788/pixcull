"""Tests for the V0.6 minimal composition detector (horizon tilt + thirds).

The detector is deliberately small — it emits three metrics and a blended
[0, 1] `composition_score`. Tests pin the geometric behavior (tilt detection,
thirds scoring) plus the graceful-degradation paths.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from pixcull.detectors.composition import (
    HORIZON_TILT_BAD_DEG,
    HORIZON_TILT_NEUTRAL_DEG,
    THIRDS_DEAD_ZONE_FRAC,
    THIRDS_HOT_ZONE_FRAC,
    _TILT_RELEVANT_SCENES,
    CompositionDetector,
    _thirds_offset,
    _thirds_score,
    _tilt_score,
)


# ------------------------------------------------ constants sanity
def test_tilt_thresholds_in_sane_range():
    assert 0 <= HORIZON_TILT_NEUTRAL_DEG < HORIZON_TILT_BAD_DEG
    assert HORIZON_TILT_BAD_DEG < 45  # full 45° would be a rotation, not a tilt


def test_thirds_thresholds_in_sane_range():
    assert 0 < THIRDS_HOT_ZONE_FRAC < THIRDS_DEAD_ZONE_FRAC < 0.5


# ------------------------------------------------ tilt score math
def test_tilt_score_level_is_perfect():
    assert _tilt_score(0.0) == 1.0


def test_tilt_score_saturates_at_bad_threshold():
    assert _tilt_score(HORIZON_TILT_BAD_DEG) == 0.0
    assert _tilt_score(HORIZON_TILT_BAD_DEG + 5) == 0.0  # clamps, doesn't go negative


def test_tilt_score_is_neutral_when_no_lines_found():
    """None means 'no evidence' — must not drag comp_score down."""
    assert _tilt_score(None) == 0.5


def test_tilt_score_ignores_sign():
    """Camera tilted +5° is just as bad as -5°."""
    assert _tilt_score(5.0) == _tilt_score(-5.0)


def test_tilt_score_is_monotonically_decreasing():
    """More tilt → lower score, in the ramp zone."""
    scores = [_tilt_score(t) for t in np.linspace(
        HORIZON_TILT_NEUTRAL_DEG, HORIZON_TILT_BAD_DEG, 10
    )]
    for a, b in zip(scores, scores[1:]):
        assert a >= b


# ------------------------------------------------ thirds score math
def test_thirds_score_on_third_point_is_perfect():
    assert _thirds_score(0.0) == 1.0
    assert _thirds_score(THIRDS_HOT_ZONE_FRAC / 2) == 1.0


def test_thirds_score_dead_center_saturates():
    assert _thirds_score(THIRDS_DEAD_ZONE_FRAC) == 0.0
    assert _thirds_score(0.5) == 0.0


def test_thirds_score_none_is_neutral():
    """No mask → no evidence."""
    assert _thirds_score(None) == 0.5


# ------------------------------------------------ _thirds_offset geometry
def test_thirds_offset_on_third_point_returns_small_frac():
    """Mask centered exactly on (w/3, h/3) → offset ~ 0."""
    h, w = 300, 600
    mask = np.zeros((h, w), dtype=bool)
    cy, cx = h // 3, w // 3  # (100, 200)
    mask[cy - 5:cy + 5, cx - 5:cx + 5] = True
    offset = _thirds_offset(mask)
    assert offset is not None
    assert offset < 0.01


def test_thirds_offset_dead_center_returns_large_frac():
    """Mask in the exact middle → offset is the diagonal-to-third-point distance."""
    h, w = 300, 600
    mask = np.zeros((h, w), dtype=bool)
    mask[h // 2 - 5:h // 2 + 5, w // 2 - 5:w // 2 + 5] = True
    offset = _thirds_offset(mask)
    # Distance from (300, 150) to (200, 100) = sqrt(10000 + 2500) ≈ 112
    # Diagonal = sqrt(600^2 + 300^2) ≈ 670 → offset ≈ 0.167
    assert offset is not None
    assert 0.15 < offset < 0.20


def test_thirds_offset_on_empty_mask_returns_none():
    mask = np.zeros((100, 100), dtype=bool)
    assert _thirds_offset(mask) is None


def test_thirds_offset_on_none_mask_returns_none():
    assert _thirds_offset(None) is None


# ------------------------------------------------ integration
def test_analyze_on_level_image_gives_no_tilt():
    """Flat image with a strong horizontal dark band: tilt must read 0."""
    arr = np.ones((500, 700, 3), dtype=np.uint8) * 200
    arr[250:260, :, :] = 20  # thick horizontal dark band
    img = Image.fromarray(arr)
    d = CompositionDetector()
    r = d.analyze(img)
    assert "composition_score" in r.metrics
    assert "horizon_tilt_deg" in r.metrics
    assert abs(r.metrics["horizon_tilt_deg"]) < 1.0


def test_analyze_on_tilted_image_detects_tilt():
    """Same image rotated by 10° → horizon_tilt should be ~10°."""
    arr = np.ones((500, 700, 3), dtype=np.uint8) * 200
    arr[245:255, :, :] = 20
    img = Image.fromarray(arr).rotate(10, expand=False, fillcolor=(128, 128, 128))
    d = CompositionDetector()
    r = d.analyze(img)
    # Hough won't be perfect; allow a wide tolerance but must detect significant tilt.
    assert abs(r.metrics.get("horizon_tilt_deg", 0)) > 5.0
    # And composition_score must be penalized from the 1.0 max.
    assert r.metrics["composition_score"] < 0.7


def test_analyze_on_abstract_image_falls_back_to_neutral():
    """No detectable lines → metrics stay neutral, no crash."""
    arr = (np.random.rand(300, 400, 3) * 40 + 100).astype(np.uint8)
    img = Image.fromarray(arr)
    d = CompositionDetector()
    r = d.analyze(img)
    assert "composition_score" in r.metrics
    # Without strong lines or a mask, score should be near neutral.
    assert 0.3 < r.metrics["composition_score"] < 0.9


def test_analyze_with_mask_uses_thirds_signal():
    """Placing a mask on a third-point should push comp_score up."""
    h, w = 600, 900
    arr = np.ones((h, w, 3), dtype=np.uint8) * 128
    arr[300:310, :, :] = 30
    img = Image.fromarray(arr)

    mask_third = np.zeros((h, w), dtype=bool)
    ty, tx = h // 3, w // 3
    mask_third[ty - 20:ty + 20, tx - 20:tx + 20] = True

    mask_center = np.zeros((h, w), dtype=bool)
    cy, cx = h // 2, w // 2
    mask_center[cy - 20:cy + 20, cx - 20:cx + 20] = True

    d = CompositionDetector()
    r_third = d.analyze(img, mask=mask_third)
    r_center = d.analyze(img, mask=mask_center)
    assert r_third.metrics["composition_score"] > r_center.metrics["composition_score"]


# ------------------------------------------------ scene gate (V0.7)
def test_tilt_relevant_scenes_set():
    """The three scenes we scope tilt signal to (landscape/street/architecture)."""
    assert "landscape" in _TILT_RELEVANT_SCENES
    assert "street" in _TILT_RELEVANT_SCENES
    assert "architecture" in _TILT_RELEVANT_SCENES
    # Scenes where tilt is often intentional — must NOT be in the set.
    for s in ("stilllife", "portrait", "event", "wildlife"):
        assert s not in _TILT_RELEVANT_SCENES, f"{s} should not be tilt-relevant"


def _tilted_img_with_mask(tilt_deg: float):
    arr = np.ones((500, 700, 3), dtype=np.uint8) * 200
    arr[245:255, :, :] = 20
    img = Image.fromarray(arr).rotate(tilt_deg, expand=False, fillcolor=(128, 128, 128))
    # Center mask (dead zone) so thirds_score → 0.
    mask = np.zeros((500, 700), dtype=bool)
    mask[240:260, 340:360] = True
    return img, mask


def test_stilllife_intentional_tilt_is_not_penalized():
    """V0.7: a stilllife with -10° intentional tilt must not get a zero-tilt penalty."""
    img, mask = _tilted_img_with_mask(-10.0)
    d = CompositionDetector()
    r_stilllife = d.analyze(img, mask=mask, scene="stilllife")
    r_landscape = d.analyze(img, mask=mask, scene="landscape")
    # Stilllife: composition_score should NOT be the tilt-saturated value.
    # Landscape: composition_score IS tilt-penalized.
    assert r_stilllife.metrics["composition_score"] > r_landscape.metrics["composition_score"]
    # And the raw tilt metric still surfaces for downstream visibility.
    assert "horizon_tilt_deg" in r_stilllife.metrics


def test_portrait_tilt_is_ignored():
    """Portrait with 15° tilt — composition_score should not be floor-saturated."""
    img, mask = _tilted_img_with_mask(15.0)
    d = CompositionDetector()
    r = d.analyze(img, mask=mask, scene="portrait")
    # Tilt 15° would give comp ≈ 0 on a tilt-relevant scene; here the mask
    # is centered (thirds_score → 0) but composition falls back to thirds-only
    # (= 0.0 when mask is in dead zone). The key assertion: the saturated
    # tilt-weighted path is NOT what produced this, and with no mask it would
    # be neutral 0.5.
    img_no_mask = img
    r_no_mask = d.analyze(img_no_mask, scene="portrait")
    assert r_no_mask.metrics["composition_score"] == 0.5


def test_landscape_preserves_tilt_penalty():
    """Landscape with strong tilt should still get the tilt penalty.

    Compare the SAME tilted image under two scenes — on landscape tilt gates
    in, on portrait it gates out; the landscape composition_score must be
    the lower of the two. (We avoid asserting absolute values because Hough
    line detection depends on the rotation angle — very large tilts may fail
    to detect the band at all.)"""
    img, mask = _tilted_img_with_mask(10.0)
    d = CompositionDetector()
    r_landscape = d.analyze(img, mask=mask, scene="landscape")
    r_portrait = d.analyze(img, mask=mask, scene="portrait")
    assert r_landscape.metrics["composition_score"] < r_portrait.metrics["composition_score"]


def test_analyze_with_none_scene_uses_full_signal():
    """Backwards compat: no scene arg → tilt is honored as before."""
    arr = np.ones((500, 700, 3), dtype=np.uint8) * 200
    arr[245:255, :, :] = 20
    tilted = Image.fromarray(arr).rotate(15, expand=False, fillcolor=(128, 128, 128))
    d = CompositionDetector()
    r = d.analyze(tilted)  # no scene kwarg
    assert r.metrics["composition_score"] < 0.3


def test_loosened_bad_tilt_threshold_is_12_deg():
    """V0.7 calibration: 10° tilt should no longer saturate the penalty.
    Previous HORIZON_TILT_BAD_DEG=8° caused 3J0A3370 (landscape keep, 13.5°
    tilt) to score 0 on tilt; new 12° gives a gentler slope."""
    assert HORIZON_TILT_BAD_DEG >= 10.0
    # 10° tilt: under the new 12° bad threshold, not saturated.
    assert _tilt_score(10.0) > 0.0
