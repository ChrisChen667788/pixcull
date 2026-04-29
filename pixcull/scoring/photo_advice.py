"""V5.2 actionable photography advice — turns scores into next-steps.

Most existing critique tools tell you a photo is bad. They rarely tell
you *why* and *how to do better next time*. This module produces a
concise, photographer-friendly verdict for each image based on:

* The 6-axis rubric stars (auto / model / VLM / meta — final priority)
* Specific failed canon checks (V5.1 metrics)
* The meta-judge's inconsistencies array

Output shape
============

  {
    "verdict_short":  "光线漂亮但主体不明确,留待后期裁切",
    "strengths":      ["光线柔和,Zone IX 保留纹理", "构图对称漂亮"],
    "weaknesses":     ["主体不清晰", "高光剪切 18% 过多"],
    "suggestions":    [
      "下次:让主体占画面 30% 以上",
      "拍摄时用 -1 EV 保护高光,后期再提阴影"
    ],
    "verdict": "keep" | "maybe" | "cull",
  }

The strings are user-facing Chinese suitable for showing in the demo's
results card without further processing.

This module is pure synthesis — no model calls, no I/O. Given a row
dict and the rubric stars, it deterministically picks 1-3 strengths,
1-3 weaknesses, and 1-2 suggestions. Designed to be cheap enough to
run on every row of every results page render.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Strength templates: how to praise a high score on each axis.
# Per-axis a dict of {metric_check: phrase}; if the metric value passes
# the threshold we get the phrase. The first 1-2 matches per axis bubble
# up to ``strengths``.
# ---------------------------------------------------------------------------

STRENGTH_TEMPLATES = {
    "technical": [
        # (metric, threshold, comparison, phrase)
        ("canon_zone_clip_pct", 0.02, "<=",
         "曝光精准,几乎无 Zone 0/X 剪切"),
        ("canon_midgray_offset", 0.05, "<=",
         "Zone V 中灰锚定准确"),
        ("laplacian_subject", 200, ">=",
         "主体锐利,焦平面到位"),
        ("score_sharpness", 0.9, ">=",
         "锐度极佳"),
    ],
    "subject": [
        ("subject_fraction", 0.25, ">=",
         "主体占画 30%+,视觉锚点稳"),
        ("face_count", 1, ">=",
         "人物清晰 + 表情可读"),
    ],
    "composition": [
        ("canon_thirds_concentration", 0.55, ">=",
         "三分法构图严谨"),
        ("canon_lead_room", 0.7, ">=",
         "Lead Room 充足,视线方向有空间"),
        ("canon_figure_ground", 0.7, ">=",
         "Figure-ground 对比强,主体跳出背景"),
        ("canon_symmetry", 0.85, ">=",
         "对称构图严谨(几何感强)"),
        ("canon_diagonal_energy", 0.40, ">=",
         "对角线 / S-曲线引导有力"),
        ("canon_balance", 0.75, ">=",
         "九宫格视觉权重均衡"),
    ],
    "light": [
        ("canon_zone_clip_pct", 0.02, "<=",
         "Zone IX 高光保留细节"),
        ("score_exposure", 0.9, ">=",
         "光线层次完整,光比合理"),
    ],
    "moment": [
        ("face_max_blink", 0.3, "<=",
         "表情自然,眼睛清晰"),
    ],
    "aesthetic": [
        ("laion_aes", 6.5, ">=",
         "美学评分高,色彩协调有记忆点"),
        ("clipiqa", 0.7, ">=",
         "图像质量评分顶级"),
    ],
}


# ---------------------------------------------------------------------------
# Weakness templates: triggered by failed canon checks.
# Each tuple: (metric, threshold, comparison, weakness_phrase, fix_phrase).
# ---------------------------------------------------------------------------

WEAKNESS_TEMPLATES = {
    "technical": [
        ("canon_zone_clip_pct", 0.10, ">=",
         "高光 / 阴影剪切严重(>10% 像素在 Zone 0/X)",
         "用 -1 EV 保护高光,RAW 后期提阴影"),
        ("laplacian_subject", 60, "<=",
         "主体不够锐(可能轻度抖动或脱焦)",
         "提高快门速度至 1/(2×焦距) 或加大光圈"),
        ("highlight_clip_pct", 0.08, ">=",
         "局部高光过曝",
         "下次开高光警告,降 EV 或用 ND 滤镜"),
    ],
    "subject": [
        ("subject_fraction", 0.05, "<=",
         "主体在画幅中占比过小",
         "走近一步或后期适度裁切提升主体比重"),
        ("subject_fraction", 0.85, ">=",
         "主体过满,缺乏负空间",
         "下次后退一步,留呼吸空间"),
    ],
    "composition": [
        ("horizon_tilt_deg_abs", 3.0, ">=",
         "地平线倾斜超过 3°",
         "拍摄时打开水平仪;后期一键拉直"),
        ("canon_figure_ground", 0.30, "<=",
         "Figure-ground 对比弱,主体融在背景里",
         "找暗背景或浅景深隔离主体"),
        ("canon_thirds_concentration", 0.30, "<=",
         "构图过于居中,缺乏三分法张力",
         "把主体移到 1/3 线交点附近"),
    ],
    "light": [
        ("canon_zone_clip_pct", 0.10, ">=",
         "光比过大,Zone 0/X 都有像素堆积",
         "加补光或 HDR 包围;后期分别提阴影/压高光"),
    ],
    "moment": [
        ("face_max_blink", 0.7, ">=",
         "可能在闭眼瞬间",
         "连拍 + 选眼最亮帧"),
    ],
    "aesthetic": [
        ("laion_aes", 4.0, "<=",
         "美学评分偏低,色彩 / 构图 / 情绪有改进空间",
         "考虑后期调色或再裁切构图"),
    ],
}


def _read(row: dict[str, Any], key: str) -> float | None:
    if key == "horizon_tilt_deg_abs":
        v = row.get("horizon_tilt_deg")
        if v is None:
            return None
        try:
            return abs(float(v))
        except (TypeError, ValueError):
            return None
    v = row.get(key)
    if v is None:
        return None
    try:
        x = float(v)
        if x != x:
            return None
        return x
    except (TypeError, ValueError):
        return None


def _passes(value: float, threshold: float, op: str) -> bool:
    if op == ">=":
        return value >= threshold
    if op == "<=":
        return value <= threshold
    if op == ">":
        return value > threshold
    if op == "<":
        return value < threshold
    return False


def _collect_strengths(row: dict, axis_stars: dict[str, float | None],
                        max_total: int = 3) -> list[str]:
    """Pull strength phrases for axes that scored 4★+."""
    out: list[str] = []
    for axis_name, stars in axis_stars.items():
        if stars is None or stars < 4.0:
            continue
        for metric, thresh, op, phrase in STRENGTH_TEMPLATES.get(axis_name, []):
            v = _read(row, metric)
            if v is None:
                continue
            if _passes(v, thresh, op):
                out.append(phrase)
                if len(out) >= max_total:
                    return out
                break  # only one strength per axis
    return out


def _collect_weaknesses(row: dict, axis_stars: dict[str, float | None],
                         max_total: int = 3) -> list[tuple[str, str]]:
    """Pull (weakness, fix) pairs for axes that scored 3★ or below."""
    out: list[tuple[str, str]] = []
    for axis_name, stars in axis_stars.items():
        if stars is None or stars > 3.0:
            continue
        for metric, thresh, op, weak, fix in WEAKNESS_TEMPLATES.get(axis_name, []):
            v = _read(row, metric)
            if v is None:
                continue
            if _passes(v, thresh, op):
                out.append((weak, fix))
                if len(out) >= max_total:
                    return out
                break  # one weakness per axis
    return out


def build_advice(
    row: dict[str, Any],
    final_stars: dict[str, float | None],
    decision: str,
    meta_inconsistencies: str = "",
) -> dict[str, Any]:
    """Produce the user-facing advice payload for one image.

    ``final_stars``: the merged 6-axis stars (human → meta → vlm → model → auto)
                     used by ``serve_demo._build_results``.
    ``decision``:    final keep/maybe/cull from the orchestrator.
    ``meta_inconsistencies``: the meta-judge's pipe-joined warning string.
    """
    strengths = _collect_strengths(row, final_stars)
    weak_pairs = _collect_weaknesses(row, final_stars)
    weaknesses = [w for w, _ in weak_pairs]
    suggestions = [f for _, f in weak_pairs]

    # Build a 1-line verdict summary.
    if decision == "keep":
        head = "保留 ✓"
    elif decision == "cull":
        head = "建议剔除 ✗"
    else:
        head = "待定"

    bits = []
    if strengths:
        bits.append(f"亮点: {strengths[0]}")
    if weaknesses:
        bits.append(f"弱点: {weaknesses[0]}")
    verdict_short = head + (" — " + "; ".join(bits) if bits else "")

    # Surface meta inconsistencies as a separate field — they're often
    # the most actionable signal for borderline images.
    inc_list: list[str] = []
    if meta_inconsistencies:
        inc_list = [
            x.strip() for x in meta_inconsistencies.split(" | ")
            if x.strip()
        ][:3]

    return {
        "verdict_short": verdict_short,
        "verdict": decision,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "suggestions": suggestions,
        "inconsistencies": inc_list,
    }
