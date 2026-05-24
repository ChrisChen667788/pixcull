# v0.9 charter — Brand identity + signature moments + Cmd+K + craft polish

## 上下文(2026-05-23)

v0.4 → v0.8 共 33 个 slice、5 个 charter、几乎覆盖了一个"功能完整"
photo culling 产品的所有功能面:

- **v0.4**(UI/UX overhaul):design tokens · chip 系统 · motion · button
  system · SVG icon sprite · empty states · hero landing · light theme ·
  stats pulse · mobile pass · PDF 导出
- **v0.5**(LR-grade aesthetic):condensed workspace · LR Library card ·
  LR Loupe filmstrip
- **v0.6**(UI 收尾):LR Library 侧栏 · LR Develop Inspector · token
  migration(upload/admin)· drag-reorder buckets · thumb buckets ·
  hold-Space cheat sheet
- **v0.7**(收尾 + 中型新功能):A/B 比较窗 · annotation modal · 5k+
  稳定性 · loupe RGB · Inspector mobile bottom-sheet · 视图预设 v2 ·
  客户分享链接 · 风格 clone V1 · tethered live · Sparkle 自更新 infra ·
  /history
- **v0.8**(分发 + 协作 + V2 + i18n):i18n 基础设施 · LAN 协作 ·
  风格 clone V2 (CLIP) · 短链 + 二维码 · EN+JA 多语 · 结构化 CSV/JSON ·
  launch post 刷新 · ModelScope studio v0.8

但 v0.8 之后的 `docs/DESIGN-AUDIT-2026Q3.md` 自检(对照 Linear /
Stripe / Vercel / CapCut / Pixelmator / Resolve / Apple Photos)发现
PixCull 已经是 "**competent product**" — 不是 "**iconic product**"。差距
集中在五维:

1. **审美**:没 motion identity / 没 hero reveal moment / 没 AI 视觉化 /
   light theme 是 afterthought
2. **视觉**:`#6366f1` 是 Tailwind 默认 indigo / 没 signature gradient /
   typography 单一 / logo 不强 / emoji 还散落
3. **IxD**:**没 Cmd+K command palette**(单点最大现代 pro tool 信号
   缺失)/ 没 multiplayer presence / iPad 仍是 90 年代 web / 没 undo
   反馈 / progress 是 spinner
4. **UI**:card hover 没 floating actions / 4 类 modal 视觉权重相同 /
   filter group 没 color hints / table view 不存在
5. **输出专业度**:/share 裸 grid 不是品牌作品集 / cli_audit PDF 没
   cover/ToC/dashboard / 没 Lr Catalog import 模板

v0.9 主线:**"从 competent 到 iconic — brand + signature moments +
keyboard-first + craft polish"**。

## 诊断 — 为什么这一轮重点是"审美 + IxD",不是"功能"

PixCull 当前缺的不是功能(v0.8 把功能塞得很满),缺的是**让人记住、想
截图分享、想推荐给朋友的"产品级"质感**。Linear 的 Cmd+K、Stripe 的紫
橘 gradient、Apple Photos 的 Memories 开场、Notion 的 / slash —
这些都不是"功能",是"identity"。

v0.9 的 11 个 ticket 全部围绕这点:让用户每次打开 `/results/<run>` 都
有"哇,这个产品做得真精致"的瞬间。

## v0.9 工作范围

### P0(必须做)

#### v0.9-P0-1 · Signature motion curve
**估时**: 0.5 天

把所有 transition / animation 的 ease 从 `cubic-bezier(0.16, 1, 0.3, 1)`
("ease-out")换成 `cubic-bezier(0.34, 1.56, 0.64, 1)`("soft-bounce" —
终点带 6% overshoot)。**单一最大的"审美感"提升**。改一行 `--ease-out`
CSS 变量,全产品 200+ 处过渡瞬间变得"活"。

#### v0.9-P0-2 · Hero reveal animation(signature moment)
**估时**: 1-2 天

打开 `/results/<run>` 时:
1. 0-300ms: workspace bar slide-in + Library sidebar slide-in
2. 200-1000ms: grid 卡片从底部 stagger fade-up(每张 +16ms)
3. 300-1500ms: workspace stats 数字 count-up
4. 500-1200ms: 每张卡 score count-up + brand gradient 数字
5. 600-2000ms: decision dot scale 0→1 + soft-bounce overshoot

2 秒总 reveal,之后 instant。**业内其他 culling 产品(LR/C1/PM)result
页都是 static load — 我们的 reveal 是行业里没有的视觉签名**。可截图
分享。prefers-reduced-motion → 退化为 static load。

#### v0.9-P0-3 · Brand identity 重做
**估时**: 1 周

3 个 sub-ticket:
- **3a. Signature gradient**:定义 `--brand-gradient: linear-gradient(135deg,
  #6E56CF, #EC4899)`(紫粉,类似 LR 的"色调"渐变 — 也跟现有 indigo 协调)。
  应用到 logo wordmark、primary CTA、loading bar、QR 码 brand-frame、
  score 数字大处、stats 数字。"看一眼 PixCull 知道是 PixCull"的视觉锚点。
- **3b. Logo mark 重做**:当前 "wireframe star" 传"分散"感不是"culling"。
  新 mark 提案:一颗大圆(gradient 填充)+ 周围几颗小圆(muted)— 视觉
  传达"我们帮你挑出那一颗"。SVG ~20 行。
- **3c. typography accent**:hero / 大数字用 PT Serif(open source,
  优雅,Inter 协调)。body 仍 Inter。改 `--font-display` token,只影响
  hero `<h1>` + stats 大数字。

#### v0.9-P0-4 · Cmd+K command palette
**估时**: 1 周

Linear / Notion / Raycast 的 keyboard-first 入口。20+ actions 可触达:
- 跳到 historical run XYZ
- 切换 lang (中/EN/日)
- 训练风格模型
- 应用 view preset X
- 打开 X bucket
- 跳到下一个 cull candidate
- 导出 X
- 触发 admin perf 调试页
- etc.

**单点最大的"产品级"信号**。markup ~150 行 + 一个轻量 fuzzy matcher
(string score)。

#### v0.9-P0-5 · /share 客户页重做
**估时**: 1 周

当前是裸 grid + filename caption。重做为"摄影师作品集"形态:
- 品牌头:摄影师 logo(可上传)+ 客户姓名 + 事件名 + 日期
- Metadata block:拍摄地点 + 设备分布 + 总数 + 选片数 + 比例
- 章节结构(可选):若 wedding_moment 标了,自动分章节
  (仪式 → 入场 → 致词 → kiss → 合影 …)
- Lightbox 内可调缩放(LR Loupe 风格)
- 客户评论框(POST 回 /annotation API)
- Footer signature 块:摄影师签名 + 联系方式 + Powered by PixCull

直接影响"摄影师交付给客户的东西" — 从工程感变作品集感。

### P1(应该做)

#### v0.9-P1-1 · Card hover floating actions + Modal 视觉差异化
**估时**: 4-5 天

- Card hover 右上角浮 3 个 28×28 icon button(👁️ 放大 / 🪣 加桶 /
  ⇆ 比较)。提升发现率,减少右键依赖。Linear / Trello 同款。
- 4 类 modal 视觉差异化:
  - info(shortcuts / share-URL)→ neutral border + 默认 close X
  - action(annotation / bucket export)→ accent border-top + 主色保存
  - destructive(删桶 / clear all)→ danger 红 border-top + 红色 confirm
    + 主色 cancel(reverse pair 要求用户 deliberate)

#### v0.9-P1-2 · Multiplayer presence(协作模式可见性) ✅
**估时**: 2-3 天 · **实际**: 1 天 · **已发布**

v0.8-P0-2 的 LAN 协作只有 polling 增量,看不到"另一个人此刻在看哪张"。
v0.9 已加:每个连接客户端每 30s heartbeat,workspace bar 上的 indigo
**presence pill** 实时显示 "👁️ 二摄-AB12 正在看 IMG_001"(单 peer)或
"👥 3 协作者在线 · 详情"(多 peer)。点 pill 打开弹层显示每位 peer 的
头像 + 当前看的照片 + 最近动作(✅ 标 keep · IMG_002 · 12s 前)+ 最近活跃。

后端
- 新模块 `pixcull.sync.presence` —— per-event JSON store,atomic write
- POST `/sync/event/<token>/presence` —— heartbeat / disconnect 复用
- GET `/api/v1/sync/event/<token>/presence?exclude=<cid>` —— peers 列表
- 90s stale TTL evict ghost peers · 32 peer hard cap

前端
- `client_id` per-tab(sessionStorage)· `display_name` per-browser(localStorage)
- 30s heartbeat + 10s poll · `_markLocalEdit(fn, action)` 自动触发额外 beat
- `sendBeacon` on pagehide / visibilitychange === hidden 即时 disconnect
- 7 zh action verbs(keep/maybe/cull/star/bucket/ann/edit)→ emoji + 中文

测试: 9 new tests in `tests/test_sync_presence.py`(field truncation,
stale TTL evict, MAX_PEERS cap, atomic write, drop_peer idempotency, ...)。

#### v0.9-P1-3 · PDF executive summary + Strava-style annual review ✅
**估时**: 4-5 天 · **实际**: 1 天 · **已发布**

`cli_audit --pdf --executive --client ... --event ... --event-date ...`
产生一份 11 页 A4 客户交付 PDF:

1. **Cover**: brand SVG + 摄影师 eyebrow + serif gradient 标题(`Charter`)+
   客户名 + 日期 + 提交 / 入选 / 入选率 3 个 keynum
2. **ToC**: serif decimal-leading-zero 编号 + dashed page break
3. **Dashboard**: Strava-annual-review 风格 6-card grid(入选率 hero card +
   提交张数 / 需复核 / 已剔除 / 综合分中位 / 人工标注 + scene chips row)
4. **最佳 5 张**: 5-up thumbnail wall,brand-gradient "BEST" badge,
   综合分 chip,score-sorted keep rows
5. **需要复核的 3 张**: human-vs-model 不一致 → 边界分 fallback,
   "WATCH" badge + 模型决定 + 综合分 注释
6. **未入选原因 top 5**: horizontal bar chart,brand-gradient fill,
   zh-CN cull reason 翻译(对焦不准 / 模糊抖动 / ...)
7-11. **技术质量审计**: 现有 cli_audit 的 scene / face / wedding / ICC /
   EXIF sections,作为 PDF 的"技术附录"

新模块: `pixcull.report.executive_pdf` — pure-function data + render
layer,thumbnails as data: URIs(self-contained PDF,可发邮件)。
20 unit tests in `tests/test_executive_pdf.py`,加 1147-row 真实婚礼
run e2e:11 页 / 1.3 MB / cover 显示真实客户名 + 76% 入选率。

默认 `--pdf`(无 `--executive`)行为不变 — 5-page engineering audit PDF。

#### v0.9-P1-4 · AI 视觉化
**估时**: 3-4 天

- score_final 旁加 micro radial progress(score/1.0,亮度对应分值)
- rubric stars 旁加 sparkline 显示 6 axis values
- 所有 ML 输出(face cluster confidence、scene probabilities)visually
  encoded,不只是数字
- brand gradient 加到关键 AI 输出数字(`score_final`、综合风格距离)

#### v0.9-P1-5 · iPad lightbox(swipe + pinch + tap-zoom)
**估时**: 2-3 天

当前必须点 ←→ 箭头 / 方向键。Apple Photos 风格 swipe gesture + pinch
zoom + tap-to-zoom-here。vanilla touch event(无第三方库),~80 行 JS。

### P2(锦上添花,视情况)

#### v0.9-P2-1 · Light theme V2
**估时**: 2-3 天

当前 light theme 是 afterthought。重做 shadow(暖色调,不是 rgba(0,0,0,X))
+ 不同的 surface-2/-3 配色 + 不同的 type weight。让 light 和 dark 都有
"我精心调过这个 theme"感。

#### v0.9-P2-2 · Filter group color hints + table-first admin perf
**估时**: 3-4 天

- 8 个 library group 各加 6px leading dot,颜色对应该 group 的 semantic
  (Decision = accent / Scene = success / Style = warn / Face = info /
  Bursts = danger …)Notion-style。
- `/admin/perf` 改成 first-class data table(列可拖、列可隐藏、cell
  inline-edit)。当前是 fixed-card 布局。

#### v0.9-P2-3 · 5 个新 empty-state SVG 插画
**估时**: 2-3 天

buckets 空 / 历史空 / sync 无 peer / annotation 0 完成 / search 无结果。
每个 ~100 行 SVG,沿用 v0.4 P1 (3/4) 的两色调 palette。

## 建议外部资源 / 灵感参考

- **Linear** — Cmd+K + signature gradient + soft-bounce motion 标杆
- **Stripe** — signature gradient + dashboard data density
- **Notion** — slash menu + color-coded properties + AI 视觉化(✨ 渐变光)
- **Apple Photos** — Memories 开场动画 + swipe gesture 标杆
- **Raycast** — Cmd+K-only design 极致
- **CapCut Pro** — Z-gen 审美 + 强烈 motion + brand gradient 一致性
- **Pixelmator Pro / Affinity Photo** — chrome-less canvas-first
- **Strava annual review** — PDF executive summary 灵感

## 不做的事(scope discipline)

- 不重写 web stack(继续 vanilla JS + zero-build)
- 不引入 npm / build tooling(Cmd+K 的 fuzzy matcher 用 200 行 vanilla JS)
- 不动 ML pipeline 内核 — v0.9 关心 brand / IxD / 输出 polish,模型保持
  v0.8 状态
- 不做新语言(KO / ES) — v0.9 之后再加
- **不为了"看起来潮"砍核心功能投入** — DESIGN-AUDIT 第 4 节的 PM
  caveat。100 小时分配:40h 视觉、30h 功能深度(P0-2c mDNS、P0-2d 双向
  push、风格 evaluation benchmark)、30h 市场(本 charter 不算市场工
  作,但要 hold capacity)

## 验收标准

v0.9 release 完成的标志:

- **打开 `/results/<run>` 第一眼有 reveal moment**,卡片 stagger fade-up
  + stats count-up + score gradient 数字 — "watch-worthy 2 秒"
- **Cmd+K 召出 command palette** 可访问 20+ actions,fuzzy 匹配 < 50ms
- **brand gradient 出现在**:logo wordmark、primary CTA、loading bar、
  QR brand-frame、score 大数字 — 全 product 视觉锚点一致
- **客户拿到的 `/share/<run>/<token>` 链接** 像作品集而不像 dashboard:
  品牌头 + 章节 + 摄影师签名
- **card hover** 显示 3 个 floating action button
- **4 类 modal 视觉差异化**(info / action / destructive 区分明显)
- **协作模式下** 看得到其他成员 last-viewed photo
- **cli_audit PDF** 像 Strava annual review 而不像 markdown 输出
- **iPad 用户能 swipe / pinch / tap-zoom** lightbox 照片
- **light theme** 和 dark theme 都有"精心调过"感

## 建议执行顺序(预计 5-6 周)

| 顺序 | 任务 | 估时 | 理由 |
|---|---|---|---|
| 1 | **v0.9-P0-1** Signature motion curve | 0.5 天 | 改一行 CSS 立刻验证"全产品瞬间提升" |
| 2 | **v0.9-P0-2** Hero reveal | 1-2 天 | signature moment,可截图分享 |
| 3 | **v0.9-P0-3** Brand identity 重做 | 1 周 | 视觉基础设施,后续都依赖 |
| 4 | **v0.9-P0-4** Cmd+K command palette | 1 周 | 单点最大现代 pro tool 信号 |
| 5 | **v0.9-P0-5** /share 客户页重做 | 1 周 | 输出专业度最大提升 |
| 6 | **v0.9-P1-1** Card hover + Modal 差异化 | 4-5 天 | 体感最高 |
| 7 | **v0.9-P1-2** Multiplayer presence | 2-3 天 | 独立小项 |
| 8 | **v0.9-P1-3** PDF executive summary | 4-5 天 | 输出专业度补完 |
| 9 | **v0.9-P1-4** AI 视觉化 | 3-4 天 | brand gradient 应用面 |
| 10 | **v0.9-P1-5** iPad lightbox | 2-3 天 | iPad 体验 ×5 |
| 11 | **v0.9-P2-x** | 视情况 | 收尾 |

---

charter timestamp: 2026-05-23
expected start: 紧接 v0.8 完成
expected duration: 5-6 周(v0.9 release Q4 2026)
predecessor: docs/ROADMAP-v0.8-charter.md
related: docs/DESIGN-AUDIT-2026Q3.md
