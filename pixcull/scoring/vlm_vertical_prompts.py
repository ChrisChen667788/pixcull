"""P-AI-3 — per-vertical VLM prompts.

The global prompt (`build_prompt` in vlm_judge.py) sets the canon
context + 6-axis schema. Across verticals though, the *priority* of
axes diverges sharply:

  wedding:    moment + light  → forgive small focus misses on close
                                action; reward expression continuity
  sports:     moment + technical → require pixel-sharp action peak
  landscape:  technical + composition → require pixel-sharp, reward
                                        rule-of-thirds + foreground
  wildlife:   subject + moment   → eye-on-target is everything
  portrait:   subject + light    → reward catchlight + skin tone
  bird:       subject + technical → eye sharp + wing pose
  journalism: moment + subject   → narrative weight beats composition

This module supplies a short *additive* block that's injected into
the prompt RIGHT BEFORE the rubric axes, telling the VLM which
axes to weight + which kinds of imperfections to forgive per
vertical. It deliberately does NOT replace the canon section — that
universal grounding stays.

The function returns "" when the vertical is unknown so callers
fall through to the existing genre_strategies path.
"""
from __future__ import annotations

_VERTICAL_PROMPTS_ZH: dict[str, str] = {
    "landscape": (
        "【风光摄影 — 评分重点】\n"
        "- technical 是必须项: 全画幅锐度 + 高光不溢出 + 阴影不死黑。"
        "  原图轻微 ICM/水流模糊是 long-exposure 风格,不扣 technical。\n"
        "- composition 是关键: 强前景 + 引导线 + 三分黄金分割 + 平衡画面。\n"
        "- light: 重黄金时刻 / 蓝调 / 戏剧性云层光。中午直射光通常扣 1 星。\n"
        "- moment 在风光里通常 3-4 星即可 — 它不是核心。\n"
        "- 风光 keep 门槛比普通高:平庸构图 + 平庸光 ≤ 3.5 整体分应 maybe。"
    ),
    "wildlife": (
        "【野生动物 — 评分重点】\n"
        "- subject + moment 决定生死: 眼神光 + 主体姿态 / 行为瞬间是 5★ 与 3★ 的分水岭。\n"
        "- technical 容忍度高: 远距长焦的轻微锐度下降不扣分,只看主体脸 / 眼是否锐。\n"
        "- 动物面部被脸检测器误判,不要扣 subject。它是动物,你能看出眼睛在哪。\n"
        "- composition 看主体留白方向 (lead room) — 朝镜外看的留对侧空间是 5★。\n"
        "- 一些经典姿态自动 +1: 飞行展翅 / 跳跃 / 捕食 / 育雏 / 跨物种互动。"
    ),
    "bird": (
        "【拍鸟 — 评分重点】\n"
        "- subject: 眼神光 + 喙锐 + 翅膀姿态独立判定。眼锐 + 翅膀模糊 = 3-4 星(动态);"
        "  眼糊 = 直接 2 星以下。\n"
        "- moment: 飞行 / 起飞 / 降落 / 啄食 / 鸣叫张口 五种 base case 5★。\n"
        "- technical: ISO 噪点容忍度高(野外光线常受限),专注主体清晰度。\n"
        "- composition: lead room 朝鸟头方向比例 ≈ 2:1 是 5★。"
    ),
    "sports": (
        "【体育 / 动作摄影 — 评分重点】\n"
        "- moment 是绝对核心: 动作峰值瞬间 vs 准备 vs 收尾,峰值 = 5★;非峰值最多 3★。\n"
        "- technical: 1/1000s 以上快门 → 主体应当pixel-sharp。任何运动模糊在主体脸 / 球上 = 2 星。\n"
        "- subject: 表情 + 肢体张力 + 眼神方向。"
        "  比如篮球扣篮里看 ball-hand-eye 三连。\n"
        "- composition 次要: 紧贴动作是体育的 native style,经典构图反而扣分。"
    ),
    "wedding": (
        "【婚礼摄影 — 评分重点】\n"
        "- moment 是首位: 真实情绪 (新人对视 / 拥抱 / 笑出眼泪 / 父亲牵手) 默认 +1★。\n"
        "  机位摆拍 vs 真情流露要明显区分。\n"
        "- light + subject 共同决定: 婚礼室内光线挑战大,容忍 ISO 较高;"
        "  但人脸不能脏(肤色发青/红)、眼神光不能死。\n"
        "- 闭眼是减项但不必直接 cull — 同一表情的另一帧通常更好。\n"
        "- composition: 三分 / 引导线 等不是核心。情绪先于构图。\n"
        "- 全场鸡尾酒 / 仪式 / 致辞 / 第一支舞 是题材的 5 大 set piece,"
        "  覆盖度 + 情绪强度 是 keep 标准。"
    ),
    "portrait": (
        "【人像摄影 — 评分重点】\n"
        "- subject: 眼神光 + 表情自然 + 肤色还原。眼神光缺失直接 -1★。\n"
        "- light: 主光方向 + 柔硬过渡 + 三角光 / 蝴蝶光 等经典模式 +1★。\n"
        "  顶光直射(无补)= 2★ 以下。\n"
        "- technical: 眼睛 pixel-sharp 是 keep 底线。\n"
        "- composition: 头顶留白 + leading lines 朝向脸 + 不切关节。"
    ),
    "event": (
        "【活动 / 会议摄影 — 评分重点】\n"
        "- moment 看是否是 set piece (上台演讲 / 颁奖 / 大合影 / handshake)。\n"
        "- subject: 主讲人正脸 + 表情自然 + 没有被遮挡 = keep 必须。侧脸 / 后脑勺 = cull。\n"
        "- technical: 室内大跨度焦距,锐度要求降低但主体必须清晰。\n"
        "- 活动里重复机位多 — 重视独立性 / 不可替代性。"
    ),
    "journalism": (
        "【新闻 / 纪实摄影 — 评分重点】\n"
        "- moment 是核心: 决定性瞬间 (Cartier-Bresson) 是金标准。\n"
        "  叙事张力 > 美学。表情冲突 / 肢体冲突 / 关键道具 入框瞬间 5★。\n"
        "- 不要因为 composition / light / technical 轻微缺陷 cull —"
        "  普利策级照片里 70% 在这些维度上是 3★ 而非 5★。\n"
        "- subject 看脸是否能看出情绪 + 上下文是否能让读者读懂事件。\n"
        "- aesthetic 评分包含照片的历史 / 文化叙事价值,不只是美学。\n"
        "- 后期不要美化判断:新闻摄影是 'as-is' 标准。"
    ),
    "commercial": (
        "【商业 / 广告摄影 — 评分重点】\n"
        "- technical: 必须 pixel-sharp 主体 + 干净的高光 + 无伪影。"
        "  商业容忍度最低,2 星以下直接 cull。\n"
        "- composition: 留白 + 颜色块平衡 + 给文字留位置 (commercial space)。\n"
        "- light: 商业光通常受控且复杂 — 棚拍光位准确度 5★ 标准。\n"
        "- subject: 产品 / 模特的角度服务于品牌叙事。\n"
        "- aesthetic 包含品牌契合度 — 这是其他题材没有的维度。"
    ),
    "stilllife": (
        "【静物 / 产品 — 评分重点】\n"
        "- technical: 焦点准确度 + 景深控制 + 干净背景 = 5★ 底线。\n"
        "- composition: 物品摆放节奏 / 重复-断裂 / 三角构图。\n"
        "- light: 光位准确性 + 反光控制 + 阴影柔硬控制。\n"
        "- moment 不适用:静物题材里 moment ≈ aesthetic,可合并打分。\n"
        "- subject: 产品本身的细节呈现 + 光泽 + 纹理。"
    ),
}


def vertical_prompt_block(vertical: str | None) -> str:
    """Return the additive prompt block for the given vertical,
    or empty string if there's no override.

    Designed to be CONCATENATED into the global build_prompt() output
    between the canon section and the per-axis schema (around line
    155 in vlm_judge.py).
    """
    if not vertical:
        return ""
    return _VERTICAL_PROMPTS_ZH.get(str(vertical).lower().strip(), "")


def known_verticals() -> tuple[str, ...]:
    """Tuple of vertical keys that have a tuned prompt."""
    return tuple(_VERTICAL_PROMPTS_ZH.keys())
