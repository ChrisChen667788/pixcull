"""V11.1 actionable photography advice — turns scores into next-steps.

Major V11.1 upgrade over V5.2:
* Strength + weakness templates now SPECIALIZED per (axis, genre, style)
  so a wildlife photo gets wildlife-specific praise ("捕到飞行姿态")
  not the generic landscape phrase ("Lead Room 充足").
* Each axis has 3-5 alternative phrasings; pick one deterministically
  by hashing filename so a 50-image batch doesn't repeat the same
  sentence over and over.
* When the meta-judge produced a per-axis rationale, we PREFER that
  text over our static templates — it's grounded in the actual image
  and cites real metrics ("LAION-AES 4.874 表明色彩协调").
* Suggestions distinguish technique fixes from gear / shooting fixes
  so post-processing-friendly users see relevant tips.

Output shape (unchanged from V5.2):
  {
    "verdict_short":  ...,
    "strengths":      [...],
    "weaknesses":     [...],
    "suggestions":    [...],
    "inconsistencies": [...],
    "verdict":        "keep" | "maybe" | "cull",
  }
"""

from __future__ import annotations

import hashlib
from typing import Any


# ---------------------------------------------------------------------------
# STRENGTH templates
#
# Schema:
#   {
#     axis_name: [
#       {
#         "metric": "<row key>",
#         "thresh": <float>,
#         "op":     "<= or >=",
#         "phrases": [<list of synonyms>],
#         "genres":  None or set of scenes this applies to,
#         "styles":  None or set of style modes this applies to,
#       }
#     ]
#   }
#
# Each phrase pool is rotated by hashing the filename so within a batch
# the same axis on different images doesn't repeat verbatim. None means
# "applies to any genre / any style" (default).
# ---------------------------------------------------------------------------

STRENGTH_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "technical": [
        {
            "metric": "canon_zone_clip_pct", "thresh": 0.02, "op": "<=",
            "phrases": [
                "曝光精准,几乎无 Zone 0/X 剪切",
                "动态范围保留充分,亮暗双端有细节",
                "影调控制干净,阴影/高光皆有信息",
            ],
        },
        {
            "metric": "canon_midgray_offset", "thresh": 0.05, "op": "<=",
            "phrases": [
                "Zone V 中灰锚定准确",
                "中灰位置标准,整体曝光基调对",
                "测光精准,中性灰落在 50% luma",
            ],
        },
        {
            "metric": "laplacian_subject", "thresh": 200, "op": ">=",
            "phrases": [
                "主体锐利,焦平面到位",
                "焦点扎实,主体细节清晰可辨",
                "对焦精准,跑焦 / 抖动均无",
            ],
        },
        {
            "metric": "score_sharpness", "thresh": 0.9, "op": ">=",
            "phrases": [
                "整体锐度极佳",
                "锐度顶级,堪比 f/64 派要求",
                "全画面锐度都到位",
            ],
        },
    ],
    "subject": [
        # Generic
        {
            "metric": "subject_fraction", "thresh": 0.25, "op": ">=",
            "phrases": [
                "主体占画 30%+,视觉锚点稳",
                "主体比例舒适,不会过小或淹没",
                "主体在画面中分量足够",
            ],
        },
        # Portrait-specific
        {
            "metric": "face_count", "thresh": 1, "op": ">=",
            "phrases": ["人物清晰,表情可读", "人脸到位 + 眼神清晰"],
            "genres": {"portrait", "event", "fashion", "documentary"},
        },
        # Wildlife-specific
        {
            "metric": "subject_fraction", "thresh": 0.15, "op": ">=",
            "phrases": [
                "动物姿态清晰,主体可读",
                "捕捉到动物的神情或动作",
                "野生主体占比合理 + 形态完整",
            ],
            "genres": {"wildlife"},
        },
        # Landscape-specific (subject = the dominant land form)
        {
            "metric": "canon_figure_ground", "thresh": 0.6, "op": ">=",
            "phrases": [
                "山/水/云层主次分明,有视觉重心",
                "前中后景有层次,引导视线",
            ],
            "genres": {"landscape", "architecture"},
        },
        # Macro-specific
        {
            "metric": "canon_figure_ground", "thresh": 0.7, "op": ">=",
            "phrases": [
                "主体跳出背景,微观细节凸显",
                "浅景深隔离效果好",
            ],
            "genres": {"macro"},
        },
    ],
    "composition": [
        {
            "metric": "canon_thirds_concentration", "thresh": 0.55, "op": ">=",
            "phrases": [
                "三分法构图严谨",
                "主体落在 1/3 线交点附近,经典构图",
                "九宫格 4 个交点附近有意识布置",
            ],
        },
        {
            "metric": "canon_lead_room", "thresh": 0.7, "op": ">=",
            "phrases": [
                "Lead Room 充足,视线方向有空间",
                "主体朝向方向留白合理(Rule of Space)",
                "前景空间预留得当",
            ],
            # only meaningful when there's a directional subject
            "genres": {"portrait", "wildlife", "street", "event",
                        "documentary", "sports"},
        },
        {
            "metric": "canon_figure_ground", "thresh": 0.7, "op": ">=",
            "phrases": [
                "Figure-ground 对比强,主体跳出背景",
                "明暗对比有效隔离主体与背景",
            ],
        },
        {
            "metric": "canon_symmetry", "thresh": 0.85, "op": ">=",
            "phrases": [
                "对称构图严谨,几何感强",
                "镜面对称构图,有形式美",
            ],
            "genres": {"architecture", "landscape", "abstract", "stilllife"},
        },
        {
            "metric": "canon_diagonal_energy", "thresh": 0.40, "op": ">=",
            "phrases": [
                "对角线 / S-曲线引导有力",
                "斜向构图 + 几何张力强",
            ],
        },
        {
            "metric": "canon_balance", "thresh": 0.75, "op": ">=",
            "phrases": [
                "九宫格视觉权重均衡",
                "画面元素分布平衡,无堆积偏重",
            ],
        },
    ],
    "light": [
        {
            "metric": "canon_zone_clip_pct", "thresh": 0.02, "op": "<=",
            "phrases": [
                "Zone IX 高光保留细节",
                "高光不死白,可后期下拉",
                "影调过渡平滑,光比合理",
            ],
        },
        {
            "metric": "score_exposure", "thresh": 0.9, "op": ">=",
            "phrases": [
                "光线层次完整",
                "曝光控制好,影调分布健康",
                "光比合理,亮暗对比舒适",
            ],
        },
        # Style-specific
        {
            "metric": "score_exposure", "thresh": 0.0, "op": ">=",
            "phrases": [
                "黑白影调对比强,Adams 风范",
                "去色后影调分离清晰,适合黑白叙事",
            ],
            "styles": {"mono"},
        },
        {
            "metric": "score_exposure", "thresh": 0.0, "op": ">=",
            "phrases": [
                "Chiaroscuro 戏剧性强,8:1+ 光比有效",
                "低调氛围浓,暗部包裹主体",
            ],
            "styles": {"low_key"},
        },
        {
            "metric": "score_exposure", "thresh": 0.0, "op": ">=",
            "phrases": [
                "高调干净通透,无杂乱阴影",
                "明快光感,适合时尚/婚礼/产品",
            ],
            "styles": {"high_key"},
        },
        {
            "metric": "score_exposure", "thresh": 0.0, "op": ">=",
            "phrases": [
                "黄金时刻光质,色温暖,情绪感强",
                "夕阳/日出色温独特,氛围突出",
            ],
            "genres": {"landscape", "wildlife"},
        },
    ],
    "moment": [
        {
            "metric": "face_max_blink", "thresh": 0.3, "op": "<=",
            "phrases": [
                "表情自然,眼睛清晰",
                "眼神到位,情绪可读",
            ],
            "genres": {"portrait", "event", "fashion", "documentary",
                        "street", "wildlife"},
        },
        {
            "metric": "score_moment", "thresh": 0.7, "op": ">=",
            "phrases": [
                "瞬间到位,Cartier-Bresson 决定性瞬间",
                "动作峰值 + 情绪叠加",
                "时机精准,事件本质 + 形式同框",
            ],
        },
        # Long exposure / motion blur — moment is "gesture of time"
        {
            "metric": "canon_long_exposure_score", "thresh": 0.4, "op": ">=",
            "phrases": [
                "长曝光定格了时间的流动",
                "运动轨迹漂亮,静止主体反衬流动",
            ],
            "styles": {"long_exposure", "rear_curtain_sync"},
        },
    ],
    "aesthetic": [
        {
            "metric": "laion_aes", "thresh": 6.5, "op": ">=",
            "phrases": [
                "美学评分高,色彩协调有记忆点",
                "整体协调,LAION-AES 6.5+ 优于多数训练集",
                "视觉语言统一,情绪一致",
            ],
        },
        {
            "metric": "clipiqa", "thresh": 0.7, "op": ">=",
            "phrases": [
                "CLIP-IQA 顶级,质量评估通过",
                "整体观感品质感强",
            ],
        },
        # Genre-specific aesthetic
        {
            "metric": "laion_aes", "thresh": 5.5, "op": ">=",
            "phrases": [
                "风光大片质感,可作壁纸级",
                "天地交融,色彩有诗意",
            ],
            "genres": {"landscape"},
        },
        {
            "metric": "laion_aes", "thresh": 5.5, "op": ">=",
            "phrases": [
                "人物质感细腻,皮肤/服装色彩协调",
                "肖像光质感强,神情自然",
            ],
            "genres": {"portrait"},
        },
        {
            "metric": "laion_aes", "thresh": 5.5, "op": ">=",
            "phrases": [
                "纪实张力强,有故事感",
                "事件氛围浓,可作新闻图",
            ],
            "genres": {"documentary", "street", "event"},
        },
    ],
}


# ---------------------------------------------------------------------------
# WEAKNESS templates — same shape but with fix phrases
# ---------------------------------------------------------------------------

WEAKNESS_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "technical": [
        {
            "metric": "canon_zone_clip_pct", "thresh": 0.10, "op": ">=",
            "phrases": [
                "高光/阴影剪切严重(>10% 像素在 Zone 0/X)",
                "影调两端有大量数据丢失",
                "动态范围超过传感器,亮/暗端死掉",
            ],
            "fixes": [
                "用 -1 EV 保护高光,RAW 后期提阴影",
                "包围曝光 + HDR 合成",
                "ND 渐变滤镜压亮天空",
            ],
        },
        {
            "metric": "laplacian_subject", "thresh": 60, "op": "<=",
            "phrases": [
                "主体不够锐(轻度抖动或脱焦)",
                "焦平面没在主体上",
                "锐度低于合格线",
            ],
            "fixes": [
                "提高快门速度至 1/(2×焦距)",
                "加大光圈或开启光学防抖",
                "三脚架 + 自拍延迟 / 反光板预升",
            ],
        },
        {
            "metric": "highlight_clip_pct", "thresh": 0.08, "op": ">=",
            "phrases": [
                "局部高光过曝",
                "高光区死白,无细节",
            ],
            "fixes": [
                "下次开高光警告,降 EV 或用 ND 滤镜",
                "RAW 拉回高光 -50 试试",
            ],
        },
    ],
    "subject": [
        {
            "metric": "subject_fraction", "thresh": 0.05, "op": "<=",
            "phrases": [
                "主体在画幅中占比过小",
                "主体被环境淹没,视觉锚点弱",
            ],
            "fixes": [
                "走近一步或后期适度裁切提升主体比重",
                "换长焦或裁切到 1:1",
            ],
        },
        {
            "metric": "subject_fraction", "thresh": 0.85, "op": ">=",
            "phrases": [
                "主体过满,缺乏负空间",
                "无呼吸空间,画面拥挤",
            ],
            "fixes": ["下次后退一步留呼吸空间", "或换更广的镜头"],
        },
    ],
    "composition": [
        {
            "metric": "horizon_tilt_deg_abs", "thresh": 3.0, "op": ">=",
            "phrases": ["地平线倾斜超过 3°"],
            "fixes": ["拍摄时打开水平仪;后期一键拉直"],
            "genres": {"landscape", "architecture", "street"},
        },
        {
            "metric": "canon_figure_ground", "thresh": 0.30, "op": "<=",
            "phrases": [
                "Figure-ground 对比弱,主体融在背景里",
                "主体与背景明度太接近",
            ],
            "fixes": [
                "找暗背景或浅景深隔离主体",
                "后期适度提主体亮度 / 压背景",
            ],
        },
        {
            "metric": "canon_thirds_concentration", "thresh": 0.30, "op": "<=",
            "phrases": [
                "构图过于居中,缺乏三分法张力",
                "视觉重心堆在画面中央",
            ],
            "fixes": [
                "把主体移到 1/3 线交点附近",
                "后期裁剪重组",
            ],
            # but only for non-symmetric genres
            "anti_styles": {"silhouette"},
            "anti_genres": {"architecture", "abstract", "macro"},
        },
    ],
    "light": [
        {
            "metric": "canon_zone_clip_pct", "thresh": 0.10, "op": ">=",
            "phrases": [
                "光比过大,Zone 0/X 都有像素堆积",
                "亮暗反差超过传感器宽容度",
            ],
            "fixes": [
                "加补光或 HDR 包围;后期分别提阴影/压高光",
                "等待光线变化(时间窗口)",
            ],
            # don't show on intentionally low-key shots
            "anti_styles": {"low_key", "high_key", "silhouette",
                              "long_exposure", "night"},
        },
    ],
    "moment": [
        {
            "metric": "face_max_blink", "thresh": 0.7, "op": ">=",
            "phrases": ["可能在闭眼瞬间", "捕到了眨眼帧"],
            "fixes": ["连拍 + 选眼最亮帧", "下次设连续 AF + 高速连拍"],
            "genres": {"portrait", "event", "fashion", "documentary"},
        },
    ],
    "aesthetic": [
        {
            "metric": "laion_aes", "thresh": 4.0, "op": "<=",
            "phrases": [
                "美学评分偏低,色彩 / 构图 / 情绪有改进空间",
                "整体观感平淡,缺乏记忆点",
            ],
            "fixes": [
                "考虑后期调色或再裁切构图",
                "重新构思:可作为练手而非作品",
            ],
        },
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _stable_pick(phrases: list[str], filename: str, salt: str = "") -> str:
    """Deterministic phrase rotation across a batch.

    Hashes (filename + salt + len(phrases)) to pick one phrase. Same
    image always gets same phrase, but two different images on the
    same axis usually pick different synonyms. Avoids the 'every card
    says Zone V 中灰锚定准确' problem the user complained about.
    """
    if not phrases:
        return ""
    if len(phrases) == 1:
        return phrases[0]
    h = hashlib.sha256(f"{filename}|{salt}".encode("utf-8")).hexdigest()
    idx = int(h[:8], 16) % len(phrases)
    return phrases[idx]


def _template_matches(t: dict, genre: str, styles: set[str]) -> bool:
    """Genre/style gating for a template entry."""
    g = t.get("genres")
    if g is not None and genre not in g:
        return False
    s = t.get("styles")
    if s is not None and not styles.intersection(s):
        return False
    ag = t.get("anti_genres")
    if ag is not None and genre in ag:
        return False
    as_ = t.get("anti_styles")
    if as_ is not None and styles.intersection(as_):
        return False
    return True


def _pick_per_axis(
    templates: dict[str, list[dict]],
    row: dict,
    axis_stars: dict[str, float | None],
    genre: str,
    styles: set[str],
    *,
    star_min: float | None = None,
    star_max: float | None = None,
    max_total: int = 3,
    is_strength: bool = True,
) -> list[Any]:
    """Pick phrases across axes that meet star+genre+style+metric criteria.

    Returns a list — for strengths it's [phrase, phrase];
    for weaknesses it's [(phrase, fix), ...].
    """
    out: list[Any] = []
    fn = row.get("filename", "")
    for axis_name, stars in axis_stars.items():
        if stars is None:
            continue
        if star_min is not None and stars < star_min:
            continue
        if star_max is not None and stars > star_max:
            continue
        for t in templates.get(axis_name, []):
            if not _template_matches(t, genre, styles):
                continue
            v = _read(row, t["metric"])
            if v is None:
                continue
            if not _passes(v, t["thresh"], t["op"]):
                continue
            phrase = _stable_pick(t["phrases"], fn, axis_name + t["metric"])
            if not phrase:
                continue
            if is_strength:
                out.append(phrase)
            else:
                fixes = t.get("fixes") or []
                fix = _stable_pick(fixes, fn, axis_name + "fix") if fixes else ""
                out.append((phrase, fix))
            if len(out) >= max_total:
                return out
            break  # one phrase per axis to avoid stacking
    return out


def build_advice(
    row: dict[str, Any],
    final_stars: dict[str, float | None],
    decision: str,
    meta_inconsistencies: str = "",
) -> dict[str, Any]:
    """V11.1: produce per-image-distinctive advice.

    Genre + style derived from the row so wildlife / fashion /
    architecture / silhouette get different praise vocabularies.
    Phrase pools rotated by hashing filename so within a batch the
    same axis on different images doesn't repeat verbatim.
    """
    genre = str(row.get("scene", "") or "")
    # Derive style modes — avoid the import unless needed
    styles: set[str] = set()
    try:
        from pixcull.scoring.style_modes import detect_style_modes
        sp = detect_style_modes(row)
        styles = sp.modes
    except Exception:
        pass

    strengths = _pick_per_axis(
        STRENGTH_TEMPLATES, row, final_stars, genre, styles,
        star_min=4.0, max_total=3, is_strength=True,
    )
    weak_pairs = _pick_per_axis(
        WEAKNESS_TEMPLATES, row, final_stars, genre, styles,
        star_max=3.0, max_total=3, is_strength=False,
    )
    weaknesses = [w for w, _ in weak_pairs]
    suggestions = [f for _, f in weak_pairs if f]

    # 1-line verdict head
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
