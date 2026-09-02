"""v3.14 — a deliberate reframe is not a duplicate.

`group_near_dups` collapses on CLIP cosine alone.  CLIP is largely
invariant to framing — that is exactly what makes it good at "same
subject" and unable to tell the same frame twice from a 16:9 crop of it.
A crop is a decision the photographer made, and folding it into the
original hides one of the two things they wanted to compare.

This is PixCull's own hypothesis.  The fact-check confirmed only
Aftershoot's headline claim of tighter duplicate detection; the mechanism
was not confirmed, so this is off until measured.
"""
from pixcull.scoring.near_dup import (
    ASPECT_ENV, ASPECT_TOL, aspect_guard_enabled, split_by_aspect,
)

THREE_TWO = 3 / 2          # 1.500
SIXTEEN_NINE = 16 / 9      # 1.778
FOUR_THREE = 4 / 3         # 1.333


def test_a_crop_variant_is_split_out_of_its_group():
    got = split_by_aspect([["a.jpg", "b.jpg", "c.jpg"]],
                          {"a.jpg": THREE_TWO, "b.jpg": THREE_TWO,
                           "c.jpg": SIXTEEN_NINE})
    assert got == [["a.jpg", "b.jpg"]]


def test_two_frames_that_were_never_duplicates_leave_the_list_entirely():
    """A pair splitting into two differently-framed singletons is not a
    smaller duplicate group — it is not a duplicate group."""
    got = split_by_aspect([["a.jpg", "c.jpg"]],
                          {"a.jpg": THREE_TWO, "c.jpg": SIXTEEN_NINE})
    assert got == []


def test_identical_framing_is_left_alone():
    g = [["a.jpg", "b.jpg", "c.jpg"]]
    asp = {k: THREE_TWO for k in ("a.jpg", "b.jpg", "c.jpg")}
    assert split_by_aspect(g, asp) == [["a.jpg", "b.jpg", "c.jpg"]]


def test_lens_correction_noise_does_not_split_a_group():
    """A few pixels of correction crop is under one percent. Splitting on
    that would turn every real duplicate pair into two singletons."""
    asp = {"a.jpg": THREE_TWO, "b.jpg": THREE_TWO * 1.004}
    assert split_by_aspect([["a.jpg", "b.jpg"]], asp) == [["a.jpg", "b.jpg"]]


def test_the_tolerance_sits_between_noise_and_a_real_reframe():
    assert abs(FOUR_THREE - THREE_TWO) / THREE_TWO > ASPECT_TOL
    assert abs(SIXTEEN_NINE - THREE_TWO) / THREE_TWO > ASPECT_TOL
    assert 0.004 < ASPECT_TOL


def test_an_unreadable_frame_stays_with_the_group_it_was_in():
    """A missing header is missing information, not evidence of a
    different framing. Making an "unknown" group out of it would be worse
    than the collapse this guards against."""
    got = split_by_aspect([["a.jpg", "b.jpg"]],
                          {"a.jpg": THREE_TWO})       # b unknown
    assert got == [["a.jpg", "b.jpg"]]


def test_a_zero_or_negative_aspect_is_treated_as_unknown():
    got = split_by_aspect([["a.jpg", "b.jpg"]],
                          {"a.jpg": THREE_TWO, "b.jpg": 0.0})
    assert got == [["a.jpg", "b.jpg"]]


def test_groups_come_back_largest_first():
    got = split_by_aspect(
        [["a.jpg", "b.jpg", "c.jpg", "d.jpg"]],
        {"a.jpg": THREE_TWO, "b.jpg": THREE_TWO, "c.jpg": THREE_TWO,
         "d.jpg": SIXTEEN_NINE})
    assert got == [["a.jpg", "b.jpg", "c.jpg"]]


def test_the_guard_is_off_until_it_has_been_measured(monkeypatch):
    monkeypatch.delenv(ASPECT_ENV, raising=False)
    assert aspect_guard_enabled() is False
    monkeypatch.setenv(ASPECT_ENV, "1")
    assert aspect_guard_enabled() is True


def test_the_guard_setting_is_part_of_the_grouping_cache_key():
    """Toggling it must not return the groups computed under the other
    setting — the shape of every cache bug in this file's history."""
    import inspect
    from pixcull.report import serve_app
    src = inspect.getsource(serve_app._cached_near_dup_groups)
    assert "aspect_guard_enabled()" in src.split("with _NEARDUP_CACHE_LOCK")[0]


def test_aspects_are_read_only_for_frames_that_already_grouped():
    """A 5,000-frame run must not pay 5,000 header reads for a
    refinement that touches a few dozen."""
    import inspect
    from pixcull.report import serve_app
    src = inspect.getsource(serve_app._cached_near_dup_groups)
    body = src[src.index("if aspect_guard_enabled() and groups:"):]
    assert "for g in groups:" in body and "for fn in g:" in body
