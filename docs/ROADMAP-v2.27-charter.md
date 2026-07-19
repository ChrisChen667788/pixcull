# v2.27 — results.css 继续拆分(内联 HTML 抽取评估后暂缓)

> 迭代队列 #3。承接 v2.22 的 CSS `@@CSS:` 拆分基建(tokens + lightbox),
> 继续把 results.css 巨石按内聚块拆成模块;serve_demo 剩余内联 HTML 抽取
> 经评估为高风险动态层,本轮暂缓(见下)。

## CSS 继续拆分 ✅

`build_results_html.py::_assemble_css()`(v2.22 建)已支持 `@@CSS:file@@` 标记
字节一致拼接。本轮再抽 5 个内聚块到 `src/modules/*.css`:

- **card.css**(557 行)· **modal.css**(283)· **chips.css**(1398,统一 chip
  系统 + legacy 别名)· **marquee.css**(183,框选+批量条)· **library-panel.css**
  (142,左侧 LR 风格库面板)。
- **results.css 4,812 → 2,268 行**(原始 5,797;累计拆出 7 个模块:tokens /
  lightbox / card / modal / chips / marquee / library-panel)。
- **验收:构建产物字节级一致**(hash `a5d7d113…` 前后相同,构建器判定 already
  current);每块抽取前验证起于 section 头 + 括号平衡;test_module_boundaries
  的 CSS 标记纪律 + 花括号平衡守卫覆盖全部 7 模块。
- 修 test_results_build 的过时断言:CSS 现分布在 results.css + modules/*.css,
  改为核**总量** >100KB(而非只看缩小的 results.css 壳)。

## serve_demo 内联 HTML 抽取 —— 评估后暂缓

6 个剩余内联 HTML 方法(`_render_share_html` 632 行 · `_serve_history_page`
278 · `_serve_tether_page` 239 · `_serve_bias_audit_page` 230 ·
`_serve_companion_page` 96 · `_serve_disagreement_page` 92)**都是重 f-string
插值的动态处理器**(实测每个 15-55 处 `{` 插值、2-10 个三引号块,HTML 与运行时
计算交织)——正是 v2.16 抽 7 个**静态**页(upload/verticals/admin…)时刻意留下的
难层。安全抽取需要:① 动态模板化(用 comment 占位符而非 `.format`,避开 CSS/JS
花括号碰撞)② 每条路由用**真实数据夹具**(带标注的 run、bias 数据、tether 状态、
share token)做字节级 sweep 验证。这是独立的高风险切片,不宜与低风险 CSS 拆分
混在一轮硬做——本轮不提交未经字节验证的抽取,留作专门版本。

- 门禁绿(5 预期 skip);版本 2.26→2.27 lockstep。
