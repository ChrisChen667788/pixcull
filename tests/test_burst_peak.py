"""P-AI-5 — tests for the motion-aware burst peak picker."""
from __future__ import annotations

import pytest

from pixcull.scoring.burst_peak import (
    BurstPeakResult,
    BurstPeakWeights,
    DEFAULT_WEIGHTS,
    _cosine_distance,
    _vector_mean,
    rank_burst_peak,
    rank_clusters,
)


def test_empty_input_returns_no_winner():
    rpt = rank_burst_peak([])
    assert rpt.has_winner is False
    assert rpt.winner_idx == -1
    assert rpt.ranking == []


def test_single_frame_cluster_picks_that_frame():
    rows = [{"filename": "IMG_001.jpg", "score_sharpness": 0.50}]
    rpt = rank_burst_peak(rows)
    assert rpt.has_winner is True
    assert rpt.winner_filename == "IMG_001.jpg"
    assert rpt.winner_idx == 0
    assert "唯一帧" in rpt.reasons["IMG_001.jpg"]


def test_sharper_frame_wins_with_equal_other_signals():
    """Two-frame burst: same embedding, one is sharper. Sharp wins."""
    rows = [
        {"filename": "soft.jpg", "score_sharpness": 0.30,
         "score_final": 0.5,
         "embedding": [1.0, 0.0, 0.0]},
        {"filename": "sharp.jpg", "score_sharpness": 0.80,
         "score_final": 0.5,
         "embedding": [1.0, 0.0, 0.0]},
    ]
    rpt = rank_burst_peak(rows)
    assert rpt.winner_filename == "sharp.jpg"
    # The reason explanation should mention sharpness
    assert "锐" in rpt.reasons["sharp.jpg"]


def test_most_distinct_embedding_wins_when_sharpness_tied():
    """Three frames, equal sharpness; one is visually different
    (different embedding). The different one is the "moment of
    peak action" and should win on distinctness."""
    rows = [
        {"filename": "a.jpg", "score_sharpness": 0.50,
         "embedding": [1.0, 0.0, 0.0]},
        {"filename": "b.jpg", "score_sharpness": 0.50,
         "embedding": [1.0, 0.0, 0.0]},
        {"filename": "peak.jpg", "score_sharpness": 0.50,
         "embedding": [-1.0, 0.0, 0.0]},   # opposite vector
    ]
    rpt = rank_burst_peak(rows)
    assert rpt.winner_filename == "peak.jpg"
    assert "差异" in rpt.reasons["peak.jpg"]


def test_score_final_breaks_tie_when_components_match():
    """If sharpness + distinctness are flat, the higher score_final
    wins via the quality weight."""
    rows = [
        {"filename": "lower.jpg", "score_sharpness": 0.5,
         "score_final": 0.3, "embedding": [1.0]},
        {"filename": "higher.jpg", "score_sharpness": 0.5,
         "score_final": 0.9, "embedding": [1.0]},
    ]
    rpt = rank_burst_peak(rows)
    assert rpt.winner_filename == "higher.jpg"


def test_face_evidence_contributes_when_other_signals_tied():
    rows = [
        {"filename": "noface.jpg", "score_sharpness": 0.5,
         "score_final": 0.5, "embedding": [1.0, 0.0]},
        {"filename": "withface.jpg", "score_sharpness": 0.5,
         "score_final": 0.5, "embedding": [1.0, 0.0],
         "face_bboxes": [(10, 10, 50, 50, 0.95)]},
    ]
    rpt = rank_burst_peak(rows)
    assert rpt.winner_filename == "withface.jpg"


def test_ranking_descends():
    rows = [
        {"filename": "a.jpg", "score_sharpness": 0.2,
         "score_final": 0.4, "embedding": [1.0, 0.0]},
        {"filename": "b.jpg", "score_sharpness": 0.6,
         "score_final": 0.5, "embedding": [1.0, 0.0]},
        {"filename": "c.jpg", "score_sharpness": 0.9,
         "score_final": 0.7, "embedding": [-1.0, 0.0]},
    ]
    rpt = rank_burst_peak(rows)
    scores = [s for _, s in rpt.ranking]
    assert scores == sorted(scores, reverse=True)
    assert rpt.ranking[0][0] == rpt.winner_filename


def test_missing_embedding_fields_dont_crash():
    """Real-world rows may have missing/None embedding (skipped
    detector). Picker should keep working."""
    rows = [
        {"filename": "a.jpg", "score_sharpness": 0.4},  # no embedding
        {"filename": "b.jpg", "score_sharpness": 0.8,
         "embedding": [1.0, 0.0]},
    ]
    rpt = rank_burst_peak(rows)
    assert rpt.has_winner
    # The sharper one wins because distinctness can't be computed
    # (one has no embedding); the sharpness weight dominates.
    assert rpt.winner_filename == "b.jpg"


def test_rank_clusters_groups_by_cluster_id():
    rows = [
        {"filename": "c1_a.jpg", "cluster_id": 1, "score_sharpness": 0.3},
        {"filename": "c1_b.jpg", "cluster_id": 1, "score_sharpness": 0.8},
        {"filename": "c2_a.jpg", "cluster_id": 2, "score_sharpness": 0.6},
        {"filename": "c2_b.jpg", "cluster_id": 2, "score_sharpness": 0.4},
        # No cluster — skipped
        {"filename": "stray.jpg", "cluster_id": None, "score_sharpness": 0.9},
    ]
    results = rank_clusters(rows)
    assert set(results.keys()) == {"1", "2"}
    assert results["1"].winner_filename == "c1_b.jpg"
    assert results["2"].winner_filename == "c2_a.jpg"


def test_cosine_distance_basics():
    """Sanity-check the cosine-distance helper."""
    assert _cosine_distance([1.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)
    assert _cosine_distance([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(2.0)
    assert _cosine_distance([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0)
    # Defensive: zero vectors → 0 not nan
    assert _cosine_distance([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert _cosine_distance([], []) == 0.0


def test_vector_mean_handles_uneven_dims():
    """Robust to mixed embedding dimensionality."""
    vecs = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    out = _vector_mean(vecs)
    assert out == pytest.approx([2.5, 3.5, 4.5])
    assert _vector_mean([]) == []


def test_annotate_burst_peak_reasons_attaches_to_v27_pick():
    """P-AI-5.1 — annotate_burst_peak_reasons should add a reason
    string to whichever row V27 already flagged as the burst peak."""
    import pandas as pd
    from pixcull.pipeline.burst_peak import annotate_burst_peak_reasons

    df = pd.DataFrame([
        # cluster 1 — V27 picks "sharp1"
        {"filename": "soft1.jpg", "cluster_id": 1,
         "score_sharpness": 0.3, "score_final": 0.4,
         "embedding": [1.0, 0.0], "is_burst_peak": False},
        {"filename": "sharp1.jpg", "cluster_id": 1,
         "score_sharpness": 0.9, "score_final": 0.8,
         "embedding": [1.0, 0.0], "is_burst_peak": True},
        # cluster 2 — singleton, V27 marked True but cluster is size 1
        {"filename": "solo.jpg", "cluster_id": 2,
         "score_sharpness": 0.5, "score_final": 0.5,
         "embedding": [1.0, 0.0], "is_burst_peak": True},
    ])
    out = annotate_burst_peak_reasons(df)
    # Reason attached to the V27 winner in the size-2 cluster
    sharp_row = out[out["filename"] == "sharp1.jpg"].iloc[0]
    assert sharp_row["burst_peak_reason"]
    assert isinstance(sharp_row["burst_peak_reason"], str)
    # Non-winner gets no reason
    soft_row = out[out["filename"] == "soft1.jpg"].iloc[0]
    assert soft_row["burst_peak_reason"] is None or \
           pd.isna(soft_row["burst_peak_reason"])
    # Singleton cluster gets no reason — not a meaningful peak
    solo_row = out[out["filename"] == "solo.jpg"].iloc[0]
    assert solo_row["burst_peak_reason"] is None or \
           pd.isna(solo_row["burst_peak_reason"])


def test_annotate_burst_peak_reasons_handles_missing_columns():
    """If cluster_id or is_burst_peak missing, just add a null column."""
    import pandas as pd
    from pixcull.pipeline.burst_peak import annotate_burst_peak_reasons

    df = pd.DataFrame([{"filename": "a.jpg", "score_sharpness": 0.5}])
    out = annotate_burst_peak_reasons(df)
    assert "burst_peak_reason" in out.columns
    assert out["burst_peak_reason"].iloc[0] is None


def test_custom_weights_change_outcome():
    """When the user tunes weights, the picker respects them.

    Three-frame burst is the minimum where embedding distinctness
    is meaningful: with 2 mirrored embeddings the centroid is the
    zero vector and cosine distance is undefined.
    """
    rows = [
        # sharp but generic (clustered with sister frame)
        {"filename": "sharp.jpg", "score_sharpness": 0.9,
         "embedding": [1.0, 0.0]},
        {"filename": "sharp2.jpg", "score_sharpness": 0.9,
         "embedding": [1.0, 0.0]},
        # softer but visually distinct (the action frame)
        {"filename": "peak.jpg",  "score_sharpness": 0.5,
         "embedding": [-1.0, 0.0]},
    ]
    # Default weights: sharpness 0.40 dominates → one of the
    # sharps wins (deterministic tie-break by filename)
    rpt_default = rank_burst_peak(rows)
    # Hand-tuned: distinctness 0.80 dominates → peak wins
    distinct_w = BurstPeakWeights(sharpness=0.1, distinctness=0.8,
                                  quality=0.1, face=0.0)
    rpt_tuned = rank_burst_peak(rows, weights=distinct_w)
    assert rpt_default.winner_filename in ("sharp.jpg", "sharp2.jpg")
    assert rpt_tuned.winner_filename == "peak.jpg"
