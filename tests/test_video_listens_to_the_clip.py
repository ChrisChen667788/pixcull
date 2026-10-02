"""v3.93 — `pixcull video` never listened to the video.

`run_audio_analysis` was written in v2.0-P1-3 and had no caller. Three
readers were built on the file it writes — the reel detector's ``why``,
the review page's event lane, the lightbox scrubber — and no run ever
produced `audio_events.json`. The learned tagger of v2.1 and v2.2, whose
evaluation is the only audio number this project has, was reachable from
its own evaluation script and nowhere else.

Wiring it turned up the second half. ``get_tagger`` falls back to the DSP
detectors when no model is installed, and the model is optional, so the
obvious wiring would have put the DSP detectors in front of most users.
``docs/AUDIO-TAGGER-EVAL.md`` is this project's own measurement of them on
64 real clips: none of 20 applause clips found, laughter right 12% of the
time. The readers print what they are handed — "现场笑声" in a caption —
so the fallback is not a weaker version of the feature, it is a wrong
one. Events come from the learned tagger or the file says nothing
listened, and why.

Held here: the command calls the pass and survives its failure; events
are the learned tagger's and never the DSP's; every way of not listening
is recorded as a reason; and both pages that draw the audio lane are sent
one sentence saying why it is empty.

The review of this version found the rest. A file that has three readers
and now a writer is also a file an earlier run can leave behind:
``--no-audio`` and a failed pass both left the last run's events for this
run's reel to caption. The pass located its clip by looking for the one
directory under ``video_frames/``, and failed as soon as there were two.
And the explanation for an empty lane had been written into one of the
two pages that draw it.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from typer.testing import CliRunner

from pixcull.report import serve_app as SA
from pixcull.scoring import audio_events as A
from pixcull.scoring.audio_events import AudioEvent
from pixcull.scoring.audio_tagger import HeuristicTagger

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "pixcull" / "report" / "templates"
PAGE = TEMPLATES / "video_review.html"
SCRUBBER = TEMPLATES / "src" / "modules" / "05-video-scrub.js"
SR = A.DEFAULT_SR


def _tone(seconds: float = 6.0) -> np.ndarray:
    """A steady chord — what the DSP path calls music, with confidence."""
    t = np.arange(int(SR * seconds)) / SR
    return 0.4 * sum(np.sin(2 * np.pi * f * t) for f in (220.0, 277.2, 329.6))


class _Learned:
    """A stand-in for the ONNX tagger: its name, and a scripted answer."""
    name = "onnx"

    def __init__(self, events=None, boom: Exception | None = None):
        self.events, self.boom, self.calls = events or [], boom, 0

    def available(self) -> bool:
        return True

    def tag(self, samples, sr):
        self.calls += 1
        if self.boom:
            raise self.boom
        return list(self.events)


def _run_dir(tmp_path: Path, *, source: Path | None, tracks: int = 1) -> Path:
    """A run directory as `pixcull video` leaves it after extraction."""
    out = tmp_path / "run"
    frames = out / "video_frames" / "clip_abc"
    frames.mkdir(parents=True)
    (frames / "manifest.json").write_text(json.dumps({
        "video_id": "clip_abc", "source_name": "clip.mp4",
        "source_path": str(source) if source else None,
        "audio_track_count": tracks, "frames": [], "schema_version": 1,
    }), "utf-8")
    return out


@pytest.fixture
def clip(tmp_path, monkeypatch):
    """A source file that 'decodes' to the tone, without ffmpeg."""
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"not a real container")
    decoded = []
    monkeypatch.setattr(A, "extract_audio",
                        lambda path, **k: (decoded.append(path) or _tone(), SR))
    return SimpleNamespace(src=src, decoded=decoded, tmp=tmp_path)


def _written(out: Path) -> dict:
    return json.loads((out / "audio_events.json").read_text("utf-8"))


# -- whose events ------------------------------------------------------------

def test_the_learned_taggers_events_are_what_is_written(clip):
    heard = [AudioEvent("applause", 3.0, 4.5, 0.9),
             AudioEvent("laughter", 1.0, 2.0, 0.8)]
    out = _run_dir(clip.tmp, source=clip.src)
    res = A.run_audio_analysis(out, tagger=_Learned(heard))
    d = _written(out)
    assert [e["kind"] for e in d["events"]] == ["laughter", "applause"], (
        "events are the tagger's, in time order")
    assert d["tagger"] == "onnx" and d["reason"] is None and d["note"] is None
    assert d["has_audio"] is True
    assert d["summary"] == {"laughter": 1, "applause": 1, "music": 0}
    assert res.tagger == "onnx"


def test_without_a_model_the_dsp_detectors_are_not_published(clip):
    """The assertion the design turns on. The tone is something the DSP
    path detects — checked first, or this would pass for the wrong
    reason — and none of that may reach the file."""
    dsp = A.analyze_audio(_tone(), SR)
    assert [e.kind for e in dsp.events] == ["music"], (
        "the fixture no longer makes the DSP detectors fire, so the "
        "assertion below would hold whatever the code did")

    out = _run_dir(clip.tmp, source=clip.src)
    A.run_audio_analysis(out, tagger=HeuristicTagger())
    d = _written(out)
    assert d["events"] == [] and d["summary"] == {
        "laughter": 0, "applause": 0, "music": 0}
    assert d["tagger"] is None and d["reason"] == "no-model"
    assert "pixcull models pull audio-tagger" in d["note"]
    assert d["has_audio"] is True, "there was sound; nothing listened to it"


def test_no_tagger_given_asks_for_the_installed_one(clip, monkeypatch):
    """The default path: what `pixcull video` actually runs."""
    from pixcull.scoring import audio_tagger as T
    out = _run_dir(clip.tmp, source=clip.src)

    monkeypatch.setattr(T, "get_tagger", lambda **k: HeuristicTagger())
    assert A.run_audio_analysis(out).reason == "no-model"

    learned = _Learned([AudioEvent("music", 0.0, 5.0, 0.7)])
    monkeypatch.setattr(T, "get_tagger", lambda **k: learned)
    res = A.run_audio_analysis(out)
    assert res.tagger == "onnx" and learned.calls == 1
    assert [e.kind for e in res.events] == ["music"]


def test_the_beat_grid_survives_either_way(clip):
    """Tempo and beats are the DSP's own measurement and no model here
    replaces them — dropping the DSP events must not drop these."""
    out = _run_dir(clip.tmp, source=clip.src)
    for tagger in (HeuristicTagger(), _Learned()):
        res = A.run_audio_analysis(out, tagger=tagger)
        dsp = A.analyze_audio(_tone(), SR)
        assert res.tempo_bpm == dsp.tempo_bpm and res.beats_s == dsp.beats_s


def test_a_model_that_listened_and_heard_nothing_is_not_a_reason(clip):
    """ "Heard nothing" and "did not listen" are different statements and
    used to be the same empty list."""
    out = _run_dir(clip.tmp, source=clip.src)
    A.run_audio_analysis(out, tagger=_Learned([]))
    d = _written(out)
    assert d["events"] == [] and d["tagger"] == "onnx"
    assert d["reason"] is None and d["note"] is None


# -- every way of not listening ----------------------------------------------

def test_a_model_that_fails_is_recorded_and_does_not_raise(clip):
    out = _run_dir(clip.tmp, source=clip.src)
    res = A.run_audio_analysis(
        out, tagger=_Learned(boom=RuntimeError("bad input shape\nmore")))
    d = _written(out)
    assert res.reason == d["reason"] == "model-failed"
    assert d["events"] == [] and d["tagger"] is None
    assert "RuntimeError: bad input shape" in d["note"]
    assert "more" not in d["note"], "one line of the error, not the traceback"


def test_an_exception_with_no_message_is_still_recorded(clip):
    out = _run_dir(clip.tmp, source=clip.src)
    res = A.run_audio_analysis(out, tagger=_Learned(boom=ValueError()))
    assert res.reason == "model-failed" and "ValueError" in res.note


def test_a_clip_with_no_audio_track_is_not_decoded(clip):
    out = _run_dir(clip.tmp, source=clip.src, tracks=0)
    learned = _Learned([AudioEvent("music", 0.0, 1.0, 0.9)])
    res = A.run_audio_analysis(out, tagger=learned)
    d = _written(out)
    assert d["reason"] == "no-track" and d["has_audio"] is False
    assert d["events"] == [] and d["tagger"] is None
    assert clip.decoded == [] and learned.calls == 0
    assert res.has_audio is False


def test_a_source_that_moved_says_so(clip):
    out = _run_dir(clip.tmp, source=clip.tmp / "gone.mp4")
    d = (A.run_audio_analysis(out, tagger=_Learned()), _written(out))[1]
    assert d["reason"] == "no-source" and d["has_audio"] is False
    assert clip.decoded == []


def test_a_manifest_with_no_source_path_says_so(clip):
    out = _run_dir(clip.tmp, source=None)
    assert A.run_audio_analysis(out, tagger=_Learned()).reason == "no-source"


def test_audio_that_cannot_be_decoded_says_so(clip, monkeypatch):
    monkeypatch.setattr(A, "extract_audio",
                        lambda path, **k: (np.zeros(0), SR))
    out = _run_dir(clip.tmp, source=clip.src)
    learned = _Learned([AudioEvent("music", 0.0, 1.0, 0.9)])
    d = (A.run_audio_analysis(out, tagger=learned), _written(out))[1]
    assert d["reason"] == "undecodable" and learned.calls == 0


def test_a_manifest_older_than_the_track_count_is_still_decoded(clip):
    """``audio_track_count`` missing is not zero: decode and find out."""
    out = _run_dir(clip.tmp, source=clip.src)
    m = out / "video_frames" / "clip_abc" / "manifest.json"
    d = json.loads(m.read_text("utf-8"))
    del d["audio_track_count"]
    m.write_text(json.dumps(d), "utf-8")
    res = A.run_audio_analysis(out, tagger=_Learned())
    assert res.has_audio is True and clip.decoded == [clip.src]


def test_every_reason_carries_a_sentence():
    produced = {"no-model", "model-failed", "no-source", "no-track",
                "undecodable"}
    assert set(A.NOT_LISTENED) == produced
    assert all(len(s) > 20 for s in A.NOT_LISTENED.values())


# -- an empty lane says why, on both pages -----------------------------------

def _audio(**kw) -> dict:
    return {"has_audio": True, "events": [], "tagger": None, "reason": None,
            **kw}


def test_every_reason_has_wording_and_none_is_left_over():
    """Twin path: the reasons are produced in ``audio_events`` and worded
    in the server. A sixth reason with no wording is an empty lane with
    no explanation — which is what every reason looked like before."""
    assert set(SA._AUDIO_NOTE_ZH) == set(A.NOT_LISTENED)


def test_the_states_of_an_empty_lane_are_told_apart():
    said = {
        "no file": SA._audio_note(None),
        "listened, nothing": SA._audio_note(_audio(tagger="onnx")),
        **{r: SA._audio_note(_audio(reason=r)) for r in A.NOT_LISTENED},
    }
    assert all(said.values()), f"a state with nothing to say: {said}"
    assert len(set(said.values())) == len(said), (
        f"two different states are described by the same sentence: {said}")
    assert "audio_events.json" in said["no file"]
    assert "onnx" in said["listened, nothing"]
    assert "pixcull models pull audio-tagger" in said["no-model"]


def test_a_lane_with_events_on_it_needs_no_sentence():
    heard = _audio(tagger="onnx", events=[{"kind": "music"}])
    assert SA._audio_note(heard) == ""


def test_a_reason_nobody_has_worded_says_nothing_rather_than_something_wrong():
    assert SA._audio_note(_audio(reason="a-new-one")) == ""


def test_a_file_that_is_not_an_object_is_not_read_as_one(tmp_path):
    (tmp_path / "audio_events.json").write_text("[1, 2]", "utf-8")
    assert SA._read_audio_events(tmp_path) is None
    (tmp_path / "audio_events.json").write_text("{not json", "utf-8")
    assert SA._read_audio_events(tmp_path) is None
    assert SA._read_audio_events(tmp_path / "nowhere") is None


def _video_run(root: Path, audio: dict | None, rid: str = "vidrun") -> str:
    """A scored video run on disk, as the review server finds one."""
    run = root / rid
    frames = run / "video_frames" / "clip_abc"
    frames.mkdir(parents=True)
    listed = []
    for i in range(3):
        fn = f"frame_{i + 1:06d}.jpg"
        (frames / fn).write_bytes(b"jpeg")
        listed.append({"frame_id": fn[:-4], "timestamp_s": float(i),
                       "filename": fn})
    (frames / "manifest.json").write_text(json.dumps({
        "video_id": "clip_abc", "source_name": "clip.mp4", "fps": 25.0,
        "duration_s": 3.0, "codec": "h264", "audio_track_count": 1,
        "frames": listed}), "utf-8")
    (run / "temporal.json").write_text(json.dumps({
        "frames": [{"frame_id": f["frame_id"], "timestamp_s": f["timestamp_s"],
                    "score_temporal": 0.5, "score_final": 0.5}
                   for f in listed], "windows": []}), "utf-8")
    if audio is not None:
        (run / "audio_events.json").write_text(json.dumps(audio), "utf-8")
    return rid


CASES = [
    ("no file", None),
    ("no model", _audio(reason="no-model")),
    ("heard nothing", _audio(tagger="onnx")),
    ("heard music", _audio(tagger="onnx", events=[
        {"kind": "music", "start_s": 0.0, "end_s": 2.0, "confidence": 0.8}])),
]


@pytest.mark.parametrize("name,audio", CASES, ids=[c[0] for c in CASES])
def test_the_lightbox_and_the_review_page_are_told_the_same_thing(
        name, audio, tmp_path, monkeypatch):
    """The two pages read the file through two payloads. The first version
    of this explained an empty lane on the review page only; the lightbox
    payload flattened the file to its events and dropped the reason."""
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    monkeypatch.setattr(SA, "_DEMO_ROOT", tmp_path)
    rid = _video_run(tmp_path, audio)
    expected = SA._audio_note(audio)

    lightbox = SA._build_video_payload(rid)
    assert lightbox is not None, "the fixture is not a video run to the server"
    assert lightbox["audio_note"] == expected

    srv = ThreadingHTTPServer(("127.0.0.1", 0), SA._Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        url = f"http://127.0.0.1:{srv.server_address[1]}/video/data/{rid}"
        with opener.open(url, timeout=60) as r:
            review = json.loads(r.read().decode("utf-8"))
    finally:
        srv.shutdown()
    assert review["audio_note"] == expected
    # The events themselves reach both, as they did before.
    n = len((audio or {}).get("events") or [])
    assert len(lightbox["audio"]) == n
    assert len(((review.get("audio") or {}).get("events")) or []) == n


def _code(js: str) -> str:
    """Script with comments removed — a call named only in a comment is
    not a call the page makes."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return "\n".join(l.split("//", 1)[0] if "://" not in l else l
                     for l in js.splitlines())


def test_both_pages_show_the_sentence_they_are_sent():
    page = _code(PAGE.read_text("utf-8"))
    assert re.search(r"^\s*audioNote\(d\.audio_note\);", page, re.M), (
        "the review page must show audio_note from every /video/data payload")
    assert 'id="audNote"' in PAGE.read_text("utf-8")
    fn = page[page.index("function audioNote("):]
    fn = fn[:fn.index("function seekEvt(")]
    assert "textContent" in fn and "innerHTML" not in fn, (
        "the sentence carries a tagger name read from a file; it is text")

    scrub = _code(SCRUBBER.read_text("utf-8"))
    assert re.search(r"if \(V\.audio_note\)\s*\{[^}]*textContent[^}]*"
                     r"hidden = false", scrub), (
        "the lightbox scrubber must show audio_note too")
    built = (TEMPLATES / "results.html").read_text("utf-8")
    assert "V.audio_note" in built, (
        "results.html is a built artifact; run scripts/build_results_html.py")


def test_a_call_in_a_comment_is_not_a_call():
    assert "audioNote(d.audio_note)" not in _code("// audioNote(d.audio_note);\n")
    assert "audioNote(d.audio_note)" not in _code("/* audioNote(d.audio_note); */")
    assert "audioNote(d.audio_note)" in _code("  audioNote(d.audio_note); // x\n")


# -- the command -------------------------------------------------------------

@pytest.fixture
def staged(monkeypatch, tmp_path):
    """`pixcull video` with every stage replaced by a recorder, so what is
    under test is the order of the stages and what a flag removes."""
    calls: list[str] = []
    meta = SimpleNamespace(
        source_name="clip.mp4", video_id="clip_abc", codec="h264", width=320,
        height=240, fps=25.0, duration_s=4.0, audio_track_count=1)
    result = SimpleNamespace(meta=meta, frame_count=4, mode="interval",
                             interval_s=1.0, frames_dir=tmp_path / "frames")

    import pixcull.io.video as V
    import pixcull.pipeline.orchestrator as O
    import pixcull.scoring.reel as R
    import pixcull.scoring.temporal as T

    monkeypatch.setattr(V, "import_video",
                        lambda *a, **k: calls.append("extract") or result)
    monkeypatch.setattr(O, "run_pipeline",
                        lambda *a, **k: calls.append("score"))
    monkeypatch.setattr(T, "run_temporal_analysis",
                        lambda *a, **k: calls.append("temporal")
                        or SimpleNamespace(windows=[]))
    monkeypatch.setattr(R, "run_reel_detection",
                        lambda *a, **k: calls.append("reel") or [])
    audio = SimpleNamespace(
        result=A.AudioResult([AudioEvent("laughter", 1.0, 2.0, 0.8)], [],
                             0.0, has_audio=True, tagger="onnx"),
        boom=None)

    def _audio(out, **k):
        calls.append("audio")
        if audio.boom:
            raise audio.boom
        return audio.result

    monkeypatch.setattr(A, "run_audio_analysis", _audio)
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"x")

    def invoke(*flags):
        from pixcull.cli import app
        calls.clear()
        return CliRunner().invoke(
            app, ["video", str(src), "-o", str(tmp_path / "out"), *flags])

    return SimpleNamespace(invoke=invoke, calls=calls, audio=audio,
                           out=tmp_path / "out", frames_dir=result.frames_dir)


def test_the_command_listens_between_scoring_and_the_reel(staged):
    """The reel detector reads audio_events.json, so it has to exist by
    the time the detector runs."""
    r = staged.invoke()
    assert r.exit_code == 0, r.output
    assert staged.calls == ["extract", "score", "audio", "temporal", "reel"]
    assert "1 laughter" in r.output and "tagger: onnx" in r.output


def test_no_audio_removes_that_stage_and_nothing_else(staged):
    r = staged.invoke("--no-audio")
    assert r.exit_code == 0, r.output
    assert staged.calls == ["extract", "score", "temporal", "reel"]


def test_the_audio_does_not_depend_on_the_temporal_pass(staged):
    r = staged.invoke("--no-temporal")
    assert r.exit_code == 0, r.output
    assert staged.calls == ["extract", "score", "audio"]


def test_extract_only_does_not_listen(staged):
    assert staged.invoke("--extract-only").exit_code == 0
    assert staged.calls == ["extract"]


def test_a_failing_audio_pass_does_not_cost_the_reel(staged):
    staged.audio.boom = OSError("disk full")
    r = staged.invoke()
    assert r.exit_code == 0, r.output
    assert staged.calls == ["extract", "score", "audio", "temporal", "reel"]
    assert "Audio analysis failed" in r.output and "disk full" in r.output


def test_the_pass_is_told_which_clip_it_is_listening_to(staged, monkeypatch):
    """The command knows the directory it just extracted; the pass must
    not go looking for it."""
    seen = {}
    monkeypatch.setattr(
        A, "run_audio_analysis",
        lambda out, **k: seen.update(k) or staged.audio.result)
    assert staged.invoke().exit_code == 0
    assert seen.get("frames_dir") == staged.frames_dir


def test_no_audio_does_not_leave_the_last_runs_events_for_the_reel(staged):
    stale = staged.out / "audio_events.json"
    staged.out.mkdir(parents=True, exist_ok=True)
    stale.write_text('{"events": [{"kind": "laughter"}]}', "utf-8")
    r = staged.invoke("--no-audio")
    assert r.exit_code == 0, r.output
    assert not stale.exists(), (
        "the reel detector reads audio_events.json if it is there; this "
        "run did not listen, and would have captioned with the last run's")
    assert "earlier run" in " ".join(r.output.split())


def test_no_audio_with_nothing_to_remove_says_nothing_about_removing(staged):
    r = staged.invoke("--no-audio")
    assert r.exit_code == 0 and "earlier run" not in r.output


def test_a_failed_pass_does_not_leave_the_last_runs_events_either(staged):
    stale = staged.out / "audio_events.json"
    staged.out.mkdir(parents=True, exist_ok=True)
    stale.write_text('{"events": [{"kind": "laughter"}]}', "utf-8")
    staged.audio.boom = OSError("disk full")
    assert staged.invoke().exit_code == 0
    assert not stale.exists()
    assert staged.calls[-1] == "reel", "the reel still runs, on no audio"


def test_a_pass_that_ran_keeps_what_it_wrote(staged, monkeypatch):
    """The other side of the two above: only a run that did not listen
    removes the file."""
    def _writes(out, **k):
        (Path(out) / "audio_events.json").write_text("{}", "utf-8")
        return staged.audio.result
    monkeypatch.setattr(A, "run_audio_analysis", _writes)
    staged.out.mkdir(parents=True, exist_ok=True)
    assert staged.invoke().exit_code == 0
    assert (staged.out / "audio_events.json").exists()


def test_a_second_clip_in_the_same_output_is_still_listened_to(clip):
    """`_resolve_frames_dir` finds the clip by there being exactly one.
    Told which, the pass does not need there to be."""
    out = _run_dir(clip.tmp, source=clip.src)
    other = out / "video_frames" / "clip_older"
    other.mkdir()
    (other / "manifest.json").write_text("{}", "utf-8")
    with pytest.raises(FileNotFoundError):
        A.run_audio_analysis(out, tagger=_Learned())
    res = A.run_audio_analysis(out, tagger=_Learned(),
                               frames_dir=out / "video_frames" / "clip_abc")
    assert res.has_audio and res.tagger == "onnx"


def test_the_command_says_why_nothing_listened(staged):
    staged.audio.result = A.AudioResult(
        [], [], 0.0, has_audio=True, tagger=None, reason="no-model",
        note=A.NOT_LISTENED["no-model"])
    r = staged.invoke()
    flat = " ".join(r.output.split())
    assert "no events" in flat and "pixcull models pull audio-tagger" in flat
    assert "✓ Audio" not in r.output, (
        "a pass that did not listen must not print the success line")


def test_listened_and_heard_nothing_is_reported_as_that(staged):
    staged.audio.result = A.AudioResult([], [], 0.0, has_audio=True,
                                        tagger="onnx")
    r = staged.invoke()
    assert "none heard" in r.output and "tagger: onnx" in r.output


def _calls_in(func: str) -> list[str]:
    tree = ast.parse((ROOT / "pixcull" / "cli.py").read_text("utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == func)
    return [getattr(c.func, "attr", getattr(c.func, "id", ""))
            for c in ast.walk(fn) if isinstance(c, ast.Call)]


def test_the_real_command_reaches_the_real_function():
    """The recorder above replaces the function; this is the unreplaced
    source. Parsed, because for four months the only thing that mentioned
    this function in the package was its own docstring."""
    assert "_video_audio_stage" in _calls_in("video")
    assert "run_audio_analysis" in _calls_in("_video_audio_stage")


# -- with a real decoder -----------------------------------------------------

@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_a_real_clip_is_decoded_and_handed_to_the_tagger(tmp_path):
    """Everything above replaces ffmpeg. This does not: a real container
    with a real audio stream, and a real one without."""
    def _clip(name: str, with_audio: bool) -> Path:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "lavfi", "-i", "testsrc=duration=2:size=160x120:rate=15"]
        if with_audio:
            cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-c:a", "aac", "-shortest"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(tmp_path / name)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        return tmp_path / name

    heard = []

    class _Listening(_Learned):
        def tag(self, samples, sr):
            heard.append((len(samples), sr))
            return [AudioEvent("music", 0.0, 1.5, 0.7)]

    out = _run_dir(tmp_path / "a", source=_clip("sound.mp4", True))
    res = A.run_audio_analysis(out, tagger=_Listening())
    assert res.has_audio and [e.kind for e in res.events] == ["music"]
    assert heard and heard[0][1] == SR and heard[0][0] > SR, (
        f"the tagger was handed {heard}: about two seconds were expected")

    # No audio stream, and a manifest that does not say so: ffmpeg is the
    # one that finds out.
    out = _run_dir(tmp_path / "b", source=_clip("mute.mp4", False))
    m = out / "video_frames" / "clip_abc" / "manifest.json"
    d = json.loads(m.read_text("utf-8"))
    del d["audio_track_count"]
    m.write_text(json.dumps(d), "utf-8")
    assert A.run_audio_analysis(out, tagger=_Listening()).reason \
        == "undecodable"
