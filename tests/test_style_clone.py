"""Tests for pixcull.style.clone — style-clone V1.

Covers
------
* Empty profile returns max distance for everything
* Identical row → near-zero distance
* Median-of-references is robust to one outlier ref
* Scene mismatch adds the documented penalty
* Missing axes / scene degrade gracefully (no exceptions)
* compute_distances round-trips filename → distance map
"""

from pixcull.style.clone import (
    AXIS_NAMES,
    compute_distances,
    learn_style_profile,
    style_distance,
)


def _row(**axis_stars):
    """Build a scores.csv-shaped row from keyword axis stars.

    Example: _row(technical=4.5, scene="landscape")
    """
    out = {}
    for axis in AXIS_NAMES:
        if axis in axis_stars:
            out[f"rubric_{axis}_stars"] = axis_stars[axis]
    if "filename" in axis_stars:
        out["filename"] = axis_stars["filename"]
    if "scene" in axis_stars:
        out["scene"] = axis_stars["scene"]
    return out


def test_empty_profile_is_max_distance():
    profile = learn_style_profile([])
    assert profile["n_refs"] == 0
    # Any non-empty row should be the max distance.
    d = style_distance(_row(technical=5, scene="landscape"), profile)
    assert d == 1.0


def test_identical_row_is_near_zero_distance():
    refs = [
        _row(technical=4, subject=4, composition=4,
             light=4, moment=4, aesthetic=4, scene="landscape"),
    ]
    profile = learn_style_profile(refs)
    # A row exactly matching the reference axes + scene
    d = style_distance(
        _row(technical=4, subject=4, composition=4,
             light=4, moment=4, aesthetic=4, scene="landscape"),
        profile,
    )
    assert d == 0.0


def test_one_axis_one_star_off_gives_small_positive_distance():
    refs = [
        _row(technical=4, subject=4, composition=4,
             light=4, moment=4, aesthetic=4, scene="landscape"),
    ]
    profile = learn_style_profile(refs)
    d = style_distance(
        _row(technical=5, subject=4, composition=4,
             light=4, moment=4, aesthetic=4, scene="landscape"),
        profile,
    )
    # 1 star out of 5 → 0.2 / 6 axes → ~0.033
    assert 0.01 < d < 0.08


def test_outlier_ref_does_not_dominate_median():
    refs = [
        _row(technical=4.0, scene="landscape"),
        _row(technical=4.1, scene="landscape"),
        _row(technical=4.0, scene="landscape"),
        _row(technical=4.2, scene="landscape"),
        _row(technical=4.0, scene="landscape"),
        # One outlier — wouldn't survive a mean but stays out of
        # the median bucket.
        _row(technical=0.0, scene="landscape"),
    ]
    profile = learn_style_profile(refs)
    assert 3.9 <= profile["axis_median"]["technical"] <= 4.1


def test_unseen_scene_adds_penalty():
    refs = [_row(technical=4, scene="portrait")]
    profile = learn_style_profile(refs)
    # Same axis stars but completely unrelated scene
    same_scene = style_distance(_row(technical=4, scene="portrait"), profile)
    diff_scene = style_distance(_row(technical=4, scene="landscape"), profile)
    assert diff_scene > same_scene
    # Penalty should be ≈ _SCENE_PENALTY since axis distance is 0
    assert 0.12 < diff_scene < 0.18


def test_missing_axis_in_row_does_not_throw():
    refs = [_row(technical=4, subject=4, scene="landscape")]
    profile = learn_style_profile(refs)
    # Row lacking any axis info — should still produce a number
    d = style_distance({"filename": "x.jpg", "scene": "landscape"}, profile)
    assert isinstance(d, float)
    assert 0 <= d <= 1


def test_missing_scene_adds_half_penalty():
    refs = [_row(technical=4, scene="landscape")]
    profile = learn_style_profile(refs)
    none_scene = style_distance(_row(technical=4), profile)
    same_scene = style_distance(_row(technical=4, scene="landscape"), profile)
    # No scene → half penalty (still > 0, < full mismatch)
    assert same_scene < none_scene
    assert 0.05 < none_scene < 0.1


def test_compute_distances_returns_full_map():
    refs = [_row(technical=4, scene="landscape")]
    profile = learn_style_profile(refs)
    rows = [
        _row(filename="a.jpg", technical=4, scene="landscape"),
        _row(filename="b.jpg", technical=5, scene="landscape"),
        _row(filename="c.jpg", technical=0, scene="portrait"),
    ]
    distances = compute_distances(rows, profile)
    assert set(distances) == {"a.jpg", "b.jpg", "c.jpg"}
    # a (exact match) < b (1 star off) < c (extreme + scene mismatch)
    assert distances["a.jpg"] < distances["b.jpg"] < distances["c.jpg"]


def test_compute_distances_skips_rows_without_filename():
    profile = learn_style_profile([_row(technical=4, scene="landscape")])
    rows = [
        _row(technical=4),                    # no filename
        _row(filename="", technical=4),       # empty filename
        _row(filename="ok.jpg", technical=4),
    ]
    distances = compute_distances(rows, profile)
    assert list(distances) == ["ok.jpg"]


def test_profile_schema_marker():
    profile = learn_style_profile([])
    # The schema marker is the migration hook; future v2 readers
    # must still recognize v1 profiles, so this string is part
    # of the public contract.
    assert profile["schema"] == "pixcull.style_profile/v1"
