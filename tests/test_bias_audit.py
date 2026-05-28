"""Tests for pixcull/scoring/bias_audit.py — v0.13-P0-4."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixcull.scoring.bias_audit import (
    BiasFinding,
    BiasReport,
    BucketStats,
    _bucket_aperture,
    _bucket_time_of_day,
    _compute_findings,
    build_report,
    get_report,
)


# ---------------------------------------------------------------------------
# bucket derivers
# ---------------------------------------------------------------------------


def test_bucket_time_of_day_segments():
    assert _bucket_time_of_day(6) == "early_morning"
    assert _bucket_time_of_day(10) == "morning"
    assert _bucket_time_of_day(13) == "midday"
    assert _bucket_time_of_day(16) == "afternoon"
    assert _bucket_time_of_day(19) == "evening"
    assert _bucket_time_of_day(23) == "night"
    assert _bucket_time_of_day(3) == "night"
    assert _bucket_time_of_day(None) is None


def test_bucket_aperture_brackets():
    assert _bucket_aperture(1.4) == "f1.4-1.8"
    assert _bucket_aperture(1.8) == "f1.4-1.8"
    assert _bucket_aperture(2.0) == "f2-2.8"
    assert _bucket_aperture(2.8) == "f2-2.8"
    assert _bucket_aperture(4.0) == "f4-5.6"
    assert _bucket_aperture(8.0) == "f8+"
    assert _bucket_aperture(11.0) == "f8+"
    assert _bucket_aperture(None) is None
    assert _bucket_aperture(0) is None


# ---------------------------------------------------------------------------
# BucketStats properties
# ---------------------------------------------------------------------------


def test_bucket_stats_rates():
    b = BucketStats(family="scene", value="wedding",
                    n=100, n_keep=40, n_cull=30, n_model_cull=50,
                    n_reversals=15)
    assert abs(b.keep_rate - 0.40) < 1e-6
    assert abs(b.cull_rate - 0.30) < 1e-6
    assert abs(b.model_cull_rate - 0.50) < 1e-6
    assert abs(b.reversal_rate - 0.15) < 1e-6


def test_bucket_stats_zero_n_safe():
    b = BucketStats(family="scene", value="empty")
    assert b.keep_rate == 0.0
    assert b.reversal_rate == 0.0


def test_under_sampled_threshold():
    assert BucketStats(family="x", value="y", n=5).under_sampled
    assert not BucketStats(family="x", value="y", n=10).under_sampled


# ---------------------------------------------------------------------------
# build_report — end-to-end on tmpdir
# ---------------------------------------------------------------------------


def _write_run(root: Path, run_name: str, rows: list[dict]) -> None:
    run = root / run_name
    run.mkdir(parents=True, exist_ok=True)
    with (run / "annotations.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def test_build_report_empty_runs_root(tmp_path):
    r = build_report(tmp_path / "absent")
    assert r.n_total_rows == 0
    assert r.buckets == []
    assert r.findings == []


def test_build_report_aggregates_scene_buckets(tmp_path):
    _write_run(tmp_path, "r1", [
        {"filename": "a.jpg", "decision": "keep", "scene": "wedding",
         "model_decision": "keep"},
        {"filename": "b.jpg", "decision": "cull", "scene": "wedding",
         "model_decision": "keep"},  # reversal
        {"filename": "c.jpg", "decision": "keep", "scene": "portrait",
         "model_decision": "keep"},
    ])
    r = build_report(tmp_path)
    assert r.n_total_rows == 3
    assert r.n_total_runs == 1
    by_v = {(b.family, b.value): b for b in r.buckets}
    assert by_v[("scene", "wedding")].n == 2
    assert by_v[("scene", "wedding")].n_reversals == 1
    assert by_v[("scene", "portrait")].n == 1


def test_build_report_aggregates_time_of_day(tmp_path):
    _write_run(tmp_path, "r1", [
        {"filename": f"x{i}.jpg", "decision": "keep",
         "capture_hour": 6} for i in range(3)
    ] + [
        {"filename": f"y{i}.jpg", "decision": "cull",
         "capture_hour": 19} for i in range(2)
    ])
    r = build_report(tmp_path)
    by_v = {(b.family, b.value): b for b in r.buckets}
    assert by_v[("time_of_day", "early_morning")].n == 3
    assert by_v[("time_of_day", "evening")].n == 2


def test_build_report_aggregates_aperture(tmp_path):
    _write_run(tmp_path, "r1", [
        {"filename": "a.jpg", "decision": "keep", "aperture": 1.4},
        {"filename": "b.jpg", "decision": "keep", "aperture": 2.8},
        {"filename": "c.jpg", "decision": "cull", "aperture": 8},
    ])
    r = build_report(tmp_path)
    by_v = {(b.family, b.value): b for b in r.buckets}
    assert by_v[("aperture", "f1.4-1.8")].n == 1
    assert by_v[("aperture", "f2-2.8")].n == 1
    assert by_v[("aperture", "f8+")].n == 1


def test_build_report_missing_fields_silently_skip(tmp_path):
    """A row missing all bucket fields contributes only to families
    it has data for."""
    _write_run(tmp_path, "r1", [
        {"filename": "a.jpg", "decision": "keep"},  # no scene/hour/aperture
    ])
    r = build_report(tmp_path)
    # No buckets created at all
    assert r.buckets == []
    # But the row is counted in n_total_rows
    assert r.n_total_rows == 1


# ---------------------------------------------------------------------------
# outlier detection
# ---------------------------------------------------------------------------


def test_compute_findings_flags_high_cull_rate():
    """5 buckets with cull rates [0.10, 0.10, 0.10, 0.10, 0.80] →
    the 0.80 bucket should be flagged."""
    bs = []
    # Need at least _MIN_BUCKET_N=10 samples to be eligible
    for i in range(4):
        bs.append(BucketStats(family="scene", value=f"v{i}",
                              n=20, n_cull=2,    # cull_rate = 0.10
                              n_keep=10))
    bs.append(BucketStats(family="scene", value="outlier",
                          n=20, n_cull=16, n_keep=2))  # cull_rate = 0.80
    findings = _compute_findings(bs)
    # At least one finding for the outlier
    flagged = [f for f in findings if f.value == "outlier"
               and f.metric == "cull_rate"]
    assert flagged
    assert flagged[0].z_score > 1.5


def test_compute_findings_skips_when_too_few_buckets():
    """< 3 buckets means we can't compute meaningful z-scores."""
    bs = [
        BucketStats(family="scene", value="wedding", n=20, n_cull=5),
        BucketStats(family="scene", value="portrait", n=20, n_cull=8),
    ]
    assert _compute_findings(bs) == []


def test_compute_findings_skips_under_sampled():
    """Under-sampled buckets shouldn't drive outliers."""
    bs = [
        BucketStats(family="scene", value=f"v{i}",
                    n=20, n_cull=2, n_keep=10)
        for i in range(4)
    ] + [
        BucketStats(family="scene", value="tiny",
                    n=3, n_cull=3),  # under-sampled — should be ignored
    ]
    findings = _compute_findings(bs)
    # The 4 eligible buckets all have the same cull_rate=0.10 →
    # std=0 → no findings
    assert findings == []


# ---------------------------------------------------------------------------
# cache layer
# ---------------------------------------------------------------------------


def test_get_report_uses_cache_within_ttl(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    runs = tmp_path / "runs"
    _write_run(runs, "r1", [{"filename": "a.jpg", "decision": "keep",
                              "scene": "wedding"}])
    r1 = get_report(runs)
    # Mutate the file — cached read should NOT pick this up
    _write_run(runs, "r1", [{"filename": "b.jpg", "decision": "cull",
                              "scene": "portrait"}])
    r2 = get_report(runs)
    # Same row count → cache hit
    assert r1.n_total_rows == r2.n_total_rows


def test_get_report_force_rebuilds(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    runs = tmp_path / "runs"
    _write_run(runs, "r1", [{"filename": "a.jpg", "decision": "keep",
                              "scene": "wedding"}])
    r1 = get_report(runs)
    _write_run(runs, "r2", [{"filename": "b.jpg", "decision": "cull",
                              "scene": "portrait"}])
    r2 = get_report(runs, force=True)
    assert r2.n_total_rows > r1.n_total_rows


def test_report_to_dict_round_trip(tmp_path):
    _write_run(tmp_path, "r1", [
        {"filename": "a.jpg", "decision": "keep", "scene": "wedding",
         "model_decision": "cull"},
    ])
    r = build_report(tmp_path)
    d = r.to_dict()
    assert "buckets" in d
    assert "findings" in d
    assert d["n_total_rows"] == 1


# ---------------------------------------------------------------------------
# v0.13.2 — per-user slicing
# ---------------------------------------------------------------------------


def test_build_report_user_filter_includes_only_matching(tmp_path):
    """user_filter='alice' should drop rows by other annotators."""
    _write_run(tmp_path, "r1", [
        {"filename": "a.jpg", "decision": "keep", "scene": "wedding",
         "edited_by": "alice"},
        {"filename": "b.jpg", "decision": "cull", "scene": "wedding",
         "edited_by": "bob"},
        {"filename": "c.jpg", "decision": "keep", "scene": "portrait",
         "edited_by": "alice"},
    ])
    r = build_report(tmp_path, user_filter="alice")
    assert r.n_total_rows == 2   # bob's row dropped
    by_v = {(b.family, b.value): b for b in r.buckets}
    assert by_v[("scene", "wedding")].n == 1   # only alice's wedding
    assert by_v[("scene", "portrait")].n == 1


def test_build_report_user_filter_matches_user_id_too(tmp_path):
    """Both `edited_by` and `user_id` should match."""
    _write_run(tmp_path, "r1", [
        {"filename": "a.jpg", "decision": "keep", "scene": "wedding",
         "user_id": "alice"},
        {"filename": "b.jpg", "decision": "cull", "scene": "wedding",
         "user_id": "bob"},
    ])
    r = build_report(tmp_path, user_filter="alice")
    assert r.n_total_rows == 1


def test_build_report_user_filter_no_match_empty(tmp_path):
    _write_run(tmp_path, "r1", [
        {"filename": "a.jpg", "decision": "keep", "scene": "wedding",
         "edited_by": "alice"},
    ])
    r = build_report(tmp_path, user_filter="charlie")
    assert r.n_total_rows == 0


def test_build_report_no_user_filter_aggregates_all(tmp_path):
    _write_run(tmp_path, "r1", [
        {"filename": "a.jpg", "decision": "keep", "scene": "wedding",
         "edited_by": "alice"},
        {"filename": "b.jpg", "decision": "cull", "scene": "wedding",
         "edited_by": "bob"},
    ])
    r = build_report(tmp_path)
    assert r.n_total_rows == 2


def test_list_annotators(tmp_path):
    from pixcull.scoring.bias_audit import list_annotators
    _write_run(tmp_path, "r1", [
        {"filename": "a.jpg", "decision": "keep", "edited_by": "alice"},
        {"filename": "b.jpg", "decision": "keep", "edited_by": "alice"},
        {"filename": "c.jpg", "decision": "keep", "edited_by": "alice"},
        {"filename": "d.jpg", "decision": "cull", "edited_by": "bob"},
        {"filename": "e.jpg", "decision": "keep"},  # no editor — ignored
    ])
    out = list_annotators(tmp_path)
    assert out == ["alice", "bob"]   # alice has 3, bob has 1


def test_list_annotators_empty(tmp_path):
    from pixcull.scoring.bias_audit import list_annotators
    assert list_annotators(tmp_path / "absent") == []


def test_get_report_separate_caches_per_user(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    runs = tmp_path / "runs"
    _write_run(runs, "r1", [
        {"filename": "a.jpg", "decision": "keep", "scene": "wedding",
         "edited_by": "alice"},
        {"filename": "b.jpg", "decision": "cull", "scene": "wedding",
         "edited_by": "bob"},
    ])
    from pixcull.scoring.bias_audit import _cache_path
    p_global = _cache_path()
    p_alice = _cache_path("alice")
    p_bob = _cache_path("bob")
    assert p_global != p_alice
    assert p_alice != p_bob
    assert "alice" in str(p_alice)
    assert "bob" in str(p_bob)
    # And the reports are different
    r_all = get_report(runs)
    r_alice = get_report(runs, user_filter="alice")
    r_bob = get_report(runs, user_filter="bob")
    assert r_all.n_total_rows == 2
    assert r_alice.n_total_rows == 1
    assert r_bob.n_total_rows == 1
