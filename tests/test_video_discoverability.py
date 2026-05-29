"""v2.1-P0-2 — /results video-review badge + /history 🎬 marker."""

from __future__ import annotations

import http.client
import importlib.util
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest


def _import_server():
    repo = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "serve_demo", repo / "scripts" / "serve_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def server_mod():
    return _import_server()


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


def _tiny_jpeg(path):
    from PIL import Image
    Image.new("RGB", (32, 24), (90, 70, 160)).save(path, "JPEG")


def _build_servable_video_run(root: Path, rid: str, n=3):
    run = root / rid
    (run / "output").mkdir(parents=True)
    # output/scores.csv → _build_results renders /results
    lines = [_HEADER]
    for i in range(n):
        fn = f"frame_{i+1:06d}.jpg"
        row = (f"/x/{fn},{fn},,landscape,\"{{'landscape':0.9}}\",,,,,0.5,800,800,"
               f"128,5,5,0.9,4.2,0.4,0,,,0.6,,,,,,,,,,,,[],,{i},keep,demo,"
               f"0.7,1.0,0.6,0.5,0.5,0.5,0,False,,4,,4,,4,,4,,4,,4,,"
               ",,,,,\n")
        lines.append(row)
    (run / "output" / "scores.csv").write_text("".join(lines), encoding="utf-8")
    # output/manifest.json → _reload_run_from_disk recognises the run (scan mode)
    (run / "output" / "manifest.json").write_text("{}")
    # video artifacts → is_video_run True
    fdir = run / "video_frames" / "clip"
    fdir.mkdir(parents=True)
    frames = []
    for i in range(n):
        fn = f"frame_{i+1:06d}.jpg"
        _tiny_jpeg(fdir / fn)
        frames.append({"frame_id": f"frame_{i+1:06d}", "timestamp_s": float(i),
                       "filename": fn})
    (fdir / "manifest.json").write_text(json.dumps(
        {"video_id": "clip", "frame_count": n, "frames": frames}))
    (run / "temporal.json").write_text(json.dumps(
        {"schema_version": 1, "frames": [], "windows": []}))
    return run


def _build_photo_run(root: Path, rid: str):
    run = root / rid
    (run / "output").mkdir(parents=True)
    row = ("/x/p.jpg,p.jpg,,landscape,\"{'landscape':0.9}\",,,,,0.5,800,800,128,"
           "5,5,0.9,4.2,0.4,0,,,0.6,,,,,,,,,,,,[],,0,keep,demo,0.7,1.0,0.6,0.5,"
           "0.5,0.5,0,False,,4,,4,,4,,4,,4,,4,,,,,,,\n")
    (run / "output" / "scores.csv").write_text(_HEADER + row, encoding="utf-8")
    (run / "output" / "manifest.json").write_text("{}")
    return run


@pytest.fixture
def live(server_mod, tmp_path, monkeypatch):
    monkeypatch.setattr(server_mod, "_DEMO_ROOT", tmp_path)
    _build_servable_video_run(tmp_path, "vidrun")
    _build_photo_run(tmp_path, "photorun")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server_mod._Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address
    srv.shutdown()


def _get(addr, path):
    c = http.client.HTTPConnection(addr[0], addr[1], timeout=5)
    c.request("GET", path); r = c.getresponse(); body = r.read(); c.close()
    return r.status, body.decode("utf-8", "replace")


def test_results_video_run_has_review_badge(live):
    status, html = _get(live, "/results/vidrun")
    assert status == 200
    assert "🎬 视频审片" in html
    assert "/video/vidrun" in html
    assert "/timeline/vidrun" in html


def test_results_photo_run_has_no_badge(live):
    status, html = _get(live, "/results/photorun")
    assert status == 200
    assert "videoReviewCta" not in html
    assert "🎬 视频审片" not in html


def test_history_marks_video_run(live):
    status, html = _get(live, "/history")
    assert status == 200
    # The video run is flagged with 🎬; the photo run is not video-marked.
    assert "🎬" in html
