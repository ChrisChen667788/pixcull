# ROADMAP v2.13 — 「抓图卡死」根因推翻 + 侧栏控件重建一致性 charter

> 承接 v2.12 留下的 ① 悬案(「near_dups 返回 200 但 body 不送达无头 chromium」的
> 玄学诊断)。本轮把它**重新查清并推翻**:根本不是传输层怪癖,而是一个**真实前端
> bug** + 冷启慢 + /tmp 被清。修掉 bug 后,又用一轮对抗式 review workflow 把**同一
> bug 类**的潜伏问题一网打尽。

## ① 真因:相似度滑块永远挂载不出来(不是 body 投递问题)

v2.12 charter 记的诊断是错的。这次坐实:

- **真症状**:点「≈ 近重复折叠」后,相似度滑块从不出现,toggle 文本永远停在
  「≈ 建索引中…」。
- **真因**:滑块的 HTML、以及 toggle 自身的 label / active 态,**只由
  `buildViewToggles()` 注入**;而点击走的是 `_toggleNearDupFold → render()`,
  **`render()` 只重绘网格、从不重建侧栏 `#viewToggles`**。`buildViewToggles()`
  只在初始化(`buildDynamicFilters()`)里调用一次,折叠开启后没人再调它 → 滑块永不
  挂载。**真浏览器里也复现**,不止无头抓图。
- **此前误判的两个叠加因素**:
  1. **冷启慢**:没有预算 `embeddings.npz` 的 run,首次 `near_dups` 要现算 CLIP
     嵌入(5 张样例 0.35s,但本机另一个 run 实测 **17.3s**)。之前抓图只等十几秒
     就放弃 → 误读成「卡死 / body 不送达」。实际 `curl` 与被 await 的 evaluate-fetch
     都能拿到完整 body,只是耗时长。
  2. **/tmp 被系统激进清理**:`/tmp/pixcull_demo` 及博物馆原图(符号链接目标
     `/tmp/relic_small`)在会话中途被清空,反复打断抓图。

- **修复**(`_toggleNearDupFold` 三条分支):翻转 `filterState.nearDupFold` 后**显式
  调 `buildViewToggles()`** 再 `render()` —— 重建工具组以注入/移除滑块、复位 toggle
  文本与 active 态。
- **验证**(无头,持久样例 run + 一个真实近重复对):点开 → 滑块挂载、active=true、
  stat「1 组 · 折叠 1 张」;拖 0.82 → 「折叠 2 张」(实时重算生效);与 🎬 时序场景
  **同时开**两者都 active、滑块存活;关闭后滑块消失;**全程零 JS 错误**。

## ② 同类 bug 扫荡(对抗式 review workflow,19 agent)

修完 ① 后,跑一轮 4 lens × 对抗验证的 workflow 找**同一 bug 类**(handler 改了
`filterState` 后只调 `render()`,而 `render()` 不重建对应侧栏控件)。15 候选 → 11 确认,
去重后修以下:

- **`_applyView`(预设恢复)/ `_cmdkResetFilters`(⌘K 重置)/ 空状态「重置所有筛选」**
  —— 改 `filterState.{burstPeakOnly,locationBestOnly,faceClusters,locationClusters}`
  后,`#burstPeakFilter / #locationFilters / #faceFilters / #viewToggles` 药丸的
  `.active` 不更新。其中**「重置所有筛选」此前根本没清 face/location/burst 状态 →
  网格被静默继续过滤**(真功能 bug,非纯视觉)。
- **Smart Collections 恢复(`_restore`)** —— 用的 `window.render()` 是**死 no-op**
  (`window.render` 全文从未赋值),恢复收藏其实**根本没重渲染**。改用词法可见的
  `render()` + 重建控件 + 同步 decision/sort。
- **滑块防抖 `_simTimer`** 由 `buildViewToggles()` 闭包局部**提到模块级**:重建工具组
  时取消在途防抖,杜绝旧 timer 用旧阈值写脏 `_NEARDUP`;并给滑块 `.then` 加
  `if (!filterState.nearDupFold) return` 守卫(脱离节点不写)。
- **`_toggleScenesView` finish()** 改用 `buildViewToggles()` 而非直接 `btn.classList`
  —— 并发 near-dup 重建会让 btn 脱离;与 `_toggleNearDupFold` 统一。
- **`.finally` 死写**加 `if (btn.isConnected)` 守卫。
- 抽出 DRY 助手 **`_rebuildFilterControls()`**(重建 burst/location/face/view 四组),
  四处批量改 `filterState` 的路径统一调用。

workflow 同时**确认干净**:主 `_toggleNearDupFold` 修复、lightbox 人脸 rail、Scenes
显示路径,均无遗漏。

## 截图(本轮决策:不动)

22(透明度工具)保留现有博物馆版(与 20/21 一致);滑块修复由测试 + 无头回归证明,
不强行换成合成样例图。23(人脸 Close-ups)继续暂缓——需真实人脸数据,owner 未在本轮
授权用婴儿图公开。

## 验证

`node --check`(占位替换后)语法 OK · `make results-html` + golden 绿 · 无头回归零
JS 错误 · 完整测试门禁全绿(2 人脸夹具如期 skip + 3 zeroconf 可选依赖 skip)。

## 后续(未做,留记录)

- Selects 模式切换(`window.render()` 同款死 no-op,~line 10363)未在本轮修——非本次
  confirmed finding 且改动有行为风险,留作单独核验。
- demo 数据持久化:本机 /tmp 激进清理使实拍抓图脆弱;长期可把样例 run 固化进仓库或
  改用更稳的根目录。
