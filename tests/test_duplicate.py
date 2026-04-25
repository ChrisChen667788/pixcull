"""Tests for scene-aware burst clustering + mediocre-burst demotion.

The demote rule is the V0.6 fix for stilllife product shoots: when the
photographer takes N similar product shots and the whole take scores low on
CLIP-IQA, they typically cull all of them. Per-image scores alone can't see
this — we need a cluster-level quality gate.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from pixcull.detectors.duplicate import (
    _SCENE_BURST_DEFAULTS,
    _time_bucket_groups,
    cluster_bursts,
    demote_mediocre_bursts,
)


# ------------------------------------------------ scene defaults sanity
def test_scene_burst_defaults_cover_expected_scenes():
    expected = {"stilllife", "wildlife", "event", "portrait", "landscape", "street"}
    assert expected.issubset(_SCENE_BURST_DEFAULTS.keys())


def test_stilllife_time_gap_is_loose():
    """Product shoots can take minutes between takes — default must accommodate."""
    assert _SCENE_BURST_DEFAULTS["stilllife"]["time_gap_s"] >= 60.0


def test_wildlife_time_gap_is_tight():
    """Wildlife burst rate is ~20-30fps — don't accidentally cluster unrelated shots."""
    assert _SCENE_BURST_DEFAULTS["wildlife"]["time_gap_s"] <= 2.0


# ------------------------------------------------ time-bucket grouping
def _make_row(scene, t):
    return {"scene": scene, "datetime": t}


def test_time_bucket_groups_respects_scene_boundaries():
    t0 = datetime(2024, 1, 1, 12, 0, 0)
    df = pd.DataFrame([
        _make_row("stilllife", t0),
        _make_row("stilllife", t0 + timedelta(seconds=30)),
        _make_row("portrait",  t0 + timedelta(seconds=60)),  # scene break
        _make_row("portrait",  t0 + timedelta(seconds=90)),
    ])
    groups = _time_bucket_groups(df, "scene", "datetime", time_gap_s=300.0)
    # Two groups: [stilllife × 2], [portrait × 2]
    assert len(groups) == 2
    assert sorted(groups[0]) == [0, 1]
    assert sorted(groups[1]) == [2, 3]


def test_time_bucket_groups_splits_on_long_gap():
    t0 = datetime(2024, 1, 1, 12, 0, 0)
    df = pd.DataFrame([
        _make_row("stilllife", t0),
        _make_row("stilllife", t0 + timedelta(seconds=30)),
        _make_row("stilllife", t0 + timedelta(hours=3)),  # far outside window
    ])
    groups = _time_bucket_groups(df, "scene", "datetime", time_gap_s=300.0)
    assert len(groups) == 2


def test_time_bucket_groups_handles_nat_datetimes():
    t0 = datetime(2024, 1, 1, 12, 0, 0)
    df = pd.DataFrame([
        _make_row("stilllife", t0),
        _make_row("stilllife", pd.NaT),
        _make_row("stilllife", t0 + timedelta(seconds=30)),
    ])
    # Rows with NaT shouldn't crash; they just won't cluster across the NaT.
    groups = _time_bucket_groups(df, "scene", "datetime", time_gap_s=300.0)
    assert isinstance(groups, list)


# ------------------------------------------------ demote_mediocre_bursts rule
def _stilllife_burst(n: int, clipiqa: float, *, start_offset_h: int = 0) -> pd.DataFrame:
    t0 = datetime(2024, 1, 1, 12, 0, 0) + timedelta(hours=start_offset_h)
    rows = [
        {
            "scene": "stilllife",
            "datetime": t0 + timedelta(seconds=i * 30),
            "clipiqa": clipiqa,
        }
        for i in range(n)
    ]
    return pd.DataFrame(rows)


def test_mediocre_stilllife_burst_is_demoted():
    df = _stilllife_burst(n=5, clipiqa=0.45).reset_index(drop=True)
    decisions = ["keep"] * len(df)
    reasons = [""] * len(df)
    new_decs, new_reasons = demote_mediocre_bursts(df, decisions, reasons)
    assert new_decs == ["cull"] * len(df)
    assert all("mediocre_burst" in r for r in new_reasons)


def test_good_stilllife_burst_is_kept():
    """Cluster with clipiqa median above floor → photographer liked the take."""
    df = _stilllife_burst(n=5, clipiqa=0.70).reset_index(drop=True)
    decisions = ["keep"] * len(df)
    reasons = [""] * len(df)
    new_decs, _ = demote_mediocre_bursts(df, decisions, reasons)
    assert new_decs == ["keep"] * len(df)


def test_small_cluster_below_min_size_is_ignored():
    """2 photos ≠ a take. Don't over-reach."""
    df = _stilllife_burst(n=2, clipiqa=0.30).reset_index(drop=True)
    decisions = ["keep"] * len(df)
    new_decs, _ = demote_mediocre_bursts(df, decisions, [""] * len(df))
    assert new_decs == ["keep", "keep"]


def test_portrait_burst_is_not_affected_by_rule():
    """The rule is stilllife-only today — portrait bursts want diversity."""
    t0 = datetime(2024, 1, 1, 12, 0, 0)
    df = pd.DataFrame([
        {"scene": "portrait", "datetime": t0 + timedelta(seconds=i), "clipiqa": 0.3}
        for i in range(5)
    ]).reset_index(drop=True)
    decisions = ["keep"] * len(df)
    new_decs, _ = demote_mediocre_bursts(df, decisions, [""] * len(df))
    assert new_decs == ["keep"] * 5


def test_demote_preserves_already_culled_rows():
    """If decide() already culled a row, don't overwrite its reason."""
    df = _stilllife_burst(n=4, clipiqa=0.30).reset_index(drop=True)
    decisions = ["cull", "keep", "keep", "keep"]
    reasons = ["low_score=0.20", "", "", ""]
    new_decs, new_reasons = demote_mediocre_bursts(df, decisions, reasons)
    assert new_decs == ["cull"] * 4
    # Row 0 kept its original reason (not appended-over).
    assert new_reasons[0] == "low_score=0.20"
    # Rows 1-3 got the mediocre_burst tag.
    assert all("mediocre_burst" in new_reasons[i] for i in (1, 2, 3))


def test_demote_no_clipiqa_column_is_no_op():
    """Graceful degradation when the signal is missing."""
    t0 = datetime(2024, 1, 1, 12, 0, 0)
    df = pd.DataFrame([
        {"scene": "stilllife", "datetime": t0 + timedelta(seconds=i * 30)}
        for i in range(5)
    ])
    decisions = ["keep"] * len(df)
    new_decs, _ = demote_mediocre_bursts(df, decisions, [""] * len(df))
    assert new_decs == ["keep"] * 5


def test_demote_skips_cluster_when_span_exceeds_time_gap():
    """5 stilllife photos 1hr apart each is not a single take."""
    t0 = datetime(2024, 1, 1, 12, 0, 0)
    df = pd.DataFrame([
        {"scene": "stilllife", "datetime": t0 + timedelta(hours=i), "clipiqa": 0.3}
        for i in range(5)
    ]).reset_index(drop=True)
    decisions = ["keep"] * len(df)
    new_decs, _ = demote_mediocre_bursts(df, decisions, [""] * len(df))
    assert new_decs == ["keep"] * 5


# ------------------------------------------------ cluster_bursts scene-awareness
def _norm(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


def test_cluster_bursts_stilllife_uses_loose_time_gap():
    """Adjacent stilllife shots 1 min apart with similar embeddings should cluster
    despite the default 2s gap."""
    t0 = datetime(2024, 1, 1, 12, 0, 0)
    emb = _norm(np.random.default_rng(0).standard_normal(384).astype(np.float32))
    df = pd.DataFrame([
        {"scene": "stilllife", "datetime": t0, "embedding": emb},
        {"scene": "stilllife", "datetime": t0 + timedelta(seconds=60), "embedding": emb},
    ])
    out = cluster_bursts(df)
    assert out["cluster_id"].iloc[0] == out["cluster_id"].iloc[1]


def test_cluster_bursts_different_scenes_never_cluster():
    t0 = datetime(2024, 1, 1, 12, 0, 0)
    emb = _norm(np.random.default_rng(0).standard_normal(384).astype(np.float32))
    df = pd.DataFrame([
        {"scene": "stilllife", "datetime": t0, "embedding": emb},
        {"scene": "portrait", "datetime": t0 + timedelta(milliseconds=500), "embedding": emb},
    ])
    out = cluster_bursts(df)
    assert out["cluster_id"].iloc[0] != out["cluster_id"].iloc[1]
