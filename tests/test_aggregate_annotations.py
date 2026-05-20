"""P-CORE-1 — tests for the annotation aggregation step that builds
training_v2.csv ahead of a rescorer retrain."""
from __future__ import annotations

import csv
import json
from pathlib import Path


def _seed_run(root: Path, run_id: str, rows: list[dict],
                annotations: list[dict]) -> None:
    out = root / run_id / "output"
    out.mkdir(parents=True, exist_ok=True)
    # scores.csv
    if rows:
        fields = list(rows[0].keys())
        with open(out / "scores.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in rows:
                w.writerow(r)
    # annotations.jsonl
    with open(out / "annotations.jsonl", "w", encoding="utf-8") as f:
        for a in annotations:
            f.write(json.dumps(a) + "\n")


def test_aggregate_pulls_annotations_into_unified_rows(tmp_path: Path):
    """Each annotation joins to its scores.csv row + gains manual_label."""
    from scripts.aggregate_annotations import aggregate

    _seed_run(
        tmp_path, "run_a",
        rows=[
            {"filename": "a.jpg", "score_final": "0.82", "scene": "landscape", "decision": "keep"},
            {"filename": "b.jpg", "score_final": "0.45", "scene": "landscape", "decision": "maybe"},
        ],
        annotations=[
            {"filename": "a.jpg", "overall_label": "keep",
             "cull_reason": "", "axes": {}, "timestamp": 1_234_500_000},
            {"filename": "b.jpg", "overall_label": "cull",
             "cull_reason": "focus_miss", "axes": {}, "timestamp": 1_234_500_100},
        ],
    )
    rows, columns = aggregate(tmp_path, golden=None)
    assert len(rows) == 2
    assert "manual_label" in columns
    assert "cull_reason" in columns
    assert "source_run" in columns
    # row a kept the score_final + got manual_label
    a = next(r for r in rows if r["filename"] == "a.jpg")
    assert a["manual_label"] == "keep"
    assert a["source_run"] == "run_a"
    assert a["score_final"] == "0.82"
    b = next(r for r in rows if r["filename"] == "b.jpg")
    assert b["manual_label"] == "cull"
    assert b["cull_reason"] == "focus_miss"


def test_aggregate_latest_wins_per_filename(tmp_path: Path):
    """Multiple annotations for the same file: latest one wins."""
    from scripts.aggregate_annotations import aggregate

    _seed_run(
        tmp_path, "run_a",
        rows=[{"filename": "x.jpg", "scene": "wildlife", "decision": "maybe"}],
        annotations=[
            {"filename": "x.jpg", "overall_label": "keep",  "axes": {}, "timestamp": 100},
            {"filename": "x.jpg", "overall_label": "maybe", "axes": {}, "timestamp": 200},
            {"filename": "x.jpg", "overall_label": "cull",  "axes": {},
             "cull_reason": "eyes_closed", "timestamp": 300},
        ],
    )
    rows, _ = aggregate(tmp_path, golden=None)
    assert len(rows) == 1
    assert rows[0]["manual_label"] == "cull"
    assert rows[0]["cull_reason"] == "eyes_closed"


def test_aggregate_seeds_with_golden_csv(tmp_path: Path):
    """A non-empty golden CSV gets prepended with source_run='_golden'."""
    from scripts.aggregate_annotations import aggregate

    golden = tmp_path / "training.csv"
    with open(golden, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["filename", "scene", "decision"])
        w.writeheader()
        w.writerow({"filename": "g1.jpg", "scene": "landscape", "decision": "keep"})
        w.writerow({"filename": "g2.jpg", "scene": "wildlife", "decision": "cull"})
    # No runs in demo_root → output is just the golden seed
    rows, columns = aggregate(tmp_path, golden=golden)
    assert len(rows) == 2
    assert all(r["source_run"] == "_golden" for r in rows)
    assert "source_run" in columns
    assert "ann_timestamp" in columns


def test_aggregate_skips_unlabeled_annotations(tmp_path: Path):
    """An annotation without overall_label keep/maybe/cull is skipped."""
    from scripts.aggregate_annotations import aggregate
    _seed_run(
        tmp_path, "run_a",
        rows=[{"filename": "z.jpg", "scene": "abstract", "decision": "maybe"}],
        annotations=[
            {"filename": "z.jpg", "overall_label": "", "axes": {}, "timestamp": 100},
        ],
    )
    rows, _ = aggregate(tmp_path, golden=None)
    assert rows == []


def test_aggregate_captures_per_axis_human_stars(tmp_path: Path):
    """When the user used the rubric modal, per-axis stars carry through."""
    from scripts.aggregate_annotations import aggregate
    _seed_run(
        tmp_path, "run_a",
        rows=[{"filename": "w.jpg", "scene": "portrait", "decision": "keep"}],
        annotations=[
            {"filename": "w.jpg", "overall_label": "keep",
             "axes": {
                 "technical": {"stars": 4.5},
                 "subject":   {"stars": 5.0},
             }, "timestamp": 100},
        ],
    )
    rows, columns = aggregate(tmp_path, golden=None)
    assert len(rows) == 1
    assert "human_technical_stars" in columns
    assert rows[0]["human_technical_stars"] == "4.5"
    assert rows[0]["human_subject_stars"] == "5.0"
