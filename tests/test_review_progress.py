"""v2.15-P0 — culling-pass finish line: per-row ``human_decided`` +
``summary.n_human_decided`` from _build_results.

The distinction under test: an annotations.jsonl record with an
``overall_label`` (keep/maybe/cull) marks the photo as human-DECIDED;
a rubric-stars-only record marks it human-LABELED but NOT decided —
the 待审 counter must only credit the former.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_HEADER = (
    "path,filename,datetime,scene,scene_probs,gps_lat,gps_lon,flags,"
    "elapsed_s,subject_fraction,laplacian_global,laplacian_subject,mean_luma,"
    "highlight_clip_pct,shadow_clip_pct,scene_confidence,laion_aes,clipiqa,"
    "face_count,horizon_tilt_deg,rule_of_thirds_offset,composition_score,"
    "canon_zone_distribution_kl,canon_zone_clip_pct,canon_midgray_offset,"
    "canon_symmetry,canon_diagonal_energy,canon_balance,"
    "canon_thirds_concentration,canon_lead_room,canon_figure_ground,"
    "canon_mono_channel_delta,canon_long_exposure_score,face_clusters,"
    "gps_cluster_id,cluster_id,decision,reason,score_final,score_sharpness,"
    "score_composition,score_exposure,score_aesthetic,score_moment,peak_rank,"
    "is_burst_peak,burst_peak_reason,rubric_technical_stars,"
    "rubric_technical_pass,rubric_subject_stars,rubric_subject_pass,"
    "rubric_composition_stars,rubric_composition_pass,rubric_light_stars,"
    "rubric_light_pass,rubric_moment_stars,rubric_moment_pass,"
    "rubric_aesthetic_stars,rubric_aesthetic_pass,model_technical_stars,"
    "model_subject_stars,model_composition_stars,model_light_stars,"
    "model_moment_stars,model_aesthetic_stars\n"
)


@pytest.fixture(scope="module")
def server_mod():
    repo = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "serve_demo_review_test", repo / "scripts" / "serve_demo.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["serve_demo_review_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _row(fn, decision):
    return (f"/x/{fn},{fn},,landscape,\"{{'landscape':0.9}}\",,,,,0.5,800,800,"
            f"128,5,5,0.9,4.2,0.4,0,,,0.6,,,,,,,,,,,,[],,0,{decision},demo,"
            f"0.7,1.0,0.6,0.5,0.5,0.5,0,False,,4,,4,,4,,4,,4,,4,,,,,,,\n")


@pytest.fixture
def run_with_annotations(server_mod, tmp_path, monkeypatch):
    rid = "reviewrun"
    out = tmp_path / rid / "output"
    out.mkdir(parents=True)
    rows = [_row("p1.jpg", "keep"), _row("p2.jpg", "maybe"),
            _row("p3.jpg", "keep"), _row("p4.jpg", "cull")]
    (out / "scores.csv").write_text(_HEADER + "".join(rows), encoding="utf-8")
    (out / "manifest.json").write_text("{}")
    ann = [
        # human DECIDED p1 (overall_label present)
        {"filename": "p1.jpg", "overall_label": "keep"},
        # human rubric-LABELED p2 only (stars, no overall_label) → not decided
        {"filename": "p2.jpg", "axes": {"technical": {"stars": 4}}},
    ]
    (out / "annotations.jsonl").write_text(
        "\n".join(json.dumps(a) for a in ann) + "\n", encoding="utf-8")
    monkeypatch.setattr(server_mod, "_DEMO_ROOT", tmp_path)
    assert server_mod._reload_run_from_disk(rid) is not None
    return rid


def test_human_decided_flag_and_summary_count(server_mod, run_with_annotations):
    rows, summary = server_mod._build_results(run_with_annotations)
    by_fn = {r["filename"]: r for r in rows}
    assert by_fn["p1.jpg"]["human_decided"] is True     # overall_label → decided
    assert by_fn["p2.jpg"]["human_decided"] is False    # rubric-only → NOT decided
    assert by_fn["p3.jpg"]["human_decided"] is False
    assert by_fn["p4.jpg"]["human_decided"] is False
    assert summary["n_human_decided"] == 1
    # ...while the rubric-progress counter still credits BOTH annotations
    assert summary["n_human_labeled"] == 2
    # the unreviewed count the UI derives
    assert summary["n_total"] - summary["n_human_decided"] == 3
