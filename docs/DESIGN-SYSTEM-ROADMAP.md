# 设计系统升级路线图 · Design system uplift roadmap

> **现状坦白:** PixCull 当前的视觉传达**"AI 味"过重** —— 像 LLM 生成的
> demo,不像被设计师精心打磨的成品。本文档承认这个差距,列出**为什么**
> 它会这样,然后给出**可执行的升级路径**:工具链选型、设计资产清单、
> 阶段化交付计划。
>
> **Status, honest:** PixCull's visual surface still reads "AI-generated
> demo" rather than "designed product".  This doc names the gap, explains
> the root causes, and lists the concrete tools + assets + phases needed
> to close it.

---

## 1 · 当前为什么"AI 味重"——七项症状诊断

| # | 症状 | 当前实现 | 为什么"AI 味" |
|---|---|---|---|
| 1 | **没有真人设计师介入** | UI 由开发者直接写 CSS / SVG | 配色、字号、间距都是"程序员品味默认安全选" |
| 2 | **字体全用系统栈** | `-apple-system, BlinkMacSystemFont, Segoe UI…` | 没识别度,任何应用都长一样;真正的产品都有 **own typeface** |
| 3 | **占位 SVG 而非定制插画** | 5 个 v0.4 + 5 个 v0.9 共 10 个,几何风格 | 形态像 Heroicons / Lucide 默认,缺少品牌"语气" |
| 4 | **brand gradient 来自 Tailwind 灵感** | indigo→violet→pink (`#6E56CF` etc.) | 接近 Linear / Stripe 调色板;不是为 PixCull 调过的 |
| 5 | **emoji 散落在 UI** | `🪣 交付桶` / `📡 协作中` / `🏆` | 跨平台渲染不一致(iOS Safari emoji ≠ Chrome ≠ Windows) |
| 6 | **文案像产品规范书** | "支持 9 种细分领域 (verticals)" | 真品牌写"我们帮你晚上 8 点交片,而不是凌晨 3 点" |
| 7 | **demo 数据看起来像测试数据** | "sample_06_sunset.jpg" + 6 张样例 | 真摄影师 portfolio 是 4000 张里挑 5 张 |

**根因:** 项目从 v0.4 起的 UI 工作全部由 **AI 协助下的开发者一人完成**。
这种"开发者 + AI"模式能在功能层做到非常高(v0.10 实测 614 个测试通过、
57 个 commit、零回归),但**永远做不到"设计师品味"** —— 因为缺少
被打磨过的审美直觉介入。

**Fix 不是再写更多 CSS**,fix 是引入下面 §3 的工具链 + 设计师协作流。

---

## 2 · 借鉴对象——七个被精心设计的对照产品

每一个,我们能学到一件具体的事:

| 对照产品 | 学什么(具体到一句话) |
|---|---|
| **Linear** | brand gradient 永远只在**关键瞬间**(loading bar / Cmd+K)出现,而非到处堆砌 |
| **Stripe** | dashboard data density · 同一行能塞下 8 个数字而不挤,得益于精心调过的字号 + 字重梯度 |
| **Notion** | slash menu 的 hover 状态用了 4 种不同灰度;不是简单 hover→accent |
| **Apple Photos** | Memories 开场 2 秒的 stagger / scale / opacity 配合,**手工调出来的非线性曲线** |
| **Raycast** | 没有任何 emoji;所有 icon 都是同一支笔画粗细的 stroke 系统 |
| **Pixelmator Pro** | 工具栏图标都是定制设计的、有"主题感"(扁平 + 微立体) |
| **Affinity Photo** | 自家 typeface `Affinity Sans`,即便细微也能识别"这是 Affinity 产品" |

**共同点:** 这些产品都有专业**视觉品牌设计师**全程介入,且都有
**design system 当作 first-class 产品** —— 不是事后补的文档。

---

## 3 · 工具链选型 — 从"开发者直接写 CSS"升级到"设计师 + 工程师协作"

下面 5 类工具是必备的;每一类给出**首选 + 备选**,并标注是否免费 / 开源
(契合 PixCull 本地优先的开源精神)。

### 3.1 · UI 设计 / prototyping

| 工具 | 用途 | 备注 |
|---|---|---|
| ⭐ **[Figma](https://www.figma.com/)** | 主设计文件 + design system + 原型 | 业内标准,个人 free;但 Adobe 收购增加锁定风险 |
| **[Penpot](https://penpot.app/)** | Figma 开源替代 | 完全本地化可部署;契合 PixCull 本地优先精神;UI 略不熟 |
| **[Framer](https://www.framer.com/)** | 高保真交互原型 + 实际可发布站点 | 适合 marketing 页;主产品仍用 Figma |

**建议:** **Figma 主、Penpot 备**。把 PixCull design system 放在 Penpot
开源镜像,定期同步;Figma 文件可发给签约设计师 / 自由职业者协作。

### 3.2 · 字体 / 排版

| 工具 / 资源 | 用途 |
|---|---|
| ⭐ **[Glyphs](https://glyphsapp.com/)** ($299, macOS) | 真正自己绘制 typeface 的工具(若有此预算) |
| **[Fontsource](https://fontsource.org/)** | 自托管开源字体打包 |
| **[Adobe Fonts](https://fonts.adobe.com/)** | Creative Cloud 订阅包含,正版授权 |
| **[Variable Fonts Playground](https://v-fonts.com/)** | 选 variable font 时的预览工具 |

**建议:** 短期内**用一支精心选的开源字体** —— 推荐 [Inter](https://rsms.me/inter/)
作为 sans-serif(已经在用)+ [PP Editorial Old](https://pangrampangram.com/products/editorial-old)
作为 display serif(目前用的 `Charter` 系统字体作为权宜之计)。
中长期(v1.0 之后)考虑定制 `PixCull Sans` —— 摄影师社区识别度的来源。

### 3.3 · 插画 / icon system

| 工具 | 用途 |
|---|---|
| ⭐ **[Phosphor Icons](https://phosphoricons.com/)** | 已经在用部分;考虑全产品统一到 Phosphor 而非自画 |
| **[Lucide](https://lucide.dev/)** | Phosphor 的免费替代,stroke 风格更细 |
| **自己画 / 委托** ([Reshot](https://www.reshot.com/) / 独立插画师) | empty-state 插画建议**全部委托一个插画师**重画 — 这是项目品质升级 ROI 最高的一步 |

**建议:** **icon 用 Phosphor 全产品统一**(替换现存的混搭 inline SVG);
**5 + 5 = 10 个 empty-state 插画委托独立画师重画**(预算 RMB 5,000-15,000),
风格统一到"editorial line-drawing with brand-gradient accents"。

### 3.4 · 动画 / motion

| 工具 | 用途 |
|---|---|
| ⭐ **[Rive](https://rive.app/)** | interactive motion + 状态机 — 替代 Lottie 的未来选择 |
| **[Lottie](https://lottiefiles.com/)** | After Effects → JSON 工作流;成熟但 Adobe 锁定 |
| **[Easings.net](https://easings.net/)** | 选 cubic-bezier 曲线时的查询表 |
| **[Cubic-bezier.com](https://cubic-bezier.com/)** | 自定义曲线时的交互工具 |

**建议:** v0.9-P0-1 的 `soft-bounce` 曲线已是工程上的"signature curve",
**v1.0 前给它取个名字**(`pixcull-overshoot`?),写进 design system。
hero reveal 用 **Rive** 重写,可以更细腻 + 状态化(目前是 CSS keyframes,
表达力有限)。

### 3.5 · 设计系统 / token

| 工具 | 用途 |
|---|---|
| ⭐ **[Tokens Studio](https://tokens.studio/)** | Figma 插件;design token → JSON → CSS variables 的桥梁 |
| **[Style Dictionary](https://amzn.github.io/style-dictionary/)** | Amazon 出品;多平台 token 输出(CSS / iOS / Android) |
| **[Storybook](https://storybook.js.org/)** | 组件库视觉文档;v1.0 后值得引入 |

**建议:** Tokens Studio + Style Dictionary 组合 ——
设计师改 Figma,token JSON 自动同步到 `pixcull/design-tokens.json`,
构建时 `style-dictionary build` 输出 `design-tokens.css` + 同名 Swift /
Kotlin 常量。**这一步把 design system 从"15k 行 results.html 里硬编码"
升级到"设计师可改、工程可消费"**。

---

## 4 · 阶段化升级计划 · Three-phase uplift

不一次做完,分**三阶段 6 个月**逐步交付。每阶段独立可验证。

### Phase A · "设计基础设施"(2 周 · v0.11 P0 平行做)

**目标:** 把目前 15k 行 results.html 里的 CSS variables(brand gradient /
typography ramp / 24 个 surface / shadow stack)**整体抽出**到一个独立的、
设计师可编辑的源文件。

**交付物:**

1. `design-system/` 新顶级目录
   ```
   design-system/
   ├── tokens.json          ← 单一来源 · Tokens Studio 兼容
   ├── tokens.css           ← 自动生成 · build step 产物
   ├── ios.swift            ← 自动生成 · iOS Companion 消费
   ├── README.md            ← 颜色 / 字号 / 间距规范
   └── figma.fig            ← 同步 Figma 库文件(每周同步)
   ```
2. `scripts/build_design_tokens.py` — JSON → CSS / Swift 转换器
3. results.html `<style>` 块开头 `<link rel="stylesheet" href="/static/tokens.css">` 替换内联 token 定义
4. CI 检查:**禁止**在 results.html `<style>` 中直接写颜色十六进制 — 全部走 `var(--color-*)`

**验收:** 设计师改 `tokens.json`,跑 `make tokens`,所有平台(web + iOS +
PDF + cli_audit)同时换色,**不需要工程介入**。

---

### Phase B · "委托设计师介入"(2 个月 · v0.11–v0.12 期间)

**目标:** 由真人**视觉品牌设计师**(自由职业者或工作室)做一次完整的
品牌 + UI 审计 + 重设计。

**交付物:**

1. **品牌指南** (`docs/BRAND-GUIDE.pdf`,设计师产出)
   - 调色板(包含明 / 暗 / 高对比 a11y 三套)
   - typography ramp(包含中 / 英 / 日 / 韩 / 西文五语种字体配对)
   - logo 完整 lockup 集
   - motion 曲线规范(可写进 CSS variables)
   - "PixCull 的语气"文案指南(给文案写手)
2. **重画 10 个 empty-state 插画** — 替换 v0.4 P1 + v0.9 P2-3 的混搭
3. **Figma 组件库**(同步到 design-system/figma.fig) — `.card`、`.chip`、`.modal`、`.button` 5 大族,每族 6 个状态
4. **3 个 marketing screenshot**(委托摄影师 + 设计师拍 / 修)
   替换 README 里的"实机截图(2022 川西行)"那 5 张
5. **icon system 全产品统一** — 删除现存所有内联 SVG,
   全用 Phosphor + 5 个定制(brand mark / radial progress dial / share-link / sparkline / portfolio-arrow)

**预算估算:**

- 视觉品牌设计师(中级,自由职业):1 个月 × RMB 15,000–25,000
- 插画师(委托 10 个):RMB 5,000–10,000
- 摄影师(marketing 拍摄):RMB 3,000–8,000
- **总计 RMB 23,000–43,000**

**验收:** 一个不知情的视觉设计师对照 v0.10 vs Phase B 的截图,
盲评"哪个像精心设计的产品",**Phase B 截图胜出**。

---

### Phase C · "自有 typeface + Rive motion"(v0.13 时机 · 6 个月后)

**目标:** 让 PixCull 的视觉**有独立识别度**,任何摄影师看一眼就知道
"这是 PixCull"。这是品牌品质的最后一步。

**交付物:**

1. **定制 `PixCull Sans`** —— 一支 variable font,
   基于 Inter 改造(weight 200–900,optical size 12–48,
   3 套数字字形:tabular / lining / oldstyle)
2. **Rive 重做 hero reveal** —— v0.9-P0-2 的 CSS 版本可用,
   但表达力有上限;Rive 状态机能做到"卡片摆动时被鼠标干扰会自动调整"
3. **App icon 重新设计** —— 现存的 brand mark(SVG "spotlight on
   one in a crowd")作为 logomark 是 OK 的,但 macOS dock icon
   需要更精细的多 size 渲染(16 / 32 / 64 / 128 / 256 / 512 / 1024)
4. **品牌延伸物料**:
   - 4 张 Apple Press Kit 风格的高分辨率 PNG
   - 一段 30 秒 trailer video(Rive 输出 + After Effects 后期)
   - 一份单页 PDF "产品介绍"(委托给做过 Stripe / Linear marketing 的 studio)

**预算估算:**

- typeface 委托(中级 type designer):RMB 30,000–60,000(2-3 个月)
- Rive 动效师:RMB 8,000–15,000
- App icon refresh:RMB 2,000–5,000
- Press kit + trailer:RMB 10,000–20,000
- **总计 RMB 50,000–100,000**

**验收:** 截图贴到 ProductHunt / 小红书,**用户回复里出现"这字体好看"
/"这个动画好讲究"**(而非"功能很强")。

---

## 5 · 短期内一个工程师能做的事 — 不等设计师,先动起来

如果上面三阶段需要预算 + 时间,**短期内有 5 件事工程师自己就能做**,
立刻让"AI 味"降低一个等级:

### 5.1 · 删 emoji,统一到 Phosphor 图标系统(半天)

把 `🪣` / `📡` / `🏆` / `📷` 等全部替换成 Phosphor 1.6px stroke 图标。
**理由:** emoji 跨平台不一致,且是"开发者偷懒"的典型符号。

### 5.2 · 引入一支真 serif 字体替代 Charter 系统字体(1 小时)

```html
<link rel="stylesheet" href="https://api.fontshare.com/v2/css?f[]=editorial-new@400,500,600,700&display=swap">
```
然后把 `--font-serif: 'Charter', ...` 改成 `--font-serif: 'Editorial New', serif`。
**理由:** Fontshare 上 Editorial New 是免费商用,且远比 Charter 有识别度。

### 5.3 · 把 demo 数据换成真摄影作品(2 小时)

`scripts/serve_demo.py` 里 `/sample_demo` 内置那 6 张"sample_*.jpg"
都很泛泛。换成**真摄影师作品**(自己拍的 2022 川西行 + 朋友的婚礼,
征得同意):每张配真实 metadata + 真 verdict。
**理由:** demo 看着像 demo,因为数据像 demo。

### 5.4 · 给文案做一次"摄影师 voice"重写(1 天)

当前 README 写法:**"6 维评分 / 9 种细分领域 / 跨机同步"** —— 程序员视角。
重写视角:**"主摄完工是凌晨 3 点;PixCull 把这变成晚上 11 点"** ——
摄影师视角,陈述用户痛点 + 解决方案。

### 5.5 · 接入 Tokens Studio + Style Dictionary 雏形(2 天)

不必完整重构,先把 brand gradient + 6 个 spacing token + 3 个 shadow
抽出来到 `design-system/tokens.json` + `tokens.css` —— **这是 Phase A 的
最小可行版本**,后续设计师就有切入点了。

---

## 6 · 衡量"是否变好了"——3 个客观指标

升级是否成功不是看个人观感;用 3 个能复现的指标:

1. **盲测对比**: 同一截图,Phase B 后让 5 位不知情的视觉设计师按"看起来精致度"打分,**目标 4.0/5 以上**(当前估计 2.5/5)
2. **品牌识别度**: 把 PixCull screenshot 与其他 5 个 AI 工具的截图并排,**目标:90% 受访者能在 < 5 秒挑出 PixCull**(当前估计 < 30%)
3. **用户文案反馈**: 在 ProductHunt / 小红书发布后,**评论里"设计"/"质感"/"漂亮"/"精致"关键词出现频次**,目标 > 30% 评论提到(当前估计 < 5%)

---

## 7 · 不做的事(scope discipline)

升级路径上要保持纪律的:

- **不放弃本地优先 / 开源精神** —— 即便引入 Figma 等闭源工具,
  最终交付物必须可以在 Penpot 中复现
- **不引入 React / Vue / Svelte** —— vanilla JS 在 v0.10 已经撑过 15k+ 行,
  设计系统升级**只换 CSS 与 SVG**,不动 JS 架构
- **不向 SaaS 化妥协** —— 即便设计 polish 后产品看起来像"应该收费的",
  本地优先 + 开源不变,商业化通过 v0.11 的 license CLI 处理
- **不把动效加到所有地方** —— Linear 的 lesson:gradient 与 motion 是
  signature moment,**不是每个 hover 都要触发**
- **不复制竞品** —— 学习他们的**做事方式**,不是抄他们的视觉

---

## 8 · 时间表 · 6 个月规划

| 月 | 阶段 | 主要交付 | 工程师工作量 | 设计师工作量 |
|---|---|---|---|---|
| **M+0** | §5 短期 5 步 | emoji 去除 + Editorial New + demo 数据 + 文案重写 + Tokens Studio 雏形 | 1 周 | — |
| **M+1** | Phase A 完成 | design-system/ 完整目录 + CI 检查 + Figma 同步流 | 1 周 | (Figma 起步) |
| **M+2-3** | Phase B 执行 | 设计师介入,品牌指南 + 10 插画 + Figma 组件库 | 评审 + 集成 = 1.5 周 | 2 个月 |
| **M+4** | Phase B 落地 | 品牌指南实装到 v0.12 release | 2 周 | 1 周(交付支持) |
| **M+5-6** | Phase C(高预算时) | 自有字体 + Rive motion + App icon + Press kit | 1 周 | 3-4 个月 |

---

## 9 · 立刻可执行的下一步 · "今天就能做的事"

如果**今天**就要让产品看起来不那么"AI 味":

1. **跑 §5.1**(半天):删除产品里所有 emoji,换 Phosphor
2. **看 §5.2**(1 小时):换字体到 Editorial New
3. **写 §5.4**(1 天):README 用"摄影师视角"重写
4. **接 §5.5**(2 天):design-system/tokens.json 雏形

完成以上 4 件事 ≈ 3.5 天工程,**主观品质感会有可感知的提升** ——
不是 "Phase B + C 完美",但够让"demo 感"明显下降。

---

## 10 · 引用 / further reading

- **[Refactoring UI](https://www.refactoringui.com/)** —— Adam Wathan 与 Steve Schoger,程序员视角学 UI
- **[Practical Typography](https://practicaltypography.com/)** —— Matthew Butterick,排版圣经
- **[Design Systems Handbook](https://www.designbetter.co/design-systems-handbook)** —— InVision 免费电子书
- **[Linear's Brand Guide](https://linear.app/brand)** —— 标杆 design system 公开范例
- **[Stripe's Press Kit](https://stripe.com/newsroom/brand-assets)** —— marketing 物料的工业级参照
- **[Figma Config 2024 talks](https://config.figma.com/)** —— 当代 design system 实践分享

---

*Document timestamp: 2026 Q4 · 配合 v0.10 release + v0.11 charter 起草*
