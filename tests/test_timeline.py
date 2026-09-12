"""v2.0-P1-2 — tests for the joint photo+video timeline in serve_demo.py."""

from __future__ import annotations

import csv
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
        "serve_demo", repo_root / "pixcull" / "report" / "serve_app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def srv_mod():
    return _import_server()


def _tiny_jpeg(path):
    from PIL import Image
    Image.new("RGB", (32, 24), (90, 70, 160)).save(path, "JPEG")


def _build_video_run(root: Path, rid="vidrun"):
    fdir = root / rid / "video_frames" / "clipA"
    fdir.mkdir(parents=True)
    frames = [{"frame_id": "frame_000001", "timestamp_s": 0.0,
               "filename": "frame_000001.jpg"}]
    _tiny_jpeg(fdir / "frame_000001.jpg")
    (fdir / "manifest.json").write_text(json.dumps({
        "video_id": "clipA", "duration_s": 5.0, "frame_count": 1,
        "source_name": "clipA.mp4", "frames": frames}))
    (root / rid / "temporal.json").write_text(json.dumps(
        {"frames": [], "windows": []}))
    (root / rid / "reel_candidates.json").write_text(json.dumps(
        [{"rank": 1, "start_s": 0, "end_s": 2, "score": 0.8,
          "why": "精彩瞬间", "best_frame_id": "frame_000001"}]))


def _build_scan_run(root: Path, rid="scanrun"):
    """A run as `pixcull run` writes it: scores.csv under output/.

    The fixture below calls itself a photo run and writes scores.csv in
    the run root, which is the layout `pixcull video` produces.  Both
    layouts exist on disk and `_reload_run_from_disk` has accepted both
    since v2.35.2; the timeline read only ever handled the video one,
    and the only fixture standing over it had the video shape too, so
    the ordinary case returned nothing and nothing said so (v3.87).
    """
    out = root / rid / "output"
    out.mkdir(parents=True)
    with open(out / "scores.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["path", "filename", "datetime",
                                           "decision", "score_final"])
        w.writeheader()
        for i, minute in enumerate(("10:00", "10:00", "11:30"), start=1):
            w.writerow({"path": f"/shoots/day1/IMG_{i}.jpg",
                        "filename": f"IMG_{i}.jpg",
                        "datetime": f"2026:05:29 {minute}:0{i}",
                        "decision": "keep", "score_final": "0.80"})


def _build_video_run_scores(root: Path, rid="vidrun"):
    """The scores.csv `pixcull video` writes: one row per extracted frame."""
    d = root / rid
    fdir = d / "video_frames" / "clipA"
    fdir.mkdir(parents=True, exist_ok=True)
    with open(d / "scores.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["path", "filename", "datetime",
                                           "decision", "score_final"])
        w.writeheader()
        for i in (1, 2, 3):
            w.writerow({"path": str(fdir / f"frame_00000{i}.jpg"),
                        "filename": f"frame_00000{i}.jpg",
                        "datetime": "", "decision": "keep",
                        "score_final": "0.70"})


def _build_photo_run(root: Path, rid="photorun"):
    d = root / rid
    d.mkdir(parents=True)
    with open(d / "scores.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["filename", "datetime",
                                           "decision", "score_final"])
        w.writeheader()
        w.writerow({"filename": "IMG_1.jpg", "datetime": "2026:05:29 10:00:00",
                    "decision": "keep", "score_final": "0.82"})
        w.writerow({"filename": "IMG_2.jpg", "datetime": "2026:05:29 10:01:00",
                    "decision": "cull", "score_final": "0.40"})


# --------------------------------------------------------------------------
# pure helpers
# --------------------------------------------------------------------------

def test_build_joint_timeline_sort(srv_mod):
    photos = [{"kind": "photo", "t": 100.0}, {"kind": "photo", "t": None}]
    videos = [{"kind": "video", "t": 50.0}]
    merged = srv_mod.build_joint_timeline(photos, videos)
    assert [it["kind"] for it in merged] == ["video", "photo", "photo"]
    assert merged[-1]["t"] is None   # missing-time sorts last


def test_parse_capture_dt(srv_mod):
    assert srv_mod._parse_capture_dt("2026:05:29 14:30:00") is not None
    assert srv_mod._parse_capture_dt("2026-05-29T14:30:00") is not None
    assert srv_mod._parse_capture_dt("") is None
    assert srv_mod._parse_capture_dt("nan") is None
    assert srv_mod._parse_capture_dt("garbage") is None


def test_photo_timeline_items(srv_mod, tmp_path, monkeypatch):
    monkeypatch.setattr(srv_mod, "_DEMO_ROOT", tmp_path)
    _build_photo_run(tmp_path, "p1")
    items = srv_mod._photo_timeline_items("p1")
    assert len(items) == 2
    assert all(it["kind"] == "photo" for it in items)
    assert items[0]["t"] is not None
    assert items[0]["decision"] == "keep"


def test_photo_timeline_items_reads_the_scan_layout(srv_mod, tmp_path,
                                                    monkeypatch):
    """`pixcull run`'s own layout must not come back empty (v3.87).

    Before the fix this returned [], so the 照片+视频时间线 link on every
    ordinary results page opened a timeline with no photographs on it —
    the one case the page exists for.
    """
    monkeypatch.setattr(srv_mod, "_DEMO_ROOT", tmp_path)
    _build_scan_run(tmp_path, "s1")
    items = srv_mod._photo_timeline_items("s1")
    assert [it["filename"] for it in items] == ["IMG_1.jpg", "IMG_2.jpg",
                                                "IMG_3.jpg"]
    assert all(it["t"] is not None for it in items)


def test_extracted_video_frames_are_not_photographs(srv_mod, tmp_path,
                                                    monkeypatch):
    """A video run's frames are the video, not N photographs (v3.87).

    The `# Skip the synthetic video frames of a video run.` comment has
    been over this loop since v2.31 with no code under it, so a 34-frame
    clip arrived as 34 undated photographs and the page's tally said 35
    时间点 where there was one.
    """
    monkeypatch.setattr(srv_mod, "_DEMO_ROOT", tmp_path)
    _build_video_run_scores(tmp_path, "v2")
    assert srv_mod._photo_timeline_items("v2") == []


def test_frame_skip_is_structural_not_by_filename(srv_mod, tmp_path,
                                                  monkeypatch):
    """Photographs are kept even when they look like extracted frames.

    Matching `frame_%06d.jpg`, or the substring `video_frames`, would
    delete the work of anyone who names files that way.  The test is
    whether the row's own path lies under THIS run's `video_frames/`.
    """
    monkeypatch.setattr(srv_mod, "_DEMO_ROOT", tmp_path)
    d = tmp_path / "v3" / "output"
    d.mkdir(parents=True)
    with open(d / "scores.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["path", "filename", "datetime",
                                           "decision", "score_final"])
        w.writeheader()
        # someone else's video_frames directory, and a frame-shaped name
        w.writerow({"path": "/shoots/video_frames/frame_000001.jpg",
                    "filename": "frame_000001.jpg",
                    "datetime": "2026:05:29 10:00:00",
                    "decision": "keep", "score_final": "0.80"})
    items = srv_mod._photo_timeline_items("v3")
    assert [it["filename"] for it in items] == ["frame_000001.jpg"]


def test_video_timeline_items(srv_mod, tmp_path, monkeypatch):
    monkeypatch.setattr(srv_mod, "_DEMO_ROOT", tmp_path)
    _build_video_run(tmp_path, "v1")
    items = srv_mod._video_timeline_items()
    assert len(items) == 1
    assert items[0]["kind"] == "video"
    assert items[0]["candidate_count"] == 1
    assert items[0]["best_why"] == "精彩瞬间"


# --------------------------------------------------------------------------
# live endpoints
# --------------------------------------------------------------------------

@pytest.fixture
def live(srv_mod, tmp_path, monkeypatch):
    monkeypatch.setattr(srv_mod, "_DEMO_ROOT", tmp_path)
    _build_photo_run(tmp_path, "photorun")
    _build_video_run(tmp_path, "vidrun")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), srv_mod._Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address
    srv.shutdown()


def _get(addr, path):
    c = http.client.HTTPConnection(addr[0], addr[1], timeout=5)
    c.request("GET", path)
    r = c.getresponse()
    b = r.read()
    c.close()
    return r.status, r.getheader("Content-Type"), b


def test_timeline_data_merges_photo_and_video(live):
    status, ctype, body = _get(live, "/timeline/data/photorun")
    assert status == 200 and "application/json" in ctype
    d = json.loads(body)
    assert d["ok"] is True
    assert d["photo_count"] == 2
    assert d["video_count"] == 1
    kinds = [it["kind"] for it in d["items"]]
    assert "photo" in kinds and "video" in kinds
    # Photos have parseable times ⇒ sorted ahead of the (later-mtime) video
    # or interleaved; at minimum the merged list holds all 3 items.
    assert len(d["items"]) == 3


def test_timeline_data_bad_id(live):
    status, _, body = _get(live, "/timeline/data/..%2fetc")
    assert status in (400, 404)


def test_timeline_page_renders(live):
    status, ctype, body = _get(live, "/timeline/photorun")
    assert status == 200 and "text/html" in ctype
    text = body.decode("utf-8")
    assert "照片 + 视频时间线" in text
    assert 'RUN_ID="photorun"' in text
    assert "/timeline/data/" in text
