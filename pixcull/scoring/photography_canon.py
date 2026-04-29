"""V5.0 Photography canon — encoded knowledge from classic sources.

Distilled from Wikipedia entries + canonical photography books into
machine-injectable text snippets and check-list rules. The goal is
to give every model in the stack (VLM, meta-judge) the same
grounded vocabulary a working photo editor would use.

Sources synthesized
===================
* **Henri Cartier-Bresson — *The Decisive Moment*** (1952)
  ``在事件本质和视觉形式精确组织的同一瞬间按下快门``
  → moment axis: peak action, peak emotion, geometric+narrative coincidence

* **Ansel Adams — *The Negative*, Zone System** (1948)
  Zone 0–X subdivides luminance from pure black (0) to pure white (X);
  Zone V = middle gray (50% luma). Acceptable exposure occupies
  zones II–IX with detail; clipping at endpoints is data loss.
  → technical axis: histogram should span II–IX; zone V near 0.5 luma

* **Ansel Adams — *Previsualization*** (1934 essay)
  Pre-shutter mental image of the final print; sharp focus near→far;
  full tonal separation; light direction/quality matches subject form.
  → technical+light axis joint signal

* **Composition (visual_arts) Wikipedia** — distilled:
  Rule of Thirds / Rule of Odds / Lead Room / Golden Ratio /
  Diagonal Tension / Negative Space / Visual Weight / Symmetry /
  Rhythm / Figure-Ground.
  → composition axis: each principle becomes a discriminative check

* **Photographic Lighting Wikipedia** — distilled:
  Loop / Butterfly / Split / Rembrandt as named portrait patterns;
  hard vs soft light; key/fill/back; golden hour; inverse-square law.
  → light axis: ratable lighting "pattern recognition"

This module exports *prompt-injectable text* (for VLM + meta-judge)
and *check-list keys* (for rubric_decompose). It is intentionally
data-only — no I/O, no network, no learned weights. The system
prompts in vlm_judge / meta_judge import from here so updating canon
in one place updates every consumer.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# 1. Per-axis canonical descriptors
# ---------------------------------------------------------------------------
# Every entry: (criterion, observable signal, why it matters).
# Used by build_canon_axis_section() to render a Markdown bullet list
# the VLM and meta-judge see as "expert grounding" before they score.

CANON_AXES_ZH: dict[str, list[tuple[str, str]]] = {
    "technical": [
        ("Zone System 完整性",
         "直方图应覆盖 Zone II-IX(2%-95% luma);两端堆积说明剪切"),
        ("中灰锚定",
         "Zone V 应落在 ~50% luma 附近,过亮/过暗代表整体偏移"),
        ("锐度与景深",
         "主体焦平面要锐(Adams: f/64 派);前后景都要可辨"),
        ("噪点 vs 噪点伪装",
         "高 ISO 下颗粒应均匀,色噪斑块说明传感器或处理失败"),
    ],
    "subject": [
        ("主体明确性",
         "去掉显性元素后画面剩什么 = 主体;主体应能 1 秒被定位"),
        ("姿态/表情峰值",
         "Cartier-Bresson:动作或表情正在'此刻'达到表现力顶点"),
        ("视线引导",
         "人物视线方向 + lead room 是否吻合(Rule of Space)"),
        ("背景不抢戏",
         "主体周围 5-10% 半径区域不应有同等视觉权重的元素"),
    ],
    "composition": [
        ("三分法 / 黄金比",
         "主体应靠近 1/3 或 0.382 分割线交点,而非画面正中"),
        ("引导线",
         "对角线、S 曲线、消失点是否引导视线到主体"),
        ("负空间",
         "主体之外的 '呼吸空间' 是否充足(过满或过空都失分)"),
        ("奇数法则",
         "多主体时 3/5/7 比 2/4/6 更自然(配对易呆板)"),
        ("对称 vs 不对称",
         "若用对称,要严格;若不用,视觉重心应不在正中"),
        ("Figure-ground",
         "主体与背景应有明度/色相/锐度对比之一,否则混作一团"),
    ],
    "light": [
        ("光质",
         "硬光阴影边缘锐(直射阳光),柔光阴影渐变(阴天/反射)"),
        ("光位",
         "顺光平面、侧光立体、逆光剪影、Rembrandt 戏剧"),
        ("光比与立体感",
         "亮暗比 1:2~1:8 给立体感;1:1 平,>1:16 死黑"),
        ("色温叙事",
         "黄金时刻暖调 = 怀旧/温情;蓝调 = 冷冽/疏离"),
        ("高光保护",
         "Adams: Zone IX 仍要有纹理,死白即数据丢失"),
    ],
    "moment": [
        ("决定性瞬间",
         "Cartier-Bresson:事件本质 + 形式精确组织在同一瞬间到位"),
        ("动作峰值",
         "运动中的转折点(球离手、跃起最高点)而非中段"),
        ("情绪含量",
         "有可读的情绪(笑/惊/思)而非中性脸"),
        ("时机 vs 摆拍",
         "自发瞬间含'真实感',摆拍痕迹会抹杀'决定性'"),
    ],
    "aesthetic": [
        ("色彩协调",
         "色相轮上 2-3 个相邻或互补色组,>4 个易杂"),
        ("情绪一致性",
         "光/色/构图/主体表达同一种情绪而非对冲"),
        ("视觉记忆点",
         "10 秒后还记得画面里的'关键 1 个元素'即合格"),
        ("作品集封面级",
         "5★ 标准:可作为代表作放在简介首屏"),
    ],
}


# ---------------------------------------------------------------------------
# 2. Canon-cited star descriptors (replace generic 1-5★ wording)
# ---------------------------------------------------------------------------
# Each entry: (axis, [1★, 2★, 3★, 4★, 5★])  with a canon-grounded
# anchor at each level. Used by rubric.RUBRIC_AXES.rubric_descriptors.

CANON_DESCRIPTORS_ZH: dict[str, tuple[str, str, str, str, str]] = {
    "technical": (
        "技术废片(直方图两端剪切 / 失焦 / 严重抖动)",
        "技术问题明显(Zone II 以下死黑或 Zone IX 以上死白 > 5%)",
        "Zone System 大致合格(直方图覆盖 II-IX,主体在焦)",
        "技术干净(Adams 标准:前后景皆锐,影调分离清晰)",
        "技术完美(每一像素皆精准 + 全 zone 范围利用)",
    ),
    "subject": (
        "无明确主体(画面散乱无视觉锚点)",
        "主体存在但姿态/表情勉强,背景抢戏",
        "主体清楚 + 1 秒可定位 + 背景不干扰",
        "主体表现力强(peak pose / 生动表情 / lead room 吻合)",
        "决定性瞬间(Cartier-Bresson 标准:事件本质 + 形式同时到位)",
    ),
    "composition": (
        "构图错位(地平线歪 > 3° / 主体被裁 / figure-ground 混)",
        "构图能看但平庸(主体居中 + 无引导线 + 无负空间利用)",
        "标准构图(三分法或对称 + 主体不在画面边缘)",
        "构图有意识(引导线 + 负空间 + 几何感受得到)",
        "构图惊艳(每个元素参与叙事 + 对角张力 / 奇数节奏 / 黄金比)",
    ),
    "light": (
        "光线问题大(死黑死白 / 光比 > 1:16 / 严重偏色)",
        "光线一般(平光 / 高光剪切 / 缺乏氛围)",
        "光线干净(光比合理 / 主体可读 / 无明显问题)",
        "光线讲究(可识别光位 - Loop/Split/Rembrandt;光质与主体相称)",
        "光线绝佳(黄金时刻 / 戏剧光质 / 决定整张照片成败的那种光)",
    ),
    "moment": (
        "时机错失(动作中段 / 闭眼 / 表情中性)",
        "时机普通(姿势 OK 但无情绪 / 无动作峰值)",
        "时机准(动作或表情到位之一)",
        "时机精彩(动作峰值 + 情绪 + 形式收敛)",
        "决定性瞬间(再拍一万张也碰不到第二次)",
    ),
    "aesthetic": (
        "美感差(色彩混杂 + 整体不协调 + 看完无记忆)",
        "美感平庸(色彩简单但视觉记忆点弱)",
        "美感及格(色彩协调 + 构图舒服 + 有 1 个记忆点)",
        "美感强(色/光/构图/情绪同向,有清晰视觉语言)",
        "美感顶级(可作品集封面 / 表达独到 / 看一次记一辈子)",
    ),
}


# ---------------------------------------------------------------------------
# 3. Prompt injection — what VLM + meta-judge see before scoring
# ---------------------------------------------------------------------------

def build_canon_section_zh() -> str:
    """A compact Markdown brief of the canon — < 600 tokens.

    Injected into both the VLM prompt and the meta-judge prompt as a
    "you are working with these reference standards" preamble. Designed
    short enough to fit Qwen3-VL's attention budget and DeepSeek's
    economic max_tokens.
    """
    lines = ["你的评分必须基于经典摄影标准:\n"]
    axis_zh = {
        "technical": "技术(对焦/曝光/锐度)",
        "subject": "主体",
        "composition": "构图",
        "light": "光线",
        "moment": "瞬间",
        "aesthetic": "美感",
    }
    for axis_name, items in CANON_AXES_ZH.items():
        lines.append(f"### {axis_zh[axis_name]}")
        for criterion, signal in items:
            lines.append(f"  • **{criterion}**:{signal}")
        lines.append("")
    lines.append("引用以上原则给分时,在 rationale 里说出对应的判断("
                 "如\"Zone III 死黑\"、\"Rule of Space 缺失\"、"
                 "\"Rembrandt 三角不完整\"、\"决定性瞬间\")。")
    return "\n".join(lines)


def get_axis_descriptors(axis_name: str) -> tuple[str, str, str, str, str]:
    """Return canon-grounded 1-5★ descriptors for one axis.

    Falls back to a generic ladder if the axis name is unknown so
    callers don't crash on schema drift.
    """
    return CANON_DESCRIPTORS_ZH.get(
        axis_name,
        ("废片", "差", "及格", "优秀", "顶级"),
    )


# Short attribution string the UI can show as a tooltip / about page.
CANON_SOURCES_ZH = (
    "评分标准源自:\n"
    "• Henri Cartier-Bresson《决定性瞬间》(1952)\n"
    "• Ansel Adams Zone System +《The Negative》(1948)\n"
    "• Composition (Visual Arts) — Wikipedia 摘要\n"
    "• Photographic Lighting — 4 种经典光位 + 光质理论"
)
