"""v2.0-P0-4 — tests for the video review surface in serve_demo.py.

Covers the module-level helpers (run-id validation, video-run detection)
and the three live HTTP endpoints (data / frame / review page) via a
real ThreadingHTTPServer on an ephemeral port, against a synthetic
video run dir.
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest


def _import_server():
    repo_root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "serve_demo", repo_root / "scripts" / "serve_demo.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def server_mod():
    return _import_server()


def _tiny_jpeg(path: Path):
    from PIL import Image
    Image.new("RGB", (32, 24), (90, 70, 160)).save(path, "JPEG")


def _build_video_run(root: Path, rid: str = "vidrun", n: int = 4) -> Path:
    run_dir = root / rid
    fdir = run_dir / "video_frames" / "clip_abc123"
    fdir.mkdir(parents=True)
    frames = []
    for i in range(n):
        fn = f"frame_{i+1:06d}.jpg"
        _tiny_jpeg(fdir / fn)
        frames.append({"frame_id": f"frame_{i+1:06d}",
                       "timestamp_s": float(i), "filename": fn})
    (fdir / "manifest.json").write_text(json.dumps({
        "video_id": "clip_abc123", "fps": 30.0, "duration_s": float(n),
        "frame_count": n, "codec": "h264", "audio_track_count": 1,
        "source_name": "clip.mp4", "frames": frames,
    }))
    (run_dir / "temporal.json").write_text(json.dumps({
        "schema_version": 1, "window_s": 1.0, "frame_count": n,
        "frames": [
            {"frame_id": f"frame_{i+1:06d}", "timestamp_s": float(i),
             "score_final": 0.5 + 0.05 * i, "score_temporal": 0.3 + 0.1 * i,
             "motion_continuity": 0.9, "temporal_stability": 0.8,
             "burst_event": 0.2 * i}
            for i in range(n)
        ],
        "windows": [],
    }))
    (run_dir / "reel_candidates.json").write_text(json.dumps([
        {"rank": 1, "start_s": 0.0, "end_s": 2.0, "duration_s": 2.0,
         "window_len_s": 2.0, "score": 0.88, "window_score": 1.5,
         "confidence": 0.9, "novelty": 1.0, "why": "精彩瞬间 + 平稳运镜",
         "best_frame_id": "frame_000002", "best_frame_score": 0.75,
         "frame_ids": ["frame_000001", "frame_000002"]},
    ]))
    return run_dir


@pytest.fixture
def live_server(server_mod, tmp_path, monkeypatch):
    """Start serve_demo on an ephemeral port with _DEMO_ROOT → tmp."""
    monkeypatch.setattr(server_mod, "_DEMO_ROOT", tmp_path)
    _build_video_run(tmp_path, "vidrun")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server_mod._Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address
    srv.shutdown()


def _get(addr, path):
    conn = http.client.HTTPConnection(addr[0], addr[1], timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, resp.getheader("Content-Type"), body


# --------------------------------------------------------------------------
# module helpers
# --------------------------------------------------------------------------

def test_safe_run_id(server_mod):
    assert server_mod._safe_run_id("run_abc-123.v2") == "run_abc-123.v2"
    assert server_mod._safe_run_id("../etc") is None
    assert server_mod._safe_run_id("a/b") is None
    assert server_mod._safe_run_id("") is None
    assert server_mod._safe_run_id("..") is None


def test_video_frames_dir(server_mod, tmp_path):
    run_dir = _build_video_run(tmp_path, "r1")
    fdir = server_mod._video_frames_dir(run_dir)
    assert fdir is not None and fdir.name == "clip_abc123"
    # No video_frames ⇒ None.
    (tmp_path / "empty").mkdir()
    assert server_mod._video_frames_dir(tmp_path / "empty") is None


def test_video_frames_dir_ambiguous(server_mod, tmp_path):
    run = tmp_path / "amb"
    for vid in ("a", "b"):
        d = run / "video_frames" / vid
        d.mkdir(parents=True)
        (d / "manifest.json").write_text("{}")
    assert server_mod._video_frames_dir(run) is None


def test_is_video_run(server_mod, tmp_path, monkeypatch):
    monkeypatch.setattr(server_mod, "_DEMO_ROOT", tmp_path)
    _build_video_run(tmp_path, "vr")
    assert server_mod.is_video_run("vr") is True
    assert server_mod.is_video_run("nope") is False
    assert server_mod.is_video_run("../x") is False


def test_render_html_injects_runid(server_mod):
    html = server_mod._render_video_review_html("myrun_42")
    assert 'RUN_ID = "myrun_42"' in html
    assert "视频审片" in html
    assert "score_temporal" in html


# --------------------------------------------------------------------------
# live HTTP endpoints
# --------------------------------------------------------------------------

def test_endpoint_video_data(live_server):
    status, ctype, body = _get(live_server, "/video/data/vidrun")
    assert status == 200
    assert "application/json" in ctype
    data = json.loads(body)
    assert data["ok"] is True
    assert data["run_id"] == "vidrun"
    assert data["frame_base"] == "/video/frame/vidrun/"
    assert data["manifest"]["codec"] == "h264"
    assert len(data["temporal"]["frames"]) == 4
    assert len(data["reel"]) == 1
    assert data["reel"][0]["why"]


def test_endpoint_video_data_missing(live_server):
    status, _, body = _get(live_server, "/video/data/ghostrun")
    assert status == 404
    assert json.loads(body)["ok"] is False


def test_endpoint_video_data_bad_id(live_server):
    status, _, body = _get(live_server, "/video/data/..%2fetc")
    assert status in (400, 404)


def test_endpoint_frame_served(live_server):
    status, ctype, body = _get(live_server, "/video/frame/vidrun/frame_000001")
    assert status == 200
    assert ctype == "image/jpeg"
    assert body[:2] == b"\xff\xd8"  # JPEG SOI marker
    # .jpg suffix is optional.
    status2, _, _ = _get(live_server, "/video/frame/vidrun/frame_000002.jpg")
    assert status2 == 200


def test_endpoint_frame_missing(live_server):
    status, _, _ = _get(live_server, "/video/frame/vidrun/frame_999999")
    assert status == 404


def test_endpoint_frame_traversal_blocked(live_server):
    status, _, _ = _get(
        live_server, "/video/frame/vidrun/..%2f..%2f..%2fetc%2fpasswd")
    assert status in (403, 404)


def test_endpoint_review_page(live_server):
    status, ctype, body = _get(live_server, "/video/vidrun")
    assert status == 200
    assert "text/html" in ctype
    text = body.decode("utf-8")
    assert "视频审片" in text
    assert 'RUN_ID = "vidrun"' in text
    assert "/video/data/" in text


def test_endpoint_review_page_not_video_run(live_server, tmp_path):
    # A run dir with no temporal.json ⇒ friendly 404 page.
    (tmp_path / "photorun").mkdir()
    status, ctype, body = _get(live_server, "/video/photorun")
    assert status == 404
    assert "text/html" in ctype
    assert "不是一个视频 run" in body.decode("utf-8")
