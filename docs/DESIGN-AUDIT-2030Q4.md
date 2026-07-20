# DESIGN-AUDIT 2030Q4 — v2.21–v2.28 收口后的复检 + 毛玻璃方向定案

> 承接 Q2(3.0)、Q3(3.1)。本轮复检 v2.21「Studio Neutral」设计翻新 + v2.22–v2.28
> 十三个功能/性能/架构版本之后的水位,并回答 owner 明确提出的问题:**要不要往
> 更有设计感的毛玻璃(frosted glass / glassmorphism)方向走。** 多 agent 审计
> workflow 撞会话限额(7 个 agent 仅触达维度跑完),其余维度由主会话据实现事实
> 复评、玻璃方向由主会话定向联网调研(Apple Liquid Glass / 2026 glassmorphism a11y
> 实践)+ 读现有代码 glass 用法后定案,行号/数字均实测。

## 总评:**3.4 / 5**(Q2 3.0 · Q3 3.1)

十三个版本是真进步,五个维度全部上移,但 owner 动作仍卡着最弱的触达层。最大的
结构性发现:**代码里已经散布着 ~30 处 `backdrop-filter: blur(...)` 的 ad-hoc 毛玻璃
(header/工具条/tooltip/tray/lightbox chrome),但值零散不成体系(blur 2/4/6/8/10/12/20px、
saturate 140/180% 各写各的)、且全仓零 `prefers-reduced-transparency`(a11y 缺口)。**
所以 owner 想要的"毛玻璃设计感"不是从零加玻璃——是把已有的、零散的玻璃**系统化**成
一套 token 化、可访问、与 Studio Neutral 判色纪律相容的玻璃层。这正是当前 UX 分数最
现实的提升杠杆。

## 各维度(Q3 → Q4)

| 维度 | Q3 | Q4 | 最大短板 |
|---|---|---|---|
| 核心 culling UX | 3.8 | **3.9** | 设计打磨:~30 处玻璃 ad-hoc、无 glass token 体系、零 reduced-transparency 兜底——「有设计感」的缺口正在这层(owner 亲点的毛玻璃方向) |
| 评分智能 / 学习 | 3.5 | **3.6** | adjudicate 仍 owner-gated:v2.23 异议复核 UI 已把"分歧→纠正流"接通(Q3 顶层短板的收集侧已修),但真学习仍需 owner 补 ~50 条真实标注,无纯代码解 |
| 触达 + 发布/CI 卫生 | ~2.4 | **2.9** | v2.24–v2.28 **五个版本未打 tag**(无 Release、无产物,README 徽章停在 v2.23.0);`pip install pixcull` 仍失败(PYPI_API_TOKEN 未配);且 pip 用户装了也**打不开审片工作台**(`pixcull serve` 未打包) |
| 架构 + 性能 | 3.2 | **3.6** | results.js 仍是 **9.7k 行单体**(最大剩余巨石);3 个动态内联 HTML 处理器留 inline;`_build_results` 业务逻辑仍在 handler 层;50k+ run 的占位符仍全量在 DOM(图片+DOM 已虚拟化,占位符本身未虚拟化) |

> Q3 的"视频/发布"维度并入触达;设计/玻璃是跨维度的打磨杠杆,单列在下面的方向判定。

## 各维度已兑现(抽样,均实测)

- **UX 3.9**:n 路 A/B 比较(v2.25,Q3 明确点名的两两瓶颈已解)· 异议复核队列
  (v2.23)· 英文首跑(v2.23,非中文用户首访即英文 onboarding)· maybe 决议队列 ·
  玻璃盒逐轴 why。
- **智能 3.6**:v2.23「⚖ 异议复核」按钮把 shadow rescorer 的模型↔规则分歧路由进
  标注流——Q3 顶层短板("算出却从未接入")的收集侧已闭合。
- **触达 2.9**:release.yml tag 触发出 wheel+sdist+Release(v2.22.0/v2.23.0 两个真
  Release)· PyPI 轨全建好(README-PYPI/twine check/gated 发布步骤)· sync 红灯止血 ·
  英文首跑 + 13 语言循环 + RTL。
- **架构 3.6**:serve_demo 18k→12.5k · results.css 5.8k→2.3k(7 模块)· 图片内存
  虚拟化(v2.24)+ 真去物化(v2.26)= 窗口化虚拟滚动 · 内联 HTML 抽取(v2.28,字节
  验证)。

## 毛玻璃方向定案:**范围采纳(adopt-scoped),非全面采纳**

### 论据(2026 现状 + 判色科学)

1. **连 Apple 都往回收。** Liquid Glass(2025 iOS 26/macOS Tahoe)上线即"controversial",
   **WWDC 2026 主动降低默认透明度、加了「清晰↔染色」用户滑块、为可读性重做**,并接
   `prefers-reduced-transparency`。玻璃是当下最强的"设计感"信号,但**全面铺开会伤可读
   性/可访问性**——业界共识是"少用、精用、战略性用",不是主视觉。
2. **对判色工具是双刃。** PixCull v2.21 刻意去彩色/中性化是为 ISO 3664 判色准确性。
   毛玻璃 = 模糊 + 半透明 + 常带染色/饱和提升(saturate 180%)。它在**永不位于判片
   照片之上的表面**(header/侧栏/工具条/浮层/模态/tray)上是纯粹的设计增益;在**照片
   周围或缩略图背景垫层**上会污染判色 —— 必须严格禁止。
3. **2026 a11y 实践刚好补齐现有缺口。** 文字下垫 ~30% 不透明"膜"稳住对比、尊重
   `prefers-reduced-transparency` 退回实底——PixCull 现在**两条都没做**。

### 判定

**采纳,但严格限定作用域**,并把它做成"系统化 + 可访问"而非"加更多模糊":

- **安全区(采纳玻璃)**:顶栏/工作条 chrome、左侧库面板、⌘K 命令面板、决议/比较
  tray、toast、模态/弹层、lightbox 的**控件 chrome**(非图片区)。
- **危险区(禁止玻璃)**:照片缩略图背后的卡面/mat、lightbox 的图片承载区、任何会
  在被判读的照片之上叠模糊/染色的层。这条守住 Studio Neutral 的判色纪律。
- **与 Studio Neutral 共存**:玻璃层的底色仍取无彩 `--chrome`/`--base` 的半透明版
  (不引入新色相),染色只保留极轻的 saturate;香槟金 accent 维持"仅选中/焦点/CTA"
  的纪律。玻璃改变的是**质感与层次**,不是**色相**——两者正交。

### CSS 机制(首切片可直接落地)

- 一套 **`--glass-*` token**:`--glass-blur`(统一到 2 档,如 chrome 12px / overlay 20px)、
  `--glass-tint`(无彩 `--chrome` 的 ~72% 不透明版做"膜",保对比)、`--glass-edge`
  (顶部 1px `rgba(255,255,255,.08)` 高光 + 底部发丝线,做玻璃边缘)、`--glass-sat`
  (轻饱和 120–140%,不再 180%)。
- **把现有 ~30 处 ad-hoc `backdrop-filter` 收敛到这套 token**(消除 blur 2/4/6/8/10/12/20
  的随意值),一处改全局一致。
- **`@media (prefers-reduced-transparency: reduce)`**:所有玻璃面退回 `--chrome` 实底
  (a11y 兜底,当前全仓缺失)。
- **性能护栏**:滚动容器内的 `backdrop-filter` 每帧重绘代价高——玻璃只用在**固定/
  少动**的 chrome(header/侧栏/tray/模态),**不用在网格滚动的卡片上**(也正好和判色
  禁区重合)。`will-change` 慎用。

### 首切片(v2.29-P0)

抽 `--glass-*` token 到 tokens.css;把 header + 库面板 + ⌘K + tray + toast + 模态六处
的 ad-hoc backdrop-filter 换成 token;加 `prefers-reduced-transparency` 兜底;顶部
1px 高光边做玻璃质感。**照片区/卡面零改动**(守判色)。浏览器实测暗/亮双主题 + 降
透明度回退 + 截图走查。

## v2.29 候选主题(排序)

### ① 毛玻璃设计系统(Frosted-Glass system)· 工作量 S–M ·【综合推荐,owner 亲点】
- **为什么**:owner 明确想要更有设计感的毛玻璃;当前 UX 最现实的提升杠杆就在这层;
  代码已有 ~30 处零散玻璃 + 零 a11y 兜底——系统化是"提升设计感"和"补 a11y 缺口"
  一箭双雕,且严格限定作用域后与 Studio Neutral 判色纪律零冲突。
- **首切片**:见上「首切片(v2.29-P0)」。

### ② results.js 继续模块化(架构/可维护)· 工作量 M
- **为什么**:results.js 仍是 **9.7k 行单体**——全代码树最后的大巨石(serve_demo 已
  18k→12.5k、results.css 已 5.8k→2.3k)。v2.16 的 `@@MODULE:` 拆分基建现成,继续把
  自洽子系统(render/renderCard、filter state、lightbox loupe 等)抽成模块,机器 lint
  守边界,产物 hash 一致。
- **首切片**:抽一个最自洽的子系统(如 EXIF/直方图 overlay 或筛选状态机)到
  `src/modules/*.js`,`make results-html` 后 hash 不变 + 边界 lint 绿。

### ③ 打包 `pixcull serve`(触达天花板)· 工作量 M
- **为什么**:即使 owner 配了 PYPI_API_TOKEN、`pip install pixcull` 通了,pip 用户
  **仍打不开审片工作台**——README-PYPI 明说 serve 得 git clone。评分流水线上了,
  差异化的交互 culling UI 没上,这是触达的结构性天花板。
- **首切片**:serve_demo 接一个 `pixcull serve` typer 子命令;用 `importlib.resources`
  从装好的包定位 templates/ + locale/;pyproject include 补齐;release.yml 的 clean-venv
  烟测里加 `pixcull serve` 冒烟。

### ④ 近重复 CLIP 折叠(功能)· 工作量 M
- **为什么**:charter 里挂了很久的 follow-up。连拍折叠已按 cluster,但跨 cluster 的
  视觉近重复(不同连拍组里的几乎同一张)没折叠——婚礼/活动摄影师的真实痛点。
- **首切片**:用已算的 CLIP 视觉 centroid 距离,在网格里把视觉近重复折叠成堆(复用
  ⧉N 堆叠 badge + 比较入口);阈值可调,默认保守。

## Owner 动作清单(无纯代码替代)

1. **补打 tag `v2.24.0`–`v2.28.0`**(或单个 `v2.28.0` 追赶 tag)——五个版本无 Release/
   产物,徽章停在 v2.23.0;release.yml 一推 tag 即自动出 Release。
2. **配仓库 secret `PYPI_API_TOKEN`** —— 解锁 `pip install pixcull`(轨已建好,配好
   下个 tag 自动发 PyPI)。
3. **~50 条真实 keep↔maybe 分歧标注**(外置盘)—— 解锁 rescorer adjudicate;v2.23
   异议复核队列已就绪收集。
4. **视频截图可公开素材**(无人脸/敏感 GPS)—— 补 gallery 18/19。

## 推荐

综合推荐 **①(毛玻璃设计系统)** 起步:owner 亲点、S–M 工作量、判色安全区严格限定、
一箭补齐设计感 + a11y 兜底,且与 Studio Neutral 正交(改质感不改色相)。②(results.js
模块化)是无依赖的架构/可维护欠债,适合任意一轮并行;③④ 按触达/功能价值排后。

## 方法论说明

本轮审计 workflow 因会话限额只跑完触达维度(2.9/5,已并入);其余维度由主会话据
v2.22–v2.28 的实现事实复评(这些版本均由本会话实现,状态第一手),毛玻璃方向由主
会话定向联网调研(Apple Liquid Glass 2025→2026 回收、2026 glassmorphism a11y 实践)+
读现有代码 glass 用法(~30 处 ad-hoc、零 reduced-transparency)后定案。所有行数/数字
实测。下次体检建议在 v2.29 玻璃系统落地后,复查设计感是否真的上台阶、a11y 兜底是否
补齐。
