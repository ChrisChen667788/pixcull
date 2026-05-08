"""V14.3 actionable photography advice — turns scores into next-steps.

Lineage:
* V5.2  introduced per-genre + per-style templating
* V11.1 added 3-5 phrasings per axis with filename-hash rotation
* V14.3 (this file):
  - Phrase rotation now anchors on batch *index*, not filename, so
    renaming a JPG no longer rotates its review text.
  - Stricter ``anti_genres`` on generic subject/composition templates
    so a macro shot no longer gets the portrait-coded phrase
    "主体占画 30%+, 视觉锚点稳" — a more specific genre template
    fires instead.
  - Canon-grounded phrases (Adams' Zone System, Cartier-Bresson's
    決定性瞬間, f/64 Group sharpness ideals) now carry a ``source``
    field, surfaced in the lightbox info pane as a small italic
    citation. Adds a sense of "you're being graded against the
    canon, not just numbers".
  - "maybe" verdicts now ship a one-sentence rationale ("低对比 +
    主体居中, 等同票") synthesized from final_stars + flags. Closes
    the audit gap where users complained "maybe" was opaque.

Output shape (V14.3 — extended, fully back-compat with V5.2 readers
that ignore unknown keys):
  {
    "verdict_short":      ...,            # one-line head + first bullet
    "verdict":            "keep" | "maybe" | "cull",
    "strengths":          ["phrase", ...] (flat strings, V5.2 shape),
    "weaknesses":         ["phrase", ...],
    "suggestions":        ["fix", ...],
    "inconsistencies":    [...],
    "rationale":          "..." | None,   # NEW: 1-line "why maybe"
    "strengths_detail":   [{phrase, source?}, ...],  # NEW: rich form
    "weaknesses_detail":  [{phrase, source?, fix?}, ...],  # NEW
  }
"""

from __future__ import annotations

import hashlib
from typing import Any


# ---------------------------------------------------------------------------
# STRENGTH templates
#
# Schema (V17.3):
#   {
#     axis_name: [
#       {
#         "metric": "<row key>",
#         "thresh": <float>,
#         "op":     "<= or >=",
#         "phrases": [<list of synonyms>],
#         "genres":         None or set of scenes this applies to,
#         "anti_genres":    None or set of scenes that DISABLE this template,
#         "styles":         None or set of style modes this applies to,
#         "anti_styles":    None or set of style modes that DISABLE this template,
#         "verticals":      None or set of business verticals
#                           (V17.3, e.g. {"wedding"} → fires only when the
#                           run was tagged with that business vertical),
#         "anti_verticals": None or set of business verticals that DISABLE,
#         "source":         optional canon citation
#                           (V14.3, e.g. "Adams · Zone System"),
#       }
#     ]
#   }
#
# V17.3 — verticals are independent of genres. A wedding shoot may be
# tagged genre=portrait, but the business vertical is "wedding" — and
# the phrase pool used for praise should reflect 婚纱-specific vocabulary
# ("Lead Room 充足 + 透视舒服 / 高调干净 / 婚纱质感") not generic portrait
# language. When ``verticals`` is set on a template, that template is
# GATED — it fires ONLY if the run's vertical key is in the set.
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
            "source": "Adams · Zone System",
        },
        {
            "metric": "canon_midgray_offset", "thresh": 0.05, "op": "<=",
            "phrases": [
                "Zone V 中灰锚定准确",
                "中灰位置标准,整体曝光基调对",
                "测光精准,中性灰落在 50% luma",
            ],
            "source": "Adams · Zone System",
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
            "source": "f/64 Group · 全画面景深",
        },
    ],
    "subject": [
        # Generic — V14.3: exclude genres that have their OWN specific
        # subject templates below (macro/wildlife/landscape/architecture/
        # abstract). Generic "主体占画 30%+" was firing for macro shots
        # where it's tonally wrong; the macro figure-ground template
        # (further down) is the right fit instead.
        {
            "metric": "subject_fraction", "thresh": 0.25, "op": ">=",
            "phrases": [
                "主体占画 30%+,视觉锚点稳",
                "主体比例舒适,不会过小或淹没",
                "主体在画面中分量足够",
            ],
            "anti_genres": {"macro", "wildlife", "landscape",
                              "architecture", "abstract", "astro"},
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
            "source": "Rule of Thirds",
            # V14.3 — abstract / macro / astro often *want* centered
            # composition; thirds praise is misleading there.
            "anti_genres": {"abstract", "macro", "astro"},
        },
        {
            "metric": "canon_lead_room", "thresh": 0.7, "op": ">=",
            "phrases": [
                "Lead Room 充足,视线方向有空间",
                "主体朝向方向留白合理(Rule of Space)",
                "前景空间预留得当",
            ],
            "source": "Rule of Space",
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
            "source": "格式塔 · 图底关系",
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
            "source": "Ansel Adams · 黑白叙事",
        },
        {
            "metric": "score_exposure", "thresh": 0.0, "op": ">=",
            "phrases": [
                "Chiaroscuro 戏剧性强,8:1+ 光比有效",
                "低调氛围浓,暗部包裹主体",
            ],
            "styles": {"low_key"},
            "source": "Caravaggio · 明暗对照法",
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
            "source": "Henri Cartier-Bresson · 决定性瞬间 (1952)",
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
# V17.3 — per-vertical phrase pools.
#
# Schema is identical to STRENGTH_TEMPLATES / WEAKNESS_TEMPLATES, but
# the outer dict is keyed by vertical FIRST (wedding / bird / kids /
# etc), then by axis. ``_pick_per_axis`` iterates the matching
# vertical's pool BEFORE falling through to the generic dict, so a
# ``wedding``-tagged run gets "Lead Room 充足 + 透视舒服" instead of
# the generic "三分法构图严谨".
#
# Templates here MUST omit the ``verticals`` filter — the vertical
# scoping is implicit from the outer dict key. Adding ``genres`` /
# ``styles`` is still allowed and useful (e.g. the wedding "high-key
# clean" phrase only fires when style_modes also detects ``high_key``).
# ---------------------------------------------------------------------------

VERTICAL_STRENGTH_TEMPLATES: dict[str, dict[str, list[dict[str, Any]]]] = {
    # ───────────────────────── 婚纱 ────────────────────────────
    "wedding": {
        "subject": [
            {
                "metric": "face_count", "thresh": 1, "op": ">=",
                "phrases": [
                    "新人眼神接触自然,情感互动到位",
                    "新人正脸入框,神情松弛",
                    "情感互动可读,有故事感",
                ],
            },
        ],
        "composition": [
            {
                "metric": "canon_lead_room", "thresh": 0.65, "op": ">=",
                "phrases": [
                    "Lead Room 充足,透视舒服",
                    "新人朝向方向留白合理(Rule of Space)",
                    "婚纱礼服展开有空间,层次感好",
                ],
                "source": "Rule of Space",
            },
        ],
        "light": [
            {
                "metric": "score_exposure", "thresh": 0.0, "op": ">=",
                "phrases": [
                    "高调干净光,皮肤通透",
                    "光质柔和,适合婚纱",
                    "婚礼现场氛围光自然",
                ],
                "styles": {"high_key"},
            },
        ],
        "moment": [
            {
                "metric": "score_moment", "thresh": 0.65, "op": ">=",
                "phrases": [
                    "笑容/泪光/对视的关键瞬间",
                    "情感峰值定格,Cartier-Bresson 决定性瞬间",
                    "动作 + 表情同步到位",
                ],
                "source": "Henri Cartier-Bresson · 决定性瞬间",
            },
        ],
        "aesthetic": [
            {
                "metric": "laion_aes", "thresh": 5.5, "op": ">=",
                "phrases": [
                    "婚纱质感柔和,色彩协调",
                    "整体氛围温暖,情绪饱满",
                    "影楼级品质,可作主推",
                ],
            },
        ],
    },
    # ───────────────────────── 拍鸟 ────────────────────────────
    "bird": {
        "subject": [
            {
                "metric": "subject_fraction", "thresh": 0.10, "op": ">=",
                "phrases": [
                    "眼神光锐,鸟眼有神",
                    "鸟头部清晰,主体可读",
                    "鸟眼焦点扎实",
                ],
            },
        ],
        "composition": [
            {
                "metric": "canon_lead_room", "thresh": 0.6, "op": ">=",
                "phrases": [
                    "栖息姿态优雅,引导视线",
                    "飞行轨迹延展感强",
                    "前方留白合理,飞行感生动",
                ],
                "source": "Rule of Space",
            },
        ],
        "moment": [
            {
                "metric": "score_moment", "thresh": 0.6, "op": ">=",
                "phrases": [
                    "展翅/捕食/降落的决定性瞬间",
                    "翅膀清晰,飞行姿态完整",
                    "动作峰值定格",
                ],
                "source": "Henri Cartier-Bresson · 决定性瞬间",
            },
        ],
        "technical": [
            {
                "metric": "laplacian_subject", "thresh": 180, "op": ">=",
                "phrases": [
                    "鸟眼焦点锁定,飞羽细节锐",
                    "高速锐度,动态主体清晰",
                    "鸟羽纹理清晰可辨",
                ],
            },
        ],
        "aesthetic": [
            {
                "metric": "laion_aes", "thresh": 5.5, "op": ">=",
                "phrases": [
                    "羽毛纹理质感丰富",
                    "野生鸟类大片质感",
                ],
            },
        ],
    },
    # ───────────────────────── 风光 ────────────────────────────
    "landscape": {
        "composition": [
            {
                "metric": "canon_thirds_concentration", "thresh": 0.5, "op": ">=",
                "phrases": [
                    "天地比例考究 (1:2 或 1:3)",
                    "前中后景过渡自然",
                    "构图严谨,层次分明",
                ],
                "source": "Rule of Thirds",
            },
        ],
        "subject": [
            {
                "metric": "canon_figure_ground", "thresh": 0.55, "op": ">=",
                "phrases": [
                    "山水主次分明,有视觉重心",
                    "前景中景远景层次清晰",
                    "地形特征突出,有视觉锚点",
                ],
            },
        ],
        "light": [
            {
                "metric": "score_exposure", "thresh": 0.85, "op": ">=",
                "phrases": [
                    "黄金时刻光质,色温温暖",
                    "蓝调时刻氛围,色彩诗意",
                    "晨昏光线柔和,影调过渡平滑",
                ],
            },
        ],
        "aesthetic": [
            {
                "metric": "laion_aes", "thresh": 6.0, "op": ">=",
                "phrases": [
                    "云海/星轨/极地大片质感",
                    "可作壁纸级风光",
                    "天地交融,意境深远",
                ],
            },
        ],
    },
    # ───────────────────────── 儿童 ────────────────────────────
    "kids": {
        "moment": [
            {
                "metric": "score_moment", "thresh": 0.55, "op": ">=",
                "phrases": [
                    "孩童表情真实可读",
                    "童真流露的瞬间",
                    "情绪峰值定格,自然不做作",
                ],
                "source": "Henri Cartier-Bresson · 决定性瞬间",
            },
        ],
        "subject": [
            {
                "metric": "face_count", "thresh": 1, "op": ">=",
                "phrases": [
                    "孩子神情自然不做作",
                    "情绪饱满,眼神有戏",
                    "童心可读,情感丰富",
                ],
            },
        ],
        "aesthetic": [
            {
                "metric": "laion_aes", "thresh": 5.0, "op": ">=",
                "phrases": [
                    "童趣感浓郁",
                    "色调温暖,适合家庭相册",
                ],
            },
        ],
    },
    # ───────────────────────── 宠物 ────────────────────────────
    "pet": {
        "subject": [
            {
                "metric": "subject_fraction", "thresh": 0.15, "op": ">=",
                "phrases": [
                    "宠物神态生动,眼神有戏",
                    "性格鲜活,动作自然",
                    "毛发蓬松,质感细腻",
                ],
            },
        ],
        "moment": [
            {
                "metric": "score_moment", "thresh": 0.6, "op": ">=",
                "phrases": [
                    "奔跑/跳跃/对视的决定性瞬间",
                    "宠物互动情绪饱满",
                ],
                "source": "Henri Cartier-Bresson · 决定性瞬间",
            },
        ],
        "aesthetic": [
            {
                "metric": "laion_aes", "thresh": 5.2, "op": ">=",
                "phrases": [
                    "毛发质感细腻,纹理清晰",
                    "宠物大片质感",
                ],
            },
        ],
    },
    # ───────────────────────── 运动 ────────────────────────────
    "sports": {
        "moment": [
            {
                "metric": "score_moment", "thresh": 0.65, "op": ">=",
                "phrases": [
                    "峰值动作定格,Cartier-Bresson 决定性瞬间",
                    "极限姿态完整,身体张力充足",
                    "运动峰值瞬间,信息浓度高",
                ],
                "source": "Henri Cartier-Bresson · 决定性瞬间",
            },
        ],
        "subject": [
            {
                "metric": "laplacian_subject", "thresh": 200, "op": ">=",
                "phrases": [
                    "运动员焦点锐,姿态完整",
                    "主体定格清晰,动作可读",
                ],
            },
        ],
        "technical": [
            {
                "metric": "laplacian_subject", "thresh": 250, "op": ">=",
                "phrases": [
                    "高速锐度,1/1000s+ 抓拍清晰",
                    "动态主体凝固,无残影",
                ],
            },
        ],
    },
    # ───────────────────────── cosplay ─────────────────────────
    "cosplay": {
        "subject": [
            {
                "metric": "subject_fraction", "thresh": 0.30, "op": ">=",
                "phrases": [
                    "角色姿态戏剧,符合作品调性",
                    "造型完整,角色气质到位",
                    "服装比例舒适,人物入框",
                ],
            },
        ],
        "aesthetic": [
            {
                "metric": "laion_aes", "thresh": 5.5, "op": ">=",
                "phrases": [
                    "服装质感细致,氛围契合角色",
                    "二次元/番剧调性贴合",
                    "光影戏剧感强,有舞台感",
                ],
            },
        ],
        "composition": [
            {
                "metric": "canon_figure_ground", "thresh": 0.55, "op": ">=",
                "phrases": [
                    "造型不被边缘剪切,完整入框",
                    "道具与人物布置协调",
                ],
            },
        ],
    },
    # ───────────────────────── 旅拍 ────────────────────────────
    "travel": {
        "composition": [
            {
                "metric": "canon_thirds_concentration", "thresh": 0.5, "op": ">=",
                "phrases": [
                    "环境与人物比例舒适",
                    "异域元素入框,叙事有层次",
                    "目的地标志性元素 + 人物呼应",
                ],
            },
        ],
        "aesthetic": [
            {
                "metric": "laion_aes", "thresh": 5.3, "op": ">=",
                "phrases": [
                    "异域氛围浓,旅行感叙事",
                    "古镇/海岛质感,有目的地辨识度",
                    "色温有地域特征",
                ],
            },
        ],
    },
    # ───────────────────────── 活动 ────────────────────────────
    "event": {
        "moment": [
            {
                "metric": "score_moment", "thresh": 0.6, "op": ">=",
                "phrases": [
                    "事件本质瞬间(发言/握手/合影/颁奖)",
                    "重要节点定格",
                    "活动 highlight 一目了然",
                ],
                "source": "Henri Cartier-Bresson · 决定性瞬间",
            },
        ],
        "composition": [
            {
                "metric": "canon_balance", "thresh": 0.7, "op": ">=",
                "phrases": [
                    "信息密度有序,主体焦点 + 环境氛围",
                    "多人场景层次分明",
                ],
            },
        ],
        "subject": [
            {
                "metric": "face_count", "thresh": 1, "op": ">=",
                "phrases": [
                    "重要人物焦点清晰",
                    "主讲人入框且神态完整",
                ],
            },
        ],
    },
    # ───────────────────────── 野生 ────────────────────────────
    "wildlife": {
        "subject": [
            {
                "metric": "subject_fraction", "thresh": 0.12, "op": ">=",
                "phrases": [
                    "动物姿态完整 + 焦点在眼",
                    "野生主体完整入框",
                    "动物神态可读,有故事感",
                ],
            },
        ],
        "moment": [
            {
                "metric": "score_moment", "thresh": 0.6, "op": ">=",
                "phrases": [
                    "捕食/对峙/狩猎的决定性瞬间",
                    "动物自然行为定格",
                ],
                "source": "Henri Cartier-Bresson · 决定性瞬间",
            },
        ],
        "technical": [
            {
                "metric": "laplacian_subject", "thresh": 200, "op": ">=",
                "phrases": [
                    "野生主体锐度顶级,毛发清晰",
                    "焦点扎实,动态主体清晰",
                ],
            },
        ],
    },
}


# Per-vertical weakness templates — only the high-impact verticals get
# specific fix-up advice; others fall through to the generic
# WEAKNESS_TEMPLATES which already covers the major axes.
VERTICAL_WEAKNESS_TEMPLATES: dict[str, dict[str, list[dict[str, Any]]]] = {
    "wedding": {
        "light": [
            {
                "metric": "score_exposure", "thresh": 0.30, "op": "<=",
                "phrases": [
                    "新人脸部欠缺光,皮肤暗沉",
                    "脸部光不均,有阴影遮挡",
                ],
                "fixes": [
                    "下次加反光板/补光灯,提亮脸部",
                    "调整角度,让主光打到脸上",
                ],
            },
        ],
        "subject": [
            {
                "metric": "face_count", "thresh": 0, "op": "<=",
                "phrases": [
                    "新人未入框/未对视镜头",
                    "缺乏正面互动,情感弱",
                ],
                "fixes": [
                    "下次提示新人方向 + 互动",
                    "等待对视瞬间再按快门",
                ],
            },
        ],
    },
    "bird": {
        "subject": [
            {
                "metric": "laplacian_subject", "thresh": 80, "op": "<=",
                "phrases": [
                    "鸟头/眼部失焦",
                    "主体不清,鸟眼模糊",
                ],
                "fixes": [
                    "用单点 AF 锁鸟眼",
                    "提高快门到 1/1600s+",
                    "改光圈到 f/5.6-8 增加景深",
                ],
            },
        ],
        "composition": [
            {
                "metric": "canon_lead_room", "thresh": 0.20, "op": "<=",
                "phrases": [
                    "翅膀/尾羽被边缘剪切",
                    "飞行方向无留白,堵感强",
                ],
                "fixes": [
                    "下次用更广焦段或退后",
                    "留出 60%+ 飞行方向空间",
                ],
            },
        ],
    },
    "sports": {
        "moment": [
            {
                "metric": "score_moment", "thresh": 0.30, "op": "<=",
                "phrases": [
                    "动作定格非峰值",
                    "捕到运动间隙,张力弱",
                ],
                "fixes": [
                    "高速连拍 (10fps+) + 选峰值帧",
                    "预判动作节奏,在峰值前 0.1s 按快门",
                ],
            },
        ],
        "technical": [
            {
                "metric": "laplacian_subject", "thresh": 100, "op": "<=",
                "phrases": [
                    "快门偏低,动态主体糊",
                ],
                "fixes": [
                    "提到 1/2000s+ 抓极限动作",
                    "提高 ISO 换更快快门",
                ],
            },
        ],
    },
    "kids": {
        "aesthetic": [
            {
                "metric": "laion_aes", "thresh": 4.0, "op": "<=",
                "phrases": [
                    "孩童表情僵硬,不自然",
                    "情绪未到,缺乏童真",
                ],
                "fixes": [
                    "让孩子放松,引导玩耍后再拍",
                    "用零食/玩具吸引注意力,等真笑",
                ],
            },
        ],
    },
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


def _stable_pick(
    phrases: list[str],
    anchor: str | int,
    salt: str = "",
) -> str:
    """Deterministic phrase rotation across a batch.

    V14.3 — ``anchor`` is either:
      * an int  (preferred): the row's index within the batch. Stable
        across renames; rotates synonyms cleanly across siblings.
      * a str   (fallback): legacy filename-anchored hash, kept for
        callers that still pass a filename.

    Same anchor + salt always returns the same phrase, but two
    different anchors on the same axis usually pick different
    synonyms — solves the "every card says Zone V 中灰锚定准确"
    repetition the user flagged.
    """
    if not phrases:
        return ""
    if len(phrases) == 1:
        return phrases[0]
    if isinstance(anchor, int):
        # Mix in salt so the same row picks different synonyms across
        # different axes/templates instead of always getting index N
        # of every pool.
        salt_bits = int(hashlib.sha256(salt.encode("utf-8")).hexdigest()[:8], 16)
        idx = (anchor * 0x9E3779B1 + salt_bits) % len(phrases)
    else:
        h = hashlib.sha256(f"{anchor}|{salt}".encode("utf-8")).hexdigest()
        idx = int(h[:8], 16) % len(phrases)
    return phrases[idx]


def _template_matches(t: dict, genre: str, styles: set[str],
                        vertical: str | None = None) -> bool:
    """Genre/style/vertical gating for a template entry.

    V17.3 — added ``verticals`` (must-match) and ``anti_verticals``
    (must-not-match) fields. Templates without a verticals filter
    fire normally; templates with a verticals filter fire ONLY when
    the run's vertical is in the set, which lets us write business-
    flavored language (婚纱 / 拍鸟 / 风光) without it leaking into
    runs that didn't pick that vertical.
    """
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
    # V17.3 — vertical gating
    v = t.get("verticals")
    if v is not None and (not vertical or vertical not in v):
        return False
    av = t.get("anti_verticals")
    if av is not None and vertical and vertical in av:
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
    anchor: int | str | None = None,
    vertical: str | None = None,
) -> list[dict[str, Any]]:
    """Pick phrases across axes that meet star+genre+style+metric criteria.

    V14.3 — returns rich dicts so callers can show source citations
    and per-axis context:

        [{"phrase": str, "source": str | None, "axis": str,
          "fix": str | None}, ...]

    Caller flattens to ``["phrase", ...]`` for the V5.2 ``strengths``
    field shape and ``[fix, ...]`` for ``suggestions``.

    ``anchor`` controls phrase rotation determinism. Pass the row's
    batch index (preferred) or filename (legacy). Falls back to
    ``row['filename']`` if None.
    """
    out: list[dict[str, Any]] = []
    if anchor is None:
        anchor = row.get("filename", "")
    # V17.3 — pick the right vertical-specific pool based on whether
    # we're picking strengths or weaknesses. The pool is empty when
    # ``vertical`` is None or when no overrides are defined for it.
    vertical_pool: dict[str, list[dict]] = {}
    if vertical:
        if is_strength:
            vertical_pool = VERTICAL_STRENGTH_TEMPLATES.get(vertical, {})
        else:
            vertical_pool = VERTICAL_WEAKNESS_TEMPLATES.get(vertical, {})
    for axis_name, stars in axis_stars.items():
        if stars is None:
            continue
        if star_min is not None and stars < star_min:
            continue
        if star_max is not None and stars > star_max:
            continue
        # V17.3 — vertical-specific templates win over generic ones
        # when they qualify (iterate them first, the ``break`` after
        # ``out.append`` ensures only one phrase per axis fires).
        candidates = list(vertical_pool.get(axis_name, []))
        candidates.extend(templates.get(axis_name, []))
        for t in candidates:
            if not _template_matches(t, genre, styles, vertical):
                continue
            v = _read(row, t["metric"])
            if v is None:
                continue
            if not _passes(v, t["thresh"], t["op"]):
                continue
            phrase = _stable_pick(t["phrases"], anchor, axis_name + t["metric"])
            if not phrase:
                continue
            entry: dict[str, Any] = {
                "phrase": phrase,
                "source": t.get("source"),
                "axis": axis_name,
            }
            if not is_strength:
                fixes = t.get("fixes") or []
                entry["fix"] = (
                    _stable_pick(fixes, anchor, axis_name + "fix")
                    if fixes else ""
                )
            out.append(entry)
            if len(out) >= max_total:
                return out
            break  # one phrase per axis to avoid stacking
    return out


# V14.3 — short-axis labels for the rationale synth. Shorter than the
# canonical RubricAxis.label_zh because it goes mid-sentence inside a
# 1-line summary; "技术" reads better than "技术(锐 / 曝光)" in that
# context.
_AXIS_LABEL_ZH = {
    "technical":   "技术",
    "subject":     "主体",
    "composition": "构图",
    "light":       "光线",
    "moment":      "瞬间",
    "aesthetic":   "美感",
}


def _synthesize_maybe_rationale(
    final_stars: dict[str, float | None],
    flags: str,
    inconsistencies_count: int,
) -> str:
    """One-line "why is this maybe" sentence.

    The audit gap: "maybe" feels opaque to users — they don't see
    what tipped it from keep / why it didn't make it to cull. We
    surface the strongest-up and strongest-down axes, plus a hint
    if the meta-judge disagreed with the rule.

    Examples:
      "瞬间高 + 构图弱,势均力敌"
      "曝光高 + 主体小,等同票"
      "美感强 + 多源判断分歧"
    """
    rated = [(n, s) for n, s in final_stars.items() if s is not None]
    if not rated:
        return ""
    rated.sort(key=lambda x: x[1])
    weakest = rated[0]
    strongest = rated[-1]
    parts: list[str] = []
    if strongest[1] >= 4.0:
        parts.append(f"{_AXIS_LABEL_ZH.get(strongest[0], strongest[0])}强")
    elif strongest[1] >= 3.5:
        parts.append(f"{_AXIS_LABEL_ZH.get(strongest[0], strongest[0])}过得去")
    if weakest[1] <= 2.0 and strongest[0] != weakest[0]:
        parts.append(f"{_AXIS_LABEL_ZH.get(weakest[0], weakest[0])}弱")
    elif weakest[1] <= 2.5 and strongest[0] != weakest[0]:
        parts.append(f"{_AXIS_LABEL_ZH.get(weakest[0], weakest[0])}偏低")

    # Flag-derived contributions
    flag_bits: list[str] = []
    fl = (flags or "").lower()
    if "blurred_subject" in fl or "soft_subject" in fl:
        flag_bits.append("主体软")
    if "blink" in fl:
        flag_bits.append("可能闭眼")
    if "highlight_clip" in fl:
        flag_bits.append("高光剪切")
    if "horizon_tilt" in fl:
        flag_bits.append("地平线斜")
    parts.extend(flag_bits[:1])  # cap at 1 flag bit to keep sentence short

    if inconsistencies_count >= 2:
        tail = "多源判断分歧"
    elif strongest[1] - weakest[1] < 1.0:
        tail = "等同票"
    else:
        tail = "势均力敌"

    if not parts:
        return tail
    return " + ".join(parts) + ", " + tail


def build_advice(
    row: dict[str, Any],
    final_stars: dict[str, float | None],
    decision: str,
    meta_inconsistencies: str = "",
    idx: int | None = None,
    vertical: str | None = None,
) -> dict[str, Any]:
    """V14.3: produce per-image-distinctive advice.

    Genre + style derived from the row so wildlife / fashion /
    architecture / silhouette get different praise vocabularies.

    Phrase pools rotated by ``idx`` (batch index) when provided —
    rename-stable. Falls back to filename hash for callers that
    don't pass an index (back-compat with the V11.1 signature).

    V17.3 — when ``vertical`` is set (passed by the orchestrator
    when the run was tagged from the scan dropdown), per-vertical
    phrase pools become eligible. A wedding-tagged run can pick
    "Lead Room 充足 + 透视舒服 / 高调干净 / 婚纱质感" instead of the
    generic portrait language; a bird-tagged run gets "眼神光锐 /
    飞行姿态完整". Falls back to genre-only when ``vertical`` is None.
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

    anchor: int | str = idx if idx is not None else str(row.get("filename", ""))

    strengths_detail = _pick_per_axis(
        STRENGTH_TEMPLATES, row, final_stars, genre, styles,
        star_min=4.0, max_total=3, is_strength=True, anchor=anchor,
        vertical=vertical,
    )
    weak_detail = _pick_per_axis(
        WEAKNESS_TEMPLATES, row, final_stars, genre, styles,
        star_max=3.0, max_total=3, is_strength=False, anchor=anchor,
        vertical=vertical,
    )

    # Flat string lists for V5.2-shape callers (card row, JS templates,
    # XMP exporter — none of them care about sources)
    strengths = [d["phrase"] for d in strengths_detail]
    weaknesses = [d["phrase"] for d in weak_detail]
    suggestions = [d.get("fix") for d in weak_detail if d.get("fix")]

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

    # V14.3 — only synthesize the rationale on "maybe". For keep/cull
    # the verdict_short already conveys it; adding more text would
    # crowd the card.
    rationale: str | None = None
    if decision == "maybe":
        rationale = _synthesize_maybe_rationale(
            final_stars,
            str(row.get("flags", "") or ""),
            len(inc_list),
        ) or None

    return {
        "verdict_short": verdict_short,
        "verdict": decision,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "suggestions": suggestions,
        "inconsistencies": inc_list,
        "rationale": rationale,
        "strengths_detail": strengths_detail,
        "weaknesses_detail": weak_detail,
    }
