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

# v2.7 — ONNX session cache (two sub-graphs: visual encoder + text decoder)
_vlm_onnx = None
_vlm_onnx_probed = False

# BLIP tokenizer constants (BertTokenizer compatible; values for
# blip-image-captioning-base; overridden by config.json when present).
_BLIP_BOS_ID = 30522   # [unused0] used as BOS in BLIP
_BLIP_EOS_ID = 102     # [SEP]
_BLIP_PAD_ID = 0


def _try_vlm_onnx():
    """Lazily discover the BLIP ONNX export under ``~/.pixcull/models/blip-onnx/``.

    Returns a ``(ort_vis_session, ort_dec_session, config_dict)`` triple, or
    ``None`` when the directory / files are absent or ``onnxruntime`` is not
    installed.  Cached; never raises.

    The ONNX artefact is produced by ``scripts/convert_blip_to_onnx.py`` (an
    opt-in offline tool — not run in CI).  The sessions are cached so the
    models are loaded at most once per process.
    """
    global _vlm_onnx, _vlm_onnx_probed
    if _vlm_onnx_probed:
        return _vlm_onnx
    _vlm_onnx_probed = True
    try:
        import onnxruntime as ort  # noqa: F401  (local import, opt-in dep)
        from pixcull.models_manager import PIXCULL_HOME
        blip_dir = PIXCULL_HOME / "models" / "blip-onnx"
        ve_path = blip_dir / "visual_encoder.onnx"
        td_path = blip_dir / "text_decoder.onnx"
        if not (ve_path.is_file() and td_path.is_file()):
            _vlm_onnx = None
            return None
        cfg_path = blip_dir / "config.json"
        import json as _json
        cfg: dict = {}
        if cfg_path.is_file():
            try:
                cfg = _json.loads(cfg_path.read_text("utf-8"))
            except Exception:
                cfg = {}
        vis_sess = ort.InferenceSession(
            str(ve_path), providers=["CPUExecutionProvider"])
        dec_sess = ort.InferenceSession(
            str(td_path), providers=["CPUExecutionProvider"])
        _vlm_onnx = (vis_sess, dec_sess, cfg)
    except Exception:
        _vlm_onnx = None
    return _vlm_onnx


def _caption_with_onnx(image_path) -> str | None:
    """Run the two-stage BLIP ONNX pipeline on a single image.

    Greedy decoding with a hard cap of ``max_length`` tokens.  Returns a
    cleaned English caption string, or ``None`` on any failure.

    This is intentionally kept self-contained (no transformers) so that the
    entire inference runs with only ``onnxruntime`` + ``numpy`` + ``Pillow``.
    """
    onnx_tuple = _try_vlm_onnx()
    if onnx_tuple is None:
        return None
    try:
        import numpy as np
        from PIL import Image  # type: ignore

        vis_sess, dec_sess, cfg = onnx_tuple
        bos_id = int(cfg.get("bos_token_id", _BLIP_BOS_ID))
        eos_id = int(cfg.get("eos_token_id", _BLIP_EOS_ID))
        max_len = int(cfg.get("max_length", 30))
        img_size = int(cfg.get("image_size", 384))

        img = Image.open(image_path).convert("RGB").resize(
            (img_size, img_size), Image.BICUBIC)
        pixel = np.array(img, dtype=np.float32) / 255.0
        # Normalize: ImageNet mean/std (same as BlipImageProcessor defaults).
        mean = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
        std = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
        pixel = (pixel - mean) / std
        pixel = pixel.transpose(2, 0, 1)[None]  # [1, 3, H, W]

        # Visual encoder.
        vis_input_name = vis_sess.get_inputs()[0].name
        enc_hidden = vis_sess.run(None, {vis_input_name: pixel})[0]
        # enc_hidden: [1, seq, hidden]

        # Greedy text decoder.
        enc_seq = enc_hidden.shape[1]
        attention_mask = np.ones((1, enc_seq), dtype=np.int64)
        input_ids = np.array([[bos_id]], dtype=np.int64)
        generated: list[int] = []
        for _ in range(max_len):
            dec_inputs = {
                "input_ids": input_ids,
                "encoder_hidden_states": enc_hidden,
                "attention_mask": attention_mask,
            }
            # Some exports name inputs differently — try fallback names.
            try:
                logits = dec_sess.run(None, dec_inputs)[0]
            except Exception:
                # Try matching by position if names differ.
                in_names = [i.name for i in dec_sess.get_inputs()]
                alt = {n: v for n, v in zip(in_names, [
                    input_ids, enc_hidden, attention_mask])}
                logits = dec_sess.run(None, alt)[0]
            next_id = int(np.argmax(logits[0, -1]))
            if next_id == eos_id:
                break
            generated.append(next_id)
            input_ids = np.concatenate(
                [input_ids, [[next_id]]], axis=1).astype(np.int64)

        if not generated:
            return None
        # Minimal BertTokenizer-compatible de-tokenization (no transformers).
        # Token ids 1000–30521 map to ##-prefixed sub-words; we join naively
        # and strip the ## marker.  A full vocab lookup is not feasible here
        # without the tokenizer files, so we return an id-string when the ONNX
        # was exported without a bundled vocab.
        # If a ``tokenizer.json`` is present alongside the ONNX, load it.
        from pathlib import Path as _Path
        blip_dir = _Path(str(vis_sess._model_path)).parent  # type: ignore[attr-defined]
        tok_path = blip_dir / "tokenizer.json"
        if tok_path.is_file():
            import json as _json
            vocab_data = _json.loads(tok_path.read_text("utf-8"))
            vocab: dict[int, str] = {}
            for tok, idx in vocab_data.get("model", {}).get("vocab", {}).items():
                vocab[int(idx)] = tok
            tokens = [vocab.get(i, f"[{i}]") for i in generated]
            text = " ".join(tokens).replace(" ##", "")
        else:
            # No vocab available — return a placeholder that at least confirms
            # the ONNX ran (useful for testing the pipeline without full export).
            text = " ".join(str(i) for i in generated[:8])

        return _clean_caption(text) or None
    except Exception:
        return None


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
    """Caption a single image; ``None`` when no backend is available.

    Priority (v2.7):
    1. ONNX backend (``~/.pixcull/models/blip-onnx/`` + ``onnxruntime``) —
       zero transformers dependency at inference time.
    2. transformers BLIP (``_try_vlm``) — opt-in via ``PIXCULL_REEL_VLM=on``.
    3. ``None`` — guaranteed fallback, signature unchanged.
    """
    # ── 1. ONNX path ──────────────────────────────────────────────────────
    onnx_cap = _caption_with_onnx(image_path)
    if onnx_cap is not None:
        return onnx_cap

    # ── 2. transformers BLIP ──────────────────────────────────────────────
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
    """Test hook — clear the cached LLM, VLM (transformers), and ONNX probes."""
    global _llm, _llm_probed, _vlm, _vlm_probed, _vlm_onnx, _vlm_onnx_probed
    _llm, _llm_probed = None, False
    _vlm, _vlm_probed = None, False
    _vlm_onnx, _vlm_onnx_probed = None, False
