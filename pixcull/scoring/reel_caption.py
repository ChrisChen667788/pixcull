"""v2.1-P0-3 — Semantic reel captions (optional LLM + template fallback).

Charter ``docs/ROADMAP-v2.1-charter.md`` § v2.1-P0-3.  The P0-3 reel
detector's ``why`` is signal-level ("精彩瞬间 + 平稳运镜 + 人物入镜").
This turns it into a fluent caption when a local LLM is installed, and
otherwise composes a richer deterministic sentence from the same signals
— mirroring the v0.13 NL-explainer's LLM-or-template contract so it
**always returns a usable string** with zero required dependencies.

A true vision model (VLM looking at the best frame) is the ideal; this
ships the signal→sentence rewrite (text LLM via the existing GGUF loader,
template otherwise), which is the honest dependency-light step.
"""

from __future__ import annotations

import os
from typing import Sequence

# Toggle: PIXCULL_REEL_CAPTION=off forces the template.
_LLM_ENABLED = os.environ.get("PIXCULL_REEL_CAPTION", "auto").lower() != "off"

_SCENE_WORDS = {
    "portrait": "人物特写", "event": "现场氛围", "wedding": "婚礼时刻",
    "landscape": "风景", "street": "街拍", "documentary": "纪实",
    "sports": "动感", "food": "美食", "architecture": "建筑",
}


def _fragments(cand: dict) -> list[str]:
    why = str(cand.get("why") or "").strip()
    if not why or why in ("可用片段", "稳定可用片段"):
        return []
    # compose_why joins with " + "; split back into atoms.
    return [f.strip() for f in why.split("+") if f.strip()]


def template_caption(cand: dict) -> str:
    """Deterministic natural caption from the candidate's signals.

    Always returns a usable string (the guaranteed fallback)."""
    start = float(cand.get("start_s", 0.0))
    end = float(cand.get("end_s", start))
    frags = _fragments(cand)
    scene = cand.get("scene")
    scene_word = _SCENE_WORDS.get(scene) if scene else None
    parts = list(frags)
    if scene_word and scene_word not in parts:
        parts.append(scene_word)
    body = "、".join(parts) if parts else "稳定可用片段"
    bf = cand.get("best_frame_score")
    tail = f"(最佳帧 {float(bf):.2f})" if isinstance(bf, (int, float)) else ""
    return f"{start:.1f}–{end:.1f}s:{body}{tail}"


_llm = None
_llm_probed = False


def _try_llm():
    global _llm, _llm_probed
    if not _LLM_ENABLED:
        return None
    if _llm_probed:
        return _llm
    _llm_probed = True
    try:
        # Reuse the NL-explainer's local-GGUF loader so the two features
        # share one optional model.
        from pixcull.scoring.nl_explain import _try_load_llm
        _llm = _try_load_llm()
    except Exception:
        _llm = None
    return _llm


def _build_prompt(cand: dict) -> str:
    frags = "、".join(_fragments(cand)) or "稳定画面"
    scene = cand.get("scene") or "未知"
    return (
        "你是婚礼/活动摄影师的视频选片助手。用一句不超过 20 字的中文，"
        "把下面的信号改写成自然、具体的镜头描述(不要列表、不要标点堆砌):\n"
        f"时间 {cand.get('start_s')}-{cand.get('end_s')}s,场景 {scene},"
        f"信号:{frags}。\n描述:"
    )


def llm_caption(cand: dict) -> str | None:
    """Fluent caption via the optional local LLM; None when unavailable."""
    llm = _try_llm()
    if llm is None:
        return None
    try:
        out = llm(_build_prompt(cand), max_tokens=48,
                  stop=["\n", "。\n"], temperature=0.4)
        text = out["choices"][0]["text"].strip().strip("。").strip()
        return text or None
    except Exception:
        return None


def caption(cand: dict) -> str:
    """LLM caption if available, else the deterministic template."""
    return llm_caption(cand) or template_caption(cand)


def enrich(candidates: Sequence[dict]) -> list[dict]:
    """Add a ``why_semantic`` field to each candidate dict (in place)."""
    for c in candidates:
        c["why_semantic"] = caption(c)
    return list(candidates)


def reset() -> None:
    """Test hook — clear the cached LLM probe."""
    global _llm, _llm_probed
    _llm, _llm_probed = None, False
