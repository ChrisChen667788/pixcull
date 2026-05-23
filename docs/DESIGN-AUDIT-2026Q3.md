# Design audit — taking PixCull from "competent" to "iconic"

**Date**: 2026-05-23 (post-v0.8-P1-3)
**Status**: input for v0.9 charter

After v0.4 → v0.8(11 个 P0/P1/P2 slice 跨四个 charter)PixCull 已经接近
**LR Classic 的 85% 视觉密度 + Linear 的 70% UI 精致度**。打开 `/results/<run>`
基本看不出"单文件 vanilla JS 工程"的本相。但从"足够好"到"让人忍不住截图发朋友圈"
之间,还差一层很难量化、但 pro 用户能瞬间感知的"产品级"。

这份 audit 不是 to-do 清单 — 而是一份从五个维度对照业内标杆的诊断 + 三层
优先级的建议。所有判断都基于:实际 build + run 过 PixCull 的当前 main、
对比看过 LR Classic / CC、Capture One Pro、Photo Mechanic Plus、Linear、
Notion、Figma、CapCut Pro、Raycast、Arc Browser、Spline、Stripe Dashboard
的 UI。

---

## 1. 五维诊断

### 1.1 输出结果专业度(Output)

**业内标杆**

- **DaVinci Resolve** 的交付页:每个 Delivery 任务都有 cover 卡片显示
  source / target / format / status / progress。颜色编码 + ETA + 重试按钮。
  纯粹的"专业感"。
- **Apple Logic Pro** 的 Mastering panel:每条 stem 有 LUFS / TruePeak /
  Dynamic Range 读数,导出时自动生成 PDF technical report。
- **Lightroom Classic** 的 Print module:可以做带 logo + signature line +
  字段化 metadata 的客户交付 contact sheet。整页 layout 引擎,不只是 grid。
- **Photo Mechanic Plus** 的 IPTC stationery:可以批量套用一个"婚礼模板"
  ,自动填 photographer / event / location / copyright。

**PixCull 当前**

- ✅ CSV 导出全字段(P-UX-15)
- ✅ XMP zip / alongside(P-PRO-1)
- ✅ DNG 内嵌(P-PRO-5)
- ✅ Standalone HTML 相册(V23.x)
- ✅ CLI audit 报告(P-PRO-8 含 pass/fail 门控)
- ✅ PDF 导出 cli_audit(v0.4 P2 4/4)
- ✅ /share 客户分享 + QR(v0.7-P1-4 + v0.8-P1-3)

**差距**

1. **CLI audit PDF 没有"摄影师交付文档"的形态** — 它是 markdown 转的纯文字报告,没有
   封面页、目录、缩略图墙、关键数字 dashboard。客户拿到看到的是
   "技术报告",不是"我的服务交付"。
2. **/share 页是默认布局** — 客户看到的是裸 grid + filename caption。没有
   品牌头(摄影师 logo + 客户姓名 + 事件名)、没有 metadata block
   (拍摄地点 + 时间 + 设备 + photographer signature),没有引导性结构
   (e.g. 仪式 → 入场 → 致词 → kiss 的章节)。
3. **CSV 导出是数据,不是 "Lightroom catalog import 模板"** — 真正
   提升专业度是输出 `.lrcat`-ready 的 collection structure。
4. **没有 stem-level data 的 "executive summary"** — 一页纸告诉客户
   "拍了 X 张,精选 Y 张,投放 Z 张,平均技术分 W,光线优等率 V%"。

**该做的(按 ROI 排)**

- **🎯 高 ROI**:重做 /share 页 → 加品牌头 + 事件章节 + 摄影师签名 +
  metadata block。同样的客户分享,从"功能页"变"作品集"。
- **🎯 高 ROI**:cli_audit PDF 加 cover page(品牌 + 客户名 + 日期)+
  ToC + key-numbers dashboard(类似 Strava annual review 的卡片式 layout)+
  关键缩略图(最佳 5 张 / 矛盾警示 3 张)。
- **中 ROI**:Lr Catalog import 模板(.lrcat-ready collection structure)—
  pro 直接拖进 LR 就有完整 collection 树。
- **低 ROI**(锦上添花):metadata stationery 批量套模板(类似 PM 的
  IPTC stationery)。

---

### 1.2 视觉设计(Visual Design)

**业内标杆**

- **Linear**:有 signature 的渐变("Linear gradient" — 紫蓝 #5D4EFF →
  #2EBAFA),内置在 logo / cursor / 关键 CTA。整个产品颜色识别度极高。
- **Stripe Dashboard**:经典紫橘渐变,出现在所有 hero 图、loading
  state、empty state 插画。看到那个颜色就知道是 Stripe。
- **Vercel**:全黑底 + Geist Sans typography + 三角形几何 logo。
  极简到识别度反而很高。
- **CapCut Pro**:橘色主色 + 大圆角 + 强烈动效 + 拟物化 thumbnail 加重影。
  完全 Z-gen 审美。
- **Figma**:三色 logo(蓝紫红绿),整个产品都是 multi-color 拼合。

**PixCull 当前**

- 配色:dark `#0b0d10` + indigo accent `#6366f1`
- typography:Inter 全栈(13px body / 24-32px hero,但 hero 只在 upload 页)
- icon:Lucide-style SVG sprite(v0.4 P1 1/4)+ emoji 装饰
- logo:"wireframe star" SVG mark + "Pix**Cull**" wordmark

**差距**

1. **颜色没有 signature** — `#6366f1` 是 Tailwind 默认 indigo,任何
   bootstrap-tier 产品都用这个。没有人会"看一眼就知道是 PixCull"。
2. **没有渐变 brand asset** — 现在 .accent-pill 用纯色,没有 Linear-style
   的渐变 wash。CTA 按钮一片平。
3. **typography 单一** — 全 Inter。Linear 用 Inter + 一点 mono;
   Stripe 用 Sohne Mono 给 code 加 character;Vercel 用 Geist 全栈但 Geist
   本身就有强 identity。PixCull 缺一个"signature 字体角色"(可能 hero 用
   serif accent,e.g. PT Serif / Source Serif / Tiempos 显示用)。
4. **icon 系统不够"产品级"** — emoji(🪣 🏆 💒 ♿)还在很多地方(虽然
   v0.6 4/5 把 buckets 改成 SVG grip)。在专业摄影 product 里,emoji 显得
   "不严肃"。LR / C1 全部 inline-SVG,没有任何 emoji。
5. **logo 概念不够强** — wireframe star 是 ok-tier 的 generic icon。
   不会让人记住。Apple Photos 的彩虹花、LR 的渐变圆、CapCut 的 C 都是
   "看一眼记住"。

**该做的**

- **🎯 高 ROI**:**定义 signature 渐变 + 强主色**。
  - 提案 A:`linear-gradient(135deg, #6E56CF, #EC4899)`(紫粉 — 像 LR 的"色调")
  - 提案 B:`linear-gradient(135deg, #F5A623, #D63384)`(琥珀红 — 像 CapCut 但更柔)
  - 提案 C:keep indigo,但加 cyan accent `#06B6D4` 做双色对比(像 Vercel)
  把这个 gradient 用在:logo wordmark 渐变、primary CTA 背景、stats 数字、
  loading bar、QR 码 brand-frame。
- **🎯 高 ROI**:**重做 logo mark**。当前 wireframe 星(circle + 6 line)
  传达"分散"感,不是"culling"概念。culling 的视觉是"分两堆"或"漏斗"或
  "一颗 highlight 在群体里"。提案:一颗大圆 + 周围几颗小圆中,大圆是
  亮色 gradient(signature 渐变),小圆 muted。视觉传达"我们帮你挑出
  那一颗"。
- **中 ROI**:typography accent — hero / 大数字用 PT Serif 或 Source Serif
  (open source,免费,优雅,与 Inter 协调)。body 仍 Inter。
- **中 ROI**:emoji 替换最后一波 — buckets toggle 的 🪣 → SVG bucket
  icon,wedding moments 的 💒 → SVG heart-knot,a11y toggle 的 ♿ → SVG。
  Lucide 库都有现成的。

---

### 1.3 交互设计(Interaction Design)

**业内标杆**

- **Linear**:**Cmd+K command palette** 是核心交互。任何 action / 任何
  filter / 任何 view 都可以从 Cmd+K 触达。"键盘是 first-class UI"。
- **Notion**:**Slash menu**(/ + 关键词)插入任何 block。同样的"键盘搜索"
  思路。
- **Raycast**:全产品就是一个 Cmd+K palette。
- **Figma**:**Multiplayer cursors** + 实时 presence + selection 高亮。
  协作是肉眼可见的存在感。
- **CapCut**:**Magnetic timeline** — 拖一个 clip,前后 clip 自动让位。
  零摩擦。
- **Apple Photos**:**Swipe-to-favorite** + **long-press for context menu**
  + **drag-to-arrange**。每个手势都有触觉式视觉反馈。
- **DaVinci Resolve**:**多 page workflow**(Media → Cut → Edit → Fusion →
  Color → Fairlight → Deliver),每个 page 是独立大屏 UI,顶部一个
  tab bar 切换。专业工具的复杂性管理范式。

**PixCull 当前**

- ✅ Photo Mechanic 级键盘(P-UX-13)— 1/2/3/F/G/[]/Shift+1/2/3
- ✅ Hold-Space cheat sheet(v0.6 5/5)— Finder pattern
- ✅ Drag-and-drop 卡片到桶(P-UX-22)
- ✅ Drag-reorder 桶(v0.6 4/5)
- ✅ A/B compare(P-UX-3)
- ✅ LAN sync 实时同步标注(v0.8-P0-2)

**差距**

1. **没有 command palette** — 这是 modern web pro tool 的标配。我们当前的
   `?` cheat sheet 只是 read-only 的查询;Cmd+K palette 是 *do anything*
   的入口("打开 historical run XYZ"、"训练风格模型"、"切到 EN"、
   "新建桶 X 并把当前 keep 全部放进去"…)。
2. **drag interactions 缺 "magnetic" 感** — 拖卡片到桶,鼠标释放才提交;
   拖动过程中没有视觉"被吸"的反馈。Trello / Linear 的 drag 全程有
   placeholder / ghost / slot-highlight。
3. **没有 multiplayer presence** — v0.8-P0-2 协作模式只有 polling 增量,
   没有"另一个人此刻在看哪张照片 / 在标注哪张"。Figma 那种实时 cursor
   太重了,但一个简单的"二摄正在 IMG_001"指示器就有协作的存在感。
4. **没有 swipe gesture 在 lightbox**(移动端)— 当前必须点 ←→ 箭头或按
   方向键。Apple Photos 整个 photo viewer 都是 swipe。
5. **annotation 流仍是"三步"** — 1) 看图 2) 按 1/2/3 3) (可选)cull reason。
   LR Classic 的 "P / X / U" 是 single-key + 立即生效。我们已经接近但
   cull reason picker 弹出又要选,流程被切断。可以"smart suggest cull
   reason" 用历史数据自动猜测,默认选中,Enter 确认。
6. **undo 反馈弱** — 当前 Cmd+Z 撤销但只是默默执行 + toast。Linear 的
   undo 会展示 "Reverted: marked 3 photos as keep · Cmd+Shift+Z to redo"。
7. **没有 progress 可视化** — 训练风格 / 上传分析 / 协作同步都是 spinner。
   现代 product 用 indeterminate-but-shaped progress(skeleton screen +
   percentage tick + ETA)让等待"有信息"。
8. **lightbox 没有 swipe + pinch zoom on touch** — iPad 用户体验是 1996 的
   web,不是 2026 的 iPad。

**该做的**

- **🎯 高 ROI**:**Cmd+K command palette**。这是单一最 visible 的现代 pro
  tool 标志。即使只支持 20 个 actions,有这个口袋就有"产品级"的感觉。
- **🎯 高 ROI**:**Multiplayer presence**。在 sync mode 下,每个连接的客户
  端发一个 30s 心跳带 `last_viewed_filename`;workspace bar 顶部显示
  "👁️ 二摄正在看 IMG_001 · 📝 编辑刚标 IMG_007"。Figma-lite,1 天工作。
- **🎯 高 ROI**:**Cull reason 智能预填**。基于 P-UX-9 已有的 cull-reason
  频次统计,自动 highlight 用户最常用的那个 + Enter 直接提交。从"3 步"
  压到"2 步"。
- **中 ROI**:**Undo 反馈升级**。toast 改成 "✓ Marked 3 as keep · Cmd+Z
  to undo" 持续 4s 可点击撤回。
- **中 ROI**:**Progress 升级**。/style/train 显示 "[训练 …] 步骤 2/5:
  收集参考嵌入 · ETA 3s"。/scan_local 同理。
- **中 ROI**:**iPad lightbox 升级**。Hammer.js-style swipe + pinch zoom
  (vanilla,无库,~80 行 touch event)。

---

### 1.4 界面设计(UI Design)

**业内标杆**

- **Notion**:**Page-block-property 三层**。每个 page 顶部有 cover image,
  下面 properties bar(date / tag / status),再下面 blocks。结构清晰
  到任何 page 都"一看就懂"。
- **Linear**:**Three-column workspace**:nav rail / list / detail。
  每列宽度可拖。所有功能都在这个布局里。
- **Stripe Dashboard**:**Data-density 之神**。一行能挤 8 个 stats 但
  完全不挤,靠 typography hierarchy + 空白节奏 + table-row 微差色。
- **Arc Browser**:**Sidebar-first**。所有控件都在左侧 vertical sidebar,
  主区域是 100% content。
- **Figma**:**Toolbar at top, panels on right, layers on left**。固化
  pattern,所有设计师秒上手。
- **Pixelmator Pro**:**Single-window dark + content-focused**。toolbar 全
  在右侧 collapsible panels,左侧零 chrome,中间 100% 是 canvas。

**PixCull 当前**

- v0.6 (1/5) 已有 LR Library 风格 left sidebar
- v0.6 (2/5) 已有 LR Develop 风格 right Inspector(collapsible details)
- workspace bar 顶部包含 stats + lang switcher + crumb
- main grid 在中间
- modals(annotation / compare / share-URL / shortcuts / buckets)

**差距**

1. **没有 Notion / Linear 风格的 "right rail" 元数据 区** — Inspector 是
   per-photo 的,但没有一个 always-on 显示当前 run 总元数据(摄影师 /
   日期 / 设备分布 / 平均分)的 strip。
2. **Card hover state 是基础的 outline + scale** — Linear 的 card hover
   会浮起来 + 显示隐藏的 action buttons(标注 / 收藏 / 比较)在右上角。
   PixCull cards 露 hover 时只 outline + 一些 chip,没有"原来这里可以
   做更多"的 affordance。
3. **modals 视觉权重相同** — share-URL modal / annotation modal /
   compare modal / shortcuts modal 都是同一个 dark card + border。
   缺乏"这个是 destructive(删桶) vs 这个是 info(快捷键)" 的视觉
   区分。Apple HIG 推荐 destructive 红色 header + 警告色 confirm button。
4. **form input 仍是基础 outline-only** — 没有 floating label,没有
   inline validation feedback(用户在 share-URL modal 输入摄影师名,我们
   没有"已保存" indicator)。Material Design / Linear 的浮动标签 + 微
   underline 动画是 modern form 标准。
5. **filter chips 在 sidebar 各组之间没有视觉区分** — Decision / Scene /
   Style / Faces / Location / Bursts 都是同样的 pill 形状 + 同样的灰底。
   Notion 的 properties bar 不同 type 有不同 color hint(date 蓝 / status
   紫 / tag 绿)。
6. **empty states 是 generic 文字** — v0.4 P1 (3/4) 有 SVG 插画但仅几个;
   buckets 空 / 历史空 / sync 空 / annotation 空 都是不同插画的机会。
7. **table-like data 不存在** — annotations.jsonl / scores.csv / 单 run
   的统计都是 inline 显示。Notion / Linear 的 "database view" 是 table
   first-class:列可拖、列可隐藏、列可排序、cell 内可 inline-edit。
   PixCull 的 admin perf 页就缺这个。

**该做的**

- **🎯 高 ROI**:**Card hover 加 floating action 区**。每张卡片右上角,
  hover 时显示 3 个隐藏图标(👁️ 放大 / 🪣 加桶 / ⇆ 比较),都是 28×28
  iconButton。提升发现率 + 减少右键依赖。
- **🎯 高 ROI**:**Modal 视觉差异化**。3 类:
  - **info modal**(shortcuts / share-URL)→ neutral border + 默认 close X
  - **action modal**(annotation rubric / bucket export)→ accent border-top
    + "保存"按钮主色
  - **destructive modal**(删桶 / clear annotations)→ danger red border-top
    + "删除"按钮 danger 色 + "取消"主色(reverse pair to make destructive
    require deliberation)
- **🎯 高 ROI**:**Filter group color hints**。每个 .lp-group summary 加
  一个 6px 圆点 leading icon,颜色对应该 group 的 semantic(Decision =
  accent / Scene = success / Style = warning / Face = info / Bursts =
  danger…)。Notion-style。
- **中 ROI**:**Floating label form inputs** — 给 annotation modal /
  share-URL modal / sync event prompt 的所有 `<input>` 加 floating-label
  + 微 underline 动画。Material 风。
- **中 ROI**:**5 个新 empty-state 插画**:buckets 空 / 历史空 / sync
  无 peer / annotation 0 完成 / search 无结果。每个 ~100 行 SVG。

---

### 1.5 产品审美(Aesthetic)

**业内标杆**

- **Spline**:dark mode + 神奇的微动 + 3D 元素穿插 + 永远在动的 hero。
  打开就觉得"这个产品好新潮"。
- **Linear**:不靠装饰,靠"每个细节都用心"。所有 button radius 一致、所有
  spacing 用 4px grid、所有 motion 都是 cubic-bezier(0.16, 1, 0.3, 1)。
  纯净到一种"克制的炫耀"。
- **Arc Browser**:不传统的 chrome、彩色的 sidebar、动效像"魔法"(swipe
  to switch space)。重新定义 browser 的可能性。
- **Apple Photos**:每年都有一次大动 — Memories 视频开头的"星点拼图"
  + 音乐 + 模糊推进 + 文字 fade-in。让人想分享。
- **Notion AI**:"打字时 ✨ 渐变光从字符流出"。让 AI 的存在有"魔法感"。
- **CapCut Pro**:Z-gen 审美 — 大圆角 + 彩色 gradient + 强烈 motion +
  emoji-heavy。年轻人最爱的产品形态。

**PixCull 当前的审美定位**

- **设计语言**:LR Classic + Linear 的杂交。dark mode 优先,density 高,
  semi-translucent chrome,克制但功能性的 motion。
- **不像什么**:不像 CapCut(我们 boring),不像 Apple Photos(我们没
  装饰),不像 Spline(我们没有惊艳的细节)。
- **像什么**:像 v2020 时代的 Lightroom Web,功能正确但没有"潮"感。

**差距 — 从设计师角度**

1. **没有 motion identity**。240ms cubic-bezier 是 ok-tier 的常规过渡。
   Linear 的招牌过渡(cubic-bezier(0.16, 1, 0.3, 1) "soft elastic")让
   人一看就觉得"这是 Linear"。
2. **没有 hero animation moment**。CapCut / Notion / Spline 进入产品时
   有"WOW"。PixCull 打开 /results 一切都已 static 呈现 — 没有 reveal。
3. **没有"AI 的视觉存在感"**。我们的 ML 是产品核心,但 UI 上完全看不出
   这点。Notion AI 用 ✨ 渐变光让 AI 输出有 motion。我们的 "score_final
   0.82" 是冷数字。
4. **dark theme 是 well-tuned,light theme 是 afterthought**。LR / Linear
   / Notion 给 light 同样的爱:不同的 surface 层级、不同的 shadow 配方、
   不同的 type weight。我们 light theme 只是把颜色翻反。
5. **品牌没有 "moment"**。Stripe 的 gradient 出现在 hero / loading /
   QR brand-frame / footer。PixCull 的 indigo 主色只在 .accent-pill 出现
   ,没有 brand-wide 一致性。

**该做的(审美 P0)**

- **🎯 高 ROI**:**Signature motion curve**。把所有过渡的 ease 换成
  `cubic-bezier(0.34, 1.56, 0.64, 1)`("soft bounce" — 终点有微 overshoot)
  。这是单点最大的"审美感"提升。改一行 CSS 变量。
- **🎯 高 ROI**:**Hero reveal**。打开 /results 时,grid 从底部 stagger
  fade-up(每张卡片延迟 16ms),workspace bar 顶部 stats 数字从 0
  count-up 到当前值(已有 v0.4 P2 的 .stat-pulse 基础)。3 秒 reveal,
  之后所有交互 instant。
- **🎯 高 ROI**:**AI 视觉化**。score_final 数字旁加一个 micro radial
  progress(score/1.0)。rubric stars 旁加一个 sparkline 显示 6 axis
  values。所有 ML 输出 visually-encoded,不只是数字。
- **中 ROI**:**Light theme P2**。重做 light 的 shadow(暖色调,不是
  rgba(0,0,0,X))+ 不同的 surface-2/-3 配色 + 不同的 type weight。
  让 light 和 dark 都有"我精心调过这个 theme"的感觉。
- **中 ROI**:**Brand gradient 全 product 一致出现**。在 logo wordmark /
  primary CTA / loading progress bar / QR brand-frame / score 数字大处
  统一使用。"看一眼 PixCull 知道是 PixCull" 的视觉锚点。
- **想做但奢侈**:**Style fingerprint 视觉化**。在 admin / user profile
  页给用户一个"我的偏好"radar chart(6 axis stars 平均值)+ "我最常拍
  的 scene"pie + "我的 cull-reason top 3"bar。从 Strava annual review
  得灵感。

---

## 2. 三层优先级建议

### v0.9-P0(必须做,4-5 周内可完成)

| Ticket | 维度 | 估时 | 单点最大提升 |
|---|---|---|---|
| **v0.9-P0-1** Brand identity(gradient + logo redo + signature motion) | 视觉 + 审美 | 1 周 | 整个产品的视觉"潮流度"+1 grade |
| **v0.9-P0-2** Cmd+K command palette | IxD | 1 周 | "产品级" 的最强单点信号 |
| **v0.9-P0-3** Client-delivery page 重做(/share 加品牌头 + 章节 + signature) | Output 专业度 | 1 周 | 客户拿到的东西从"工程师产物"变"摄影师作品集" |
| **v0.9-P0-4** Card hover floating actions + Modal 视觉差异化 | UI | 4-5 天 | 整个 grid 交互的发现性 ×3 |

### v0.9-P1(应该做,加 2-3 周)

| Ticket | 维度 | 估时 | 价值 |
|---|---|---|---|
| **v0.9-P1-1** Multiplayer presence(协作 mode 下显示其他成员 last-viewed) | IxD | 2-3 天 | 协作的"存在感" |
| **v0.9-P1-2** PDF executive summary + Strava-style annual-review for cli_audit | Output | 4-5 天 | 客户交付 PDF 上一个 tier |
| **v0.9-P1-3** AI 视觉化(radial progress, axis sparkline, gradient on AI numbers) | 视觉 | 3-4 天 | "这个产品的 AI 真酷" |
| **v0.9-P1-4** iPad lightbox(swipe + pinch + tap-zoom) | IxD | 2-3 天 | iPad 用户体验 ×5 |
| **v0.9-P1-5** Light theme V2 | 视觉 | 2-3 天 | "我可以白天用了" |

### v1.0-P2(中期目标,v0.9 之后)

- 真正的 brand book(brand colors / typography / motion / icon system 写入
  `docs/BRAND.md`)
- 公开 roadmap 页面("Coming next" 可投票)
- Strava-style "我的 PixCull 年度报告"页面
- 5 个新 empty-state SVG 插画
- Pricing 页面 + "PixCull vs PM / LR" 对比表
- Showcase 页面 — 用户作品集 + 案例

### v2.0+(长期愿景)

- 完全 chromeless lightbox(Arc-style)
- 真正的多窗口工作台(DaVinci Resolve 的 page workflow)
- "AI 在思考"的视觉化 — 训练 / VLM 调用 / CLIP encoding 实时 progress
- 移动端原生 app(iOS 已有 PixCullCompanion 基础)
- 摄影师社群:其他 photographer 的 style profile 可以"借鉴"

---

## 3. 一个具体的「signature moment」提案

如果只能加 ONE 件事让 PixCull 有"被记住"的瞬间,我选:

**Hero reveal + score count-up + brand gradient on the 综合分**

打开 `/results/<run>` 时:
1. **0-300ms**:workspace bar 从顶部 slide-in。Library 侧栏从左 slide-in。
2. **200-1000ms**:grid 卡片从底部 stagger fade-up(每张延迟 16ms)。
3. **300-1500ms**:workspace stats 数字 count-up — keep / maybe / cull 从
   0 跳到当前值。
4. **500-1200ms**:每张卡片右下角的 score 数字也从 0 → final score
   count-up,数字本身用品牌 gradient 渲染。
5. **600-2000ms**:每张卡的 decision dot(keep/maybe/cull glyph)从中心
   scale 0→1 + soft bounce overshoot(我们新的 signature curve)。

总共 2 秒 reveal,之后是 instant 交互。

为什么这个 ROI 最高:
- **唯一性**:其他 photo culling 产品(LR / C1 / PM)的 result 页都是
  static load。我们的 reveal 是行业里没有的视觉签名。
- **可分享**:用户截图 / 录屏发朋友圈,这个 reveal 是 watch-worthy。
- **品牌 vehicle**:每次用户打开 results,gradient + soft-bounce 这俩
  signature 元素被 reinforce 一次。1 个月后用户能凭这两个元素回想起
  "PixCull"。
- **实现成本**:CSS animation + 已有的 stat-pulse(P2 2/4)+ count-up
  helper。预计 1-2 天。
- **可关闭**:`prefers-reduced-motion` 时整个 reveal 退化为 static load
  。无障碍 ok。

---

## 4. PM 视角的 caveat — 不要为了 design 而 design

写到这里要狠狠 reality-check 一下。**审美和视觉提升不会自动转化为产品
成功**。LR 的视觉一直是行业标准,但 LR 的市场份额是被 Adobe 月费订阅
模式 + Creative Cloud bundle 锁定的;Photo Mechanic 难看一辈子但
photographer-pro 还是买,因为它"快"。

PixCull 当前的核心优势:
1. **本地优先** — pro 在意数据不上云
2. **AI 选片** — 替代 30 分钟的人工初选
3. **风格 clone** — 学习个性偏好(v0.7 + v0.8)
4. **完全 open source + 免费**

视觉提升放大上述价值。但如果有 100 小时的工作时间,**40 小时投视觉**(本
audit 的内容)、**30 小时投产品功能深度**(v0.8-P0-2b/c/d 的 SQLite +
mDNS + 双向 push、Active Learning 主动学习改善、风格 clone 的 evaluation
benchmark)、**30 小时投市场内容**(pricing 页 / case study / "Why I built
this" 博客发表 / ModelScope studio 升级)是最佳分配。

**不要为了"看起来潮"砍掉产品功能投入。**审美是 leverage,不是 substitute。

---

## 5. 建议的下一步

1. **立刻**:把 v0.9-P0-1 brand identity 拆成 3 个 sub-slice 排进 v0.9
   charter。先做 signature motion curve(改一行 CSS 变量,半天)以验证
   "这一改全产品瞬间提升"。
2. **本周**:决定要不要把 Cmd+K command palette 作为 v0.9 的 hero 功能
   推上去 — 它是单点最大的"产品级"信号,值得占一整周。
3. **下周**:cli_audit PDF + /share 客户页 重做(共 1 周)。直接影响
   交付物专业度,客户拿到的"输出物"上一个 grade。
4. **v0.9 charter 完整写出来**(参照 v0.4 / v0.7 / v0.8 charter 体例)
   ,把上面所有 P0 / P1 拆成 11-13 个 ticket。

---

audit 完。

charter timestamp: 2026-05-23
expected follow-up: v0.9 charter draft within 1 week
related docs: ROADMAP-v0.4-charter.md, ROADMAP-v0.7-charter.md,
ROADMAP-v0.8-charter.md
