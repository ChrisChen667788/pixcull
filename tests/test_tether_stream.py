"""Tests for pixcull.tether_stream — v0.10-P1-2 streaming
burst-peak picker.

Pure-function module; tests cover the cluster + rerank logic
without touching any real tether session.
"""

from __future__ import annotations

import pytest

from pixcull.tether_stream import (
    BURST_GAP_S,
    WINDOW_SIZE,
    cluster_recent,
    rerank_cluster,
    update_burst_peaks,
)


# ---------------------------------------------------------------------------
# cluster_recent
# ---------------------------------------------------------------------------


def test_cluster_empty():
    assert cluster_recent([]) == []


def test_cluster_singleton():
    rows = [{"filename": "a.jpg", "mtime": 1.0, "scene": "wedding"}]
    out = cluster_recent(rows)
    assert out == [rows]


def test_cluster_splits_on_time_gap():
    rows = [
        {"filename": "a.jpg", "mtime": 0.0,  "scene": "wedding"},
        {"filename": "b.jpg", "mtime": 0.1,  "scene": "wedding"},
        {"filename": "c.jpg", "mtime": 0.2,  "scene": "wedding"},
        # >2 s gap — new burst
        {"filename": "d.jpg", "mtime": 10.0, "scene": "wedding"},
        {"filename": "e.jpg", "mtime": 10.05, "scene": "wedding"},
    ]
    out = cluster_recent(rows)
    assert len(out) == 2
    assert [r["filename"] for r in out[0]] == ["a.jpg", "b.jpg", "c.jpg"]
    assert [r["filename"] for r in out[1]] == ["d.jpg", "e.jpg"]


def test_cluster_splits_on_scene_change():
    rows = [
        {"filename": "a.jpg", "mtime": 0.0, "scene": "wedding"},
        {"filename": "b.jpg", "mtime": 0.1, "scene": "wedding"},
        {"filename": "c.jpg", "mtime": 0.2, "scene": "landscape"},
        {"filename": "d.jpg", "mtime": 0.3, "scene": "landscape"},
    ]
    out = cluster_recent(rows)
    assert len(out) == 2
    assert [r["scene"] for r in out[0]] == ["wedding", "wedding"]
    assert [r["scene"] for r in out[1]] == ["landscape", "landscape"]


def test_cluster_custom_gap_threshold():
    rows = [
        {"filename": "a.jpg", "mtime": 0.0, "scene": "x"},
        {"filename": "b.jpg", "mtime": 0.5, "scene": "x"},  # 500 ms
    ]
    # Default gap (2 s) → 1 cluster
    assert len(cluster_recent(rows, gap_s=BURST_GAP_S)) == 1
    # Tight 300 ms gap → split into 2
    assert len(cluster_recent(rows, gap_s=0.3)) == 2


# ---------------------------------------------------------------------------
# rerank_cluster
# ---------------------------------------------------------------------------


def test_rerank_singleton_marks_self_as_peak():
    out = rerank_cluster([
        {"filename": "a.jpg", "score_final": 0.5, "sharpness": 0.8},
    ])
    assert out[0]["is_burst_peak"] is True


def test_rerank_picks_highest_peakness():
    cluster = [
        {"filename": "a.jpg", "score_final": 0.6, "sharpness": 0.5,
         "face_eyes_open": 0.8, "face_smile": 0.1, "face_no_frown": 0.9},
        {"filename": "b.jpg", "score_final": 0.85, "sharpness": 0.9,
         "face_eyes_open": 0.9, "face_smile": 0.7, "face_no_frown": 1.0},
        {"filename": "c.jpg", "score_final": 0.4, "sharpness": 0.3,
         "face_eyes_open": 0.5, "face_smile": 0.0, "face_no_frown": 0.5},
    ]
    out = rerank_cluster(cluster)
    flags = {r["filename"]: r["is_burst_peak"] for r in out}
    assert flags == {"a.jpg": False, "b.jpg": True, "c.jpg": False}


def test_rerank_breaks_ties_toward_latest():
    # Two identically-scored frames — we want the later one to win
    # because the photographer probably paused on that moment.
    cluster = [
        {"filename": "early.jpg", "score_final": 0.7, "sharpness": 0.5},
        {"filename": "late.jpg",  "score_final": 0.7, "sharpness": 0.5},
    ]
    out = rerank_cluster(cluster)
    flags = {r["filename"]: r["is_burst_peak"] for r in out}
    assert flags == {"early.jpg": False, "late.jpg": True}


def test_rerank_does_not_mutate_input():
    cluster = [{"filename": "a.jpg", "score_final": 0.5,
                "is_burst_peak": False}]
    out = rerank_cluster(cluster)
    # Input untouched
    assert cluster[0]["is_burst_peak"] is False
    # Output reflects the new state
    assert out[0]["is_burst_peak"] is True


# ---------------------------------------------------------------------------
# update_burst_peaks — full streaming flow
# ---------------------------------------------------------------------------


def test_update_burst_peaks_streams_window_only():
    """The streaming update only touches the trailing window; rows
    outside it are frozen (their is_burst_peak doesn't change)."""
    rows = []
    # Far-past row, no further frames in its cluster — should stay
    # peak after the new window arrives.
    for i in range(WINDOW_SIZE + 5):
        rows.append({
            "filename":      f"f{i}.jpg",
            "mtime":         float(i),       # 1 s apart
            "scene":         "wedding",
            "score_final":   0.5,
            "is_burst_peak": False,
        })
    # Only the last WINDOW_SIZE rows come back; older are not in
    # the output (the caller knows that and doesn't rewrite them).
    out = update_burst_peaks(rows)
    assert len(out) == WINDOW_SIZE


def test_update_burst_peaks_each_burst_has_exactly_one_peak():
    """Across multiple bursts in the trailing window, each cluster
    gets exactly one is_burst_peak=True."""
    rows = []
    # Burst 1: 3 frames at t=0-0.2s, scene=wedding
    for i, t in enumerate([0.0, 0.1, 0.2]):
        rows.append({
            "filename": f"b1-{i}.jpg",
            "mtime":    t,
            "scene":    "wedding",
            "score_final": [0.5, 0.9, 0.6][i],   # peak = middle frame
        })
    # Gap — burst 2: 2 frames at t=10-10.1s, same scene
    for i, t in enumerate([10.0, 10.1]):
        rows.append({
            "filename": f"b2-{i}.jpg",
            "mtime":    t,
            "scene":    "wedding",
            "score_final": [0.4, 0.7][i],         # peak = second frame
        })
    out = update_burst_peaks(rows)
    peaks = [r for r in out if r["is_burst_peak"]]
    assert len(peaks) == 2
    peak_names = {r["filename"] for r in peaks}
    assert peak_names == {"b1-1.jpg", "b2-1.jpg"}


def test_update_burst_peaks_new_row_promotes_to_peak():
    """When a new frame arrives that beats the existing peak, it
    becomes the new peak and the previous winner gets demoted."""
    rows = [
        {"filename": "old.jpg", "mtime": 0.0, "scene": "wedding",
         "score_final": 0.85, "is_burst_peak": True},
        # New frame, 50 ms later, higher score
        {"filename": "new.jpg", "mtime": 0.05, "scene": "wedding",
         "score_final": 0.95, "is_burst_peak": False},
    ]
    out = update_burst_peaks(rows)
    flags = {r["filename"]: r["is_burst_peak"] for r in out}
    assert flags == {"old.jpg": False, "new.jpg": True}
