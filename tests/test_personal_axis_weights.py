"""v2.14-P1 — axis-aware personalization: wire personal_learn.axis_weights
into fuse_score's per-dim weights.

Pins the contract: no-op without a profile (generic runs byte-identical),
no-op for an uninformative (equal) profile, a correct-signed tilt toward the
axes the user values, total-weight-budget preserved, and the tilt clamped so a
noisy profile nudges rather than overrides.
"""

import pytest

from pixcull.config import PixCullConfig
from pixcull.scoring.fusion import fuse_score, _personalize_weights, _N_RUBRIC_AXES
from pixcull.scoring.personal_learn import axis_weights
from pixcull.scoring.personalized import PersonalProfile


@pytest.fixture(scope="module")
def config():
    return PixCullConfig.load()


def _raw(**kw):
    base = {
        "laion_aes": 5.0, "clipiqa": 0.5, "laplacian_global": 200,
        "highlight_clip_pct": 0, "shadow_clip_pct": 0, "mean_luma": 128,
        "composition_score": 0.5, "moment_score": None,
    }
    base.update(kw)
    return base


# ── _personalize_weights ─────────────────────────────────────────────────────

def test_no_pref_or_empty_is_unchanged():
    w = {"sharpness": 0.25, "composition": 0.2, "exposure": 0.2, "aesthetic": 0.25, "moment": 0.1}
    assert _personalize_weights(w, None) == w
    assert _personalize_weights(w, {}) == w


def test_equal_pref_is_noop():
    w = {"sharpness": 0.25, "composition": 0.2, "exposure": 0.2, "aesthetic": 0.25, "moment": 0.1}
    eq = {a: 1.0 / _N_RUBRIC_AXES for a in
          ("technical", "subject", "composition", "light", "moment", "aesthetic")}
    out = _personalize_weights(w, eq)
    for k in w:
        assert out[k] == pytest.approx(w[k])


def test_composition_heavy_pref_tilts_and_preserves_total():
    w = {"sharpness": 0.25, "composition": 0.2, "exposure": 0.2, "aesthetic": 0.25, "moment": 0.1}
    # user weights composition far above the rest
    pref = {"technical": 0.05, "subject": 0.05, "composition": 0.6,
            "light": 0.1, "moment": 0.1, "aesthetic": 0.1}
    out = _personalize_weights(w, pref)
    assert sum(out.values()) == pytest.approx(sum(w.values()))   # budget preserved
    # composition dim's SHARE of the budget must rise; sharpness (technical, low pref) must fall
    assert out["composition"] / sum(out.values()) > w["composition"] / sum(w.values())
    assert out["sharpness"] / sum(out.values()) < w["sharpness"] / sum(w.values())


def test_tilt_is_clamped_no_collapse():
    w = {"sharpness": 0.25, "composition": 0.2, "exposure": 0.2, "aesthetic": 0.25, "moment": 0.1}
    total = sum(w.values())
    # pathological profile: composition is "everything". The per-dim tilt is
    # clamped to rel∈[0.5, 2.0] BEFORE re-normalisation, so the down-tilted
    # dims keep ≥0.5× their pre-renorm weight and never collapse to zero.
    pref = {"technical": 0.0, "subject": 0.0, "composition": 1.0,
            "light": 0.0, "moment": 0.0, "aesthetic": 0.0}
    out = _personalize_weights(w, pref)
    assert sum(out.values()) == pytest.approx(total)        # budget preserved
    assert all(v > 0 for v in out.values())                 # nothing collapses
    # composition share rose; a down-tilted dim's SHARE stays ≥0.5× original
    # (rel floor 0.5) — proof the clamp prevents an override.
    assert out["composition"] / total > w["composition"] / total
    assert (out["sharpness"] / total) >= 0.5 * (w["sharpness"] / total)


# ── fuse_score integration ───────────────────────────────────────────────────

def test_fuse_score_axis_pref_none_matches_4arg(config):
    raw = _raw(composition_score=0.9, laplacian_global=50)
    assert (fuse_score(raw, [], "landscape", config)
            == fuse_score(raw, [], "landscape", config, axis_pref=None))


def test_composition_lover_scores_comp_strong_photo_higher(config):
    # photo strong on composition, weak on sharpness
    raw = _raw(composition_score=0.95, laplacian_global=40)
    pref = {"technical": 0.05, "subject": 0.05, "composition": 0.6,
            "light": 0.1, "moment": 0.1, "aesthetic": 0.1}
    generic = fuse_score(raw, [], "landscape", config)["final"]
    personal = fuse_score(raw, [], "landscape", config, axis_pref=pref)["final"]
    assert personal > generic   # the comp-lover rewards this comp-strong frame


# ── axis_weights → fuse_score (the real wiring) ──────────────────────────────

def _profile(keep_means, cull_means, n=120):
    return PersonalProfile(
        user_id="test", n_annotations=n, keep_rate=0.6, cull_rate=0.2,
        keep_threshold_shift=0.0, axis_keep_means=keep_means,
        axis_cull_means=cull_means, most_cared_axis=None,
    )


def test_axis_weights_from_profile_drives_the_tilt(config):
    # a user whose keep vs cull diverges most on composition
    prof = _profile(
        keep_means={"technical": 3.0, "subject": 3.0, "composition": 4.5,
                    "light": 3.0, "moment": 3.0, "aesthetic": 3.0},
        cull_means={"technical": 2.8, "subject": 2.8, "composition": 1.5,
                    "light": 2.8, "moment": 2.8, "aesthetic": 2.8},
    )
    aw = axis_weights(prof)
    assert max(aw, key=lambda a: aw[a]) == "composition"
    raw = _raw(composition_score=0.95, laplacian_global=40)
    generic = fuse_score(raw, [], "landscape", config)["final"]
    personal = fuse_score(raw, [], "landscape", config, axis_pref=aw)["final"]
    assert personal > generic


# ── v3.81 — clamping a negative gap threw away the evidence ───────────

def _profile(keep_means, cull_means):
    from pixcull.scoring.personal_learn import PersonalProfile
    return PersonalProfile(
        user_id="t", n_annotations=158, keep_rate=0.81, cull_rate=0.19,
        keep_threshold_shift=0.0,
        axis_keep_means=dict(keep_means), axis_cull_means=dict(cull_means),
        most_cared_axis=None)


def test_the_first_real_correction_set_weights_nothing():
    """Measured, not invented. The first genuinely blind correction set
    (158 frames, two verticals, 2026-09-12) had four of six axes pointing
    the WRONG way: the frames the photographer culled scored higher on
    composition, subject, light and aesthetic than the ones they kept.

    `max(0.0, gap)` dropped all four to zero and put the entire weight on
    the two tiny positives that survived, +0.08 and +0.12 stars:

        technical 0.4 · moment 0.6 · everything else 0.0

    A confident claim that this photographer does not care about
    composition, built from noise."""
    from pixcull.scoring.personal_learn import AXES, axis_weights
    keep = {"technical": 4.600, "subject": 3.680, "composition": 4.560,
            "light": 4.270, "moment": 1.080, "aesthetic": 2.960}
    cull = {"technical": 4.520, "subject": 3.830, "composition": 4.720,
            "light": 4.410, "moment": 0.960, "aesthetic": 3.170}
    w = axis_weights(_profile(keep, cull))
    equal = 1.0 / len(AXES)
    assert all(abs(v - equal) < 1e-9 for v in w.values()), (
        f"weighted {w} from gaps of +0.08 and +0.12 with four axes "
        "pointing the other way")


def test_a_wrong_way_gap_as_big_as_the_right_way_one_weights_nothing():
    """The rule stated on its own. A negative gap is not an absence of
    evidence, it is evidence against."""
    from pixcull.scoring.personal_learn import AXES, axis_weights
    keep = {a: 3.0 for a in AXES}
    cull = dict(keep)
    keep["moment"] = 3.6          # gap +0.6, the right way
    keep["composition"] = 2.3     # gap -0.7, the wrong way and bigger
    w = axis_weights(_profile(keep, cull))
    equal = 1.0 / len(AXES)
    assert all(abs(v - equal) < 1e-9 for v in w.values()), (
        f"weighted {w} while one axis disagreed harder than the best "
        "axis agreed")


def test_a_real_preference_is_still_learned():
    """The guard must not refuse everything — a photographer who
    genuinely favours one axis has to come through."""
    from pixcull.scoring.personal_learn import axis_weights
    keep = {"technical": 3.0, "subject": 4.5, "composition": 3.0,
            "light": 3.0, "moment": 3.0, "aesthetic": 3.0}
    cull = {"technical": 3.0, "subject": 2.0, "composition": 3.0,
            "light": 3.0, "moment": 3.0, "aesthetic": 3.0}
    w = axis_weights(_profile(keep, cull))
    assert w["subject"] > 0.9, f"a 2.5-star gap on subject was not learned: {w}"


def test_a_gap_too_small_to_act_on_is_not_acted_on():
    """0.12 stars, because that is the number that actually fooled it —
    the largest surviving gap in the first blind correction set.

    An earlier version of this test used `MIN_MEANINGFUL_GAP * 0.5`,
    which reads well and cannot fail: set the constant to zero and the
    test's own gap goes to zero with it. A test derived from the thing it
    is checking checks nothing."""
    from pixcull.scoring.personal_learn import AXES, MIN_MEANINGFUL_GAP, axis_weights
    assert MIN_MEANINGFUL_GAP > 0.12, (
        "the floor no longer excludes the gap that produced a confident "
        "wrong profile from real corrections")
    keep = {a: 3.0 for a in AXES}
    cull = dict(keep)
    keep["light"] = 3.12                      # +0.12, the measured noise
    w = axis_weights(_profile(keep, cull))
    equal = 1.0 / len(AXES)
    assert all(abs(v - equal) < 1e-9 for v in w.values()), (
        f"weighted {w} on a 0.12-star gap")


def test_the_weights_still_sum_to_one():
    from pixcull.scoring.personal_learn import AXES, axis_weights
    for keep, cull in (
        ({a: 3.0 for a in AXES}, {a: 3.0 for a in AXES}),
        ({**{a: 3.0 for a in AXES}, "subject": 4.5},
         {**{a: 3.0 for a in AXES}, "subject": 2.0}),
    ):
        w = axis_weights(_profile(keep, cull))
        assert abs(sum(w.values()) - 1.0) < 1e-9
