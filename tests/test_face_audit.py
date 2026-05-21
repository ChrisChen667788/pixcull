"""P-AI-4 — tests for the cross-run face library quality audit.

All helpers are pure-Python / numpy-free so these tests run in
~ms and don't need ArcFace / InsightFace loaded.
"""
from __future__ import annotations

import pytest

from pixcull.pipeline.face_audit import (
    CLUSTER_PAIR_OUTLIER_SIM,
    LIBRARY_FRAGMENT_FLOOR,
    _cosine_sim,
    cluster_precision_audit,
    cross_run_continuity_audit,
    library_fragmentation_audit,
)


# ---------- _cosine_sim ----------

def test_cosine_sim_identical_vectors_is_one():
    assert _cosine_sim([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == pytest.approx(1.0)


def test_cosine_sim_orthogonal_vectors_is_zero():
    assert _cosine_sim([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_sim_opposite_vectors_is_negative_one():
    assert _cosine_sim([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_sim_degenerate_inputs_safe():
    """Zero vectors, mismatched lengths, empty → 0.0 not NaN."""
    assert _cosine_sim([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert _cosine_sim([], []) == 0.0
    assert _cosine_sim([1.0], [1.0, 0.0]) == 0.0  # mismatched


# ---------- cluster_precision_audit ----------

def test_single_member_cluster_trivially_healthy():
    rpt = cluster_precision_audit([[1.0, 0.0]], cluster_id=42)
    assert rpt.healthy is True
    assert rpt.polluted is False
    assert rpt.n_members == 1
    assert rpt.outlier_indices == []


def test_pristine_cluster_high_pair_sims():
    """Same identity, slight noise → all pair sims close to 1."""
    embs = [
        [1.0, 0.0, 0.05],
        [1.0, 0.05, 0.0],
        [0.95, 0.05, 0.05],
    ]
    rpt = cluster_precision_audit(embs, cluster_id=1)
    assert rpt.healthy is True
    assert rpt.min_pair_sim > 0.9
    assert rpt.mean_pair_sim > 0.95
    assert rpt.outlier_indices == []


def test_polluted_cluster_flags_outlier():
    """A cluster where one member is wildly different from the rest."""
    embs = [
        [1.0, 0.0, 0.0],     # Alice
        [0.95, 0.05, 0.0],   # Alice
        [0.98, 0.02, 0.02],  # Alice
        [-1.0, 0.0, 0.0],    # Not Alice (intruder)
    ]
    rpt = cluster_precision_audit(embs, cluster_id="alice")
    assert rpt.polluted is True
    assert 3 in rpt.outlier_indices  # the intruder index
    # And the three Alice members should NOT be flagged
    assert 0 not in rpt.outlier_indices
    assert 1 not in rpt.outlier_indices
    assert 2 not in rpt.outlier_indices


def test_outlier_threshold_is_configurable():
    """Caller can pick a stricter / looser outlier threshold."""
    embs = [
        [1.0, 0.0],
        [0.7, 0.7],   # 0.71 sim with the first — borderline
    ]
    loose = cluster_precision_audit(embs, outlier_threshold=0.50)
    strict = cluster_precision_audit(embs, outlier_threshold=0.80)
    assert loose.polluted is False
    assert strict.polluted is True


def test_empty_cluster_safe():
    rpt = cluster_precision_audit([], cluster_id="ghost")
    assert rpt.n_members == 0
    assert rpt.healthy is True
    assert rpt.outlier_indices == []


# ---------- library_fragmentation_audit ----------

def test_fragmentation_flags_labels_near_cap():
    """Labels with ≥ LIBRARY_FRAGMENT_FLOOR centroids → fragmented."""
    library = {
        "alice":   [[1.0, 0.0]] * (LIBRARY_FRAGMENT_FLOOR + 1),  # over
        "bob":     [[1.0, 0.0]] * LIBRARY_FRAGMENT_FLOOR,        # at
        "carl":    [[1.0, 0.0]] * 3,                             # fine
    }
    reports = library_fragmentation_audit(library)
    by_label = {r.label: r for r in reports}
    assert by_label["alice"].fragmented is True
    assert by_label["bob"].fragmented is True
    assert by_label["carl"].fragmented is False


def test_fragmentation_sorted_by_count_desc():
    library = {
        "small":  [[1.0]] * 2,
        "large":  [[1.0]] * 10,
        "medium": [[1.0]] * 5,
    }
    reports = library_fragmentation_audit(library)
    labels = [r.label for r in reports]
    assert labels == ["large", "medium", "small"]


def test_empty_library_returns_empty_audit():
    assert library_fragmentation_audit({}) == []


# ---------- cross_run_continuity_audit ----------

def test_continuity_all_matched():
    """Every current centroid linked to a library centroid."""
    library = [[1.0, 0.0], [0.0, 1.0]]
    current = [[0.98, 0.01], [0.01, 0.98]]
    rpt = cross_run_continuity_audit(current, library)
    assert rpt.n_current_clusters == 2
    assert rpt.n_matched_to_library == 2
    assert rpt.match_rate == 100.0


def test_continuity_partial_match():
    library = [[1.0, 0.0], [0.0, 1.0]]
    current = [
        [0.95, 0.05],     # matches first lib centroid
        [0.05, 0.95],     # matches second
        [-1.0, 0.0],      # nothing matches
        [0.0, -1.0],      # nothing matches
    ]
    rpt = cross_run_continuity_audit(current, library)
    assert rpt.n_current_clusters == 4
    assert rpt.n_matched_to_library == 2
    assert rpt.match_rate == 50.0


def test_continuity_no_library_zero_match():
    current = [[1.0, 0.0]]
    rpt = cross_run_continuity_audit(current, [])
    assert rpt.n_matched_to_library == 0
    assert rpt.match_rate == 0.0


def test_continuity_no_current_clusters_zero():
    """Defensive: a run with no faces → 0% rather than NaN."""
    rpt = cross_run_continuity_audit([], [[1.0, 0.0]])
    assert rpt.n_current_clusters == 0
    assert rpt.match_rate == 0.0


def test_continuity_match_threshold_respected():
    """Caller can crank the threshold; fewer matches."""
    library = [[1.0, 0.0]]
    current = [[0.6, 0.8]]   # cos sim 0.6
    rpt_loose  = cross_run_continuity_audit(current, library,
                                            match_threshold=0.50)
    rpt_strict = cross_run_continuity_audit(current, library,
                                            match_threshold=0.80)
    assert rpt_loose.n_matched_to_library == 1
    assert rpt_strict.n_matched_to_library == 0
