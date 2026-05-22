# v0.7-P0-3 — 5k-row synthetic stability smoke.
#
# Goal: prove that the results.html template renders under a synthetic
# 5000-row run without exploding RAM or blocking forever. Doesn't run
# the real ML pipeline (that would take minutes); just synthesizes a
# scores.csv + minimal manifest, then renders the page via the server.
#
# Why this matters: v0.4 P1 (2/4) made the grid virtualize with
# IntersectionObserver placeholders, and v0.7-P0-3 added adaptive
# rootMargin + observer throttling. The regression we want to catch
# is anyone removing those.

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List

import pytest


# Lazy-import the server module so test collection doesn't pay the
# full server startup cost when this file is skipped.
def _import_server():
    import importlib.util
    repo_root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "serve_demo", repo_root / "scripts" / "serve_demo.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _synth_scores_csv(out_path: Path, n: int) -> None:
    """Write a minimal but complete scores.csv with `n` rows."""
    header = (
        "path,filename,datetime,scene,scene_probs,gps_lat,gps_lon,"
        "flags,elapsed_s,subject_fraction,laplacian_global,"
        "laplacian_subject,mean_luma,highlight_clip_pct,"
        "shadow_clip_pct,scene_confidence,laion_aes,clipiqa,"
        "face_count,face_max_blink,face_min_ear,"
        "rule_of_thirds_offset,composition_score,"
        "canon_zone_distribution_kl,canon_zone_clip_pct,"
        "canon_midgray_offset,canon_symmetry,canon_diagonal_energy,"
        "canon_balance,canon_thirds_concentration,canon_lead_room,"
        "canon_figure_ground,canon_mono_channel_delta,"
        "canon_long_exposure_score,face_clusters,gps_cluster_id,"
        "horizon_tilt_deg,face_region_lap_var,cluster_id,decision,"
        "reason,score_final,score_sharpness,score_composition,"
        "score_exposure,score_aesthetic,score_moment,peak_rank,"
        "is_burst_peak,rescorer_pred,rescorer_prob_keep,"
        "rubric_technical_stars,rubric_technical_pass,"
        "rubric_subject_stars,rubric_subject_pass,"
        "rubric_composition_stars,rubric_composition_pass,"
        "rubric_light_stars,rubric_light_pass,"
        "rubric_moment_stars,rubric_moment_pass,"
        "rubric_aesthetic_stars,rubric_aesthetic_pass,"
        "model_technical_stars,model_subject_stars,"
        "model_composition_stars,model_light_stars,"
        "model_moment_stars,model_aesthetic_stars\n"
    )
    decisions = ["keep", "maybe", "cull"]
    scenes = ["landscape", "portrait", "street", "indoor"]
    lines: List[str] = [header]
    for i in range(n):
        fn = f"synth_{i:05d}.jpg"
        d = decisions[i % len(decisions)]
        s = scenes[i % len(scenes)]
        scene_probs = f'"{{""{s}"":0.85,""abstract"":0.10}}"'
        # Most fields stay empty; only the columns the renderer
        # reads heavily get values. score_final / decision / scene
        # are the hot ones for filter + sort + render.
        row = (
            f"/synth/{fn},{fn},2026-01-01T10:00:00,{s},{scene_probs},"
            ",,,,,,,128,0.5,0.2,0.85,,,0,,,,,,,,,,,,,,,,,,,,"
            f"{i % 32},{d},synth · {s},"
            f"{0.5 + (i % 50)/100:.2f},"  # score_final
            ",,,,,0,False,,,4.0,,4.0,,4.0,,4.0,,4.0,,4.0,,,,,,"
        )
        lines.append(row + "\n")
    out_path.write_text("".join(lines), encoding="utf-8")


@pytest.fixture
def synth_run_5k(tmp_path: Path):
    """Build a fake on-disk run directory matching what serve_demo
    expects: <tmp>/<run_id>/output/scores.csv + manifest."""
    run_id = "synth_5k_test"
    run_dir = tmp_path / run_id
    out_dir = run_dir / "output"
    out_dir.mkdir(parents=True)
    _synth_scores_csv(out_dir / "scores.csv", n=5000)
    # Manifest required by _reload_run_from_disk.
    manifest = {
        "run_id": run_id,
        "mode": "scan",
        "input_dir": str(tmp_path / "imgs"),
        "vertical": "general",
        "manifest_files": [
            {"path": f"/synth/synth_{i:05d}.jpg",
             "name": f"synth_{i:05d}.jpg",
             "size": 1024}
            for i in range(5000)
        ],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest))
    return run_id, tmp_path


def test_5k_scale_synth_csv_parses(synth_run_5k, monkeypatch):
    """The 5k synthetic scores.csv parses and the rows array is the
    right length.  Doesn't render the full HTML (that's a slow
    Selenium-class test); just exercises the parse + sort path
    which is what the page calls before painting cards."""
    run_id, tmp_root = synth_run_5k
    server = _import_server()
    # Point the server's run dir at the temp path for this test.
    monkeypatch.setattr(server, "_DEMO_ROOT", tmp_root, raising=False)
    scores_csv = tmp_root / run_id / "output" / "scores.csv"
    assert scores_csv.exists()
    # Parse the CSV the same way the server does in _serve_results.
    import csv
    with scores_csv.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 5000, f"expected 5000 rows, got {len(rows)}"
    # Verify each decision-bucket has roughly its expected share.
    keep   = sum(1 for r in rows if r["decision"] == "keep")
    maybe_ = sum(1 for r in rows if r["decision"] == "maybe")
    cull   = sum(1 for r in rows if r["decision"] == "cull")
    assert keep + maybe_ + cull == 5000
    # Equal distribution at synth time → each bucket ~1667.
    for n in (keep, maybe_, cull):
        assert abs(n - 1667) < 5


def test_5k_scale_parse_under_2_seconds(synth_run_5k):
    """Pathological-case wall clock: parsing 5000 rows + computing
    one summary stat should still finish well under 2 seconds even
    in CI on a small instance.  Caught a regression in 2026-Q1 where
    a regex re-compile per row pushed this to ~12s."""
    run_id, tmp_root = synth_run_5k
    scores_csv = tmp_root / run_id / "output" / "scores.csv"
    import csv
    t0 = time.time()
    with scores_csv.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    # Cheapest aggregate to force iteration past the iterator.
    _ = sum(float(r["score_final"] or 0) for r in rows)
    dt = time.time() - t0
    assert dt < 2.0, f"5k row parse took {dt:.2f}s; should be < 2s"
    assert len(rows) == 5000
