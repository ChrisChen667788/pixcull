# ROADMAP v2.9 — 智能透明 + 内容优先观看 charter

> **触发 / 承接**：v2.8 完成了「减法 + OKLCH」那一刀（让界面安静下来）。
> 但 [`docs/DESIGN-REFLECTION-v2.8.md`](DESIGN-REFLECTION-v2.8.md) 明确**搁置**了
> 三个被竞品验证过的模式——Narrative Select 的**人脸 Close-ups**、Peakto 的
> **可调相似度**、Narrative 的 **Scenes 时序分组**。v2.9 就是把反思里自己点名
> 的「下一步」做掉：让 AI **透明、可调**，把**内容优先观看**补齐。

## 北极星

反思第 3 节总结的 2026 culling 工具趋势：**AI 工作流要透明（让用户看到并微调），
界面要克制。** v2.9 一句话 = **「把你的判断亮出来，并让我能拨动它。」**

- **透明（glass box）**：近重复分组从固定阈值的黑箱，变成用户可见、可拨的滑块；
  判定理由一键可达。
- **内容优先**：lightbox 不只是放大原图——像 Narrative 一样，把每张脸的放大裁切
  收进可隐藏侧栏，无需手动缩放就能查清表情/闭眼/虚焦。
- **克制不变**：透明本身就是一种克制——给一个控件，而不是摊十个数字；默认收起；
  照片始终是主角。延续 v2.8 的渐进披露纪律。

## 现状盘点（已确认的可复用基建）

- 近重复后端**已支持阈值**：`GET /api/v1/runs/<id>/near_dups?threshold=0.92`
  （`_serve_api_v1_near_dups`，clamp [0.5, 0.999]），底层 `near_dup.group_near_dups(
  threshold=…)`。→ **P0-2 是纯前端接线。**
- 人脸检测器现成：`pixcull/detectors/face.py`（MediaPipe FaceDetector +
  FaceLandmarker）；裁切助手 `pipeline/face_clustering.py::_crop_face_with_margin`。
  → **P0-1 可在 serve 时按需检测 + 裁切 + 缓存（不依赖管线持久化 bbox）。**
- 拍摄时间现成：`pixcull/io/exif.py` 解析 `DateTimeOriginal`。
  → **P1-1 Scenes 可按拍摄时间间隙切段。**
- 前端是构建产物：编辑 `templates/src/{results.src.html,results.css,results.js}`
  → `make results-html`；`tests/test_results_build.py` 守门。

## P0 — 最高杠杆

### P0-1 · 人脸 Close-ups 侧栏（对标 Narrative Select）
- **What**：lightbox 增加一条**可折叠**的右侧 close-ups 条，显示当前照片里每张
  检测到的人脸的放大方形裁切（保留全幅上下文的同时按需细看）。点裁切 → 在主图上
  高亮/放大到该脸。默认收起（内容优先），`f` 键或按钮切换。
- **Why**：反思病症 A（内容未居中）+ 竞品金矿（Narrative Close-ups 被赞「干净、
  直观」）。人像/婚礼摄影师最高频的细看动作就是「这张脸睁眼了吗、笑到位吗、虚没虚」。
- **How**：
  - 后端：`GET /api/v1/runs/<id>/faces/<filename>` → 懒检测（`detectors/face.py`）+
    square-crop（`_crop_face_with_margin`，可调 margin）+ 像 thumb 一样落盘缓存；
    返回 bbox 列表（归一化坐标）+ 每脸 crop 的 URL `/face_crop/<id>/<fn>/<i>?w=`。
    无人脸 → 空数组（侧栏不渲染）。
  - 前端：`results.js` lightbox 内渲染 close-ups 条 + click-to-locate；
    键盘可达；`registerModal` 焦点陷阱内安全（**不**再绑 Tab，沿用 v2.8.1 教训）。
- **Verify**：`tests/test_serve_faces.py`（端点 + 无脸/多脸/缓存）；Playwright 截图。

### P0-2 · 可调相似度滑块（对标 Peakto 透明度）
- **What**：近重复 fold 旁加一个可见滑块（0.80–0.99，默认 0.92）。拖动 → 防抖
  重取 `near_dups?threshold=X` → 实时重折叠 + 显示「N 组 · 折叠 M 张」，让用户
  **看见** AI 分组随阈值变化（黑箱 → 玻璃箱）。
- **Why**：反思竞品趋势——Peakto「相似度滑块让摄影师**可见地**控制 AI 分组
  （透明 > 黑箱）」。后端已就绪，是最低风险、最高透明杠杆的一刀。
- **How**：纯前端。沿用 `filterState.nearDupFold` / `_NEARDUP` / byHero 逻辑；
  滑块 `input` 防抖（~250ms）重取并 re-render；阈值持久化到 localStorage。
- **Verify**：构建守门 + Playwright（低/高阈值两档截图，组数应随阈值单调变化）。

## P1 — 深度

### P1-1 · Scenes 时序叙事视图（对标 Narrative Scenes View）
- **What**：新增「Scenes」视图开关——按拍摄时间间隙把一个 run 切成时序「场景」
  段，每段一个 header（时间范围 · 张数 · keep 数），而非一格格扁平网格；叙事流。
- **How**：新模块 `pixcull/scoring/scenes.py`：按 `DateTimeOriginal` 排序，
  自适应间隙阈值（median + k·MAD）切段；EXIF 缺失回退文件名顺序。端点
  `GET /api/v1/runs/<id>/scenes`。前端：视图切换 + 分段渲染（复用现有卡片）。
- **Verify**：`tests/test_scenes.py`（间隙切段 / 单段 / 无 EXIF 回退）。

### P1-2 · 判定理由一键透明（glass box for the verdict）
- **What**：把已有的逐轴归因 / NL「为什么」收成 lightbox inspector 里**一键可达**
  的玻璃箱面板（判定本身的透明化），按 v2.8 渐进披露纪律收紧——默认一句话，
  「展开」才看逐轴。
- **How**：复用 `scoring/nl_explain` + 逐轴归因；前端在 inspector 内挂一个折叠区。

## P2 — 系统收口

### P2-1 · DESIGN-AUDIT-2029Q3 + 一致性 + 守门
- close-ups / 滑块 / scenes 与 grid/lightbox/video 的对齐、留白、强调色纪律复核；
  palette guard（防强调色回潮）；`make results-html` 重建；门禁绿（逐文件 runner
  规避本机后台杀手）。

### P2-2 · gallery 重生成 + GitHub ⇄ ModelScope 同步
- 为 close-ups / 滑块 / scenes 出新截图（下一个空号 = **20**）；README 双端刷新；
  `make modelscope-sync` + curl 核对镜像 README 渲染成文本。

## 验证总则（每切片）

1. 单测镜像模块（`scenes.py`→`test_scenes.py`；face 端点→`test_serve_faces.py`）。
2. UI 改动跑 Playwright 前后对比截图。
3. `make results-html` + `tests/test_results_build.py` 守门（**永远改 src/，不碰产物**）。
4. 门禁：`python -m pytest tests/ --ignore=tests/test_v1_1_scripts.py`（逐文件 runner）。
5. 提交带 trailer；推送 = 公开发布，先 hygiene 审计、经用户确认再推。

## 方法论延续（v2.8 → v2.9）

v2.8 学会了「敢删」。v2.9 学会「敢亮 + 敢让用户拨」——透明不是再加十个数字，而是
把**一个**可操作控件交到用户手里，把 AI 的判断从断言变成可检视、可调的过程。
衡量标准：用户能否**看懂并相信**这次分组/判定，而不是被动接受黑箱。
