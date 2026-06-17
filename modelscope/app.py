"""ModelScope Studio entry point — PixCull v2.8 live demo.

Two surfaces, one editorial-warm page:

  1. **单张评分** — upload one image, run the auto rubric pipeline
     (no rescorer / faces / GPS clustering — those need a batch +
     train history), render the 6-axis verdict + advice envelope.
  2. **双语镜头字幕 (VLM)** — caption the uploaded frame in English
     (BLIP — self-hosted ONNX if present, else transformers) and
     Chinese.  The Chinese half mirrors the desktop product's
     ``reel_caption`` path: it prefers the local GGUF LLM rewrite, then
     falls back to an ``opus-mt-en-zh`` machine translation (so the free
     CPU Studio still shows real Chinese), then — only if both backends
     are absent — to the English itself, clearly labelled.

The page itself wears the v2.8 **OKLCH tri-variable palette**
(``--base`` espresso · ``--accent`` brass · ``--contrast`` cream → every
surface derived via ``oklch(from var(--base) calc(l ± δ) c h)``), with a
hex fallback for browsers without relative-color OKLCH.  A small swatch
strip renders the system so the colour story is visible on the page.

The full PixCull experience — batch scoring, video reel culling, XMP /
IPTC export, Lightroom plugin, iOS swipe companion, tether mode — is at
https://github.com/ChrisChen667788/pixcull.

To deploy this Studio:
    1. Upload this directory to a ModelScope Studio repo
    2. Add requirements.txt + this file at the repo root
    3. ModelScope auto-detects gradio entry points and serves :7860

Local test:
    python app.py
"""
from __future__ import annotations

import os

# The bilingual caption demo needs the transformers BLIP path, which is
# OPT-IN in reel_caption (a captioning VLM is a ~1 GB download).  Enable
# it BEFORE importing pixcull so the module-level gate is read as "on".
os.environ.setdefault("PIXCULL_REEL_VLM", "on")

import html
import json
import tempfile
from pathlib import Path

import gradio as gr


# ════════════════════════════════════════════════════════════════════
#  v2.8 editorial-warm palette  (hex fallbacks of the OKLCH tokens)
# ════════════════════════════════════════════════════════════════════
ESPRESSO   = "#161310"   # --base   ground            oklch(0.189 .0077 77)
CARD       = "#1e1a14"   # base + 0.031 L
CARD_HI    = "#272118"   # base + 0.062 L
SURFACE_3  = "#322a1e"   # base + 0.101 L
CHROME     = "#100d0a"   # base − 0.030 L
BRASS      = "#c4b9a9"   # --accent film ochre        oklch(0.791 .0254 77)
BRASS_HI   = "#d8cebf"   # accent + 0.064 L
BRASS_DEEP = "#6a6052"   # gradient tail
CREAM      = "#f3ede1"   # --contrast primary text    oklch(0.937 .0135 80)
FG_2       = "#d3c9b6"   # secondary text
MUTED      = "#a89d88"
BORDER     = "#2b241a"
BORDER_HI  = "#3a3122"
C_KEEP     = "#6faa78"   # sage
C_MAYBE    = "#d6a443"   # ochre-amber
C_CULL     = "#cf6f5b"   # terracotta
C_INFO     = "#6ea2b0"   # muted teal-slate


# A warm brass ramp so Gradio's own primary controls (buttons, focus
# rings, sliders) inherit the editorial-warm accent instead of blue.
_BRASS = gr.themes.Color(
    c50="#f6f1e8", c100="#ece3d4", c200="#ddd1bd", c300="#c4b9a9",
    c400="#ab9f8c", c500="#8f8470", c600="#6a6052", c700="#4f473b",
    c800="#352f27", c900="#211d17", c950="#161310", name="brass",
)
# A warm espresso/taupe neutral ramp (Gradio's greys → warm, not cold).
_TAUPE = gr.themes.Color(
    c50="#f3ede1", c100="#e6dccb", c200="#cabfa9", c300="#a89d88",
    c400="#7d7361", c500="#5a5246", c600="#3a3122", c700="#2b241a",
    c800="#1e1a14", c900="#161310", c950="#100d0a", name="taupe",
)

THEME = gr.themes.Base(
    primary_hue=_BRASS,
    neutral_hue=_TAUPE,
    font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui",
          "-apple-system", "Segoe UI", "PingFang SC",
          "Microsoft YaHei", "sans-serif"],
    font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace",
               "SFMono-Regular", "monospace"],
).set(
    # Force the espresso ground in BOTH light- and dark-mode slots so the
    # Studio always renders editorial-warm regardless of the viewer's
    # system preference.
    body_background_fill=ESPRESSO,
    body_background_fill_dark=ESPRESSO,
    background_fill_primary=CARD,
    background_fill_primary_dark=CARD,
    background_fill_secondary=CARD_HI,
    background_fill_secondary_dark=CARD_HI,
    body_text_color=CREAM,
    body_text_color_dark=CREAM,
    body_text_color_subdued=MUTED,
    body_text_color_subdued_dark=MUTED,
    border_color_primary=BORDER,
    border_color_primary_dark=BORDER,
    block_background_fill=CARD,
    block_background_fill_dark=CARD,
    block_border_color=BORDER,
    block_border_color_dark=BORDER,
    block_label_background_fill=CARD_HI,
    block_label_text_color=FG_2,
    block_label_text_color_dark=FG_2,
    block_title_text_color=CREAM,
    block_title_text_color_dark=CREAM,
    input_background_fill=CARD_HI,
    input_background_fill_dark=CARD_HI,
    input_border_color=BORDER,
    panel_background_fill=CARD,
    panel_background_fill_dark=CARD,
    button_primary_background_fill=f"linear-gradient(135deg, {BRASS} 0%, {BRASS_DEEP} 100%)",
    button_primary_background_fill_dark=f"linear-gradient(135deg, {BRASS} 0%, {BRASS_DEEP} 100%)",
    button_primary_text_color=ESPRESSO,
    button_primary_text_color_dark=ESPRESSO,
    button_secondary_background_fill=CARD_HI,
    button_secondary_background_fill_dark=CARD_HI,
    button_secondary_text_color=CREAM,
    button_secondary_text_color_dark=CREAM,
    button_secondary_border_color=BORDER_HI,
    link_text_color=BRASS_HI,
    link_text_color_dark=BRASS_HI,
)

# Progressive-enhancement CSS: real OKLCH relative-color where supported
# (Chrome 111+, Safari 16.4+), hex fallback everywhere else.  Also styles
# the custom showcase swatches + bilingual caption cards.
CUSTOM_CSS = f"""
:root {{
    --pc-base:     {ESPRESSO};
    --pc-card:     {CARD};
    --pc-card-hi:  {CARD_HI};
    --pc-surf3:    {SURFACE_3};
    --pc-accent:   {BRASS};
    --pc-accent-hi:{BRASS_HI};
    --pc-contrast: {CREAM};
    --pc-fg2:      {FG_2};
    --pc-muted:    {MUTED};
    --pc-border:   {BORDER};
}}
@supports (color: oklch(from white l c h)) {{
    :root {{
        --pc-base:      oklch(0.189 0.0077 77);
        --pc-accent:    oklch(0.791 0.0254 77);
        --pc-contrast:  oklch(0.937 0.0135 80);
        --pc-card:      oklch(from var(--pc-base) calc(l + 0.031) c h);
        --pc-card-hi:   oklch(from var(--pc-base) calc(l + 0.062) c h);
        --pc-surf3:     oklch(from var(--pc-base) calc(l + 0.101) c h);
        --pc-accent-hi: oklch(from var(--pc-accent) calc(l + 0.064) c h);
    }}
}}
.gradio-container {{ max-width: 1100px !important; }}
footer {{ display: none !important; }}
.verdict-box h2 {{ font-size: 28px; margin-top: 0; letter-spacing: -0.01em; }}

/* —— OKLCH palette showcase strip —— */
.pc-palette {{ display:flex; flex-wrap:wrap; gap:10px; margin:6px 0 2px; }}
.pc-swatch {{
    flex:1 1 110px; min-width:96px; border-radius:12px;
    border:1px solid var(--pc-border); padding:14px 12px 12px;
    font-size:11px; line-height:1.35; letter-spacing:.01em;
    box-shadow:0 1px 0 rgba(0,0,0,.25) inset;
}}
.pc-swatch b {{ display:block; font-size:12px; margin-bottom:2px; }}
.pc-swatch code {{ font-size:10px; opacity:.8; }}
.pc-sw-base    {{ background:var(--pc-base);     color:var(--pc-contrast); }}
.pc-sw-card    {{ background:var(--pc-card);     color:var(--pc-contrast); }}
.pc-sw-cardhi  {{ background:var(--pc-card-hi);  color:var(--pc-contrast); }}
.pc-sw-surf3   {{ background:var(--pc-surf3);    color:var(--pc-contrast); }}
.pc-sw-accent  {{ background:var(--pc-accent);   color:var(--pc-base); }}
.pc-sw-accenthi{{ background:var(--pc-accent-hi);color:var(--pc-base); }}
.pc-sw-contrast{{ background:var(--pc-contrast); color:var(--pc-base); }}

/* —— bilingual caption cards —— */
.pc-cap-wrap {{ display:flex; flex-direction:column; gap:12px; }}
.pc-cap {{
    border:1px solid var(--pc-border); border-radius:14px;
    background:var(--pc-card-hi); padding:16px 18px;
    position:relative; overflow:hidden;
}}
.pc-cap::before {{
    content:""; position:absolute; left:0; top:0; bottom:0; width:4px;
    background:linear-gradient(180deg, {BRASS} 0%, {BRASS_DEEP} 100%);
}}
.pc-cap .pc-lang {{
    font-size:11px; text-transform:uppercase; letter-spacing:.08em;
    color:var(--pc-muted); margin-bottom:6px; display:flex;
    align-items:center; gap:8px;
}}
.pc-cap .pc-line {{ font-size:19px; line-height:1.5; color:var(--pc-contrast); }}
.pc-cap-zh .pc-line {{ font-size:21px; }}
.pc-badge {{
    display:inline-block; font-size:10px; letter-spacing:.04em;
    padding:2px 8px; border-radius:999px; border:1px solid var(--pc-border);
    background:var(--pc-card); color:var(--pc-fg2);
}}
.pc-note {{ font-size:12px; color:var(--pc-muted); margin-top:2px; }}
"""


# ════════════════════════════════════════════════════════════════════
#  Lazy backends
# ════════════════════════════════════════════════════════════════════
_PIPELINE_READY = False


def _ensure_pipeline() -> None:
    global _PIPELINE_READY
    if _PIPELINE_READY:
        return
    # These pull in CLIP / aesthetic / MediaPipe / etc. — ~500 MB
    # download on first call, cached afterwards.
    import pixcull.pipeline.worker  # noqa: F401
    _PIPELINE_READY = True


# opus-mt-en-zh — the Studio's Chinese-rewrite fallback when the desktop
# product's local GGUF LLM isn't mounted.  Lazy + fail-soft: any import /
# load error leaves Chinese gracefully degraded to the English text.
_OPUS = {"pipe": None, "probed": False}


def _studio_translate_zh(en_text: str) -> tuple[str, str]:
    """Translate the BLIP English caption to Chinese via opus-mt.

    Returns ``(text, backend_label)``.  On any failure returns the
    English unchanged with a label that says so — the demo never invents
    Chinese it didn't actually produce.
    """
    if _OPUS["probed"] and _OPUS["pipe"] is None:
        return en_text, "回退英文(opus-mt 未就绪)"
    if _OPUS["pipe"] is None:
        _OPUS["probed"] = True
        try:
            from transformers import pipeline
            _OPUS["pipe"] = pipeline(
                "translation", model="Helsinki-NLP/opus-mt-en-zh")
        except Exception:
            _OPUS["pipe"] = None
            return en_text, "回退英文(opus-mt 未就绪)"
    try:
        out = _OPUS["pipe"](en_text, max_length=80)
        zh = (out[0].get("translation_text") or "").strip()
        if zh and any("一" <= c <= "鿿" for c in zh):
            return zh, "opus-mt 机器翻译"
    except Exception:
        pass
    return en_text, "回退英文(opus-mt 未就绪)"


_AXIS_LABELS = {
    "technical":   "技术",
    "subject":     "主体",
    "composition": "构图",
    "light":       "光线",
    "moment":      "瞬间",
    "aesthetic":   "美感",
}


def _format_stars(stars: float | None) -> str:
    if stars is None:
        return "—"
    s = max(1, min(5, round(stars)))
    return "★" * s + "☆" * (5 - s) + f"  ({stars:.1f})"


# ════════════════════════════════════════════════════════════════════
#  Surface 1 — single-image rubric scoring
# ════════════════════════════════════════════════════════════════════
def _persist_upload(image) -> Path:
    """Gradio gives us a numpy array; persist to a temp JPG so the
    existing path-based pipeline can consume it unmodified."""
    import numpy as np
    from PIL import Image
    arr = np.asarray(image)
    pil = Image.fromarray(arr)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as fh:
        pil.save(fh.name, "JPEG", quality=95)
        return Path(fh.name)


def cull_one_image(image) -> tuple[str, str, str]:
    """Score a single image. Returns (verdict_markdown, axes_markdown, raw_json)."""
    if image is None:
        return "请先上传一张照片。", "", "{}"

    _ensure_pipeline()
    from pixcull.pipeline.worker import analyze_one
    from pixcull.scoring.photo_advice import build_advice

    path = _persist_upload(image)
    try:
        result = analyze_one(path)
    finally:
        try:
            path.unlink()
        except OSError:
            pass

    if result is None:
        return "无法解析这张照片(可能格式不支持)。", "", "{}"

    rubric = {
        name: result.get(f"rubric_{name}_stars")
        for name in _AXIS_LABELS
    }
    decision = result.get("decision") or "maybe"
    scene = result.get("scene") or "unknown"
    advice = build_advice(
        row=result,
        final_stars=rubric,
        decision=decision,
        meta_inconsistencies="",
        idx=0,
        vertical=None,
    )

    badge_color = {"keep": "🟢", "maybe": "🟡", "cull": "🔴"}.get(decision, "⚪")
    verdict_md = (
        f"## {badge_color} {decision.upper()}\n\n"
        f"**场景**: {scene}  ·  **综合分**: {result.get('score_final', 0):.2f}\n\n"
    )
    if advice and advice.get("verdict_short"):
        verdict_md += f"> {advice['verdict_short']}\n\n"

    axes_md = "### 6 维评分\n\n| 维度 | 评分 |\n|---|---|\n"
    for name, label in _AXIS_LABELS.items():
        axes_md += f"| {label} | {_format_stars(rubric[name])} |\n"

    if advice:
        strengths = advice.get("strengths") or []
        suggestions = advice.get("suggestions") or []
        if strengths:
            axes_md += "\n### 优点\n\n"
            for s in strengths[:4]:
                axes_md += f"- ✓ {s}\n"
        if suggestions:
            axes_md += "\n### 改进建议\n\n"
            for s in suggestions[:4]:
                axes_md += f"- → {s}\n"

    raw = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    return verdict_md, axes_md, raw


# ════════════════════════════════════════════════════════════════════
#  Surface 2 — bilingual VLM caption (feature shipped v2.7)
# ════════════════════════════════════════════════════════════════════
def _caption_card(zh: str, en: str, zh_backend: str, en_backend: str) -> str:
    # Caption text is model-generated (BLIP / opus-mt), not user free-text,
    # but it lands in gr.HTML as raw markup — escape so a stray '<' / '&'
    # in a caption can never break the card layout.
    zh, en = html.escape(zh), html.escape(en)
    zh_backend, en_backend = html.escape(zh_backend), html.escape(en_backend)
    return (
        '<div class="pc-cap-wrap">'
        '  <div class="pc-cap pc-cap-zh">'
        '    <div class="pc-lang">🇨🇳 中文'
        f'      <span class="pc-badge">{zh_backend}</span></div>'
        f'    <div class="pc-line">{zh}</div>'
        '  </div>'
        '  <div class="pc-cap pc-cap-en">'
        '    <div class="pc-lang">🇬🇧 English'
        f'      <span class="pc-badge">{en_backend}</span></div>'
        f'    <div class="pc-line">{en}</div>'
        '  </div>'
        '</div>'
    )


def caption_one_image(image) -> str:
    """Caption the uploaded frame bilingually, mirroring the desktop
    product's reel_caption path (EN via BLIP, ZH via LLM→opus-mt→EN)."""
    if image is None:
        return '<div class="pc-note">请先上传一张照片。</div>'

    from pixcull.scoring import reel_caption as rc

    path = _persist_upload(image)
    try:
        en = rc.vlm_caption_from_image(path)
    finally:
        try:
            path.unlink()
        except OSError:
            pass

    if not en:
        return (
            '<div class="pc-cap"><div class="pc-line">VLM 后端未就绪。</div>'
            '<div class="pc-note">Studio 首次会下载 BLIP-base(~1GB);'
            '若反复失败,说明该 Studio 实例算力/网络受限 —— '
            '完整版在本地一次预热后稳定可用。</div></div>'
        )

    # English backend badge: self-hosted ONNX export wins when present.
    en_backend = "self-hosted ONNX (BLIP)" if rc._try_vlm_onnx() else "transformers BLIP"

    # Chinese: prefer the product's local-LLM rewrite, then opus-mt, then
    # the English itself — each path honestly labelled.
    zh = rc._zh_rewrite(en)
    if zh:
        zh_backend = "本地 LLM 改写"
    else:
        zh, zh_backend = _studio_translate_zh(en)

    return _caption_card(zh, en, zh_backend, en_backend)


# ════════════════════════════════════════════════════════════════════
#  Page
# ════════════════════════════════════════════════════════════════════
_PALETTE_HTML = """
<div class="pc-palette">
  <div class="pc-swatch pc-sw-base"><b>--base</b>espresso<br><code>oklch(.189 .008 77)</code></div>
  <div class="pc-swatch pc-sw-card"><b>+0.031 L</b>card<br><code>derived surface</code></div>
  <div class="pc-swatch pc-sw-cardhi"><b>+0.062 L</b>card-hi<br><code>derived surface</code></div>
  <div class="pc-swatch pc-sw-surf3"><b>+0.101 L</b>surface-3<br><code>derived surface</code></div>
  <div class="pc-swatch pc-sw-accent"><b>--accent</b>brass<br><code>oklch(.791 .025 77)</code></div>
  <div class="pc-swatch pc-sw-accenthi"><b>+0.064 L</b>accent-hi<br><code>derived accent</code></div>
  <div class="pc-swatch pc-sw-contrast"><b>--contrast</b>cream<br><code>oklch(.937 .014 80)</code></div>
</div>
"""

with gr.Blocks(title="PixCull — AI 选片 · v2.8", theme=THEME, css=CUSTOM_CSS) as demo:
    gr.Markdown(
        """
# PixCull · AI 选片实时体验 · v2.8

> 本地优先的摄影师 / 视频博主 AI 选片工具 — 上传一张照片,得到 6 维评分 + 建议,
> 或生成一句**双语镜头字幕**。完整版本(批量 + 视频抽帧选 reel + Lr 同步 +
> iOS 伴侣 + 风格 clone)请到
> [github.com/ChrisChen667788/pixcull](https://github.com/ChrisChen667788/pixcull) 部署。

**v2.4 → v2.8 完整版新增**(本 Studio 展示单张评分 + 双语字幕,以节省 ModelScope 算力):

- 🎬 **视频选片 + reel 自动剪辑** — 抽帧打分 + 连贯片段检测 + EDL/竖屏导出
- 💬 **双语 VLM 镜头字幕** — BLIP 描述最佳帧,中英双语(可自托管 ONNX,零 transformers 推理)
- 🪞 **跨拍摄去重 + 视频重复帧裁剪**(完整版 CLI) — CLIP / dHash 折叠近似画面,留 hero
- 🎯 **从纠正中学习** — 你改判后写入个人画像,阈值自动微调 + "🎯 已按你调校" 徽标
- ⌨️ **键盘优先 cull 流** + 🔍 **自然语言语义搜索**(CLIP)
- 🎨 **v2.8 OKLCH 三变量配色** — base/accent/contrast 派生全部表面,旧浏览器 hex 兜底
- 📤 **XMP / DNG / CSV / JSON 导出** · 💾 **5k+ 张稳定** · 0 上传 · 开源
        """
    )

    gr.Markdown("#### 🎨 v2.8 OKLCH 配色系统（本页即采用 · 浏览器支持时为真 OKLCH 相对色）")
    gr.HTML(_PALETTE_HTML)

    with gr.Tabs():
        # —— Tab 1: single-image scoring ——
        with gr.Tab("单张评分"):
            with gr.Row():
                with gr.Column(scale=1):
                    image_in = gr.Image(
                        type="numpy",
                        label="上传一张照片",
                        sources=["upload", "clipboard"],
                        height=460,
                    )
                    run_btn = gr.Button("评分", variant="primary", size="lg")
                    gr.Markdown(
                        "*首次评分约 30 秒(预热模型);之后每张 ~3 秒。*"
                    )
                with gr.Column(scale=1):
                    verdict_out = gr.Markdown(elem_classes=["verdict-box"])
                    axes_out = gr.Markdown()
            with gr.Accordion("原始指标(供调试)", open=False):
                raw_out = gr.Code(language="json", lines=20)
            run_btn.click(
                fn=cull_one_image,
                inputs=[image_in],
                outputs=[verdict_out, axes_out, raw_out],
            )

        # —— Tab 2: bilingual VLM caption ——
        with gr.Tab("双语镜头字幕 (VLM)"):
            gr.Markdown(
                "用 **BLIP** 描述这一帧的内容(英文),再改写成中文 —— "
                "这正是完整版里给每个视频 reel 生成双语字幕的同一条链路。\n\n"
                "*首次会下载 BLIP(~1GB);中文优先走本地 LLM 改写,Studio 未挂 LLM 时"
                "回退 opus-mt 机器翻译,徽标会如实标注当前后端。*"
            )
            with gr.Row():
                with gr.Column(scale=1):
                    cap_image_in = gr.Image(
                        type="numpy",
                        label="上传一帧画面",
                        sources=["upload", "clipboard"],
                        height=460,
                    )
                    cap_btn = gr.Button("生成双语字幕", variant="primary", size="lg")
                with gr.Column(scale=1):
                    cap_out = gr.HTML()
            cap_btn.click(
                fn=caption_one_image,
                inputs=[cap_image_in],
                outputs=[cap_out],
            )

    gr.Markdown(
        """
---

#### 关于 PixCull v2.8

PixCull 是一个本地优先的摄影师 / 视频博主 AI 选片工具。在你的电脑上跑,
照片 / 视频永远不上传。开源:
[github.com/ChrisChen667788/pixcull](https://github.com/ChrisChen667788/pixcull)

**双语字幕的后端逻辑**(与桌面版一致,本页如实标注当前用的是哪个):
EN = BLIP(自托管 ONNX 优先,否则 transformers);
ZH = 本地 GGUF LLM 改写 → opus-mt-en-zh 机器翻译 → 英文原文(三级兜底)。
免费 Studio 通常落在 opus-mt 这一级,本地完整版挂上 LLM 后中文更自然。

测试全绿(`python -m pytest tests/`)。如果觉得有用,在 GitHub 点个 ⭐
是单人项目持续打磨下去的最大动力。
        """
    )


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
