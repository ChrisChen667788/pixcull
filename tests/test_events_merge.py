"""Unit tests for the INFRA-3 multi-shooter event merger."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from pixcull.events import merge_runs


def _write_run(root: Path, run_id: str, rows: list[dict]) -> None:
    """Make a minimal source run with the given rows."""
    out = root / run_id / "output"
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / "scores.csv"
    if not rows:
        csv_path.write_text("filename\n", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def test_merge_two_runs_basic(tmp_path: Path):
    """Two non-overlapping shooters → merged run has all rows + source tag."""
    _write_run(tmp_path, "alice", [
        {"filename": "A001.jpg", "path": "/photos/alice/A001.jpg",
         "scene": "wedding", "decision": "keep", "cluster_id": "1"},
        {"filename": "A002.jpg", "path": "/photos/alice/A002.jpg",
         "scene": "wedding", "decision": "maybe", "cluster_id": "1"},
    ])
    _write_run(tmp_path, "bob", [
        {"filename": "B001.jpg", "path": "/photos/bob/B001.jpg",
         "scene": "wedding", "decision": "keep", "cluster_id": "1"},
    ])
    merged_id = merge_runs(["alice", "bob"], name="2026-wedding",
                            demo_root=tmp_path)
    assert merged_id.startswith("event_")
    merged_csv = tmp_path / merged_id / "output" / "scores.csv"
    assert merged_csv.is_file()

    with open(merged_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 3
    sources = sorted(r["source_run"] for r in rows)
    assert sources == ["alice", "alice", "bob"]
    # cluster_id rewritten to namespace by source
    cluster_ids = sorted(r["cluster_id"] for r in rows)
    assert cluster_ids == ["alice:1", "alice:1", "bob:1"]


def test_merge_collides_filename_disambiguates(tmp_path: Path):
    """Same camera-serial filename from two shooters → second gets prefixed."""
    _write_run(tmp_path, "alice", [
        {"filename": "IMG_0001.jpg", "path": "/photos/alice/IMG_0001.jpg",
         "decision": "keep"},
    ])
    _write_run(tmp_path, "bob", [
        {"filename": "IMG_0001.jpg", "path": "/photos/bob/IMG_0001.jpg",
         "decision": "keep"},
    ])
    merged_id = merge_runs(["alice", "bob"], demo_root=tmp_path)
    with open(tmp_path / merged_id / "output" / "scores.csv") as f:
        rows = list(csv.DictReader(f))
    fns = sorted(r["filename"] for r in rows)
    assert fns == ["IMG_0001.jpg", "bob__IMG_0001.jpg"]


def test_merge_writes_manifest(tmp_path: Path):
    """Manifest maps each merged filename back to its absolute on-disk source."""
    _write_run(tmp_path, "alice", [
        {"filename": "A.jpg", "path": "/photos/alice/A.jpg", "decision": "keep"},
    ])
    _write_run(tmp_path, "bob", [
        {"filename": "B.jpg", "path": "/photos/bob/B.jpg", "decision": "keep"},
    ])
    merged_id = merge_runs(["alice", "bob"], demo_root=tmp_path)
    manifest_path = tmp_path / merged_id / "output" / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text("utf-8"))
    assert manifest["A.jpg"] == "/photos/alice/A.jpg"
    assert manifest["B.jpg"] == "/photos/bob/B.jpg"


def test_merge_rejects_single_run(tmp_path: Path):
    _write_run(tmp_path, "alice", [{"filename": "A.jpg", "decision": "keep"}])
    with pytest.raises(ValueError):
        merge_runs(["alice"], demo_root=tmp_path)


def test_merge_rejects_missing_run(tmp_path: Path):
    _write_run(tmp_path, "alice", [{"filename": "A.jpg", "decision": "keep"}])
    with pytest.raises(FileNotFoundError):
        merge_runs(["alice", "ghost"], demo_root=tmp_path)


def test_merge_emits_event_meta(tmp_path: Path):
    _write_run(tmp_path, "alice", [{"filename": "A.jpg", "decision": "keep"}])
    _write_run(tmp_path, "bob", [{"filename": "B.jpg", "decision": "keep"}])
    merged_id = merge_runs(["alice", "bob"], name="My Event",
                            demo_root=tmp_path)
    meta_path = tmp_path / merged_id / "event_meta.json"
    assert meta_path.is_file()
    meta = json.loads(meta_path.read_text("utf-8"))
    assert meta["schema"] == "pixcull.event_merge.v1"
    assert meta["source_runs"] == ["alice", "bob"]
    assert meta["name"] == "My Event"
    assert "created_at" in meta
