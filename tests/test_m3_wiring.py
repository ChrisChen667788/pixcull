"""v2.52.1 — the five places the M3 modules were built but never connected.

I shipped v2.51 and v2.52 claiming they were complete. The modules were
written and tested; five of them were not wired into anything, so nothing
in the product could reach them. That is precisely the "advertised but
unreachable" defect this repo has a name for, committed by the person who
kept writing tests for it in other people's code.

The lesson is in what these tests assert. A test that imports
``m3_video.rerank`` and checks the maths passes just as happily when
``reel.py`` never calls it. So every test here asserts the CONNECTION —
that the caller reaches the callee — not that the callee works.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 1. ReelCandidate carries the content fields
# ---------------------------------------------------------------------------

def test_candidate_has_somewhere_to_put_a_content_score():
    import dataclasses

    from pixcull.scoring.reel import ReelCandidate
    names = {f.name for f in dataclasses.fields(ReelCandidate)}
    for f in ("m3_keep_score", "m3_happening", "m3_moment_type",
              "m3_has_speech", "m3_reason", "m3_error",
              "window_score_norm_proxy"):
        assert f in names, f"{f} has nowhere to live on the dataclass"


def test_content_fields_serialise():
    """reel_candidates.json is read by the review page and the lightbox."""
    from pixcull.scoring.reel import ReelCandidate
    c = ReelCandidate(rank=1, start_s=0, end_s=2, duration_s=2,
                      window_len_s=2, score=0.5, window_score=1.0,
                      confidence=0.5, novelty=0.5, why="", best_frame_id=None,
                      best_frame_score=0.0)
    d = c.to_dict()
    assert "m3_keep_score" in d and "m3_happening" in d


def test_unjudged_is_distinguishable_from_judged_and_dull():
    """None, not 0.0. A clip nobody watched and a clip judged worthless
    are different facts, and only one of them is worth re-running."""
    from pixcull.scoring.reel import ReelCandidate
    c = ReelCandidate(rank=1, start_s=0, end_s=2, duration_s=2,
                      window_len_s=2, score=0.5, window_score=1.0,
                      confidence=0.5, novelty=0.5, why="", best_frame_id=None,
                      best_frame_score=0.0)
    assert c.m3_keep_score is None


# ---------------------------------------------------------------------------
# 2. reel.py actually calls the content pass
# ---------------------------------------------------------------------------

def test_run_reel_detection_calls_the_content_pass():
    from pixcull.scoring import reel
    src = inspect.getsource(reel.run_reel_detection)
    assert "_m3_rerank(" in src, (
        "the M3 video module is built and tested but nothing in the "
        "pipeline reaches it — reel ranking is still 100% proxy")


def test_the_content_pass_runs_before_captioning():
    """Order matters twice.

    enrich() can use M3's observation instead of guessing from one frozen
    frame, and the re-ranked list is what gets written — otherwise the
    JSON is captioned in one order and scored in another.
    """
    from pixcull.scoring import reel
    lines = [ln.strip() for ln in
             inspect.getsource(reel.run_reel_detection).splitlines()]
    i_m3 = next(i for i, ln in enumerate(lines)
                if ln.startswith("m3_verdicts = _m3_rerank"))
    i_cap = next(i for i, ln in enumerate(lines)
                 if ln.startswith("enrich(dicts"))
    assert i_m3 < i_cap


def test_the_content_pass_is_silent_when_it_cannot_run(monkeypatch):
    """No key, no consent, no video path — v2.51 behaviour, no exception."""
    from pixcull.scoring import reel
    monkeypatch.setattr("pixcull.scoring.m3.api_key_from_env", lambda: "")
    dicts = [{"start_s": 0.0, "end_s": 2.0, "window_score_norm": 0.5}]
    assert reel._m3_rerank(dicts, None) is False
    assert reel._m3_rerank(dicts, "/nowhere/v.mp4") is False
    assert dicts[0]["window_score_norm"] == 0.5


def test_a_broken_content_pass_does_not_break_reel_detection(monkeypatch):
    from pixcull.scoring import reel
    monkeypatch.setattr("pixcull.scoring.m3.api_key_from_env",
                        lambda: "sk-" + "0" * 32)
    monkeypatch.setattr("pixcull.scoring.m3.has_consent", lambda: True)

    def _boom(*a, **kw):
        raise RuntimeError("ffmpeg vanished")

    monkeypatch.setattr("pixcull.scoring.m3_video.score_clips", _boom)
    dicts = [{"start_s": 0.0, "end_s": 2.0, "window_score_norm": 0.5}]
    assert reel._m3_rerank(dicts, "/nowhere/v.mp4") is False


def test_the_returned_objects_agree_with_the_written_json():
    """Two sources of truth that drift silently is the worse bug.

    run_reel_detection writes dicts and returns dataclasses. If only the
    dicts get re-ranked, the JSON and the return value disagree about
    which clip is best.
    """
    from pixcull.scoring import reel
    src = inspect.getsource(reel.run_reel_detection)
    assert "setattr(c, f, d[f])" in src
    assert "candidates.sort(" in src


# ---------------------------------------------------------------------------
# 3. enrich() prefers what M3 saw
# ---------------------------------------------------------------------------

def test_enrich_uses_the_content_observation_when_there_is_one():
    from pixcull.scoring import reel_caption
    c = [{"start_s": 0, "end_s": 2, "m3_happening": "新人交换戒指"}]
    reel_caption.enrich(c)
    assert c[0]["why_semantic"] == "新人交换戒指"
    assert c[0]["caption_source"] == "minimax-m3-video"


def test_enrich_falls_back_when_m3_said_nothing():
    """A skipped or errored clip must caption exactly as it did in v2.51."""
    from pixcull.scoring import reel_caption
    c = [{"start_s": 3, "end_s": 5, "scene": "wedding", "m3_error": "skipped"}]
    reel_caption.enrich(c)
    assert c[0]["why_semantic"]
    assert c[0]["caption_source"] != "minimax-m3-video"


def test_an_empty_observation_is_not_treated_as_one():
    from pixcull.scoring import reel_caption
    c = [{"start_s": 0, "end_s": 2, "scene": "wedding", "m3_happening": "  "}]
    reel_caption.enrich(c)
    assert c[0]["caption_source"] != "minimax-m3-video"


# ---------------------------------------------------------------------------
# 4. reset() clears every backend, not three of four
# ---------------------------------------------------------------------------

def test_reset_clears_the_m3_handle():
    """A reset that clears 3 of 4 leaves a handle alive across test cases,
    and the symptom is a test that passes or fails depending on what ran
    before it — blamed on the test, not on reset()."""
    from pixcull.scoring import reel_caption
    reel_caption._m3 = object()
    reel_caption._m3_probed = True
    reel_caption.reset()
    assert reel_caption._m3 is None and reel_caption._m3_probed is False


def test_reset_covers_every_declared_backend_handle():
    """The generalised version — catches the fifth backend too."""
    import re

    from pixcull.scoring import reel_caption
    src = Path(reel_caption.__file__).read_text("utf-8")
    declared = set(re.findall(r"^(_(?:llm|vlm|vlm_onnx|m3))_probed\s*=",
                              src, re.M))
    cleared = inspect.getsource(reel_caption.reset)
    missing = [h for h in declared if f"{h}_probed" not in cleared]
    assert not missing, f"reset() does not clear: {missing}"


# ---------------------------------------------------------------------------
# 5. XMP carries what the cloud judge said, and that it judged at all
# ---------------------------------------------------------------------------

def _fields(row, advice=None):
    from pixcull.io.xmp import build_iptc_fields_from_row
    return build_iptc_fields_from_row(row, advice=advice or {
        "verdict_short": "保留 ✓", "strengths": ["睫毛清晰"],
        "weaknesses": [], "suggestions": []})


def test_the_judges_reason_reaches_lightroom():
    """It lived only in scores.csv and the JSONL — invisible to the person
    the whole XMP round-trip exists for."""
    f = _fields({"decision": "keep", "scene": "portrait",
                 "vlm_overall_label": "keep",
                 "vlm_overall_rationale": "新娘回头那一下抓住了"})
    assert "新娘回头那一下抓住了" in f["description"]


def test_cloud_judged_frames_are_keyword_marked():
    """"Which of my photos left this machine" is a question a photographer
    may have to answer to a client. A keyword is how Lightroom asks it."""
    f = _fields({"decision": "keep", "scene": "portrait",
                 "vlm_overall_label": "keep",
                 "vlm_model_name": "minimax:minimax-m3"})
    assert "PixCull:judged-by:minimax" in f["keywords"]


def test_frames_the_api_never_saw_are_not_marked():
    """A run can be configured for M3 and still have frames it never
    reached — skipped, errored, over budget. Keywording those would claim
    an upload that did not happen."""
    f = _fields({"decision": "cull", "scene": "portrait",
                 "vlm_model_name": "minimax:minimax-m3"})
    assert not [k for k in f["keywords"] if "judged-by" in k]


def test_a_local_judge_is_not_labelled_cloud():
    f = _fields({"decision": "keep", "scene": "portrait",
                 "vlm_overall_label": "keep",
                 "vlm_model_name": "mlx-community/Qwen3-VL-4B"})
    marks = [k for k in f["keywords"] if "judged-by" in k]
    assert marks == ["PixCull:judged-by:cloud"] or not marks, marks
    assert "minimax" not in " ".join(marks)


def test_an_unjudged_row_produces_no_stray_marker():
    f = _fields({"decision": "keep", "scene": "portrait"})
    assert not [k for k in f["keywords"] if "judged-by" in k]
    assert "◇" not in f["description"]
