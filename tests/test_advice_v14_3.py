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
