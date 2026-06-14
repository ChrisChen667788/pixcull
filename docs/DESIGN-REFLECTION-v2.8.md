# PixCull 设计反思 + v2.8-DESIGN 重构 charter

> 触发：用户实测后判定当前 UI/UX「一塌糊涂」。这条反馈比过去 9 个季度
> DESIGN-AUDIT 自评的 4.x/5 更可信——那些自评是**自我感觉良好的失真**。
> 本文基于实看主网格 (`01-results-grid.png`) 与 lightbox
> (`03-lightbox.png`) 截图 + 联网搜集的业界标杆，给出诚实诊断与可落地方案。

## 1. 根因：功能驱动的增量堆叠 + 工程师审美

设计系统本身不弱：`results.css` 有 106 个 CSS 变量、espresso/paper 双主题、
完整的 space / radius / shadow / ease scale。**问题不在「没有设计系统」，而在
「用它的方式」**——信息架构、布局、视觉层级、强调色纪律全部失序。

病灶是**方法论**：每加一个 feature 就往界面塞一个控件 / 角标 / 数字，9 个
季度的 DESIGN-AUDIT 都在做**加法补丁**而非**减法重构**，日积月累成了「什么
都要展示」的拥挤界面。这是典型的工程师审美——把后端的每一项能力都摊在脸上。

## 2. 实看诊断（成体系的 5 大病症）

### 病症 A — 内容未居中舞台（最致命）
lightbox 是看图工具的心脏，但截图里：**照片缩在右上角小窗，屏幕中央大片死黑，
下半屏被 6 个评分维度 + 双滑块 + 胶片条的密集面板占据**。这直接违背 culling/
lightbox 的第一原则——「让用户无干扰地聚焦单张照片」（UX Planet / Mobbin）。
内容（照片）没有获得它应有的舞台。

### 病症 B — 信息过载、无渐进披露
评分维度（评分 / 人工 / DeepSeek / VLM / 模板 / 自动，6 张分数卡）一次性全摊
在脸上。顶栏一长串裸数字（596 / 187 / 11 / 0…）无分组无标签。专业 ≠ 把所有
数据同时显示。

### 病症 C — 强调色滥用
绿色（keep）铺满卡片左上序号角标 + 底部状态标签，大面积出现 → 廉价、抢眼、
不高级。强调色失去了「强调」的意义。

### 病症 D — 工具栏图标墙
第二行一排无标签小图标 + 「100%」+ 文字按钮挤成一团，看不懂、无分组、无留白。

### 病症 E — 视觉层级扁平
顶栏 / 工具栏 / 侧栏 / 卡片几乎同等权重，没有主次引导视线，眼睛无处落脚。

## 3. 业界标杆与方法（联网搜集）

### Linear 重设计的可落地原则（核心金矿）
- **像素级对齐 = 感觉到的质量**：label / icon / button 垂直水平对齐，「不是
  一眼看到、而是感觉到」的质感。
- **强调色克制**：限制 chrome（强调色）的用量 → 「中性、隽永」。强调色只留给
  **可操作元素 + 关键状态**，去掉装饰性 chrome。
- **内容对比 > 界面对比**：让用户数据（照片）比 UI chrome 更亮、更清晰。
- **配色即基础设施**：从 98 个硬编码变量 → 3 个（base / accent / contrast），
  用 LCH 色彩空间算法生成各层级（感知均匀）。
- **排版克制**：display 字体只用于标题，正文用 regular；按**功能**而非美学缩放。
- **先做压力测试**：对核心视图（Inbox/Triage…）先验证 environment / appearance /
  hierarchy 再开发。

### 竞品 culling 工具的关键模式
- **Narrative Select**——被赞「干净、直观」：**Close-ups 侧栏**自动显示每张脸的
  放大裁切（保留全幅上下文的同时按需细看，无需手动放大）；**Scenes View** 按
  时序把照片分组成「叙事流」而非一格格网格。
- **PhotoCuller**——「fast / focused / **distraction-free**」、session-based、
  smart stacking（连拍折叠）。
- **Peakto**——相似度滑块让摄影师**可见地**控制 AI 分组（透明 > 黑箱）。
- **Aftershoot**——界面胜在**有组织的分区 + tooltips**。
- 共同趋势（2026）：AI 工作流要**透明**（让用户看到并微调），界面要**克制**。

## 4. 显著提升审美的方案（原则 → PixCull 落地）

### ① 内容优先布局（最高杠杆）
- **lightbox**：照片占视口 ≥ 70%、居中、深色无干扰底；元数据/评分默认收进一条
  可隐藏的右侧 inspector（学 Narrative Close-ups）。`Tab` 切显隐，默认精简。
- **grid**：卡片只留「图 + 极轻状态指示」，去掉廉价绿角标与底部标签堆。

### ② 强调色纪律（学 Linear）
- 绿色只用于**真实 keep 动作/状态**，且改为克制呈现（左缘细色条 / 小圆点，
  非整块色角标）。cull=暖灰、maybe=brass 描边、keep=绿点。
- 强调色总用量预算化：一屏内 accent 像素占比设上限，超了就是滥用。

### ③ 渐进披露（学 progressive disclosure + Narrative）
- 6 个评分维度默认折叠成 **1 个总分 + 一句话理由**，「展开」才看分维度。
- 顶栏统计默认只显「总数 · keep 数」，其余 hover / 点开。

### ④ 密度与留白（学 Linear 对齐 + Apple 留白）
- 工具栏：按职能**分组**（决策 | 视图 | 折叠 | 导出），组间留白；关键操作给
  文字标签，次要操作收进 overflow（⋯）。
- 像素级对齐所有 label/icon/button；统一 padding 节奏（已有 space token，要
  **真的用对**）。

### ⑤ 排版克制（学 Linear）
- `--font-display` 只用于标题/数字；正文 `--font-body`；字号按功能分级，砍掉
  装饰性大字。

### ⑥ 视觉层级
- 主内容大且显著，辅助元素降低对比退到背景；用**大小/对比/位置**而非颜色制造
  主次。

## 5. v2.8-DESIGN charter（分优先级）

### P0 — 最大审美杠杆（先做）
- **P0-1 lightbox 内容优先重构**：照片居中占舞台 + inspector 收侧栏（`Tab`
  切换）+ 评分维度默认折叠。
- **P0-2 grid 卡片极简化**：去绿角标 / 状态堆，改细色缘 + 小圆点；卡片留白。
- **P0-3 强调色纪律**：全局 accent 审计，去装饰性绿；keep/maybe/cull 改克制呈现。

### P1 — 密度与层级
- **P1-1 顶栏 + 工具栏重排**：统计精简（渐进披露）、工具栏分组+标签+overflow。
- **P1-2 像素级对齐 + 留白节奏**统一复核（跨 grid/lightbox/video）。

### P2 — 系统升级
- **P2-1 LCH 三变量配色系统**（base/accent/contrast 生成层级，替代部分硬编码）。
- **P2-2 排版分级复核** + 跨界面（video/timeline/share）一致性收口。

### 验证
- 每个切片：Playwright 前后对比截图（用上一轮的逐文件 runner 规避本机后台杀手）
  + palette guard（防强调色回潮）+ `make results-html` 重建 + 门禁绿。
- 重新生成 19 张 gallery，GitHub ⇄ ModelScope 同步。

## 6. 方法论转变（最重要的一条）
**从「加法审计」转向「减法重构」。** 过去每季度 audit 都在加东西、自评 4.x/5；
这次要**敢删**——删角标、删常显数字、删装饰 chrome、把次要功能收进二级。衡量
标准不是「展示了多少能力」，而是「用户的眼睛能否一眼落在照片上」。

---
*来源：Linear UI redesign（linear.app/now）、Narrative Select / Aftershoot /
FilterPixel / Peakto / PhotoCuller 对比（cyme.io、aftershoot.com、imagen-ai.com）、
图库/lightbox UX（uxplanet.org、mobbin.com、uxpin.com）、progressive disclosure
（Wikipedia）、Raycast 设计分析（getdesign.md）。*
