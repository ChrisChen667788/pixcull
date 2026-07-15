# ROADMAP v2.16 — 前端拆分 + 可维护性 charter

> DESIGN-AUDIT-2030Q2 主题①(综合推荐项,架构 2.5/5 的根因)。v2.4 就承诺「v2.5 拆
> 单文件前端」,拖了 11 个版本;其间 v2.13 一个不变量被破同时炸 9 处、v2.15 又自抓
> TDZ/detached-node 两个同族——**单闭包巨石的代价已被反复实证**。本主题分片偿还:
> 先做零逻辑、最高杠杆的抽取,再逐步给 results.js 立模块边界。

## P0 — serve_demo.py 七个内联 HTML 巨块抽成模板文件(已交付)

**问题**:serve_demo.py 18,225 行,其中 ~5,300 行是 7 个 `r"""…"""` 内联 HTML 页面
(upload/verticals/vertical_bulk/admin/admin_perf/first_run/privacy)——不可 grep、
不可 diff review、编辑器高亮全失效,还把 HTTP 逻辑埋在中间。

**做法**(机械、可字节级验证):
- AST 抽取器:`ast.parse` 定位 7 个赋值,`literal_eval` 原样求值(3 个是
  `字符串 + _DESIGN_TOKENS_CSS + 字符串` 的拼接 → 模板里放唯一占位符
  `/*__DESIGN_TOKENS_CSS__*/`,加载时 `.replace()` 注入,运行时字节不变)。
- 7 个页面落到 `pixcull/report/templates/pages/*.html`,serve_demo 里的常量改为
  `_read_template("pages/…")`(v2.5 给 video_review/timeline 立的同一机制)。
- `pyproject.toml` 补 `templates/pages/*.html` 打包 include(否则 wheel 会漏)。

**结果**:serve_demo.py **18,225 → 12,884 行(−29%)**,零行为变化。

**验证(金标准:curl 字节级 diff)**:抽取前后各起一次 server,7 条路由
(`/`、`/first_run`、`/privacy`、`/verticals`、`/verticals/bulk/<key>`、`/admin`、
`/admin/perf`)响应**全部字节级一致**。守卫测试 `tests/test_page_templates.py`
(文件存在且完整、常量是整页、占位符不外泄、design-tokens 真被注入)。完整门禁绿。

## 后续切片(本主题未完)

- **P1 — results.js 模块化**:11.5k 行单 IIFE、422 个顶层声明、14+ 个 setup*() 嵌套
  IIFE 共享一个闭包。先抽 3-4 个最自洽子系统(撤销栈 / 多 tab 同步 / onboarding /
  ⌘K 面板)到 `src/modules/*.js`,由 `make results-html` 装配;给
  `test_results_build.py` 加模块边界 lint(禁跨模块共享闭包写)。**风险**:undo/sync
  与网格/lightbox 共享状态,边界划错即回归——先零逻辑、后有状态。
- **P2 — serve_demo 路由表**:do_GET 200+ 行 if/elif 链(~60 个 path)改注册表,
  业务函数与 HTTP 管道分层。
- PyInstaller spec 的 templates 打包 glob 待核(pyproject 已修;.spec 是发行物主题
  ② 的一部分,届时一并处理)。

## 方法论

抽取型重构的验收标准只有一条:**产物字节级不变**(curl-diff),而不是「看起来一样」。
AST 求值 + 占位符注入保证了这点;任何伪手工搬运都可能引入不可见的空白/转义漂移。
