"""v2.14 — moment-axis de-stub tests.

Until v2.14 the "moment" fusion axis was a constant 0.5 for EVERY frame and two
of its three rubric checks always returned None — so moment carried no
discriminative signal and could never be learned by the rescorer (a constant
feature is useless). These tests pin the new behaviour:

* a real ``moment_score`` flows through fusion when a signal exists;
* an explicit ``None`` (worker writes this on no-signal frames) and an absent
  key both fall back to the deliberate neutral 0.5 placeholder;
* ``emotion_present`` is evaluated from ``wedding_moment_confidence`` for
  wedding scenes only; ``action_at_peak`` stays honestly unmodelled.
"""

import pytest

from pixcull.config import PixCullConfig
from pixcull.scoring.fusion import fuse_score
from pixcull.scoring import rubric_decompose


@pytest.fixture(scope="module")
def config():
    return PixCullConfig.load()


def _fuse(config, scene="landscape", **raw):
    base = {
        "laion_aes": 5.0, "clipiqa": 0.5, "laplacian_global": 200,
        "highlight_clip_pct": 0, "shadow_clip_pct": 0, "mean_luma": 128,
    }
    base.update(raw)
    return fuse_score(base, [], scene, config)


# ── fusion: moment_score flow ────────────────────────────────────────────────

def test_moment_score_present_flows_through(config):
    assert _fuse(config, moment_score=0.9)["moment"] == pytest.approx(0.9)
    assert _fuse(config, moment_score=0.1)["moment"] == pytest.approx(0.1)


def test_moment_score_none_falls_back_to_neutral(config):
    # explicit None key — worker writes this on no-signal (landscape/no-face) frames
    assert _fuse(config, moment_score=None)["moment"] == pytest.approx(0.5)
    # absent key — older rows / CSV round-trips
    assert _fuse(config)["moment"] == pytest.approx(0.5)


def test_moment_score_nan_falls_back_to_neutral(config):
    # REGRESSION GUARD: fuse_score is called with row.to_dict() from a pandas
    # DataFrame, where worker's None becomes NaN. An un-coalesced NaN clamps
    # score_final to 1.0 (== always keep) for EVERY no-signal frame. Must be
    # coalesced to the neutral 0.5 just like None.
    out = _fuse(config, moment_score=float("nan"))
    assert out["moment"] == pytest.approx(0.5)
    assert 0.0 <= out["final"] <= 1.0
    assert out["final"] == pytest.approx(0.5, abs=0.5)  # not silently saturated to 1.0


def test_composition_score_none_or_nan_falls_back_to_neutral(config):
    assert _fuse(config, composition_score=None)["composition"] == pytest.approx(0.5)
    assert _fuse(config, composition_score=float("nan"))["composition"] == pytest.approx(0.5)


def test_strong_moment_outscores_neutral_when_weighted(config):
    # A confident moment must not score identically to the neutral placeholder
    # (only when the scene template actually weights moment).
    w = config.template_for("wedding").weights.get("moment", 0.0)
    strong = _fuse(config, scene="wedding", moment_score=0.95)["final"]
    neutral = _fuse(config, scene="wedding", moment_score=None)["final"]
    if w > 0:
        assert strong > neutral
    else:
        assert strong == pytest.approx(neutral)


# ── rubric: moment-axis checks ───────────────────────────────────────────────

def test_emotion_present_from_wedding_confidence():
    ev = rubric_decompose._check_eval
    assert ev("emotion_present", {"wedding_moment_confidence": 0.8}) is True
    assert ev("emotion_present", {"wedding_moment_confidence": 0.3}) is False
    assert ev("emotion_present", {"wedding_moment_confidence": None}) is None
    assert ev("emotion_present", {}) is None  # non-wedding frame → skip, not faked


def test_action_at_peak_stays_unmodelled():
    # No honest signal exists for stills — must stay None (skipped from the
    # denominator) rather than fabricate a value.
    ev = rubric_decompose._check_eval
    assert ev("action_at_peak", {"wedding_moment_confidence": 0.9}) is None
    assert ev("action_at_peak", {}) is None


def test_not_blink_check_unchanged():
    ev = rubric_decompose._check_eval
    assert ev("not_blink_or_mid_yawn", {"face_count": 1, "flags": []}) is True
    assert ev("not_blink_or_mid_yawn", {"face_count": 1, "flags": ["closed_eyes"]}) is False
    assert ev("not_blink_or_mid_yawn", {"face_count": 0}) is None  # no face → skip
