# v0.4 charter — UI/UX overhaul

## 用户反馈(2026-05-21)

> "下一轮迭代时,需要新增对产品UI/UX的全面升级,目前还太像一个demo,
> 而不像一个公开发布的产品,UI/UX设计的一点也不潮流和有设计感和审美"

也就是:**当前 UI 像 demo,不像 product**。需要审美级别的全面重构,
不只是局部 polish。

## 诊断:为什么当前 UI 像 demo

v0.2 → v0.3 prep 这 4 轮迭代专注在 ML correctness + workflow
深度(P-AI-5.x 系列、P-PRO-x audit 系列)。UI 是叠出来的:每个
ticket 加一个 chip / banner / toggle,但没有人做过一次「整体审美
pass」。结果:

1. **配色割裂**:深色背景 #0b0d10 是干净的,但每个 ticket 加的
   chip 用了自己的色板:cull-reason 红 / review-me 黄 / moment 粉 /
   peak 金 / a11y 蓝 / multi-tab 琥珀 / pie 七彩。一张 card 上可能
   同时出现 5 种颜色 chip,视觉噪音爆炸。

2. **typography 单调**:全站基本上 13px Inter,不分层级。h1/h2/
   meta-line/code 全在 11.5-16px 之间游走,没有大跨度的视觉锚点。
   现代 product UI 通常会用 24-32px 大标题 + 11px 细体小字制造
   节奏感。

3. **间距不一致**:CSS 里有 `--space-1` 到 `--space-6`,但 chip /
   pill / button 各自用了硬编码 padding(8px 14px / 1px 6px /
   5px 11px),没人系统使用 space scale。

4. **没有 motion design**:除了 P-UX-26 onboarding pulse,几乎所有
   状态变化都是 instant(`display: none` → `display: block`)。
   现代 product 普遍用 200-300ms 的 ease-in-out 过渡,让 UI 看
   起来「活」。

5. **图标系统散乱**:emoji (🪣 🏆 💒 ♿ ✕ ⚠) 混合 Unicode 符号
   (✓ ?  ⇆ ↩) 混合 ASCII (X ✕)。视觉重量不一致。

6. **无视觉品牌**:logo 是文本「分析结果」+ 灰色「← 上传新一批」。
   没有 product mark,没有色彩品牌,没有 hero 图。访客打开第一眼
   就觉得「这是个内部工具」。

7. **空状态/loading 状态简陋**:loading 就是 toast「上传中...」;
   空状态就是「当前筛选下没有图片」+ 重置按钮。现代 product UI
   会用插画 / 微交互让这些时刻不那么 utilitarian。

## v0.4 工作范围

### 必须做(P0)
- **设计系统建立**:tokens(color / typography / spacing / radius /
  shadow / motion duration)落地到 `pixcull/report/templates/
  design-tokens.css`,所有现有 chip/pill/button 改用 token。
- **统一 chip 设计语言**:所有状态 chip 用同一个形状(pill,
  border-radius 6px / 12px)+ 同一组语义色板(success/warn/
  danger/info/neutral),配 SVG icon 而不是 emoji 混搭。
- **品牌**:产品 logo(SVG)+ wordmark + accent color。
- **typography 节奏**:hero 28px / section 16px / body 13px /
  meta 11px,line-height 1.5/1.6。

### 应该做(P1)
- **motion design**:页面切换、modal 进入/退出、chip toggle、
  filter 应用都加 240ms cubic-bezier 过渡。
- **空状态/loading 插画**:7-10 个常见状态(空 grid / 空 bucket /
  上传中 / 分析中 / 出错 / 离线)各做一张 SVG 插画。
- **图标系统**:全站 emoji 替换为 inline SVG sprite(图标库:
  Lucide 或 Phosphor 风格),保持 emoji 仅在 UI chrome 之外
  (e.g., cull-reason 文案里 ✕)。
- **首屏 hero**:上传页 / `/`改成 hero 风格(产品名 + 一句 value
  prop + CTA + screenshot/animation)。

### 想做(P2)
- **dark / light theme switch**:当前固定 dark,加 light 模式
  + system preference 检测。
- **mobile 二次 pass**:P-UX-17 把移动端做能用了,但还不漂亮 —
  bottom-sheet pattern 替换 modal,thumb-friendly tap targets
  ≥44pt。
- **键盘交互 micro-interaction**:每次 1/2/3 标注后 card 给一个
  微弹动(scale 1.05 → 1.0)+ 颜色 ripple,让 keyboard culling
  体验更生动。
- **导出 PDF 报告**:cli_audit 的 markdown 报告加一个 "Generate
  PDF" 路径(weasyprint / Chromium headless)— 给客户看的高质
  量交付文档。

## 建议外部资源 / 灵感参考

- **Linear** (linear.app) — 深色 + 高对比 + 精致 typography 的产品级标杆
- **Notion** — 状态 chip 设计语言极佳
- **Vercel** — wordmark + landing page 的最佳实践
- **Lucide / Phosphor** — 开源 SVG 图标库
- **Apple Photos / Lightroom CC** — 同行业 hero 图设计

## 不做的事情(scope discipline)

- 不重写整个 web 框架(不上 React / Vue / Svelte;继续 vanilla JS)
- 不引入 npm / build tooling(继续 zero-build,direct-edit results.html)
- 不动核心 ML 代码 — v0.4 是 UI/UX 轮回,ML 部分保持 v0.3 状态

## 验收标准

打开 `/results/<run_id>` 第一眼:**应该看不出这是一个 1500 行单
文件 vanilla JS 的工程**。它应该像一个 funded SaaS 产品的 dashboard。

---
charter timestamp: 2026-05-21
expected start: 紧接当前 v0.3 prep
expected duration: 3-4 周(v0.4 release)
