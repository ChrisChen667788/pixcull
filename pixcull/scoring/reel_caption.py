"""v2.1-P0-3 — Semantic reel captions (optional LLM + template fallback).

Charter ``docs/ROADMAP-v2.1-charter.md`` § v2.1-P0-3.  The P0-3 reel
detector's ``why`` is signal-level ("精彩瞬间 + 平稳运镜 + 人物入镜").
This turns it into a fluent caption when a local LLM is installed, and
otherwise composes a richer deterministic sentence from the same signals
— mirroring the v0.13 NL-explainer's LLM-or-template contract so it
**always returns a usable string** with zero required dependencies.

v2.4-P0-1 closes the loop: when **opt-in** (``PIXCULL_REEL_VLM=on``) and a
small captioning VLM is installed (default ``Salesforce/blip-image-
captioning-base`` via transformers, like the CLIP path elsewhere), we now
caption the **actual best frame** — a true vision model looking at the
pixels.  The priority is VLM → text-LLM-over-signals → template, so the
guaranteed-string contract and zero-dependency default are unchanged
(the VLM is off unless explicitly enabled, since it's a ~1 GB download).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

# Toggle: PIXCULL_REEL_CAPTION=off forces the template (disables text LLM).
_LLM_ENABLED = os.environ.get("PIXCULL_REEL_CAPTION", "auto").lower() != "off"

# v2.4-P0-1 — the true-VLM path is OPT-IN (a captioning VLM is a ~1 GB
# download + a couple of seconds per candidate; auto-enabling would
# silently slow every video run).  Enable with PIXCULL_REEL_VLM=on.
_VLM_ENABLED = os.environ.get("PIXCULL_REEL_VLM", "off").lower() in {
    "on", "1", "true", "yes", "auto"}
_VLM_MODEL = os.environ.get(
    "PIXCULL_VLM_MODEL", "Salesforce/blip-image-captioning-base")

_SCENE_WORDS = {
    "portrait": "人物特写", "event": "现场氛围", "wedding": "婚礼时刻",
    "landscape": "风景", "street": "街拍", "documentary": "纪实",
    "sports": "动感", "food": "美食", "architecture": "建筑",
}

# v2.7 — English counterparts for the bilingual caption. Mirrors the zh map
# so the English template line never leaks a Chinese scene word.
_SCENE_WORDS_EN = {
    "portrait": "portrait", "event": "the scene", "wedding": "wedding moment",
    "landscape": "landscape", "street": "street scene", "documentary": "documentary",
    "sports": "action", "food": "food", "architecture": "architecture",
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


def template_caption_en(cand: dict) -> str:
    """v2.7 — deterministic English caption (time range + scene word +
    best-frame score). The ``why`` signals are Chinese, so the EN line
    intentionally carries only language-neutral atoms, never a translated
    fragment list. Always returns a usable string."""
    start = float(cand.get("start_s", 0.0))
    end = float(cand.get("end_s", start))
    scene = cand.get("scene")
    scene_word = _SCENE_WORDS_EN.get(scene) if scene else None
    body = scene_word or "stable usable clip"
    bf = cand.get("best_frame_score")
    tail = f" (best frame {float(bf):.2f})" if isinstance(bf, (int, float)) else ""
    return f"{start:.1f}–{end:.1f}s: {body}{tail}"


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


# --------------------------------------------------------------------------
# v2.4-P0-1 — true VLM caption (looks at the best frame's pixels)
# --------------------------------------------------------------------------

_vlm = None
_vlm_probed = False


def _try_vlm():
    """Lazily load the optional captioning VLM (transformers).  Returns a
    ``(processor, model)`` tuple or ``None``.  Cached; never raises."""
    global _vlm, _vlm_probed
    if not _VLM_ENABLED:
        return None
    if _vlm_probed:
        return _vlm
    _vlm_probed = True
    try:
        from transformers import BlipForConditionalGeneration, BlipProcessor
        proc = BlipProcessor.from_pretrained(_VLM_MODEL)
        model = BlipForConditionalGeneration.from_pretrained(_VLM_MODEL)
        model.eval()
        _vlm = (proc, model)
    except Exception:
        _vlm = None
    return _vlm


def _resolve_best_frame(cand: dict, frames_root) -> Path | None:
    """Locate the best frame's extracted JPEG under a run's output dir.

    Frames live at ``<output_dir>/video_frames/<video_id>/frame_NNNNNN.jpg``
    (io/video.py).  ``frames_root`` may be the output dir, the
    ``video_frames`` dir, or a direct frame dir — try each."""
    fid = cand.get("best_frame_id")
    if not fid or frames_root is None:
        return None
    root = Path(frames_root)
    name = f"{fid}.jpg"
    for p in (root / name, *root.glob(f"video_frames/*/{name}"),
              *root.glob(f"*/{name}")):
        if p.is_file():
            return p
    return None


def _clean_caption(text: str) -> str:
    text = " ".join((text or "").split()).strip(" .。")
    for junk in ("araffe ", "arafed ", "there is ", "there are "):
        if text.lower().startswith(junk):
            text = text[len(junk):]
    return (text[:1].upper() + text[1:]) if text else ""


def vlm_caption_from_image(image_path) -> str | None:
    """Caption a single image with the VLM; ``None`` when unavailable."""
    vlm = _try_vlm()
    if vlm is None:
        return None
    try:
        import torch
        from PIL import Image
        proc, model = vlm
        img = Image.open(image_path).convert("RGB")
        with torch.no_grad():
            inputs = proc(img, return_tensors="pt")
            out = model.generate(**inputs, max_new_tokens=24, num_beams=3)
        return _clean_caption(
            proc.decode(out[0], skip_special_tokens=True)) or None
    except Exception:
        return None


def _zh_rewrite(text: str) -> str | None:
    """v2.5 — bilingual bridge: BLIP captions in English, but the product
    speaks Chinese.  When the optional local text LLM (the same GGUF the
    NL-explainer shares) is present, rewrite the English frame description
    into a short natural Chinese line; ``None`` (→ keep English) when the
    LLM is absent or misbehaves, so the VLM path never gets worse than the
    English it already had."""
    llm = _try_llm()
    if llm is None:
        return None
    try:
        out = llm(
            "把下面这句英文镜头描述翻译成不超过 20 字的自然中文,"
            "只输出译文本身:\n" + text + "\n译文:",
            max_tokens=48, stop=["\n"], temperature=0.2)
        zh = out["choices"][0]["text"].strip().strip("。「」\"'").strip()
        # Sanity: a usable rewrite is short and actually contains CJK.
        if zh and len(zh) <= 40 and any("一" <= c <= "鿿" for c in zh):
            return zh
    except Exception:
        pass
    return None


def vlm_caption_bilingual(cand: dict, frames_root=None) -> tuple[str, str] | None:
    """v2.7 — caption the best frame in BOTH languages: ``(zh, en)``, each
    prefixed with the time range.  ``en`` is the raw BLIP English; ``zh`` is
    the local-LLM rewrite of it, or the English itself when no LLM is present
    (so zh is never worse than the English we already had).  ``None`` when the
    frame can't be found or the VLM produced nothing."""
    frame = _resolve_best_frame(cand, frames_root)
    if frame is None:
        return None
    en_desc = vlm_caption_from_image(frame)
    if not en_desc:
        return None
    zh_desc = _zh_rewrite(en_desc) or en_desc
    start = float(cand.get("start_s", 0.0))
    end = float(cand.get("end_s", start))
    prefix = f"{start:.1f}–{end:.1f}s:"
    return prefix + zh_desc, prefix + en_desc


def vlm_caption(cand: dict, frames_root=None) -> str | None:
    """Backward-compatible single-language (zh-preferred) VLM caption — the
    ``zh`` half of :func:`vlm_caption_bilingual`.  ``None`` when no frame/VLM."""
    pair = vlm_caption_bilingual(cand, frames_root)
    return pair[0] if pair else None


def caption_bilingual(cand: dict, frames_root=None) -> tuple[str, str, str]:
    """v2.7 — ``(zh, en, source)`` with source ∈ {vlm, llm, template}.
    The VLM (best frame) yields a genuine bilingual pair; the text-LLM path is
    zh-only so its English falls back to the deterministic EN template; the
    template path renders both deterministically.  ``en`` is always present."""
    pair = vlm_caption_bilingual(cand, frames_root)
    if pair:
        return pair[0], pair[1], "vlm"
    lc = llm_caption(cand)
    if lc:
        return lc, template_caption_en(cand), "llm"
    return template_caption(cand), template_caption_en(cand), "template"


def caption_with_source(cand: dict, frames_root=None) -> tuple[str, str]:
    """Backward-compatible ``(zh_caption, source)`` — wraps
    :func:`caption_bilingual` and drops the English half."""
    zh, _en, src = caption_bilingual(cand, frames_root)
    return zh, src


def caption(cand: dict, frames_root=None) -> str:
    """VLM (best frame) if enabled+available, else text LLM, else template."""
    return caption_with_source(cand, frames_root)[0]


def enrich(candidates: Sequence[dict], frames_root=None) -> list[dict]:
    """Add ``why_semantic`` (+ ``caption_source``) to each candidate dict.

    ``frames_root`` (a run's output dir) lets the VLM path find the best
    frame's image; omit it and captioning gracefully drops to LLM/template."""
    for c in candidates:
        zh, en, src = caption_bilingual(c, frames_root)
        c["why_semantic"] = zh
        c["why_semantic_en"] = en
        c["caption_source"] = src
    return list(candidates)


def reset() -> None:
    """Test hook — clear the cached LLM + VLM probes."""
    global _llm, _llm_probed, _vlm, _vlm_probed
    _llm, _llm_probed = None, False
    _vlm, _vlm_probed = None, False
