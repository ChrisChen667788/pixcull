"""Tests for scene-aware decide() — the V0.6 fix for `no_clear_subject` hard-cull
over-firing on minimalist architecture/landscape/street compositions.
"""

from __future__ import annotations

import pytest

from pixcull.config import PixCullConfig
from pixcull.scoring.decision import (
    Decision,
    _BLUR_TOLERANT_SCENES,
    _TINY_SUBJECT_TOLERANT_SCENES,
    decide,
)


@pytest.fixture(scope="module")
def config() -> PixCullConfig:
    return PixCullConfig.load()


def test_no_clear_subject_is_hard_cull_for_portrait(config):
    """Portraits without a clear subject really are broken — cull must stick."""
    dec, reasons = decide(0.72, ["no_clear_subject"], config, scene="portrait")
    assert dec is Decision.CULL
    assert "no_clear_subject" in reasons


def test_no_clear_subject_is_soft_for_landscape(config):
    """Tiny subjects are compositionally normal for landscape."""
    dec, _ = decide(0.72, ["no_clear_subject"], config, scene="landscape")
    assert dec is Decision.KEEP


def test_no_clear_subject_is_soft_for_architecture(config):
    """Architecture shots routinely embed the building in environment."""
    dec, _ = decide(0.72, ["no_clear_subject"], config, scene="architecture")
    assert dec is Decision.KEEP


def test_no_clear_subject_is_soft_for_street(config):
    dec, _ = decide(0.72, ["no_clear_subject"], config, scene="street")
    assert dec is Decision.KEEP


def test_other_hard_cull_flags_still_fire_on_tolerant_scenes(config):
    """The exemption is scoped to `no_clear_subject` only. Closed eyes, blown
    highlights, etc. still mean cull everywhere."""
    for flag in ("closed_eyes", "severely_overexposed", "motion_blur_on_face"):
        dec, reasons = decide(0.72, [flag], config, scene="landscape")
        assert dec is Decision.CULL, f"{flag} should still hard-cull"
        assert flag in reasons


def test_missing_scene_uses_strict_interpretation(config):
    """When scene is None (caller omitted it), we don't know whether it's a
    minimalist composition. Fall back to the strict hard-cull behavior."""
    dec, _ = decide(0.72, ["no_clear_subject"], config, scene=None)
    assert dec is Decision.CULL


def test_tolerant_scene_set_matches_templates():
    """Doc-tie: these three scenes are where we demoted the flag."""
    assert "landscape" in _TINY_SUBJECT_TOLERANT_SCENES
    assert "architecture" in _TINY_SUBJECT_TOLERANT_SCENES
    assert "street" in _TINY_SUBJECT_TOLERANT_SCENES
    # Portraits / stilllife / wildlife should NOT be tolerant.
    assert "portrait" not in _TINY_SUBJECT_TOLERANT_SCENES
    assert "stilllife" not in _TINY_SUBJECT_TOLERANT_SCENES
    assert "wildlife" not in _TINY_SUBJECT_TOLERANT_SCENES


def test_score_based_decisions_still_work(config):
    """Without any hard-cull flags, decide() falls through to score thresholds."""
    assert decide(0.90, [], config, scene="portrait")[0] is Decision.KEEP
    assert decide(0.30, [], config, scene="portrait")[0] is Decision.CULL
    assert decide(0.55, [], config, scene="portrait")[0] is Decision.MAYBE


def test_strictness_presets_shift_thresholds(config):
    """Lenient should keep more, strict should keep fewer. Scene-tolerance is
    independent of strictness."""
    score = 0.60  # sits in the maybe band at standard (6.5/4.0)
    assert decide(score, [], config, scene="portrait", strictness="lenient")[0] is Decision.KEEP
    assert decide(score, [], config, scene="portrait", strictness="strict")[0] is Decision.MAYBE


# --------------------------------------------------- V0.8 hard-cull loosening
def test_severely_underexposed_is_not_hard_cull(config):
    """V0.8: `severely_underexposed` is now advisory across all scenes.

    Rationale: 0/9 correct culls on the V0.7 golden set depended on it, while
    3 keep-photos (AB4A4609/4644 stilllife, 20210801-3J0A8098 landscape) were
    wrongly culled by it. Underexposure is either intentional (low-key,
    silhouette, mood) or recoverable from RAW; `score_exposure` already
    reflects the luma signal in `final_score`.
    """
    for scene in ("stilllife", "landscape", "portrait", "event", "wildlife", None):
        dec, _ = decide(0.72, ["severely_underexposed"], config, scene=scene)
        assert dec is Decision.KEEP, f"scene={scene}: severely_underexposed must not hard-cull"


def test_severely_underexposed_low_score_still_culls_via_score(config):
    """The flag being advisory doesn't let garbage through — a low final_score
    still hits `cull_max` on its own."""
    dec, _ = decide(0.30, ["severely_underexposed"], config, scene="portrait")
    assert dec is Decision.CULL


def test_severely_blurry_still_hard_culls_non_landscape_scenes(config):
    """V0.8: the blur exemption is scoped to landscape only. Portrait,
    stilllife, event, wildlife still hard-cull on severely_blurry."""
    for scene in ("portrait", "stilllife", "event", "wildlife", "architecture", "street"):
        dec, reasons = decide(0.72, ["severely_blurry"], config, scene=scene)
        assert dec is Decision.CULL, f"scene={scene}: severely_blurry should still hard-cull"
        assert "severely_blurry" in reasons


def test_severely_blurry_is_soft_on_landscape(config):
    """V0.8: long-exposure water / clouds / ICM are legitimate landscape techniques.
    A high-score landscape with `severely_blurry` should keep, not cull."""
    dec, _ = decide(0.72, ["severely_blurry"], config, scene="landscape")
    assert dec is Decision.KEEP


def test_severely_blurry_landscape_low_score_goes_to_maybe(config):
    """A mid-band landscape with severely_blurry shouldn't be hard-culled;
    falls through to the score bands — 3J0A3760 (0.455) / 3J0A4411 (0.511)
    are the two photos this fix was targeting. Both land in MAYBE rather
    than CULL — within-one improvement."""
    dec, _ = decide(0.50, ["severely_blurry"], config, scene="landscape")
    assert dec is Decision.MAYBE


def test_blur_tolerant_scene_set_is_landscape_only(config):
    """Doc-tie: V0.8 only exempts landscape from the blur hard-cull. We want
    portrait / wildlife to still cull on blur (subject out-of-focus is a real
    failure there)."""
    assert "landscape" in _BLUR_TOLERANT_SCENES
    for s in ("portrait", "stilllife", "event", "wildlife", "architecture", "street"):
        assert s not in _BLUR_TOLERANT_SCENES, f"{s} should not be blur-tolerant"


def test_missing_scene_still_hard_culls_blur(config):
    """Scene=None (caller omitted it) should fall back to the strict blur
    interpretation — we can't assume the intent was long-exposure."""
    dec, _ = decide(0.72, ["severely_blurry"], config, scene=None)
    assert dec is Decision.CULL


def test_other_hard_cull_flags_still_fire_on_landscape(config):
    """V0.8 exemption is scoped to `severely_blurry` + `no_clear_subject` on
    landscape. Other hard-cull flags still fire."""
    for flag in ("closed_eyes", "severely_overexposed", "motion_blur_on_face"):
        dec, _ = decide(0.72, [flag], config, scene="landscape")
        assert dec is Decision.CULL, f"{flag} should still hard-cull on landscape"
