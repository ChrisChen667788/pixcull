# v0.7 charter — UI/UX 收尾 + 大批量可用性 + LR-parity

## 上下文(2026-05-23)

经过 v0.4 → v0.5 → v0.6 三轮 UI/UX 重做:

- **v0.4 P0**:design tokens / chip 系统 / motion / button system
- **v0.4 P1**:SVG icon sprite / grid filter motion / empty state / hero landing
- **v0.4 P2**:light theme / stats pulse / mobile pass / PDF 导出
- **v0.5 LR-grade**:condensed workspace chrome / LR Library card / LR Loupe filmstrip
- **v0.6**:Left Library panel / Inspector pane / token migration / thumb buckets /
  hold-Space cheat-sheet

主网格 / Library 侧栏 / Inspector / Upload / Admin / Filmstrip 已经接近 LR-grade。
打开 `/results/<run>` 第一眼已经看不出是单文件 vanilla JS 工程。

剩下还能一眼看出"内部工具感"的地方收敛到 **两个深处 modal**(A/B 比较窗、
Annotation rubric form)和一些 **5k+ 大批量场景的隐性可用性问题**。同时和 LR /
PS / 剪映对照,还差 **Loupe RGB 读数 / 客户交付页 / 历史时间线** 这几个 pro
期待项。

v0.7 主线:**"把最后几面 demo-look 收尾 + 大批量稳得住 + LR-parity 补齐"**。

## 诊断:剩下的粗糙面

1. **A/B 比较窗(cmpModal)还停留在 v0.2 状态**:黑底 + 三排按钮 + 中间两张图 +
   `<small>` hint。和 v0.5/v0.6 的 inspector / sidebar 视觉脱节。LR Compare
   模块视觉是行业标杆,我们差得远。

2. **Annotation rubric modal 是 v0.1 时写的 form**:`<input type="number">` +
   行尾 `<small>` hint。这是产品最深的人机触点(6 维度打星 + cull reason),
   pro 在这上面花的时间不亚于浏览网格。但它视觉/手感都差 inspector 一大截。

3. **大批量(5k+ 张)有几个隐性泄漏**:
   - 标注状态全在 `localStorage` — 5k 张 quota 会爆
   - `MutationObserver` 链长在大 grid 上回调过频
   - 缩略图懒加载 viewport 触发距离不自适应
   - 没有内存峰值基准线 / 性能调试页

4. **LR-parity 项缺失**:Loupe 没有 RGB 像素读数;Inspector 移动端还是 stacked
   而不是 bottom sheet;视图预设不能跨 run 复用;客户交付只能 zip(没有
   shareable link)。

5. **风格 clone + tethered 是产品差异化关键**:每个用户的"keep 偏好"和
   "现场实时分级"这两个 use case 决定了 PixCull 是不是真的比 PM/PG 更聪明,
   而不只是"长得像 LR"。

## v0.7 工作范围

### P0(必须做)

#### v0.7-P0-1 · A/B 比较窗(cmpModal)重设计
- 对称双图布局 + 中央分隔条可拖
- 同步缩放 / 平移已存在 → 补 **像素读数 overlay**(LR Compare 风格)
- metadata 行统一用 design tokens(meta-line 类)
- 决策按钮换成 `.pill` 系统(和 Decision pills 一致)
- 移动端切上下叠加(swiper 风格)
- 影响面:`results.html` 内 ~600 行 modal markup + CSS + JS

#### v0.7-P0-2 · Annotation rubric modal 重设计
- `★★★★★` 视觉星条(可点击 + 半星)
- 每个维度的 hint 用 inline pill,不是行尾 `<small>`
- 顶部小进度条(6 个维度填到第几个)
- cull reason picker 内嵌进同一 modal,不开第二层
- 键盘流:Tab 换维 + 1-5 直接打星 + Enter 提交
- 移动端:整页式而不是 modal

#### v0.7-P0-3 · 大批量(5k+ 张)稳定性 audit
- 写一层 **storage adapter**(API 保持 `_readBuckets() / _writeBuckets()`
  等不变),底层从 `localStorage` 迁到 `IndexedDB`
- `MutationObserver` 回调 throttle / batch
- 缩略图 IntersectionObserver `rootMargin` 根据 grid 大小自适应
- 新增 `/admin/perf` 调试页:GPU / CPU / RAM 时间线 + storage usage +
  observer 回调频次
- pytest 加一个 5k synthetic run smoke
- 内存峰值基准线写到 `docs/perf-baseline.md`

### P1(应该做)

#### v0.7-P1-1 · Loupe RGB readout
Lightbox 按 `Z` 进 1:1 后,光标位置浮出一个 **R / G / B / Hex /
Y(luminance)** 小读数框 — LR / PS 都有。从 `lbImg` 上 canvas 取样,
不需要服务端配合。

#### v0.7-P1-2 · Inspector mobile 重做
v0.6 (2/5) 把 desktop 的 Inspector 改成 LR Develop 风格了,但 ≤640px
还是 stacked-below。改成 **bottom sheet**(LR Mobile-Library 风格):
上拉抽屉 + drag handle + scrim 背景,fold 状态共享同一
`pixcull_inspector_state` localStorage。

#### v0.7-P1-3 · 视图预设 v2(import / export)
P-UX-20 预设当前是 per-run。v2 加 JSON export/import,跨 run 复用;
同时内置 3-4 个 starter 预设("仪式 only" / "废片二审" / "连拍峰值
only" / "高置信 keep")。

#### v0.7-P1-4 · 客户交付分享链接
新增 `GET /share/<run>/<token>` — token 化的只读 HTML 页,只展示用户
标的 keeps,带摄影师 logo + 客户姓名水印 + 简单评论框(POST 回
`/annotation`)。客户浏览器里就能看,不需要安装/下载。zip 工作流保留。

### P2(进阶 — v0.7 包含,但风险较高)

#### v0.7-P2-1 · 风格 clone(Style Clone V1)
给 5-20 张精修参考样本,学摄影师的风格中心。下次同类活动跑 PixCull 时,
把"和你过去风格不像"的片子降分。
- **Phase 1**(v0.7):仅用现有 axis stars + scene 做 logistic regression。
  Inspector 新增"风格距离"行。
- **Phase 2**(v0.8):CLIP embedding 风格中心 + 余弦距离 + 风格漂移检测。

#### v0.7-P2-2 · Tethered live scoring
PixCull 监听 TetherSink(iOS 端已有)/ 现场指定 watch dir,新 RAW 进来
即刻分析。摄影师在拍时,后台实时排序 → 助理立刻知道哪几张可以预览给
客户。和现有 `/scan_local` pipeline 共享分析路径,触发源换成 fs watcher。
新加 `/tether/<dir>` 路由 + WebSocket 推送新片事件。

#### v0.7-P2-3 · macOS 签名 + Sparkle 自动更新
brew tap 已存在但每次手动新版。v0.7 集成 **Sparkle XML appcast** +
Apple Developer ID 签名 — Mac 用户开应用直接收到更新提示。

#### v0.7-P2-4 · 历史时间线(/history)
当前 `/` 是 upload。加 `/history` 列所有以前的 run(从
`/tmp/pixcull_demo/*/` + on-disk manifest 还原),按时间排,缩略图 +
数量 + decision 分布 — 快速跳回任意以前的分析。

## 建议外部资源 / 灵感参考

- **Lightroom Compare 模块** — A/B 比较的标杆
- **Lightroom Develop 模块** — annotation rubric 的视觉密度参考
- **Capture One Sessions** — tethered live workflow 的产品形态
- **Sparkle** — macOS 自更新框架(开源)
- **CLIP / OpenCLIP** — 风格 clone V2 的 embedding 来源

## 不做的事(scope discipline)

- 不重写整个 Web stack(继续 vanilla JS + direct-edit `results.html`)
- 不引入 npm / build tooling(继续 zero-build)
- 不动核心 ML 代码 — v0.7 是 UI/UX 收尾 + 稳定性 + 中型新功能;rescorer /
  scene / face / burst peak 保持 v0.6 状态
- **多人协作 / INFRA-3** 留到 v0.8(牵涉 server state migration,要单独
  一轮)
- 风格 clone Phase 2(CLIP)留到 v0.8

## 验收标准

打开 `/results/<run>` 第一眼,继续看不出这是单文件 vanilla JS 工程
(v0.6 已达成)。同时:

- **A/B 比较窗** 单独打开,视觉密度 / 触感 / 元数据布局达到 LR Compare 的
  85%+
- **Annotation rubric modal** 打 6 维度星全键盘可控,< 5 秒完成一张全打星
- **5k 张合成 run** 在 16GB Mac 上跑得动(峰值内存 < 6GB,grid 滚动 60fps)
- **/share/<run>/<token>** 链接可以在没装 PixCull 的设备上正常显示 keeps
- **风格 clone** 给 10 张精修样本后,新 run 的"风格距离"列在 inspector 上可见
- **tethered** 一张新 RAW 进 watch dir,< 3 秒在 grid 出现并完成分析

## 建议执行顺序(预计 4-5 周完成 v0.7)

| 顺序 | 任务 | 估时 | 理由 |
|---|---|---|---|
| 1 | **v0.7-P0-1** A/B 比较窗 | 2-3 天 | 最显眼的剩余 demo-look |
| 2 | **v0.7-P0-2** Annotation modal | 2-3 天 | 紧接 P0-1,同类 modal 重做 |
| 3 | **v0.7-P0-3** 大批量稳定性 | 3-4 天 | 后续 P1/P2 都依赖 5k+ 跑得动 |
| 4 | **v0.7-P1-1** Loupe RGB readout | 1-2 天 | 独立小项 |
| 5 | **v0.7-P1-2** Inspector mobile | 1-2 天 | 独立小项 |
| 6 | **v0.7-P1-3** 预设 v2 | 1 天 | 独立小项 |
| 7 | **v0.7-P1-4** 客户分享链接 | 2-3 天 | 涉及新路由 + token 鉴权 |
| 8 | **v0.7-P2-1** 风格 clone V1 | 3-4 天 | 中型 — ML + UI 联调 |
| 9 | **v0.7-P2-2** Tethered live | 4-5 天 | 大型 — fs watcher + WS 推送 |
| 10 | **v0.7-P2-3** Sparkle 自更新 | 1-2 天 | 外部依赖 |
| 11 | **v0.7-P2-4** 历史时间线 | 1-2 天 | 收尾 |

---

charter timestamp: 2026-05-23
expected start: 紧接当前 v0.6 完成
expected duration: 4-5 周(v0.7 release)
predecessor: docs/ROADMAP-v0.4-charter.md
