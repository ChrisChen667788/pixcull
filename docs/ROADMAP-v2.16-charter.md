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

## P1 — results.js 模块化·第一批(已交付)

11.8k 行单 IIFE 里,尾部 8 个**边界干净的嵌套 IIFE 子系统**抽成
`src/modules/*.js`(共 802 行):onboarding、transparency-hint、**undo 栈**、
Selects 模式、Smart Collections、书签/冲突、**marquee 框选**、WebRTC。

- **机制**:构建器新增 `@@MODULE:<file>@@` 标记——`_assemble_js()` 把模块文件在
  **原位**回拼进 results.js 再进 shell;标记↔文件 1:1 强校验(孤儿模块、未解析标记
  都直接 fail build)。
- **验收**:抽取后 `make results-html` 直接报 *already current* ——
  **results.html 产物 hash 与抽取前完全一致**(`2d1ba47…`),零运行时风险。
- **机器化边界 lint**(`tests/test_module_boundaries.py`,3 项):
  ① 标记纪律(1:1、无孤儿);② 每个模块必须是**单条自包含 IIFE**(不向主闭包泄漏
  顶层声明);③ **跨模块隔离**——模块 A 的顶层内名不得被模块 B 引用(模块间只准走
  `window.PixCull*`);引用扫描剥离注释、自有声明任意缩进豁免(开发中即抓掉 4 个
  误报,规则已校准)。
- 装配后整体 `node --check` 语法绿;完整门禁 exit=0。

> 这一步的价值不在行数,在**边界被机器看住了**:下次谁把 marquee 的手伸进 undo 的
> 内部状态,CI 直接红——v2.13「一处破九处炸」的传播路径被截断了一段。

## 后续切片(本主题未完)

- **P1.1 — 中部子系统继续抽**:多 tab 同步(`_pixMultiTab`)、⌘K 面板、confidence
  modal、EXIF overlay 等边界稍粘的块(与主闭包 render/rows 交互多,需先立接口再搬)。
- **P2 — serve_demo 路由表**:do_GET 200+ 行 if/elif 链(~60 个 path)改注册表,
  业务函数与 HTTP 管道分层。
- PyInstaller spec 的 templates 打包 glob 待核(pyproject 已修;.spec 是发行物主题
  ② 的一部分,届时一并处理)。

## 方法论

抽取型重构的验收标准只有一条:**产物字节级不变**(curl-diff),而不是「看起来一样」。
AST 求值 + 占位符注入保证了这点;任何伪手工搬运都可能引入不可见的空白/转义漂移。
