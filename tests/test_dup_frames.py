"""v2.7 — tests for duplicate / near-static frame trimming."""
from __future__ import annotations

import numpy as np

from pixcull.scoring.dup_frames import (
    dhash, find_duplicate_runs, hamming, trim_plan)


def test_hamming():
    assert hamming(0b1010, 0b1000) == 1
    assert hamming(0, (1 << 64) - 1) == 64
    assert hamming(42, 42) == 0


def test_find_runs_basic():
    # 0,1,2 near-static; 3 is a cut; 4,5 near-static
    h = [10, 10, 11, 5000, 9000, 9001]
    assert find_duplicate_runs(h, max_distance=2, min_run=2) == [(0, 2), (4, 5)]


def test_find_runs_min_run():
    h = [10, 10, 5000, 9000]
    assert find_duplicate_runs(h, max_distance=2, min_run=2) == [(0, 1)]
    assert find_duplicate_runs(h, max_distance=2, min_run=3) == []


def test_find_runs_all_static_and_all_cuts():
    assert find_duplicate_runs([7, 7, 7, 7], max_distance=1) == [(0, 3)]
    # every frame is a hard cut → no runs (distances all >1)
    assert find_duplicate_runs([1, 1 << 20, 1 << 40, 1 << 60], max_distance=1) == []


def test_trim_plan_keeps_one_per_run():
    ids = ["f0", "f1", "f2", "f3", "f4", "f5"]
    h = [10, 10, 11, 5000, 9000, 9001]
    plan = trim_plan(ids, h, max_distance=2, min_run=2, keep="first")
    assert plan["drop_ids"] == ["f1", "f2", "f5"]
    assert plan["keep_ids"] == ["f0", "f3", "f4"]
    assert plan["runs"][0] == {
        "start": 0, "end": 2, "keep": "f0", "drop": ["f1", "f2"]}


def test_trim_plan_keep_middle_last():
    ids = ["a", "b", "c"]; h = [5, 5, 5]
    assert trim_plan(ids, h, max_distance=1, keep="middle")["keep_ids"] == ["b"]
    assert trim_plan(ids, h, max_distance=1, keep="last")["keep_ids"] == ["c"]
    assert trim_plan(ids, h, max_distance=1, keep="first")["keep_ids"] == ["a"]


def test_trim_plan_mismatch_is_noop():
    plan = trim_plan(["a", "b"], [1], max_distance=2)
    assert plan["keep_ids"] == ["a", "b"] and plan["drop_ids"] == []


def test_dhash_identical_and_scale_invariant():
    from PIL import Image
    arr = np.random.default_rng(3).integers(0, 256, (80, 80), dtype=np.uint8)
    a = Image.fromarray(arr, "L")
    a2 = Image.fromarray(arr.copy(), "L")
    assert hamming(dhash(a), dhash(a2)) == 0            # pixel-identical
    big = a.resize((160, 160))
    assert hamming(dhash(a), dhash(big)) <= 2           # robust to scale


def test_dhash_distinguishes_content():
    from PIL import Image
    flat = Image.new("L", (64, 64), 128)                # no gradient → dHash 0
    arr = np.concatenate(
        [np.full((64, 32), 255, np.uint8), np.zeros((64, 32), np.uint8)], axis=1)
    edge = Image.fromarray(arr, "L")                    # bright→dark step
    assert dhash(flat) == 0
    assert hamming(dhash(flat), dhash(edge)) >= 4       # a real edge differs


def test_trim_dupes_cli(tmp_path):
    """End-to-end CLI: 3 identical (flat) frames + 1 distinct → 1 run,
    2 trimmable, JSON plan written."""
    import json
    from PIL import Image
    from typer.testing import CliRunner
    from pixcull.cli import app
    fd = tmp_path / "video_frames" / "v"; fd.mkdir(parents=True)
    for i in range(3):                               # flat → dHash 0 → one run
        Image.new("L", (48, 48), 128).save(fd / f"frame_{i:06d}.jpg", quality=95)
    arr = np.concatenate(
        [np.full((48, 24), 255, np.uint8), np.zeros((48, 24), np.uint8)], axis=1)
    Image.fromarray(arr, "L").save(fd / "frame_000003.jpg", quality=95)  # a cut
    rep = tmp_path / "plan.json"
    res = CliRunner().invoke(app, ["trim-dupes", str(fd), "-o", str(rep)])
    assert res.exit_code == 0, res.stdout
    data = json.loads(rep.read_text(encoding="utf-8"))
    assert data["schema"] == "pixcull.trim_dupes.v1"
    assert sorted(data["drop_ids"]) == ["frame_000001.jpg", "frame_000002.jpg"]
    assert "frame_000000.jpg" in data["keep_ids"]
    assert "frame_000003.jpg" in data["keep_ids"]     # the distinct frame survives


def test_trim_dupes_cli_empty_dir(tmp_path):
    """No frames → friendly non-zero exit, not a crash."""
    from typer.testing import CliRunner
    from pixcull.cli import app
    (tmp_path / "empty").mkdir()
    res = CliRunner().invoke(app, ["trim-dupes", str(tmp_path / "empty")])
    assert res.exit_code == 1
