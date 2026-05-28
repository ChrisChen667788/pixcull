"""v0.13-P1-1 — Natural-language explanation generator.

Given a photo's per-axis attribution + neighbor delta + similar past
culls, generate a ~50-token English/Chinese summary explaining why
the model decided keep/maybe/cull.

Two backends
============
1. **Local LLM** (default when ``ggml`` / ``llama.cpp`` is available):
   ``models/qwen2.5-3b-q5.gguf`` (or any compatible 3B Q5 model) runs
   inference at ~200ms/photo on M-series Mac.  Template input keeps
   the prompt deterministic + cache-friendly.
2. **Template fallback** (always): when the LLM isn't installed (or
   ``PIXCULL_NL_EXPLAIN=off``), we string-format a fixed template
   with the same input fields.  Quality is lower but it's instant
   and zero-dependency.

Local-first contract: nothing leaves the box.  The cloud LLM path is
not implemented intentionally — every PixCull AI explanation must
work offline.

Public API
==========

  explain(features) -> str
      features = {
        "axes": {axis_name: {"stars": float, "rationale": str}},
        "score_final": float,
        "burst_neighbor_delta": float | None,
        "scene": str,
        "decision": "keep" | "maybe" | "cull",
      }

  Returns a string suitable for inline display in the Inspector.
"""

from __future__ import annotations

import os
from typing import Any


# Toggle: set to "off" to force the template fallback.
_LLM_ENABLED = os.environ.get("PIXCULL_NL_EXPLAIN", "auto").lower() != "off"


def _try_load_llm():
    """Probe for a local GGUF model.  Returns the llama instance or None."""
    if not _LLM_ENABLED:
        return None
    try:
        from llama_cpp import Llama
    except ImportError:
        return None
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent.parent
    candidates = [
        repo_root / "models" / "qwen2.5-3b-q5.gguf",
        repo_root / "models" / "llama-3.2-3b-q5.gguf",
        # User can override via env var
        os.environ.get("PIXCULL_NL_MODEL_PATH"),
    ]
    candidates = [Path(c) for c in candidates if c]
    for path in candidates:
        if path.exists():
            try:
                return Llama(
                    model_path=str(path),
                    n_ctx=512,
                    n_threads=2,
                    verbose=False,
                )
            except Exception:
                continue
    return None


_llm = None


def _llm_explain(features: dict) -> str | None:
    global _llm
    if _llm is None:
        _llm = _try_load_llm()
    if _llm is None:
        return None
    prompt = _build_prompt(features)
    try:
        result = _llm(
            prompt,
            max_tokens=60,
            stop=["</s>", "\n\n"],
            temperature=0.3,
        )
        text = result["choices"][0]["text"].strip()
        return text if text else None
    except Exception:
        return None


def _build_prompt(features: dict) -> str:
    axes = features.get("axes", {})
    sorted_axes = sorted(
        ((name, a.get("stars", 0)) for name, a in axes.items()
         if a and isinstance(a.get("stars"), (int, float))),
        key=lambda p: p[1],
    )
    weak = sorted_axes[:2]
    strong = sorted_axes[-2:] if len(sorted_axes) >= 2 else []
    bn = features.get("burst_neighbor_delta")
    bn_str = ""
    if isinstance(bn, (int, float)):
        if bn > 0.02:
            bn_str = (f"  the next burst frame is {bn:.2f} sharper; "
                      f"consider it instead.\n")
    weak_str = ", ".join(f"{n} {s:.1f}★" for n, s in weak)
    strong_str = ", ".join(f"{n} {s:.1f}★" for n, s in strong)
    decision = features.get("decision", "maybe")
    return (
        f"Summarise in one short sentence why this {features.get('scene', 'photo')}"
        f" was decided '{decision}'.\n"
        f"Weak axes: {weak_str}\n"
        f"Strong axes: {strong_str}\n"
        f"{bn_str}"
        f"Sentence:"
    )


def _template_explain(features: dict) -> str:
    """Deterministic fallback.  Always returns a usable string."""
    axes = features.get("axes", {})
    weak = None
    weakest_stars = 6.0
    for name, a in axes.items():
        if not a or not isinstance(a.get("stars"), (int, float)):
            continue
        if a["stars"] < weakest_stars:
            weakest_stars = a["stars"]
            weak = name
    bn = features.get("burst_neighbor_delta")
    scene = features.get("scene", "photo")
    decision = features.get("decision", "maybe")

    parts: list[str] = []
    if weak and weakest_stars < 3.5:
        parts.append(f"{weak} 较弱 ({weakest_stars:.1f}★)")
    if isinstance(bn, (int, float)) and bn > 0.02:
        parts.append(f"同组邻居高 {bn:.2f}")
    if not parts:
        if decision == "keep":
            return f"各轴均衡 — 推荐保留这张 {scene}."
        if decision == "cull":
            return f"无明显亮点 — 建议丢弃这张 {scene}."
        return f"评分接近 maybe 边界 — 看你的偏好."
    return "; ".join(parts) + "."


def explain(features: dict) -> str:
    """LLM if available, fallback to template otherwise.

    Always returns a non-empty string.  Never raises.
    """
    try:
        out = _llm_explain(features)
        if out:
            return out
    except Exception:
        pass
    return _template_explain(features)


def reset() -> None:
    """Drop the cached LLM instance (tests + admin)."""
    global _llm
    _llm = None
