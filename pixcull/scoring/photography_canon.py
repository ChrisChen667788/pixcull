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

# v0.10-P2-2 — canon library v2.  Adds 30 contemporary entries
# extending the v0.4 set (Adams / Cartier-Bresson / Wikipedia
# composition) into modern editorial + wedding + commercial +
# 中国风光 territory.  Each entry retains the (label, body)
# tuple shape so RUBRIC_AXES.canon_cites can iterate uniformly.
#
# The new entries are appended (not interleaved) so an existing
# call-site that pinned itself to `CANON_AXES_ZH["light"][0]`
# (the v0.4 order) doesn't shift.  Consumers reading the full
# axis list iterate +5 entries on each, no other change.
_CANON_V2_ADDITIONS: dict[str, list[tuple[str, str]]] = {
    "technical": [
        ("感光元件原生 ISO 优先",
         "现代 CMOS 的 native ISO(双原生:64/400 or 100/640)"
         " 比拉伸 ISO 噪点低 1-1.5 档,Adams Zone System 在数码"
         " 上等价于'尽量靠近原生 ISO 拍'"),
        ("拍 RAW 才有 zone V 可拉",
         "JPEG 直方图被 sRGB 8-bit 截断,Adams 的 zone II→IX 在"
         " RAW 中才有完整重建空间;Lr 拉回 ±3EV 不掉调子"),
        ("白平衡叙事而非'准'",
         "Solo Sokolova 大量用'故意冷'记录冬季婚礼;白平衡是"
         " 情绪决策,不是'正确性'"),
        ("镜头特征显化",
         "85mm f/1.2 的过渡 vs 24mm f/14 的全画面锐,选镜头"
         " 等于选'画面边界质感'"),
        ("分屏处理审查",
         "黑场暗部 + 高光分别处理(Adams '分区显影' 数码版),"
         " 后期 OR 前期两段曝光,任何整片 push 都掉立体感"),
    ],
    "subject": [
        ("环境肖像 vs 特写",
         "Annie Leibovitz:让环境替主体说一半;近景剪环境"
         " = 只看脸,远景太琐碎 = 弱主体"),
        ("自然光人物 = 简洁背景",
         "Steve McCurry《阿富汗少女》:面孔占满,背景全模糊"
         "/纯色"),
        ("婚礼现场'第二动作'",
         "Andrew Suryono:除了主角动作,捕捉旁观亲属的微反应"
         " — 第二个视觉支点撑起整张照片"),
        ("Z-gen 自拍审美",
         "CapCut 时代,'故意失焦 + 强暖色 + 主体不在 1/3 而"
         " 在画面贴边' 也是合格构图(打破规则的当代变体)"),
        ("中国风光的'藏'与'露'",
         "川西山水:大山藏雾、小屋藏树、人物藏在比例 1/40 以下"
         " 的位置,留白比例 ≥ 60%"),
    ],
    "composition": [
        ("当代极简",
         "Solo Sokolova 婚礼组:单色背景 + 主体 1 人 + 留白 > 70%"
         ",废掉传统三分法的'重元素填满'信条"),
        ("环境为框",
         "门窗 / 桥拱 / 树梢自然形成的内框,把主体放在框内一次"
         " 完成'引导'"),
        ("反向 lead room",
         "传统:人物视线方向留空。现代实验:视线撞墙的封闭感"
         " 表达'压抑/思考' — Wim Wenders《柏林苍穹下》"),
        ("竖向构图的当代复兴",
         "TikTok / Reels 9:16 倒推回选片:重要 keep 同时按"
         " 竖向裁切检查,不能裁掉的才是 5★"),
        ("纹理叠加",
         "前景实焦的栏杆 + 中景虚焦的主体 + 远景实焦的山,3 层"
         "锐度差形成深度暗示"),
    ],
    "light": [
        ("Blue Hour 后 10 分钟",
         "天空仍有 -2EV 残蓝 + 室内灯已开 = 双光源叙事窗口"
         ",仅持续 ~10 分钟"),
        ("反射光做主光",
         "Andrew Suryono 中印婚礼:用走廊瓷砖把窗光反射上来,"
         "比直射柔 2 档但保留方向感"),
        ("OCF(off-camera flash)叙事",
         "Joe McNally:闪光不是补光,是写'第二个太阳';光位 ≠"
         " 主光源位"),
        ("色温撞击",
         "5500K 日光 + 3200K 钨丝灯同时入画,色温差 2300K → 强"
         "戏剧 ='婚礼现场 vs 婚礼餐厅' 切换"),
        ("'反向高光' 趋势",
         "传统:保护高光不剪。Z-gen:故意让窗光 100% 死白,"
         "主体在中景 zone V → 制造'梦境'感"),
    ],
    "moment": [
        ("情绪余波 vs 峰值",
         "Magnum 教学:笑声峰值后 0.5 秒的'松气' 比笑声峰值"
         "本身更打动人"),
        ("Z-gen '反高潮'",
         "B-roll 美学:不拍亲吻瞬间,拍亲吻后两人对视的 0.8 秒"),
        ("非语言对话",
         "Garry Winogrand:两人不看彼此但身体姿势在'回话',"
         "三人以上场景的核心"),
        ("微表情捕捉",
         "Paul Ekman FACS:嘴角 ±2px、眉峰 ±1mm 决定'真"
         "笑/客套笑' — 5★ 笑容应该是 Duchenne 笑(眼角)"),
        ("环境时钟",
         "钟表 / 日历 / 街灯 / 季节叶 — 给画面打时间戳的"
         "二级元素"),
    ],
    "aesthetic": [
        ("Wes Anderson 对称美学",
         "正面 1 点透视 + 调色板 ≤ 3 色 + 主体居中 → 故意"
         "反三分法,但需要严格执行"),
        ("Roger Deakins 单一光源",
         "《1917》摄影:即便复杂场景,光也只有 1 个主源 +"
         " 1 个反射 + 0 个补光 → 极简但戏剧"),
        ("Pixelmator-级 polish",
         "5★ 照片应该在 100% 缩放下经得起 30 秒检查 — 边缘"
         "无 fringe、暗部无色噪、肤色不偏品红"),
        ("色彩心理学",
         "红/橙 = 警觉 + 食欲;蓝/绿 = 静止 + 时间感;紫 ="
         "尊贵 + 距离 — 婚礼商业题主色要明确"),
        ("当代'2020s+' 调色趋势",
         "高光带浅蓝 + 阴影带橙红(orange-teal 的变体);"
         "高对比但低 saturation;胶片颗粒 + 现代锐度"),
    ],
}

# Merge v2 additions into the canonical CANON_AXES_ZH so every
# downstream consumer (rubric, VLM prompt, meta-judge, /share
# canon-cite chip) sees them on the next import.
for _ax, _entries in _CANON_V2_ADDITIONS.items():
    CANON_AXES_ZH.setdefault(_ax, []).extend(_entries)


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
# v0.10-P2-2 — expanded with the contemporary additions.
CANON_SOURCES_ZH = (
    "评分标准源自:\n"
    "• Henri Cartier-Bresson《决定性瞬间》(1952)\n"
    "• Ansel Adams Zone System +《The Negative》(1948)\n"
    "• Composition (Visual Arts) — Wikipedia 摘要\n"
    "• Photographic Lighting — 4 种经典光位 + 光质理论\n"
    "• Annie Leibovitz · Steve McCurry · Andrew Suryono ——\n"
    "  当代环境肖像 + 婚礼现场二级动作\n"
    "• Wes Anderson · Roger Deakins ·《1917》——\n"
    "  对称构图 + 单一光源戏剧光\n"
    "• Paul Ekman FACS —— Duchenne smile 微表情判读\n"
    "• Solo Sokolova · 2020s wedding —— 当代极简 + 反规则\n"
    "• CapCut / Reels —— Z-gen 9:16 + 反高潮 + 反向高光"
)
