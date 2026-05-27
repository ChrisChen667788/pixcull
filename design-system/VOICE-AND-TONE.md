# PixCull Voice & Tone · v0.10 AI draft

> **STATUS: AI-AUTHORED FIRST DRAFT.**  Companion to
> [BRAND-GUIDE.md §6](BRAND-GUIDE.md#6--voice--tone).  A Phase B
> copywriter or brand designer should redo this against the
> photographer-voice that emerges from real user interviews;
> until then, this is the operational guide.

---

## 1 · The core principle

> **PixCull speaks like a photographer who happens to write
> code — never like software that happens to be used by
> photographers.**

That direction matters in every line.

---

## 2 · Three tonal contexts

| Context | Tone | Example |
|---------|------|---------|
| **Quiet moments** (idle UI, settings) | Confident, no exclamation | "DeepSeek API key(可选)" |
| **Action moments** (after a label, after a save) | Direct, brief | "标 keep · 已同步" |
| **Friction moments** (errors, conflicts, network out) | Acknowledging, never apologetic | "DeepSeek 没回应,这次先跳过解释" |

Three things PixCull never does:
- Apologize when it didn't do anything wrong ("Sorry, an error occurred")
- Celebrate trivial successes ("Yay! 1 photo uploaded!")
- Hide what it just did ("Processing your request…")

---

## 3 · DO / DON'T examples by surface

### 3.1 · First-run / onboarding

| DO (photographer-peer) | DON'T (software-vendor) |
|---|---|
| 拖一个文件夹进来 | Welcome to PixCull! Let's get started |
| 首次模型预热 ~30 秒,之后每张 ~1 秒 | Initializing AI engine, please wait |
| 给 Lightroom / Capture One 用?选 XMP 导出 | Configure your photo workflow integration |

### 3.2 · Mid-workflow feedback

| DO | DON'T |
|---|---|
| 12 张 keep · 4 张 maybe · 2 张 cull | 18 photos analyzed successfully |
| 按 1 标 keep · 按 2 maybe · 按 3 cull | Use keyboard shortcuts to label photos |
| 二摄正在看 IMG_077 | Second shooter is currently viewing IMG_077 |
| (留空 / 不显示) | Successfully synchronized |

### 3.3 · Empty states

| DO | DON'T |
|---|---|
| 上传第一批照片,这里就有片单了 | No data available |
| 还没有桶 — 在下面输入名字 + Enter | Click "+ Add" to create your first bucket |
| 没有照片匹配 "golden hour beach" — 试试同义词 | Search returned 0 results |
| 暂无其他协作者在线 — 把分享链接发出去 | No active connections detected |

### 3.4 · Errors + friction

| DO | DON'T |
|---|---|
| DeepSeek 没回应,这次先跳过解释 | An error occurred while contacting the AI service |
| 这张照片读不了 — 跳过 | Unable to decode image file |
| 协作会话已失效 — 让主摄重新发链接 | Session token expired. Please request a new one |
| 文件夹是空的 | No images found in the specified directory |

### 3.5 · Destructive confirmations

| DO | DON'T |
|---|---|
| 删掉 "婚礼-keep" 桶?里面 12 张会取消归类 | Are you sure you want to delete this bucket? This action cannot be undone |
| 把 80 张标 cull,然后立刻 export 删除? | Confirm bulk cull operation |
| 撤销刚才的批量改动?(8 张回到原来的状态) | Revert recent changes? |

### 3.6 · Settings

| DO | DON'T |
|---|---|
| DeepSeek API key(可选 — 不填也能用) | DeepSeek API Configuration |
| 默认导出位置 | Default export path |
| 模型库位置 | Model storage directory |
| 启动时自动检查更新 | Enable automatic update checking on startup |

### 3.7 · Settings — telemetry

| DO | DON'T |
|---|---|
| 崩溃报告:关 / 仅崩溃 / 包括用量(默认关) | Telemetry configuration |
| 默认关。开启不上传任何照片内容或文件名 | Help us improve PixCull by sharing usage data |

---

## 4 · Vocabulary banlist

These words break the voice immediately.  If they appear in any
copy, ship a rewrite:

**English:**
- "AI-powered" / "powered by AI" / "intelligent" / "smart"
- "magical" / "seamless" / "frictionless"
- "next-generation" / "revolutionary" / "cutting-edge"
- "leverage" / "utilize" / "optimize"
- "Welcome to" / "Get started with"
- "Discover" (as a CTA)
- "Click here"
- "Please wait" / "Please try again"
- "We apologize for the inconvenience"

**Chinese:**
- "智能" / "智慧" (用"AI"或具体描述替代)
- "海量" / "极速" / "一键"
- "焕新" / "赋能" / "落地"
- "操作流畅" / "丝般顺滑"
- "欢迎使用" / "开启 PixCull 之旅"
- "请稍候" / "请重试" / "出错了,请检查网络"

---

## 5 · Photographer-voice tells

Voice is the lines, but also the structure.  A photographer talking
to another photographer:

### 5.1 · Names the photo's content, not the technique

| ✓ Photographer-voice | ✗ Engineer-voice |
|---|---|
| "切蛋糕那张" | "wedding_moment=cake_cutting 的那张" |
| "靠左的那个 cull" | "scores.csv[3]" |
| "新娘那一刻的笑" | "row with face_smile=0.87" |

### 5.2 · Tools, not features

| ✓ | ✗ |
|---|---|
| "桶可以分别 export zip" | "Bucket export functionality" |
| "Lr 同步走 XMP" | "Lightroom integration via XMP sidecar" |
| "iPad 端可以 swipe 翻片" | "iPad swipe gesture support" |

### 5.3 · Quantities the photographer cares about

| ✓ | ✗ |
|---|---|
| "30 秒得到 batch verdict" | "Sub-second per-image inference" |
| "今晚 8 点交片,不是凌晨 3 点" | "Reduces culling time by 80%" |
| "1500 张,M2 Pro 25 分钟" | "Optimized for Apple Silicon" |

### 5.4 · Acknowledges what's hard

| ✓ | ✗ |
|---|---|
| "选片是判断,不是机械活" | "Streamlined workflow automation" |
| "这一张是 maybe — 你比模型懂" | "Confidence-weighted decision system" |
| "RAW 慢一点,JPEG 快" | "Format-adaptive performance" |

---

## 6 · Localisation handoff (Phase B → translators)

When translating to a new language, translators should be given:

1. This VOICE-AND-TONE.md as context
2. The 5 § sections above translated as guideposts
3. Examples of the voice in the target language (find similar
   tools' UX writing in that locale to anchor)
4. Explicit instruction: **do not literally translate; rewrite
   in the native voice**

KO + ES locales shipped in v0.10-P1-5 were AI-translated and
should be reviewed by a native photographer-leaning copywriter
before v1.0.  Same for any future locales (DE / FR / IT).

---

## 7 · Examples — the voice in action

The following lines appear (or should appear) in the v0.10
product.  They are the operational benchmark — if a new copy
addition can't sit next to these without sounding off, rewrite.

### Workspace bar

> 1,500 张原片 · 380 keep · 76% 入选率

### History page hover

> 川西行 · 2022-10 · 32 张

### Annotation modal title

> 标 IMG_077 — 你的评分会写进训练集

### Tether session status

> 监听 ~/wedding-2026/raw · 等下一张

### Active learning prompt

> 这一组里模型最不确定,先看这张

### LAN sync presence

> 二摄正在看 IMG_001 · 编辑刚标 IMG_007

### Conflict resolution

> 这两个版本不一样 — 选一个,或者两边都保留进 audit

### Setting tooltip

> 关掉自动更新 → Sparkle 不再检查;手动 `brew upgrade --cask pixcull`

### Empty buckets

> 还没有桶
> 在下面输入名字 + Enter 创建第一个
> 创建后,把卡片拖到桶上即可归属

### Executive PDF cover line

> 本报告由 PixCull 本地生成 · 照片永远不出本机

---

## 8 · The 5-second test

Before any new piece of copy ships:

1. **Read it aloud.**  Does it sound like a real photographer
   said it to a colleague?
2. **Does it pass the banlist** (§4)?
3. **Does it name the photographer's reality** (§5)?
4. **Does it require 0 prior PixCull knowledge to understand?**
5. **Is it ≤ 2x the length of the equivalent engineer-voice?**
   (Photographer-voice is concise; rambling is a tell.)

If all 5 pass → ship.  If any fail → rewrite.

---

*v0.10-AI draft · companion to BRAND-GUIDE.md · designed for
Phase B replacement.*
