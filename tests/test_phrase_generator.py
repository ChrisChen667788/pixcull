"""V17.5 — phrase generator unit tests.

Network/LLM call is mocked; we test the deterministic parts:
* validation of the LLM payload shape (rejects junk)
* override file roundtrip (save / load / delete)
* photo_advice consults phrase_override BEFORE the hand-written pool
* falls back cleanly when override absent / malformed
"""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import pytest

from pixcull import phrase_generator as pg
from pixcull import verticals as vmod
from pixcull.scoring.photo_advice import build_advice


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(vmod, "_data_root", lambda: tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# _validate_phrases
# ---------------------------------------------------------------------------

def test_validate_phrases_happy_path():
    payload = {
        "axes": {
            "subject":     {"phrases": ["新人眼神到位", "情感互动自然", "氛围温柔"]},
            "composition": {"phrases": ["Lead Room 充足", "透视舒服"]},
            "light":       {"phrases": ["皮肤通透"]},
            "moment":      {"phrases": ["决定性瞬间", "情绪峰值"]},
            "aesthetic":   {"phrases": ["质感细腻", "情绪饱满", "色彩协调"]},
            "technical":   {"phrases": ["焦点锁定", "锐度顶级"]},
        }
    }
    out = pg._validate_phrases(payload)
    assert "subject" in out and len(out["subject"]) == 3
    # Each axis capped at 3 phrases
    for ax, phrases in out.items():
        assert 1 <= len(phrases) <= 3


def test_validate_phrases_strips_punct_and_caps_length():
    """Validation: strip trailing punct, drop too-long entries, trim
    whitespace. Output is capped to 3 per axis so we only verify the
    cleaning rules, not which ones survive the trim."""
    payload = {
        "axes": {
            "subject": {"phrases": [
                "句号结尾。",      # → "句号结尾"
                "x" * 50,        # too long → dropped
                "感叹号!",        # → "感叹号"
            ]},
            "light": {"phrases": ["  空白包裹  "]},  # → "空白包裹"
        }
    }
    out = pg._validate_phrases(payload)
    # Trailing punctuation stripped
    assert "句号结尾。" not in out["subject"]
    assert "句号结尾" in out["subject"]
    assert "感叹号" in out["subject"]
    # Too-long entry dropped (not in either axis)
    assert not any(len(p) > 30 for p in out["subject"])
    # Whitespace trimmed
    assert "空白包裹" in out["light"]


def test_validate_phrases_rejects_missing_axes():
    with pytest.raises(ValueError, match="axes"):
        pg._validate_phrases({"foo": 1})


def test_validate_phrases_rejects_all_empty():
    """Payload with empty / invalid phrase lists for every axis → raise."""
    payload = {
        "axes": {ax: {"phrases": []} for ax in pg._REQUIRED_AXES}
    }
    with pytest.raises(ValueError, match="no valid phrases"):
        pg._validate_phrases(payload)


def test_validate_phrases_ignores_non_string():
    payload = {"axes": {"subject": {"phrases": ["valid", 42, None, "also valid"]}}}
    out = pg._validate_phrases(payload)
    assert out["subject"] == ["valid", "also valid"]


# ---------------------------------------------------------------------------
# Override persistence
# ---------------------------------------------------------------------------

def test_phrase_override_roundtrip(isolated_data_dir):
    result = pg.GenerateResult(
        vertical="wedding",
        n_samples_seen=12,
        scene_mode="portrait",
        style_modes=["high_key"],
        high_axes=["light", "moment"],
        axes={
            "subject":   ["新人眼神到位"],
            "light":     ["皮肤通透干净"],
            "moment":    ["决定性表情"],
        },
        model="deepseek-chat",
        prompt_tokens=420, completion_tokens=180,
        elapsed_s=2.4,
    )
    pg.save_phrase_override("wedding", result)
    p = pg.phrase_override_path("wedding")
    assert p.exists()
    loaded = pg.load_phrase_override("wedding")
    assert loaded["vertical"] == "wedding"
    assert loaded["n_samples_seen"] == 12
    assert loaded["axes"]["light"]["phrases"] == ["皮肤通透干净"]
    assert pg.delete_phrase_override("wedding") is True
    assert not p.exists()


def test_phrase_override_load_missing(isolated_data_dir):
    assert pg.load_phrase_override("wedding") is None


def test_phrase_override_load_corrupt(isolated_data_dir):
    pg.phrase_override_path("wedding").write_text("not json", encoding="utf-8")
    assert pg.load_phrase_override("wedding") is None


# ---------------------------------------------------------------------------
# photo_advice consults override BEFORE hand-written pool
# ---------------------------------------------------------------------------

_HOT_ROW = {
    "filename":        "x.jpg",
    "scene":           "portrait",
    "face_count":      2,
    "subject_fraction": 0.45,
    "canon_lead_room": 0.78,
    "score_moment":    0.80,
    "laion_aes":       6.2,
    "score_final":     0.80,
}
_HOT_FINAL = {ax: 5.0 for ax in
              ("subject", "technical", "composition",
               "light", "moment", "aesthetic")}


def test_advice_uses_phrase_override_when_present(isolated_data_dir):
    """Save an override → wedding-tagged advice should use the
    override phrases, not the V17.3 hand-written ones."""
    result = pg.GenerateResult(
        vertical="wedding",
        n_samples_seen=10, scene_mode="portrait",
        style_modes=["high_key"], high_axes=["light", "moment", "subject"],
        axes={
            "subject":     ["★用户专属·主体短语"],
            "composition": ["★用户专属·构图短语"],
            "light":       ["★用户专属·光线短语"],
            "moment":      ["★用户专属·瞬间短语"],
            "aesthetic":   ["★用户专属·美感短语"],
            "technical":   ["★用户专属·技术短语"],
        },
        model="deepseek-chat",
        prompt_tokens=0, completion_tokens=0, elapsed_s=0.0,
    )
    pg.save_phrase_override("wedding", result)

    ad = build_advice(_HOT_ROW, _HOT_FINAL, "keep", idx=0, vertical="wedding")
    blob = " ".join(ad["strengths"])
    # User-specific phrase appears
    assert "★用户专属" in blob
    # V17.3 hand-written wedding phrases SHOULDN'T appear
    assert "新人眼神接触" not in blob
    assert "婚纱质感" not in blob
    # Source attribution shows "AI · 用户专属"
    sources = [(s.get("source") or "") for s in ad["strengths_detail"]]
    assert any("AI" in s and "wedding" in s for s in sources)


def test_advice_falls_back_to_handwritten_when_no_override(isolated_data_dir):
    """No override → V17.3 hand-written wedding pool fires."""
    ad = build_advice(_HOT_ROW, _HOT_FINAL, "keep", idx=0, vertical="wedding")
    blob = " ".join(ad["strengths"])
    # V17.3 hand-written wedding vocabulary should appear
    assert "★用户专属" not in blob
    assert any(kw in blob for kw in
                ("新人", "Lead Room", "情感"))


def test_advice_no_vertical_unaffected_by_override(isolated_data_dir):
    """Saving a wedding override should NOT leak into non-vertical runs."""
    result = pg.GenerateResult(
        vertical="wedding", n_samples_seen=10,
        scene_mode="portrait", style_modes=[], high_axes=[],
        axes={"subject": ["★泄漏检测短语"]},
        model="deepseek-chat",
        prompt_tokens=0, completion_tokens=0, elapsed_s=0.0,
    )
    pg.save_phrase_override("wedding", result)
    ad = build_advice(_HOT_ROW, _HOT_FINAL, "keep", idx=0, vertical=None)
    blob = " ".join(ad["strengths"])
    assert "★泄漏检测" not in blob


def test_advice_override_only_overrides_strength_not_weakness(isolated_data_dir):
    """Override pool is for STRENGTHS only — weakness fallback to
    V17.3 hand-written weakness templates."""
    result = pg.GenerateResult(
        vertical="wedding", n_samples_seen=10,
        scene_mode="portrait", style_modes=[], high_axes=[],
        axes={"light": ["★好光"]},
        model="deepseek-chat",
        prompt_tokens=0, completion_tokens=0, elapsed_s=0.0,
    )
    pg.save_phrase_override("wedding", result)
    # Bad-light row should produce hand-written wedding weakness
    bad_light = {"filename": "x.jpg", "scene": "portrait",
                  "face_count": 2, "score_exposure": 0.20}
    weak_final = {"subject": 4.0, "technical": 3.0, "composition": 3.0,
                   "light": 1.0, "moment": 3.0, "aesthetic": 3.0}
    ad = build_advice(bad_light, weak_final, "maybe",
                       idx=0, vertical="wedding")
    weak_blob = " ".join(ad["weaknesses"])
    # V17.3 wedding-specific weakness language should still appear
    # (override doesn't apply to weakness pool)
    assert "新人" in weak_blob or "脸部" in weak_blob


# ---------------------------------------------------------------------------
# Build prompt (no LLM call, just shape check)
# ---------------------------------------------------------------------------

def test_build_prompt_includes_vertical_metadata():
    v = vmod.get_vertical("wedding")
    profile = pg.SampleProfile(
        n_samples=15,
        scenes={"portrait": 12, "event": 3},
        styles={"high_key": 8},
        metric_means={"laion_aes": 5.8, "score_moment": 0.74},
        metric_p90={"laion_aes": 6.5, "score_moment": 0.85},
        high_axes=["light", "moment", "aesthetic"],
    )
    prompt = pg._build_prompt(v, profile)
    payload = json.loads(prompt)
    assert payload["vertical"]["key"] == "wedding"
    assert payload["user_samples"]["n"] == 15
    # Most common scene appears
    assert payload["user_samples"]["common_scenes"][0]["scene"] == "portrait"
    # Schema-shape hint to LLM
    assert "axes" in payload["output_schema"]
