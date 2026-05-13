"""V14.3 photo_advice regression tests.

Each test pins a single behavioural invariant the audit flagged and
the V14.3 patch fixed:

1. Phrase rotation anchors on batch ``idx``, not filename — renaming
   a JPG must not rotate its review text.
2. Generic ``subject_fraction >= 0.25`` strength must NOT fire on
   macro / wildlife / abstract / landscape / architecture / astro
   genres (they have their own specific templates).
3. Canon-grounded templates carry a ``source`` field that surfaces
   in ``strengths_detail`` / ``weaknesses_detail``.
4. ``decision == "maybe"`` produces a one-sentence rationale built
   from final_stars + flags.
"""

from __future__ import annotations

import pytest

from pixcull.scoring.photo_advice import (
    _stable_pick,
    _synthesize_maybe_rationale,
    build_advice,
)


# ---------------------------------------------------------------------------
# 1. Phrase rotation now anchored on idx (rename-stable)
# ---------------------------------------------------------------------------

def test_idx_anchored_rotation_is_rename_stable():
    """Renaming the file must not change the picked phrase when idx
    is held constant."""
    row_a = {"filename": "img-001.jpg", "scene": "portrait",
             "subject_fraction": 0.6, "face_count": 1}
    row_b = {"filename": "totally-different-name.jpg", "scene": "portrait",
             "subject_fraction": 0.6, "face_count": 1}
    final = {"subject": 5.0, "technical": 5.0, "composition": 4.5,
             "light": 4.0, "moment": 4.0, "aesthetic": 5.0}
    ad_a = build_advice(row_a, final, "keep", idx=4)
    ad_b = build_advice(row_b, final, "keep", idx=4)
    assert ad_a["strengths"] == ad_b["strengths"]


def test_different_idx_can_rotate_synonyms():
    """Different rows in the same batch should usually pick different
    synonyms from the same template pool."""
    picks = set()
    for i in range(20):
        picks.add(_stable_pick(["alpha", "beta", "gamma"], i, "salt"))
    # With 3 phrases and 20 trials, we expect all 3 to appear.
    assert picks == {"alpha", "beta", "gamma"}


def test_same_idx_same_salt_is_deterministic():
    a = _stable_pick(["x", "y", "z"], 7, "abc")
    b = _stable_pick(["x", "y", "z"], 7, "abc")
    assert a == b


# ---------------------------------------------------------------------------
# 2. Generic subject phrase no longer leaks into specialty genres
# ---------------------------------------------------------------------------

GENERIC_SUBJECT_PHRASES = {
    "主体占画 30%+,视觉锚点稳",
    "主体比例舒适,不会过小或淹没",
    "主体在画面中分量足够",
}


@pytest.mark.parametrize("genre", [
    "macro", "wildlife", "abstract", "landscape", "architecture", "astro",
])
def test_generic_subject_excluded_from_specialty_genres(genre):
    """The portrait-coded "主体占画 30%+" phrase used to fire on macro
    shots etc.; V14.3 added anti_genres to gate it out."""
    row = {
        "filename": "x.jpg", "scene": genre,
        "subject_fraction": 0.5,             # would trigger generic
        "canon_figure_ground": 0.4,          # below the macro/landscape threshold
    }
    final = {"subject": 5.0, "technical": 3.0, "composition": 3.0,
             "light": 3.0, "moment": 3.0, "aesthetic": 3.0}
    ad = build_advice(row, final, "keep", idx=0)
    leaked = [s for s in ad["strengths"] if s in GENERIC_SUBJECT_PHRASES]
    assert not leaked, (
        f"genre={genre} got generic subject phrase {leaked} — should be filtered"
    )


def test_portrait_still_gets_generic_subject_phrase():
    """The filter applies to specialty genres only — portrait/event/
    documentary should still see the generic phrase if no more
    specific template fires."""
    row = {
        "filename": "p.jpg", "scene": "portrait",
        "subject_fraction": 0.5, "face_count": 0,  # no face → won't trigger portrait-specific
    }
    final = {"subject": 5.0, "technical": 3.0, "composition": 3.0,
             "light": 3.0, "moment": 3.0, "aesthetic": 3.0}
    ad = build_advice(row, final, "keep", idx=0)
    matched = [s for s in ad["strengths"] if s in GENERIC_SUBJECT_PHRASES]
    assert matched, "portrait should still pick up the generic subject phrase"


# ---------------------------------------------------------------------------
# 3. Canon source attached and surfaced
# ---------------------------------------------------------------------------

def test_canon_source_attached_to_zone_system_template():
    """Adams Zone System grounded templates must carry source attribution."""
    row = {
        "filename": "z.jpg", "scene": "landscape",
        "canon_zone_clip_pct": 0.005,   # passes Zone-clip strength
        "canon_midgray_offset": 0.02,   # passes midgray strength
    }
    final = {"subject": 5.0, "technical": 5.0, "composition": 5.0,
             "light": 5.0, "moment": 5.0, "aesthetic": 5.0}
    ad = build_advice(row, final, "keep", idx=0)
    sources = {d.get("source") for d in ad["strengths_detail"]}
    assert "Adams · Zone System" in sources


def test_canon_source_for_decisive_moment():
    """Cartier-Bresson 决定性瞬间 should carry the citation."""
    row = {
        "filename": "m.jpg", "scene": "street",
        "score_moment": 0.85,
    }
    final = {"subject": 3.0, "technical": 3.0, "composition": 3.0,
             "light": 3.0, "moment": 5.0, "aesthetic": 3.0}
    ad = build_advice(row, final, "keep", idx=0)
    sources = {d.get("source") for d in ad["strengths_detail"]}
    assert any(s and "Cartier-Bresson" in s for s in sources)


# ---------------------------------------------------------------------------
# 4. "maybe" rationale synthesis
# ---------------------------------------------------------------------------

def test_maybe_emits_rationale():
    row = {"filename": "x.jpg", "scene": "portrait", "flags": ""}
    final = {"subject": 4.5, "technical": 1.5, "composition": 3.0,
             "light": 2.0, "moment": 3.5, "aesthetic": 3.5}
    ad = build_advice(row, final, "maybe", idx=0)
    assert ad["rationale"], "maybe verdict must include a rationale"
    # Should mention the strongest (subject) and weakest (technical) axes
    assert "主体" in ad["rationale"]
    assert "技术" in ad["rationale"]


def test_keep_does_not_emit_rationale():
    row = {"filename": "x.jpg", "scene": "portrait", "flags": ""}
    final = {"subject": 5.0, "technical": 5.0, "composition": 5.0,
             "light": 5.0, "moment": 5.0, "aesthetic": 5.0}
    ad = build_advice(row, final, "keep", idx=0)
    assert ad.get("rationale") is None


def test_rationale_picks_up_flags():
    """Common flags should surface in the rationale text."""
    final = {"subject": 4.0, "technical": 4.0, "composition": 4.0,
             "light": 4.0, "moment": 4.0, "aesthetic": 4.0}
    out = _synthesize_maybe_rationale(final, "highlight_clip", 0)
    assert "高光剪切" in out
    out2 = _synthesize_maybe_rationale(final, "horizon_tilt", 0)
    assert "地平线斜" in out2


def test_rationale_mentions_inconsistencies():
    final = {"subject": 4.0, "technical": 4.0, "composition": 4.0,
             "light": 4.0, "moment": 4.0, "aesthetic": 4.0}
    out = _synthesize_maybe_rationale(final, "", inconsistencies_count=3)
    assert "多源判断分歧" in out


# ===========================================================================
# V17.3 — per-vertical phrase pools.  Templates registered under a vertical
# key fire ONLY for that vertical; runs without a vertical fall back to
# generic templates.  These tests pin that wedding/bird/etc tagged runs see
# business-flavored vocabulary, not the same language as untagged runs.
# ===========================================================================

# A "perfect" portrait row that hits multiple strength templates.
_PERFECT_PORTRAIT = {
    "filename":          "x.jpg",
    "scene":             "portrait",
    "face_count":        1,
    "subject_fraction":  0.40,
    "canon_lead_room":   0.75,
    "canon_thirds_concentration": 0.60,
    "canon_figure_ground": 0.75,
    "score_moment":      0.75,
    "laplacian_subject": 220,
    "laion_aes":         6.0,
    "score_exposure":    0.90,
    "canon_zone_clip_pct": 0.005,
}
_PERFECT_FINAL = {
    "subject":     5.0, "technical":  5.0, "composition": 5.0,
    "light":       5.0, "moment":     5.0, "aesthetic":   5.0,
}


def test_wedding_vertical_uses_wedding_phrases():
    """wedding-tagged run should produce phrases from VERTICAL_STRENGTH_TEMPLATES['wedding']
    not the generic portrait phrases."""
    ad = build_advice(_PERFECT_PORTRAIT, _PERFECT_FINAL, "keep",
                      idx=0, vertical="wedding")
    phrases = " ".join(ad["strengths"])
    # Wedding-specific vocabulary should appear
    assert "新人" in phrases or "婚纱" in phrases or "情感" in phrases or "透视舒服" in phrases
    # And the generic portrait subject phrase should NOT appear
    assert "主体在画面中分量足够" not in phrases


def test_no_vertical_falls_back_to_generic():
    """No vertical → V14.3 behavior — generic phrases, no wedding language."""
    ad = build_advice(_PERFECT_PORTRAIT, _PERFECT_FINAL, "keep", idx=0)
    phrases = " ".join(ad["strengths"])
    assert "新人" not in phrases
    # Should at least pick up some generic strength
    assert ad["strengths"], "should produce some generic strengths"


def test_unknown_vertical_falls_back_to_generic():
    """Unknown vertical key shouldn't crash and shouldn't produce
    vertical-specific text."""
    ad = build_advice(_PERFECT_PORTRAIT, _PERFECT_FINAL, "keep",
                      idx=0, vertical="__not_a_real_vertical__")
    phrases = " ".join(ad["strengths"])
    assert "新人" not in phrases


def test_bird_vertical_uses_bird_phrases():
    bird_row = {
        "filename": "b.jpg", "scene": "wildlife",
        "subject_fraction": 0.18, "canon_lead_room": 0.70,
        "score_moment": 0.70, "laplacian_subject": 220, "laion_aes": 6.0,
    }
    ad = build_advice(bird_row, _PERFECT_FINAL, "keep",
                      idx=0, vertical="bird")
    phrases = " ".join(ad["strengths"])
    assert "鸟" in phrases or "飞行" in phrases or "栖息" in phrases or "翅膀" in phrases


def test_landscape_vertical_uses_landscape_phrases():
    ls_row = {
        "filename": "ls.jpg", "scene": "landscape",
        "canon_thirds_concentration": 0.65,
        "canon_figure_ground": 0.70,
        "score_exposure": 0.92,
        "laion_aes": 6.5,
    }
    ad = build_advice(ls_row, _PERFECT_FINAL, "keep",
                      idx=0, vertical="landscape")
    phrases = " ".join(ad["strengths"])
    # At least one of the landscape-specific phrases should appear
    assert any(kw in phrases for kw in
                ("天地比例", "前中后景", "山水主次", "黄金时刻",
                 "蓝调时刻", "云海", "壁纸级"))


@pytest.fixture(autouse=True)
def _isolate_vertical_data_root(tmp_path, monkeypatch):
    """V17.5 isolation — any override JSONs that exist on the
    developer's machine (e.g. from live testing) must not leak
    into the vertical-pool tests, which check the V17.3 hand-written
    fallback behavior."""
    from pixcull import verticals as vmod
    monkeypatch.setattr(vmod, "_data_root", lambda: tmp_path)
    yield


def test_sports_vertical_uses_sports_phrases():
    sp_row = {
        "filename": "sp.jpg", "scene": "sports",
        "score_moment": 0.75,
        "laplacian_subject": 280,
    }
    ad = build_advice(sp_row, _PERFECT_FINAL, "keep",
                      idx=0, vertical="sports")
    phrases = " ".join(ad["strengths"])
    assert any(kw in phrases for kw in
                ("峰值动作", "极限姿态", "运动员", "1/1000"))


def test_kids_weakness_includes_specific_fix():
    """kids weakness for low aesthetic should produce a kids-specific
    fix ("让孩子放松"), not the generic aesthetic fix."""
    kids_row = {
        "filename": "k.jpg", "scene": "portrait",
        "face_count": 1, "subject_fraction": 0.4, "laion_aes": 3.0,
    }
    kids_final = {"subject": 4.0, "technical": 3.0, "composition": 3.0,
                   "light": 3.0, "moment": 2.0, "aesthetic": 1.0}
    ad = build_advice(kids_row, kids_final, "maybe",
                      idx=0, vertical="kids")
    fixes = " ".join(ad["suggestions"])
    # Kids-specific fix language
    assert "孩子" in fixes or "玩耍" in fixes or "童真" in fixes


def test_wedding_weakness_for_low_light():
    """Low light on a wedding-tagged run should fire the wedding-specific
    weakness 'new couple's face lacks light'."""
    weak_light_row = {
        "filename": "w.jpg", "scene": "portrait",
        "face_count": 2, "score_exposure": 0.20,
    }
    weak_final = {"subject": 4.0, "technical": 3.0, "composition": 3.0,
                   "light": 1.0, "moment": 3.0, "aesthetic": 3.0}
    ad = build_advice(weak_light_row, weak_final, "maybe",
                      idx=0, vertical="wedding")
    weak_phrases = " ".join(ad["weaknesses"])
    # Wedding-flavored weakness phrasing
    assert "新人" in weak_phrases or "脸部" in weak_phrases


def test_idx_rotation_still_works_with_vertical():
    """Phrase rotation by batch index should still produce different
    phrases across different rows even when a vertical is set."""
    picks = set()
    for i in range(10):
        ad = build_advice(_PERFECT_PORTRAIT, _PERFECT_FINAL, "keep",
                           idx=i, vertical="wedding")
        if ad["strengths"]:
            picks.add(ad["strengths"][0])
    # With 3 wedding subject phrases and 10 different idx values,
    # we expect at least 2 different phrases to appear.
    assert len(picks) >= 2, f"only saw {len(picks)} unique phrases: {picks}"
