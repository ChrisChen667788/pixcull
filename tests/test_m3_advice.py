"""v2.51 — M3 writes the advice, and the output contract holds.

The risk here is not that the prose is bad. It is that the *shape* drifts
and three consumers break without raising anything:

* ``caption_gen.compose_caption`` does ``strengths[0]`` then a regex — a
  dict there drops the caption fragment with no error.
* the lightbox pane renders ``strengths_detail[i].source`` as the canon
  citation; a missing key blanks the citation UI silently.
* the XMP/IPTC exporter builds Caption-Abstract from the same dict, so a
  drift reaches Lightroom.

So the model's reply is validated and repaired into the template shape,
and anything unrepairable falls back. A photographer with an expired key
must get v2.50's advice, not an empty pane.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pixcull.scoring.m3_advice import (
    ADVICE_KEYS,
    advice_from_m3,
    build_prompt,
    enrich_advice,
)


@pytest.fixture
def fallback():
    from pixcull.scoring.photo_advice import build_advice
    stars = {"technical": 4.0, "subject": 4.0, "composition": 3.0,
             "light": 4.0, "moment": 3.0, "aesthetic": 4.0}
    return build_advice({"filename": "a.jpg", "scene": "portrait",
                         "laplacian_subject": 300, "score_final": 0.7},
                        stars, "keep")


GOOD = json.dumps({
    "rationale": "新娘回头的瞬间抓住了,眼神有内容。",
    "strengths": ["睫毛清晰可数,焦点落在近眼", "背景教堂的拱门形成天然画框"],
    "weaknesses": ["右下角有个穿荧光衣的路人"],
    "suggestions": ["再等半秒让手完全离开脸"],
    "strengths_detail": [
        {"axis": "technical", "phrase": "睫毛清晰可数,焦点落在近眼",
         "source": "Adams · Zone System"},
        {"axis": "composition", "phrase": "背景教堂的拱门形成天然画框",
         "source": ""},
    ],
    "weaknesses_detail": [
        {"axis": "subject", "phrase": "右下角有个穿荧光衣的路人", "source": ""},
    ],
}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------

def test_every_key_survives(fallback):
    out = advice_from_m3(GOOD, decision="keep", fallback=fallback)
    for k in ADVICE_KEYS:
        assert k in out, f"{k} vanished — a consumer reads it by name"


def test_strengths_stay_flat_strings(fallback):
    """compose_caption does strengths[0] then a regex. A dict is silent."""
    out = advice_from_m3(GOOD, decision="keep", fallback=fallback)
    assert all(isinstance(s, str) for s in out["strengths"])
    import re
    first = out["strengths"][0]
    assert re.sub(r"\s*[(（].*?[)）]", "", first).strip()


def test_a_model_that_returns_dicts_is_repaired(fallback):
    """Models do this. Rejecting the whole reply over it wastes the call."""
    raw = json.dumps({"rationale": "ok",
                      "strengths": [{"phrase": "锐利", "axis": "technical"},
                                    {"text": "光好"}]},
                     ensure_ascii=False)
    out = advice_from_m3(raw, decision="keep", fallback=fallback)
    assert out["strengths"] == ["锐利", "光好"]


def test_detail_rows_always_carry_source(fallback):
    """The lightbox reads .source directly; a missing key blanks the pane."""
    out = advice_from_m3(GOOD, decision="keep", fallback=fallback)
    for d in out["strengths_detail"] + out["weaknesses_detail"]:
        assert set(d) == {"axis", "phrase", "source"}
        assert isinstance(d["source"], str)


def test_details_are_synthesised_when_the_model_omits_them(fallback):
    """An uncited strength is still a strength; an empty pane looks broken."""
    raw = json.dumps({"rationale": "r", "strengths": ["很锐"]},
                     ensure_ascii=False)
    out = advice_from_m3(raw, decision="keep", fallback=fallback)
    assert [d["phrase"] for d in out["strengths_detail"]] == ["很锐"]
    assert out["strengths_detail"][0]["source"] == ""


def test_an_invented_axis_is_dropped_not_passed_through(fallback):
    raw = json.dumps({"rationale": "r", "strengths": ["x"],
                      "strengths_detail": [
                          {"axis": "vibes", "phrase": "x", "source": ""}]},
                     ensure_ascii=False)
    out = advice_from_m3(raw, decision="keep", fallback=fallback)
    assert out["strengths_detail"][0]["axis"] == ""


def test_lists_are_capped(fallback):
    raw = json.dumps({"rationale": "r",
                      "strengths": [f"s{i}" for i in range(9)],
                      "suggestions": [f"g{i}" for i in range(9)]},
                     ensure_ascii=False)
    out = advice_from_m3(raw, decision="keep", fallback=fallback)
    assert len(out["strengths"]) == 3
    assert len(out["suggestions"]) == 2


def test_partial_output_is_kept_and_filled(fallback):
    """Good strengths + forgotten suggestions still beats a template."""
    raw = json.dumps({"rationale": "有内容", "strengths": ["锐"]},
                     ensure_ascii=False)
    out = advice_from_m3(raw, decision="keep", fallback=fallback)
    assert out["rationale"] == "有内容"
    assert out["suggestions"] == fallback["suggestions"]


def test_the_source_is_recorded(fallback):
    out = advice_from_m3(GOOD, decision="keep", fallback=fallback)
    assert out["advice_source"] == "minimax-m3"


# ---------------------------------------------------------------------------
# Refusing bad output
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "", "not json at all",
    json.dumps({"rationale": "", "strengths": [], "weaknesses": []}),
    json.dumps({"strengths": "", "weaknesses": None}),
    json.dumps([1, 2, 3]),
])
def test_unusable_output_falls_back(raw, fallback):
    assert advice_from_m3(raw, decision="keep", fallback=fallback) is None


def test_valid_json_carrying_nothing_is_refused(fallback):
    """A template beats a blank pane."""
    assert advice_from_m3('{"rationale": "   "}', decision="keep",
                          fallback=fallback) is None


# ---------------------------------------------------------------------------
# enrich_advice never costs anyone their cull
# ---------------------------------------------------------------------------

class _Judge:
    def __init__(self, raw="", error=None, boom=False):
        self.raw, self.error, self.boom = raw, error, boom
        self.prompts: list[str] = []

    def score(self, path, scene="", max_tokens=700, row=None,
              prompt_override=None):
        if self.boom:
            raise RuntimeError("network gone")
        self.prompts.append(prompt_override or "")
        v = type("V", (), {})()
        v.raw_text, v.error = self.raw, self.error
        return v


class _OldJudge:
    """A backend that predates prompt_override (the MLX one)."""

    def score(self, path, scene="", max_tokens=700, row=None):
        raise AssertionError("should not be reached")


@pytest.fixture
def photo(tmp_path):
    from PIL import Image
    p = tmp_path / "a.jpg"
    Image.new("RGB", (32, 32)).save(p, "JPEG")
    return p


def test_happy_path(fallback, photo):
    out = enrich_advice({"scene": "portrait"}, {}, "keep", fallback,
                        _Judge(raw=GOOD), image_path=photo)
    assert out["advice_source"] == "minimax-m3"


def test_an_exploding_judge_keeps_the_template(fallback, photo):
    out = enrich_advice({}, {}, "keep", fallback, _Judge(boom=True),
                        image_path=photo)
    assert out is fallback


def test_an_errored_verdict_keeps_the_template(fallback, photo):
    out = enrich_advice({}, {}, "keep", fallback,
                        _Judge(raw=GOOD, error="503"), image_path=photo)
    assert out is fallback


def test_a_missing_file_keeps_the_template(fallback, tmp_path):
    out = enrich_advice({}, {}, "keep", fallback, _Judge(raw=GOOD),
                        image_path=tmp_path / "nope.jpg")
    assert out is fallback


def test_no_judge_keeps_the_template(fallback, photo):
    assert enrich_advice({}, {}, "keep", fallback, None,
                         image_path=photo) is fallback


def test_a_backend_without_prompt_override_is_declined(fallback, photo):
    """Its axis scores answer a different question; do not pretend."""
    out = enrich_advice({}, {}, "keep", fallback, _OldJudge(),
                        image_path=photo)
    assert out is fallback


# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------

def test_the_prompt_carries_the_measurements():
    p = build_prompt({"laplacian_subject": 412.0, "face_count": 2},
                     {"technical": 4.0}, "keep")
    assert "412" in p and "客观测量" in p


def test_the_prompt_asks_for_observations_not_numbers():
    p = build_prompt({}, {}, "keep")
    assert "说画面,不说数字" in p


def test_the_prompt_invites_disagreement_with_the_instruments():
    """A judge that cannot contradict the sensor is just a formatter."""
    p = build_prompt({}, {}, "keep")
    assert "冲突" in p


# ---------------------------------------------------------------------------
# Cache separation
# ---------------------------------------------------------------------------

def test_scoring_and_advice_do_not_share_a_cache_entry():
    """Two different questions about the same bytes.

    Without the prompt in the key, whichever ran first would answer for
    both — the advice pane would show axis JSON, or the score would come
    back as prose.
    """
    import inspect

    from pixcull.scoring import m3
    src = inspect.getsource(m3.MiniMaxM3Judge.score)
    key = src[src.index("_content_hash("):src.index("hit = ")]
    assert "prompt_override" in key
