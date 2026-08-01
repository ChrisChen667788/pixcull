"""v2.44-P2 — the /video/edit routes the review page drives.

The page posts its whole operation log and draws what comes back, so the
server is the only place the span arithmetic happens.  These tests pin
that contract: what the page needs to render, what it may send, and what
happens when it sends nonsense.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixcull.report import serve_app as SA
from pixcull.scoring.transcribe import Segment, Transcript, write_transcript


@pytest.fixture
def run(tmp_path, monkeypatch) -> str:
    """A run dir with a word-level transcript, served from a temp root."""
    monkeypatch.setattr(SA, "_DEMO_ROOT", tmp_path)
    rid = "editrun"
    d = tmp_path / rid
    d.mkdir()
    s1 = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]
    s2 = [(2.0, 2.2), (2.2, 2.4), (2.4, 2.6), (2.6, 2.8), (2.8, 3.0)]
    write_transcript(
        Transcript(segments=[Segment(0.0, 1.0, "今天拍婚礼", char_spans=s1),
                             Segment(2.0, 3.0, "灯光准备好", char_spans=s2)],
                   engine="paraformer", language="zh"), d)
    return rid


class FakeHandler:
    """Just enough of the request handler to exercise the methods.

    Subclassing the real BaseHTTPRequestHandler needs a socket; these
    routes only touch _send_json / send_error / headers / rfile, so
    standing those up directly keeps the test hermetic.
    """

    def __init__(self, body: bytes = b""):
        self.headers = {"Content-Length": str(len(body))}
        self.rfile = __import__("io").BytesIO(body)
        self.status = None
        self.payload = None
        self.error = None

    def _send_json(self, status, data):
        self.status = status
        self.payload = json.loads(data.decode("utf-8"))

    def send_error(self, code, msg=""):
        self.status = code
        self.error = msg

    # methods under test, bound off the real class
    _edit_session_for = SA._Handler._edit_session_for
    _edit_view = SA._Handler._edit_view
    _serve_video_edit = SA._Handler._serve_video_edit
    _handle_video_edit = SA._Handler._handle_video_edit


def test_get_returns_an_empty_edit_and_the_precision(run):
    h = FakeHandler()
    h._serve_video_edit(run)
    assert h.status == 200
    assert h.payload["ok"] is True
    assert h.payload["precision"] == "word"
    assert h.payload["ops"] == []
    assert h.payload["kept_s"] == pytest.approx(2.0)
    assert [s["gone"] for s in h.payload["segments"]] == [False, False]


def test_post_applies_a_segment_delete_and_persists(run, tmp_path):
    ops = [{"kind": "delete", "label": "今天拍婚礼", "spans": [[0.0, 1.0]]}]
    h = FakeHandler(json.dumps({"ops": ops}).encode())
    h._handle_video_edit(run)
    assert h.status == 200
    assert h.payload["kept_s"] == pytest.approx(1.0)
    assert [s["gone"] for s in h.payload["segments"]] == [True, False]
    saved = json.loads((tmp_path / run / "edit.json").read_text("utf-8"))
    assert saved["schema"] == "pixcull.edit/v1"
    assert len(saved["ops"]) == 1


def test_post_maps_character_indices_to_times(run):
    """The page sends indices; only the server has char_spans."""
    h = FakeHandler(json.dumps({"ops": [],
                             "chars": {"i": 0, "first": 2, "last": 4}}).encode())
    h._handle_video_edit(run)
    assert h.status == 200
    # 拍婚礼 = 0.4..1.0 removed, so 0.0..0.4 plus the second line survive.
    assert h.payload["kept_s"] == pytest.approx(1.4)
    assert h.payload["segments"][0]["kept_text"] == "今天"
    # The appended op must come back, or the page cannot undo it.
    assert len(h.payload["ops"]) == 1


def test_get_reloads_what_was_saved(run):
    post = FakeHandler(json.dumps(
        {"ops": [{"kind": "delete", "spans": [[0.0, 1.0]]}]}).encode())
    post._handle_video_edit(run)
    fresh = FakeHandler()
    fresh._serve_video_edit(run)
    assert len(fresh.payload["ops"]) == 1
    assert fresh.payload["kept_s"] == pytest.approx(1.0)


def test_character_cut_on_a_spanless_transcript_is_refused(tmp_path,
                                                           monkeypatch):
    monkeypatch.setattr(SA, "_DEMO_ROOT", tmp_path)
    d = tmp_path / "plain"
    d.mkdir()
    write_transcript(Transcript(segments=[Segment(0.0, 1.0, "no times")],
                                engine="whisper"), d)
    h = FakeHandler(json.dumps({"ops": [],
                             "chars": {"i": 0, "first": 0, "last": 1}}).encode())
    h._handle_video_edit("plain")
    assert h.status == 400
    assert "per-character" in h.payload["error"]


def test_run_without_a_transcript_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(SA, "_DEMO_ROOT", tmp_path)
    (tmp_path / "bare").mkdir()
    h = FakeHandler()
    h._serve_video_edit("bare")
    assert h.status == 404
    assert h.payload["error"] == "no transcript"


def test_bad_run_id_is_rejected(run):
    h = FakeHandler()
    h._serve_video_edit("../../etc")
    assert h.status == 400


def test_oversized_body_is_rejected(run):
    h = FakeHandler()
    h.headers = {"Content-Length": str(300_000)}
    h._handle_video_edit(run)
    assert h.status == 400


def test_malformed_ops_do_not_500(run):
    h = FakeHandler(json.dumps({"ops": [{"kind": "delete"}]}).encode())
    h._handle_video_edit(run)
    assert h.status == 400
    assert h.payload["ok"] is False


# ── render ────────────────────────────────────────────────────────────

def _render_handler_cls():
    class H(FakeHandler):
        _handle_video_render = SA._Handler._handle_video_render
        _serve_video_render_status = SA._Handler._serve_video_render_status
    return H


def test_render_refuses_before_anything_is_edited(run):
    h = _render_handler_cls()()
    h._handle_video_render(run)
    assert h.status == 400
    assert h.payload["error"] == "nothing edited yet"


def test_render_returns_immediately_and_reports_running(run, tmp_path,
                                                        monkeypatch):
    """The POST must not block on ffmpeg.

    A wedding clip is minutes of encoding; holding the request open that
    long has the browser give up and tell the photographer it failed
    while it is still working.
    """
    (tmp_path / run / "edit.json").write_text(
        json.dumps({"schema": "pixcull.edit/v1", "ops": []}), encoding="utf-8")

    started = {"n": 0}
    real = SA.threading.Thread

    class _Blocking(real):
        def start(self):
            started["n"] += 1      # count it, never actually run ffmpeg

    monkeypatch.setattr(SA.threading, "Thread", _Blocking)
    h = _render_handler_cls()()
    h._handle_video_render(run)
    assert h.status == 200
    assert h.payload["state"] == "running"
    assert started["n"] == 1


def test_second_render_while_one_runs_does_not_start_another(run, tmp_path,
                                                             monkeypatch):
    """Two ffmpegs writing the same output file would race."""
    (tmp_path / run / "edit.json").write_text(
        json.dumps({"schema": "pixcull.edit/v1", "ops": []}), encoding="utf-8")
    starts = {"n": 0}

    class _Counting(SA.threading.Thread):
        def start(self):
            starts["n"] += 1

    monkeypatch.setattr(SA.threading, "Thread", _Counting)
    SA._RENDERS.pop(run, None)
    H = _render_handler_cls()
    H()._handle_video_render(run)
    H()._handle_video_render(run)
    assert starts["n"] == 1
    SA._RENDERS.pop(run, None)


def test_status_is_idle_before_any_render(run):
    SA._RENDERS.pop(run, None)
    h = _render_handler_cls()()
    h._serve_video_render_status(run)
    assert h.status == 200
    assert h.payload["state"] == "idle"
