"""v2.52 — content understanding for reel candidates.

Reel ranking has always been ``mean_final + max_temporal``: per-frame
photo scores plus motion statistics. A clip of the vows and a clip of
someone adjusting a mic score identically whenever camera motion and face
count match. That is not a tuning problem — no content signal was ever
collected.

The tests here are mostly about the ways this can degrade, because it
degrades often: no ffmpeg, a 4K ProRes clip that blows the 50 MB limit,
an unprobed wire format, a malformed reply. Every one of those must leave
proxy ranking intact rather than shuffle half the list against the other
half.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixcull.scoring.m3_video import (
    M3_WEIGHT,
    TARGET_CLIP_BYTES,
    ClipTooLarge,
    ClipVerdict,
    PROMPT,
    rerank,
    score_clips,
)


class FakeJudge:
    def __init__(self, replies=None, error=None, boom=False):
        self.replies = list(replies or [])
        self.error = error
        self.boom = boom
        self.calls: list[tuple] = []

    def score_video(self, clip, prompt, *, fps=1.0, **kw):
        self.calls.append((Path(clip), prompt, fps))
        if self.boom:
            raise RuntimeError("connection reset")
        v = type("V", (), {})()
        v.error = self.error
        v.raw_text = (self.replies.pop(0) if self.replies
                      else json.dumps({"happening": "x", "keep_score": 50}))
        return v


def reply(score, happening="新人交换戒指", mtype="vows"):
    return json.dumps({"happening": happening, "keep_score": score,
                       "moment_type": mtype, "has_speech": True,
                       "reason": "不可替代"}, ensure_ascii=False)


def cands(*specs):
    """specs: (start, end, proxy_score)"""
    return [{"start_s": s, "end_s": e, "window_score_norm": p}
            for s, e, p in specs]


@pytest.fixture
def probed(monkeypatch):
    monkeypatch.setattr("pixcull.scoring.m3.load_capabilities",
                        lambda: {"video_part_shape": "video_url_object"})


@pytest.fixture
def cut(monkeypatch, tmp_path):
    """Stand in for ffmpeg; returns a real (tiny) file."""
    made = []

    def _cut(source, start_s, end_s, *, out_dir=None, max_bytes=0):
        p = tmp_path / f"c{len(made)}.mp4"
        p.write_bytes(b"\0" * 1024)
        made.append((float(start_s), float(end_s)))
        return p

    monkeypatch.setattr("pixcull.scoring.m3_video.clip_to_tempfile", _cut)
    return made


# ---------------------------------------------------------------------------
# The prompt has to ask the right question
# ---------------------------------------------------------------------------

def test_the_prompt_separates_content_from_stability():
    """The entire reason this version exists.

    Someone adjusting a mic can be filmed perfectly steadily. If the
    prompt does not say so, M3 will happily reward the same things the
    proxy metrics already reward, and we will have paid for a second
    opinion identical to the first.
    """
    assert "调麦克风" in PROMPT
    assert "发生了什么" in PROMPT
    assert "不是按拍得稳不稳" in PROMPT


def test_the_prompt_defines_the_score_bands():
    for band in ("90+", "60-89", "30-59"):
        assert band in PROMPT


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def test_each_candidate_is_cut_and_judged(probed, cut, tmp_path):
    judge = FakeJudge([reply(95), reply(20)])
    out = score_clips(cands((1.0, 3.0, 0.5), (10.0, 12.0, 0.5)),
                      tmp_path / "src.mp4", judge)
    assert [v.keep_score for v in out] == [95.0, 20.0]
    assert cut == [(1.0, 3.0), (10.0, 12.0)]
    assert out[0].moment_type == "vows"


def test_scores_are_clamped(probed, cut, tmp_path):
    judge = FakeJudge([reply(999), reply(-40)])
    out = score_clips(cands((0, 1, 0.5), (2, 3, 0.5)), tmp_path / "s.mp4",
                      judge)
    assert [v.keep_score for v in out] == [100.0, 0.0]


def test_max_clips_bounds_the_spend(probed, cut, tmp_path):
    judge = FakeJudge()
    out = score_clips(cands(*[(i, i + 1, 0.5) for i in range(20)]),
                      tmp_path / "s.mp4", judge, max_clips=5)
    assert len(out) == 5 and len(judge.calls) == 5


def test_fps_is_passed_through(probed, cut, tmp_path):
    judge = FakeJudge()
    score_clips(cands((0, 2, 0.5)), tmp_path / "s.mp4", judge, fps=2.0)
    assert judge.calls[0][2] == 2.0


# ---------------------------------------------------------------------------
# Degradation — the common case
# ---------------------------------------------------------------------------

def test_an_unprobed_wire_format_is_named_not_silent(monkeypatch, cut,
                                                     tmp_path):
    """A stream of empty fields would read as "the model had no opinion"."""
    monkeypatch.setattr("pixcull.scoring.m3.load_capabilities", lambda: {})
    judge = FakeJudge()
    out = score_clips(cands((0, 2, 0.5)), tmp_path / "s.mp4", judge)
    assert not judge.calls, "sent a request with an unverified wire format"
    assert "m3 doctor" in out[0].skipped


def test_a_clip_that_cannot_be_cut_is_skipped_not_fatal(probed, monkeypatch,
                                                        tmp_path):
    def _boom(*a, **kw):
        raise ClipTooLarge("187 MB after transcoding")

    monkeypatch.setattr("pixcull.scoring.m3_video.clip_to_tempfile", _boom)
    out = score_clips(cands((0, 2, 0.5), (3, 5, 0.5)), tmp_path / "s.mp4",
                      FakeJudge())
    assert len(out) == 2
    assert all("187 MB" in v.skipped for v in out)


def test_a_dead_connection_does_not_abort_the_batch(probed, cut, tmp_path):
    out = score_clips(cands((0, 1, 0.5), (2, 3, 0.5)), tmp_path / "s.mp4",
                      FakeJudge(boom=True))
    assert len(out) == 2 and all(v.error for v in out)


def test_malformed_json_is_flagged(probed, cut, tmp_path):
    out = score_clips(cands((0, 1, 0.5)), tmp_path / "s.mp4",
                      FakeJudge(["not json"]))
    assert out[0].error == "JSON parse failed"


def test_valid_json_with_nothing_useful_is_flagged(probed, cut, tmp_path):
    out = score_clips(cands((0, 1, 0.5)), tmp_path / "s.mp4",
                      FakeJudge([json.dumps({"moment_type": "filler"})]))
    assert out[0].error == "no usable fields"


# ---------------------------------------------------------------------------
# Re-ranking
# ---------------------------------------------------------------------------

def test_content_reorders_two_clips_the_proxy_cannot_tell_apart():
    """The headline case, stated as the scenario.

    Identical proxy scores — same camera motion, same face count — one is
    the vows, one is someone fixing a mic.
    """
    c = cands((10, 13, 0.80), (40, 43, 0.80))
    rerank(c, [ClipVerdict(10, 13, keep_score=95, happening="誓词"),
               ClipVerdict(40, 43, keep_score=15, happening="调麦克风")])
    assert c[0]["m3_happening"] == "誓词"
    assert c[0]["window_score_norm"] > c[1]["window_score_norm"]


def test_the_proxy_still_carries_weight():
    """A gorgeous moment through a shaking lens is still unusable, and
    only mean_final knows that."""
    assert 0.0 < M3_WEIGHT < 1.0
    c = cands((0, 2, 0.0))
    rerank(c, [ClipVerdict(0, 2, keep_score=100)])
    assert c[0]["window_score_norm"] == pytest.approx(M3_WEIGHT)


def test_the_original_score_is_kept_for_inspection():
    c = cands((0, 2, 0.4))
    rerank(c, [ClipVerdict(0, 2, keep_score=90)])
    assert c[0]["window_score_norm_proxy"] == pytest.approx(0.4)


def test_unjudged_candidates_keep_their_proxy_score():
    """A partial pass must degrade smoothly, not shuffle half the list
    against the other half on two different scales."""
    c = cands((0, 2, 0.9), (5, 7, 0.3))
    rerank(c, [ClipVerdict(0, 2, skipped="no ffmpeg"),
               ClipVerdict(5, 7, skipped="no ffmpeg")])
    assert [x["window_score_norm"] for x in c] == [0.9, 0.3]
    assert "window_score_norm_proxy" not in c[0]


def test_every_candidate_carries_the_reason_it_was_skipped():
    c = cands((0, 2, 0.5))
    rerank(c, [ClipVerdict(0, 2, skipped="video input unverified")])
    assert c[0]["m3_error"] == "video input unverified"


def test_the_list_comes_back_sorted():
    c = cands((0, 2, 0.1), (3, 5, 0.1), (6, 8, 0.1))
    rerank(c, [ClipVerdict(0, 2, keep_score=10),
               ClipVerdict(3, 5, keep_score=90),
               ClipVerdict(6, 8, keep_score=50)])
    assert [x["m3_keep_score"] for x in c] == [90.0, 50.0, 10.0]


def test_the_serialised_keys_are_namespaced():
    """reel_candidates.json is consumed by the review page and the
    lightbox by fixed field name; new fields must not collide."""
    d = ClipVerdict(0, 1, keep_score=50).as_dict()
    assert all(k.startswith("m3_") for k in d)


# ---------------------------------------------------------------------------
# The 50 MB gate
# ---------------------------------------------------------------------------

def test_the_budget_leaves_headroom_under_the_vendor_limit():
    from pixcull.scoring.m3 import MAX_VIDEO_BYTES
    assert TARGET_CLIP_BYTES < MAX_VIDEO_BYTES, (
        "a transcode that lands exactly on the limit will fail on the "
        "next clip that is one byte larger")


def test_transcode_is_attempted_before_giving_up():
    """4K ProRes is ~187 MB for 3 s and trips this on EVERY clip.

    Structural: without the second ffmpeg invocation, every ProRes
    shooter gets an exception per candidate and the feature is simply
    unavailable to them.
    """
    import inspect

    from pixcull.scoring import m3_video
    src = inspect.getsource(m3_video.clip_to_tempfile)
    assert src.index('"-c", "copy"') < src.index('"libx264"'), (
        "stream copy must be tried first — it is free and correct for "
        "most H.264 deliverables")
    assert "ClipTooLarge" in src


# ---------------------------------------------------------------------------
# v2.52.6 — the wire format, now verified rather than guessed
# ---------------------------------------------------------------------------

def test_the_confirmed_shape_is_the_first_candidate():
    """Probed against the live CN endpoint on 2026-08-14.

    The first guess turned out to be right. That is worth pinning, and it
    is also worth being clear that "my guess was right" and "I verified
    it" are different claims — only the second is safe to build 3000 API
    calls on, which is why score_video still refuses to run until a probe
    has recorded a shape.
    """
    from pixcull.scoring.m3 import VIDEO_PART_SHAPES
    part = VIDEO_PART_SHAPES["video_url_object"]("data:video/mp4;base64,AA==",
                                                 1.0)
    assert part == {"type": "video_url",
                    "video_url": {"url": "data:video/mp4;base64,AA==",
                                  "fps": 1.0}}


def test_the_module_no_longer_claims_the_shape_is_unknown():
    from pathlib import Path

    from pixcull.scoring import m3
    doc = (m3.__doc__ or "")
    assert "CONFIRMED against the live API" in doc
    assert "not pinned down" not in doc
    assert Path(m3.__file__).exists()
