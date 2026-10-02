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
is recorded as a reason, and the review page has words for each one.
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

from pixcull.scoring import audio_events as A
from pixcull.scoring.audio_events import AudioEvent
from pixcull.scoring.audio_tagger import HeuristicTagger

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "pixcull" / "report" / "templates" / "video_review.html"
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


# -- the page has words for each ---------------------------------------------

def _js(html: str) -> str:
    """The page's script with comments removed — a reason named only in a
    comment is not a reason the page handles."""
    js = re.sub(r"/\*.*?\*/", "", html, flags=re.S)
    return "\n".join(l.split("//", 1)[0] if "://" not in l else l
                     for l in js.splitlines())


def _page_reasons() -> set[str]:
    js = _js(PAGE.read_text("utf-8"))
    block = js[js.index("const AUD_WHY={"):]
    block = block[:block.index("};")]
    return set(re.findall(r"^\s*'([a-z-]+)'\s*:", block, re.M))


def test_the_review_page_explains_every_reason():
    """Twin path: the reasons are written in Python and worded in the
    page. A sixth reason with no wording renders as an empty lane, which
    is what every reason looked like before."""
    assert _page_reasons() == set(A.NOT_LISTENED)


def test_the_review_page_writes_the_note_from_every_payload():
    js = _js(PAGE.read_text("utf-8"))
    assert re.search(r"^\s*audioNote\(d\.audio\);", js, re.M), (
        "the page must write the note from every /video payload")
    assert 'id="audNote"' in PAGE.read_text("utf-8")


def _note_source() -> str:
    """The three definitions the note needs, lifted out of the page."""
    js = PAGE.read_text("utf-8")
    why = js[js.index("const AUD_WHY={"):]
    why = why[:why.index("};") + 2]
    esc = js[js.index("function esc(x){"):]
    esc = esc[:esc.index("); }") + 4]
    fn = js[js.index("function audioNoteText("):]
    fn = fn[:fn.index("function audioNote(")]
    return "\n".join((esc, why, fn))


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_the_page_tells_the_states_of_an_empty_lane_apart():
    """Run, not read. The first version asserted that ``a.tagger`` appears
    in the function, and a function rewritten to ``if(false) return …``
    still contained it."""
    cases = {
        "no file": None,
        "heard something": {"events": [{"kind": "music"}], "tagger": "onnx"},
        "listened, nothing": {"events": [], "tagger": "onnx"},
        "tagger name is escaped": {"events": [], "tagger": "<b>x</b>"},
        "unknown reason": {"events": [], "tagger": None, "reason": "new"},
        **{r: {"events": [], "tagger": None, "reason": r}
           for r in A.NOT_LISTENED},
    }
    script = (_note_source() + "\nconst C=" + json.dumps(cases) + ";\n"
              "const out={};for(const k in C) out[k]=audioNoteText(C[k]);\n"
              "console.log(JSON.stringify(out));")
    proc = subprocess.run(["node", "-e", script], capture_output=True,
                          text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    got = json.loads(proc.stdout)

    assert got["heard something"] == "", "the lane itself says it"
    assert "audio_events.json" in got["no file"]
    assert "onnx" in got["listened, nothing"]
    assert "&lt;b&gt;" in got["tagger name is escaped"]
    assert "<b>" not in got["tagger name is escaped"]
    assert got["unknown reason"] == ""
    for reason in A.NOT_LISTENED:
        assert got[reason], f"no wording for {reason}"
    said = [got[k] for k in ("no file", "listened, nothing", *A.NOT_LISTENED)]
    assert len(set(said)) == len(said), (
        "two different states of the lane are described with the same "
        f"sentence: {said}")
    assert "pixcull models pull audio-tagger" in got["no-model"]


def test_a_reason_in_a_comment_is_not_a_reason_the_page_handles():
    assert "'no-model'" not in _js("// 'no-model': 'x',\n")
    assert "'no-model'" not in _js("/* 'no-model': 'x', */\n")
    assert "'no-model'" in _js("  'no-model':'x', // why\n")


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

    return SimpleNamespace(invoke=invoke, calls=calls, audio=audio)


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
    source. Parsed, because for five months the only thing that mentioned
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
