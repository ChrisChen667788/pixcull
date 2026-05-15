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


@pytest.fixture(autouse=True)
def _isolate_vertical_overrides(tmp_path, monkeypatch):
    """V18 — isolate vertical-data root so any policy_override.json or
    phrase_override.json files written during real usage don't pollute
    decide() tests that exercise the V17.2 baseline policies.

    V28 — also patch ``pixcull.users._app_data_root`` because that's
    where ``vertical_root`` now resolves through.
    """
    from pixcull import verticals as vmod
    from pixcull import users as _users_mod
    monkeypatch.setattr(vmod, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(_users_mod, "_app_data_root", lambda: tmp_path)
    yield


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
    """V18 doc-tie: wildlife + astro joined the tolerant set after the
    100CANON scan revealed 22 false-cull wildlife shots (small/distant
    subjects shot on telephoto — birds across a lake, monkeys at
    canopy distance — where the small subject IS the genre)."""
    assert "landscape" in _TINY_SUBJECT_TOLERANT_SCENES
    assert "architecture" in _TINY_SUBJECT_TOLERANT_SCENES
    assert "street" in _TINY_SUBJECT_TOLERANT_SCENES
    assert "wildlife" in _TINY_SUBJECT_TOLERANT_SCENES   # V18 addition
    assert "astro" in _TINY_SUBJECT_TOLERANT_SCENES      # V18 addition
    # Portraits + stilllife still should NOT be tolerant.
    assert "portrait" not in _TINY_SUBJECT_TOLERANT_SCENES
    assert "stilllife" not in _TINY_SUBJECT_TOLERANT_SCENES


def test_v18_wildlife_tolerates_no_clear_subject(config):
    """V18: wildlife shots with small/distant subjects are valid (genre
    norm). Before V18, no_clear_subject hard-culled them.

    Verified on the V17.13 100CANON scan: 22 wildlife shots flipped
    from cull → 17 keep + 5 maybe. The flips were all shots that
    scored ≥0.5 (high-quality shots killed only by this one flag)."""
    dec, _ = decide(0.85, ["no_clear_subject"], config, scene="wildlife")
    assert dec is Decision.KEEP


def test_v18_astro_tolerates_no_clear_subject(config):
    """V18: starfield / milky-way shots don't have a "clear subject" by
    the detector's measure. Tolerate."""
    dec, _ = decide(0.75, ["no_clear_subject"], config, scene="astro")
    assert dec is Decision.KEEP


def test_v18_wildlife_still_hard_culls_other_flags(config):
    """The V18 exemption is scoped to no_clear_subject. Closed eyes,
    motion blur on face, severely overexposed still hard-cull a
    wildlife shot."""
    for flag in ("closed_eyes", "motion_blur_on_face",
                  "severely_overexposed"):
        dec, _ = decide(0.85, [flag], config, scene="wildlife")
        assert dec is Decision.CULL, f"{flag} should still cull wildlife"


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


# ============================================================================
# V17.2 — per-vertical policy override.  decide(vertical=...) reads the
# registered VerticalPolicy and shifts thresholds + tolerated flags.
# ============================================================================


def test_vertical_unset_is_no_op(config):
    """Calling decide() without ``vertical=`` must reproduce V1.x behavior."""
    score = 0.60
    dec_no_vert, _ = decide(score, [], config, scene="portrait")
    dec_none, _   = decide(score, [], config, scene="portrait", vertical=None)
    dec_empty, _  = decide(score, [], config, scene="portrait", vertical="")
    assert dec_no_vert is dec_none is dec_empty


def test_vertical_unknown_falls_through(config):
    """Unknown vertical key shouldn't crash or change behavior — it's
    treated as if the kwarg wasn't passed."""
    score = 0.60
    dec_a, _ = decide(score, [], config, scene="portrait")
    dec_b, _ = decide(score, [], config, scene="portrait",
                       vertical="__not_a_real_vertical__")
    assert dec_a is dec_b


def test_kids_keep_min_delta_promotes_marginal_score(config):
    """Score that's MAYBE on the default 6.5 keep-line should land KEEP
    on kids (which has keep_min_delta = -0.05)."""
    # 0.61 is below default keep_min (0.65) → MAYBE without vertical.
    dec_default, _ = decide(0.61, [], config, scene="portrait")
    assert dec_default is Decision.MAYBE
    # With kids vertical, threshold drops to ~0.60 → row tips to KEEP.
    dec_kids, _ = decide(0.61, [], config, scene="portrait", vertical="kids")
    assert dec_kids is Decision.KEEP


def test_landscape_keep_min_delta_demotes_marginal_score(config):
    """Score that's barely KEEP on the default 6.5 keep-line should land
    MAYBE on landscape (which has keep_min_delta = +0.03 — stricter)."""
    # 0.66 sits just above default keep_min (0.65) → KEEP without vertical.
    dec_default, _ = decide(0.66, [], config, scene="landscape")
    assert dec_default is Decision.KEEP
    # With landscape vertical, threshold rises to ~0.68 → tips to MAYBE.
    dec_landscape, _ = decide(0.66, [], config, scene="landscape",
                                vertical="landscape")
    assert dec_landscape is Decision.MAYBE


def test_kids_tolerates_motion_blur_on_face(config):
    """kids policy adds motion_blur_on_face to tolerated_flags. Without
    vertical the flag hard-culls; with kids vertical the row falls
    through to score-based decision."""
    dec_default, _ = decide(0.72, ["motion_blur_on_face"], config,
                              scene="portrait")
    assert dec_default is Decision.CULL

    dec_kids, _ = decide(0.72, ["motion_blur_on_face"], config,
                           scene="portrait", vertical="kids")
    assert dec_kids is Decision.KEEP   # 0.72 > kids keep_min (0.60)


def test_kids_does_not_tolerate_severe_overexposure(config):
    """tolerated_flags is scoped — kids tolerates motion_blur but NOT
    severely_overexposed (which is always destructive)."""
    dec_kids, _ = decide(0.72, ["severely_overexposed"], config,
                           scene="portrait", vertical="kids")
    assert dec_kids is Decision.CULL


def test_landscape_tolerates_severely_blurry_via_vertical(config):
    """The V0.8 scene-based exemption already lets landscape tolerate
    severely_blurry. Vertical policy is independent and additive — pass
    a different scene and the vertical-level exemption alone should
    still demote."""
    # scene=portrait wouldn't normally tolerate severely_blurry; but
    # the landscape vertical's policy says it should.
    dec_with_vert, _ = decide(0.72, ["severely_blurry"], config,
                                scene="portrait", vertical="landscape")
    assert dec_with_vert is Decision.KEEP


def test_wedding_tolerates_shadow_clipping(config):
    """Wedding's policy tolerates `shadows_clipped` (not in the default
    hard_cull set anyway, but this confirms the vertical doesn't add
    spurious cull conditions)."""
    # shadows_clipped is NOT in default hard_cull so this is mostly a
    # smoke check — high score should land KEEP regardless of flag.
    dec_w, _ = decide(0.80, ["shadows_clipped"], config,
                       scene="portrait", vertical="wedding")
    assert dec_w is Decision.KEEP


def test_threshold_clamps_to_unit_range(config):
    """Pathologically large delta shouldn't push threshold past 1.0."""
    # We don't actually have such a vertical, but the clamp logic in
    # decide() should withstand one. Use ad-hoc monkeypatch via a
    # custom Vertical fixture below if needed; this just smoke-tests
    # that the existing clamp doesn't crash on the 10 real verticals.
    for vkey in ("kids", "landscape", "wedding", "sports", "bird"):
        # Score at extreme ends should still produce a valid decision.
        for score in (0.0, 0.5, 1.0):
            dec, _ = decide(score, [], config, scene="portrait", vertical=vkey)
            assert dec in (Decision.KEEP, Decision.MAYBE, Decision.CULL)
