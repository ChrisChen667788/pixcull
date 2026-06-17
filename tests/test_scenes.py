"""v2.9-P1-1 — Scenes 时序叙事分组 unit tests."""
from __future__ import annotations

from datetime import datetime

from pixcull.scoring.scenes import (
    Scene, adaptive_gap_threshold, parse_timestamp, segment_scenes,
)


def _items(pairs):
    return [{"filename": fn, "timestamp": ts} for fn, ts in pairs]


def test_parse_timestamp_formats():
    base = datetime(2025, 2, 28, 14, 42, 23)
    assert parse_timestamp("2025-02-28 14:42:23") == base.timestamp()
    assert parse_timestamp("2025:02:28 14:42:23") == base.timestamp()
    assert parse_timestamp("2025-02-28T14:42:23") == base.timestamp()
    assert parse_timestamp(base) == base.timestamp()
    assert parse_timestamp(1_700_000_000) == 1_700_000_000.0
    assert parse_timestamp("") is None
    assert parse_timestamp(None) is None
    assert parse_timestamp("not a date") is None
    assert parse_timestamp(0) is None        # non-positive epoch → None


def test_single_scene_when_cadence_uniform():
    # Frames every 3 min — one continuous shoot, must NOT fragment.
    pairs = [(f"f{i}.jpg", f"2025-02-28 14:{42 + i*3:02d}:00") for i in range(6)]
    scenes = segment_scenes(_items(pairs))
    assert len(scenes) == 1
    assert scenes[0].n == 6
    assert scenes[0].filenames == [f"f{i}.jpg" for i in range(6)]


def test_gap_splits_into_two_scenes():
    # Morning cluster, a 2-hour jump, then an afternoon cluster.
    pairs = [
        ("a1.jpg", "2025-02-28 09:00:00"),
        ("a2.jpg", "2025-02-28 09:03:00"),
        ("a3.jpg", "2025-02-28 09:06:00"),
        ("b1.jpg", "2025-02-28 11:30:00"),
        ("b2.jpg", "2025-02-28 11:33:00"),
        ("b3.jpg", "2025-02-28 11:36:00"),
    ]
    scenes = segment_scenes(_items(pairs))
    assert len(scenes) == 2
    assert [s.n for s in scenes] == [3, 3]
    assert scenes[0].filenames == ["a1.jpg", "a2.jpg", "a3.jpg"]
    assert scenes[1].filenames == ["b1.jpg", "b2.jpg", "b3.jpg"]
    # chronological + timestamps populated
    assert scenes[0].end_ts < scenes[1].start_ts


def test_untimed_photos_form_trailing_scene():
    pairs = [
        ("t1.jpg", "2025-02-28 09:00:00"),
        ("t2.jpg", "2025-02-28 09:03:00"),
        ("u1.jpg", None),
        ("u2.jpg", ""),
    ]
    scenes = segment_scenes(_items(pairs))
    assert len(scenes) == 2
    assert scenes[-1].start_ts is None and scenes[-1].end_ts is None
    assert set(scenes[-1].filenames) == {"u1.jpg", "u2.jpg"}


def test_fewer_than_two_timestamps_is_one_scene():
    scenes = segment_scenes(_items([("only.jpg", "2025-02-28 09:00:00"),
                                    ("nodate.jpg", None)]))
    assert len(scenes) == 1
    assert set(scenes[0].filenames) == {"only.jpg", "nodate.jpg"}


def test_empty_input():
    assert segment_scenes([]) == []


def test_adaptive_threshold_floor_and_outlier():
    # Uniform 60s gaps → threshold floored at min_gap_s (no spurious split).
    assert adaptive_gap_threshold([60, 60, 60, 60]) == 120.0
    # An outlier raises the threshold but the floor still applies sensibly.
    thr = adaptive_gap_threshold([60, 60, 7200, 60], min_gap_s=120.0)
    assert thr >= 120.0


def test_chronological_reorder():
    # Input out of order → scenes come back time-sorted.
    pairs = [
        ("late.jpg", "2025-02-28 18:00:00"),
        ("early.jpg", "2025-02-28 09:00:00"),
        ("mid.jpg", "2025-02-28 09:02:00"),
    ]
    scenes = segment_scenes(_items(pairs))
    # early+mid cluster first, late is its own scene after the big gap
    assert scenes[0].filenames[0] == "early.jpg"
    assert scenes[-1].filenames[-1] == "late.jpg"
    assert isinstance(scenes[0], Scene)
