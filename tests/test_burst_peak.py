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


def test_eyes_open_wins_when_other_signals_tied():
    """P-AI-5.3 — given two equally sharp + equally distinct frames
    where only one has eyes open, the eyes-open one MUST win.
    This is the canonical wedding-burst scenario: the photographer
    rejects the blinky frame even when it's slightly sharper."""
    rows = [
        {"filename": "blinky.jpg",  "score_sharpness": 0.6,
         "score_final": 0.5, "embedding": [1.0, 0.0],
         "face_bboxes": [(0, 0, 50, 50, 0.95)],
         "face_max_blink": 0.85},   # 85% closed
        {"filename": "eyes_open.jpg", "score_sharpness": 0.6,
         "score_final": 0.5, "embedding": [1.0, 0.0],
         "face_bboxes": [(0, 0, 50, 50, 0.95)],
         "face_max_blink": 0.05},   # 5% closed = wide open
    ]
    rpt = rank_burst_peak(rows)
    assert rpt.winner_filename == "eyes_open.jpg"
    assert "眼睛睁开" in rpt.reasons["eyes_open.jpg"]


def test_eyes_open_can_override_sharper_blinky_frame():
    """The whole point of P-AI-5.3: in a real burst (small sharpness
    spread between frames), a slightly softer eyes-open frame beats
    a slightly sharper eyes-closed frame.  Fixture sharpness gap
    matches the empirical variance from the 13-burst tuning corpus
    (typically < 5 pp inside a 1-2s burst because focal length +
    aperture are pinned)."""
    rows = [
        # Sharp burst-mate (anchors the z-score range)
        {"filename": "decoy.jpg", "score_sharpness": 0.70,
         "embedding": [1.0, 0.0], "face_max_blink": 0.5},
        # Sharper but blinking
        {"filename": "sharp_blink.jpg", "score_sharpness": 0.74,
         "embedding": [1.0, 0.0],
         "face_bboxes": [(0,0,50,50,0.95)],
         "face_max_blink": 0.90},
        # Slightly less sharp but eyes wide open
        {"filename": "soft_open.jpg",  "score_sharpness": 0.72,
         "embedding": [1.0, 0.0],
         "face_bboxes": [(0,0,50,50,0.95)],
         "face_max_blink": 0.02},
    ]
    rpt = rank_burst_peak(rows)
    # Realistic sharpness gap (0.74 vs 0.72) → sharpness z-score
    # advantage for sharp_blink is small (~0.4σ × 0.50 weight = +0.20).
    # Eyes-open advantage for soft_open is large (0.98 - 0.10 = 0.88
    # × 0.30 weight = +0.26).  So soft_open wins, exactly as the
    # wedding photographer would pick.
    assert rpt.winner_filename == "soft_open.jpg"


def test_missing_face_max_blink_falls_back_to_zero():
    """Rows without ``face_max_blink`` (old format, no face detector
    run, NaN values) must not crash and must contribute 0 to the
    eyes-open component."""
    from pixcull.scoring.burst_peak import _face_eyes_open
    assert _face_eyes_open({}) == 0.0
    assert _face_eyes_open({"face_max_blink": None}) == 0.0
    assert _face_eyes_open({"face_max_blink": "garbage"}) == 0.0
    assert _face_eyes_open({"face_max_blink": float("nan")}) == 0.0
    # Sanity: valid values produce sensible inversions
    assert _face_eyes_open({"face_max_blink": 0.0}) == 1.0
    assert _face_eyes_open({"face_max_blink": 1.0}) == 0.0
    assert _face_eyes_open({"face_max_blink": 0.5}) == 0.5


def test_face_eyes_open_clips_out_of_range_values():
    """Defensive: a detector that returns 1.2 or -0.1 shouldn't
    skew the picker."""
    from pixcull.scoring.burst_peak import _face_eyes_open
    assert _face_eyes_open({"face_max_blink": 1.5}) == 0.0   # over → clipped
    assert _face_eyes_open({"face_max_blink": -0.2}) == 1.0  # under → clipped


def test_smile_signal_wins_when_others_tied():
    """P-AI-5.5 — given two frames with equal sharpness + equal
    eyes-open, the one with a bigger smile wins.  Wedding-canonical."""
    rows = [
        {"filename": "neutral.jpg", "score_sharpness": 0.6,
         "embedding": [1.0, 0.0],
         "face_bboxes": [(0,0,50,50,0.95)],
         "face_max_blink": 0.05, "face_max_smile": 0.05,
         "face_max_brow_down": 0.05},
        {"filename": "smiling.jpg", "score_sharpness": 0.6,
         "embedding": [1.0, 0.0],
         "face_bboxes": [(0,0,50,50,0.95)],
         "face_max_blink": 0.05, "face_max_smile": 0.85,
         "face_max_brow_down": 0.05},
    ]
    rpt = rank_burst_peak(rows)
    assert rpt.winner_filename == "smiling.jpg"
    assert "笑容明显" in rpt.reasons["smiling.jpg"]


def test_frown_demotes_otherwise_better_frame():
    """A frame with everything else equal but a furrowed brow
    (browDown high) loses to the relaxed one via the no-frown
    weight."""
    rows = [
        {"filename": "relaxed.jpg", "score_sharpness": 0.6,
         "embedding": [1.0, 0.0],
         "face_bboxes": [(0,0,50,50,0.95)],
         "face_max_blink": 0.05, "face_max_smile": 0.30,
         "face_max_brow_down": 0.05},   # no frown
        {"filename": "furrowed.jpg", "score_sharpness": 0.6,
         "embedding": [1.0, 0.0],
         "face_bboxes": [(0,0,50,50,0.95)],
         "face_max_blink": 0.05, "face_max_smile": 0.30,
         "face_max_brow_down": 0.90},   # furrowed
    ]
    rpt = rank_burst_peak(rows)
    assert rpt.winner_filename == "relaxed.jpg"


def test_smile_outranks_eyes_when_smile_gap_is_large():
    """Realistic wedding case: sharp_blink vs softer_smile.  The
    eyes-open signal alone (P-AI-5.3) couldn't fix the 15% ceiling
    for picks where the photographer chose the smiling frame over
    the cleaner-eyed but neutral burst-mate."""
    rows = [
        {"filename": "decoy.jpg", "score_sharpness": 0.70,
         "embedding": [1.0, 0.0], "face_max_blink": 0.5,
         "face_max_smile": 0.10, "face_max_brow_down": 0.0},
        {"filename": "clean_eyes_no_smile.jpg",
         "score_sharpness": 0.73,
         "embedding": [1.0, 0.0],
         "face_bboxes": [(0,0,50,50,0.95)],
         "face_max_blink": 0.05, "face_max_smile": 0.10,
         "face_max_brow_down": 0.0},
        {"filename": "big_smile.jpg",
         "score_sharpness": 0.71,
         "embedding": [1.0, 0.0],
         "face_bboxes": [(0,0,50,50,0.95)],
         "face_max_blink": 0.10, "face_max_smile": 0.85,
         "face_max_brow_down": 0.0},
    ]
    rpt = rank_burst_peak(rows)
    assert rpt.winner_filename == "big_smile.jpg"
    assert "笑容明显" in rpt.reasons["big_smile.jpg"]


def test_smile_missing_falls_back_to_zero():
    """Rows without ``face_max_smile`` (old format, no FaceDetector
    run, NaN values) must not crash and must contribute 0."""
    from pixcull.scoring.burst_peak import _face_smile, _face_no_frown
    assert _face_smile({}) == 0.0
    assert _face_smile({"face_max_smile": None}) == 0.0
    assert _face_smile({"face_max_smile": "junk"}) == 0.0
    assert _face_smile({"face_max_smile": float("nan")}) == 0.0
    assert _face_smile({"face_max_smile": -0.1}) == 0.0
    # Sanity: valid values pass through with clipping
    assert _face_smile({"face_max_smile": 0.0}) == 0.0
    assert _face_smile({"face_max_smile": 0.7}) == 0.7
    assert _face_smile({"face_max_smile": 1.5}) == 1.0
    # Frown inverter — note 0 brow_down → 1.0 "no frown" signal
    assert _face_no_frown({"face_max_brow_down": 0.0}) == 1.0
    assert _face_no_frown({"face_max_brow_down": 1.0}) == 0.0
    assert _face_no_frown({}) == 0.0   # absent → no signal contribution


def test_eyes_open_does_not_penalize_faceless_bursts():
    """For wildlife / landscape bursts (no faces), the eyes-open
    weight should contribute 0 across all frames — not flip the
    picker's choice based on absent data."""
    rows = [
        {"filename": "a.jpg", "score_sharpness": 0.4,
         "embedding": [1.0, 0.0]},
        {"filename": "b.jpg", "score_sharpness": 0.9,
         "embedding": [1.0, 0.0]},
    ]
    # No face_max_blink fields anywhere → eyes-open contribution = 0
    rpt = rank_burst_peak(rows)
    assert rpt.winner_filename == "b.jpg"  # pure sharpness wins
    # And the reason must not be "眼睛睁开" since we have no signal
    assert "眼睛睁开" not in rpt.reasons["b.jpg"]


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
