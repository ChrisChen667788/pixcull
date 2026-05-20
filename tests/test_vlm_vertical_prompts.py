"""P-AI-3 — sanity tests for the per-vertical VLM prompt blocks."""
from __future__ import annotations

import pytest

from pixcull.scoring.vlm_vertical_prompts import (
    vertical_prompt_block,
    known_verticals,
)


def test_unknown_vertical_returns_empty():
    assert vertical_prompt_block("not-a-vertical") == ""
    assert vertical_prompt_block(None) == ""
    assert vertical_prompt_block("") == ""


def test_each_known_vertical_returns_substantive_block():
    """Every advertised vertical produces a non-trivial prompt."""
    for v in known_verticals():
        block = vertical_prompt_block(v)
        assert block, f"empty block for vertical={v!r}"
        # Must contain the 评分重点 header so the VLM sees its purpose
        assert "评分重点" in block, f"missing 评分重点 header in {v}"
        # Each block should reference at least 3 of the 6 rubric axes
        # so the VLM actually has axis-specific guidance
        axis_terms = ["technical", "subject", "composition", "light",
                       "moment", "aesthetic"]
        hits = sum(1 for term in axis_terms if term in block)
        assert hits >= 3, f"vertical {v} mentions only {hits} axes in {block!r}"


def test_case_insensitive_lookup():
    """Vertical lookup is case-folded so callers don't have to."""
    base = vertical_prompt_block("wedding")
    assert vertical_prompt_block("Wedding") == base
    assert vertical_prompt_block("WEDDING") == base
    assert vertical_prompt_block("  wedding  ") == base


def test_known_verticals_cover_core_set():
    """Cover the 9 verticals PixCull's UI exposes."""
    kv = set(known_verticals())
    must_have = {
        "landscape", "wildlife", "bird", "sports", "wedding",
        "portrait", "event", "journalism", "commercial", "stilllife",
    }
    missing = must_have - kv
    assert not missing, f"missing prompts for: {missing}"


def test_build_prompt_includes_vertical_block_when_set():
    """The build_prompt() integration actually injects the vertical block."""
    from pixcull.scoring.vlm_judge import build_prompt

    base = build_prompt(scene="wedding")
    with_vert = build_prompt(scene="wedding", vertical="wedding")
    # The vertical-specific text must appear when vertical= is passed
    assert "婚礼摄影" in with_vert
    assert with_vert != base
    # And NOT appear without vertical=
    assert "婚礼摄影" not in base or "评分重点" not in base


def test_build_prompt_vertical_unknown_is_no_op():
    """Unknown vertical is silently dropped (degrades to global prompt)."""
    from pixcull.scoring.vlm_judge import build_prompt
    base = build_prompt(scene="landscape")
    ghost = build_prompt(scene="landscape", vertical="ghost-vertical-xyz")
    assert ghost == base
