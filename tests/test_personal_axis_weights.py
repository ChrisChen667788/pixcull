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
