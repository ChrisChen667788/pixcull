"""ModelScope Studio entry point — single-image PixCull demo.

This is the *lite* version that runs comfortably on ModelScope's free
CPU Studio tier. It accepts one uploaded image, runs the auto rubric
scoring pipeline (no rescorer, no faces, no GPS clustering — those
need a batch + train history to be meaningful), and renders the
6-axis verdict + V5.2 advice envelope.

The full PixCull experience — batch scoring, XMP / IPTC export,
Lightroom plugin, iOS swipe companion, tether mode — is at
https://github.com/ChrisChen667788/pixcull.

To deploy this Studio:
    1. Upload this directory to a ModelScope Studio repo
    2. Add requirements.txt + this file at the repo root
    3. ModelScope auto-detects gradio entry points and serves :7860

Local test:
    python app.py
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import gradio as gr

# Lazy import so the cold-start cost is only paid on first inference
# (matters for ModelScope's free tier "spin-up on first request" model).
_PIPELINE_READY = False


def _ensure_pipeline() -> None:
    global _PIPELINE_READY
    if _PIPELINE_READY:
        return
    # These pull in CLIP / aesthetic / MediaPipe / etc. — ~500 MB
    # download on first call, cached afterwards.
    import pixcull.pipeline.worker  # noqa: F401
    _PIPELINE_READY = True


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


def cull_one_image(image) -> tuple[str, str, str]:
    """Score a single image. Returns (verdict_markdown, axes_markdown, raw_json)."""
    if image is None:
        return "请先上传一张照片。", "", "{}"

    _ensure_pipeline()
    from pixcull.pipeline.worker import analyze_one
    from pixcull.scoring.photo_advice import build_advice

    # Gradio gives us a numpy array; persist to a temp file so analyze_one
    # can use the existing path-based pipeline without modification.
    import numpy as np
    from PIL import Image
    arr = np.asarray(image)
    pil = Image.fromarray(arr)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as fh:
        pil.save(fh.name, "JPEG", quality=95)
        path = Path(fh.name)

    try:
        result = analyze_one(path)
    finally:
        try:
            path.unlink()
        except OSError:
            pass

    if result is None:
        return "无法解析这张照片(可能格式不支持)。", "", "{}"

    # Build advice from the per-axis stars + raw metrics
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

    # Pretty verdict block
    badge_color = {"keep": "🟢", "maybe": "🟡", "cull": "🔴"}.get(decision, "⚪")
    verdict_md = (
        f"## {badge_color} {decision.upper()}\n\n"
        f"**场景**: {scene}  ·  **综合分**: {result.get('score_final', 0):.2f}\n\n"
    )
    if advice and advice.get("verdict_short"):
        verdict_md += f"> {advice['verdict_short']}\n\n"

    # Axis table
    axes_md = "### 6 维评分\n\n| 维度 | 评分 |\n|---|---|\n"
    for name, label in _AXIS_LABELS.items():
        axes_md += f"| {label} | {_format_stars(rubric[name])} |\n"

    # Strengths + suggestions
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


with gr.Blocks(
    title="PixCull — AI 选片",
    theme=gr.themes.Soft(primary_hue="blue"),
    css="""
        .verdict-box h2 { font-size: 28px; margin-top: 0; }
        footer { display: none; }
    """,
) as demo:
    gr.Markdown(
        """
# PixCull · AI 选片实时体验 · v0.8

> 本地优先的摄影师 AI 选片工具 — 上传一张照片,30 秒内得到 6 维评分 + 建议。
> 完整版本(批量 + Lr 同步 + 协作 + iOS 伴侣 + 风格 clone)请到
> [github.com/ChrisChen667788/pixcull](https://github.com/ChrisChen667788/pixcull) 部署。

**v0.8 完整版包含**(本 Studio 只展示单张评分,以节省 ModelScope 算力):

- 🪣 **批量 6 维评分** + 连拍峰值识别 + 人脸 / GPS 聚类
- 🎨 **风格 clone V2** — 给 5-20 张你以前 keep 的,学你的个人风格(CLIP centroid)
- 📡 **Tethered live** + **LAN 协作** — 二摄 / 编辑实时同步标注
- 🔗 **客户分享链接 + QR 码** — 客户扫码即看 keeps,无需安装
- ⌨️ **Photo Mechanic 级键盘** + hold-Space cheat sheet
- 📐 **LR Library + Develop 风格 UX** — 左侧 8 组可折叠 filter + 右侧 9 段 Inspector
- 🌐 **中 / EN / 日 三语切换**
- 📤 **XMP / DNG / 结构化 CSV / JSON 导出** — Lr / C1 兼容
- 💾 **5k+ 张稳定** — IndexedDB · 0 上传 · MIT 开源
        """
    )
    with gr.Row():
        with gr.Column(scale=1):
            image_in = gr.Image(
                type="numpy",
                label="上传一张照片",
                sources=["upload", "clipboard"],
                height=480,
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

    gr.Examples(
        examples=[],
        inputs=image_in,
        label="示例",
    )

    run_btn.click(
        fn=cull_one_image,
        inputs=[image_in],
        outputs=[verdict_out, axes_out, raw_out],
    )

    gr.Markdown(
        """
---

#### 关于 PixCull v0.8

PixCull 是一个本地优先的摄影师 AI 选片工具。在你的电脑上跑,
照片永远不上传。Apache-2 开源:
[github.com/ChrisChen667788/pixcull](https://github.com/ChrisChen667788/pixcull)

v0.7 + v0.8 共 22 个 slice 已发布(charter trail 在
`docs/ROADMAP-v0.4-charter.md` → `-v0.7-` → `-v0.8-`)。新功能包括
风格 clone V2(CLIP)、LAN 协作、tethered live、客户分享 QR、
i18n(zh/en/ja)、loupe RGB 读数、hold-Space cheat sheet 等。

97 个 unit test 全过。如果觉得有用,在 GitHub 点个 ⭐ 是单人项目
持续打磨下去的最大动力。
        """
    )


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
