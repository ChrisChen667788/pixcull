"""Tests for pixcull/scoring/nl_explain.py — v0.13-P1-1.

The LLM path is hardware-dependent + has its own llama.cpp coverage.
Here we exercise:
  * the template fallback (deterministic)
  * the prompt builder (covered by the LLM path but pure-fn)
  * graceful behaviour when no LLM is available
"""

from __future__ import annotations

import os

import pytest

from pixcull.scoring import nl_explain as ne


def test_template_explain_weak_axis():
    s = ne._template_explain({
        "axes": {
            "technical": {"stars": 2.0},
            "subject":   {"stars": 4.5},
            "composition": {"stars": 4.0},
        },
        "scene": "wedding",
        "decision": "maybe",
    })
    assert "technical" in s
    assert "2.0" in s


def test_template_explain_burst_neighbor():
    s = ne._template_explain({
        "axes": {"subject": {"stars": 4.5}},
        "burst_neighbor_delta": 0.05,
        "scene": "wedding",
        "decision": "maybe",
    })
    assert "0.05" in s
    assert "邻居" in s or "neighbor" in s.lower()


def test_template_explain_keep_balanced():
    s = ne._template_explain({
        "axes": {
            "technical": {"stars": 4.5},
            "subject":   {"stars": 4.6},
        },
        "scene": "portrait",
        "decision": "keep",
    })
    # Balanced (no weak axis) → keep summary
    assert "保留" in s or "推荐" in s or "keep" in s.lower()


def test_template_explain_cull_balanced():
    s = ne._template_explain({
        "axes": {
            "technical": {"stars": 4.0},
            "subject":   {"stars": 4.2},
        },
        "scene": "portrait",
        "decision": "cull",
    })
    assert "丢弃" in s or "discard" in s.lower() or "无" in s


def test_template_explain_maybe_no_weak_axis():
    """Decision = maybe + axes balanced → neutral 'edge case' string."""
    s = ne._template_explain({
        "axes": {
            "technical": {"stars": 4.0},
            "subject":   {"stars": 4.0},
        },
        "decision": "maybe",
    })
    assert "maybe" in s.lower() or "偏好" in s or "边界" in s


def test_template_handles_empty_axes():
    """Robust to missing/empty axes field."""
    s = ne._template_explain({
        "axes": {},
        "decision": "keep",
    })
    assert isinstance(s, str)
    assert len(s) > 0


def test_template_handles_garbage_axes():
    """Stars that aren't numbers are silently skipped."""
    s = ne._template_explain({
        "axes": {
            "technical": {"stars": "not a number"},
            "subject":   {"stars": None},
            "composition": {"stars": 4.0},   # valid; ignored as not weakest
        },
        "decision": "keep",
    })
    assert isinstance(s, str)


def test_build_prompt_includes_axes():
    p = ne._build_prompt({
        "axes": {
            "technical": {"stars": 2.0},
            "subject":   {"stars": 4.5},
            "composition": {"stars": 1.5},
        },
        "scene": "wedding",
        "decision": "maybe",
    })
    assert "Weak axes" in p
    assert "Strong axes" in p
    assert "wedding" in p
    assert "maybe" in p


def test_build_prompt_burst_neighbor_threshold():
    p = ne._build_prompt({
        "axes": {"subject": {"stars": 4.0}},
        "burst_neighbor_delta": 0.05,
    })
    assert "0.05" in p


def test_build_prompt_skips_small_burst_delta():
    """Below 0.02 threshold the burst-neighbor line is omitted."""
    p = ne._build_prompt({
        "axes": {"subject": {"stars": 4.0}},
        "burst_neighbor_delta": 0.001,
    })
    assert "sharper" not in p


def test_explain_falls_back_to_template_when_no_llm(monkeypatch):
    """With no LLM available, explain() still returns a string."""
    monkeypatch.setenv("PIXCULL_NL_EXPLAIN", "off")
    ne.reset()
    s = ne.explain({
        "axes": {"technical": {"stars": 1.5}},
        "decision": "cull",
    })
    assert isinstance(s, str)
    assert len(s) > 0


def test_explain_never_raises_on_garbage_input():
    s = ne.explain({})
    assert isinstance(s, str)
    # Reasonable default
    assert len(s) > 0
