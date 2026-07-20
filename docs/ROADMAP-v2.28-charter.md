# v2.28 — serve_demo 内联 HTML 抽取(承接 v2.27 暂缓项)

> v2.27 把 CSS 拆分做完、把内联 HTML 抽取评估后暂缓(动态 f-string、需字节
> 验证)。本轮按承诺**先搭字节级路由验证网,再逐方法抽**——只抽干净可验的,
> 动态交织的诚实留 inline。

## 方法(先建安全网)

对每个候选路由:抓取抽取**前**的渲染字节 → 抽取 → 重启 → 抓取**后**的字节 →
`diff` 必须为空。用 curl 对 `/tether`、`/history`、`/admin/disagreement` 逐一
before/after 字节比对。

## 抽取了什么(3 个静态壳型方法)✅

按结构甄别(`raw"""` 静态 vs `f"""` 动态):

- **`_serve_tether_page`(219 行 → templates/pages/tether.html)**:**纯静态**——
  `r"""..."""` + `_DESIGN_TOKENS_CSS` 拼接,零运行时数据(JS 客户端自取)。v2.16
  静态页同款,`/*__DESIGN_TOKENS_CSS__*/` 占位符。
- **`_serve_history_page`(→ history.html)**:静态壳 + 3 个注入点(design-tokens、
  run 计数、run 卡片列表)。
- **`_serve_disagreement_page`(→ disagreement.html)**:静态壳(自带 `<style>`)+
  3 个注入点(记录数、反转桶表、per-run 表)。

生成模板用**源码块 eval 法**(块内动态操作数换占位符字面量再求值),机械、零手抄
风险。**serve_demo.py 12,909 → 12,518 行**(391 行出)。

**验收:三条路由抽取前后字节完全一致**(`diff` 空)。test_page_templates 加 2 条
守卫(模板存在 + 占位符各 1 次 + serve_demo 确实 `_read_template` 引用)。

## 诚实留 inline 的(3 个)

- **`_render_share_html`(632 行)**:单个 500 行大 f-string、~40 处插值散布——
  抽成模板需 40 个占位符,反而更难读。
- **`_serve_bias_audit_page`(230 行)**:静态壳 + **内联 annotator-chip 生成器**
  + 条件标题;且 `/admin/bias` 空态路由**测不到 annotator 动态路径**——无数据夹具
  无法字节验证那条路径,不 ship 未验证重构。
- **`_serve_companion_page`(96 行)**:动态位散在 JS 里逐字符交织,抽取转录风险高、
  收益低。

理由已写进 CLAUDE.md 架构说明,避免下次重复评估。

- 门禁绿(5 预期 skip);版本 2.27→2.28 lockstep;pages 模板自动进 wheel。
