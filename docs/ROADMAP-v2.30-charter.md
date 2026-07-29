# v2.30 — results.js 模块化第 5 波 + 发布卫生两修

> Q4 队列 ②。results.js 是全树最后的大巨石(9,681 行);继续用 v2.16 的
> `@@MODULE:` 拆分基建抽自洽子系统。附带修掉两处发布卫生问题(补 tag 时发现)。

## 模块化(9,681 → 9,263 行,31 个 JS 模块)✅

抽取纪律:内容锚点定位(行号会飘)+ **泄漏守卫**(块内 2-space 顶层声明若被块外
引用即中止——主体引用模块内名会在运行时炸;模块引用主体共享名则安全:词法作用域
+ lint shared 白名单)。本波三块全部零泄漏:

- **27-lb-touch.js(~300 行)**:iPad/触屏手势(捏合缩放/滑动翻页/下滑关闭/
  底部抽屉 MQ)。原区段尾部两个函数(`_updateLbDecisionToolbar`/`_lbLabel`)被
  键盘路径引用,**留在主体**,切点按归属注释精确划开。
- **28-a11y-toggle.js(~53 行)**:色盲/无障碍配色开关。
- **29-theme-toggle.js(~70 行)**:亮暗主题三态循环(system→light→dark)。

验收:边界 lint + 构建测试绿;node --check 产物 JS 语法 OK;Playwright 行为
验证——页面零错误、a11y 按钮在、theme 连点三次循环 dark→dark→light→dark
(三态符合预期)、触屏模块随载安装。

## 发布卫生两修(补 tag 过程捡出)✅

1. **一次推 6 个 tag 不触发任何工作流**:GitHub 已知限制(单次推送 >3 个 tag
   不产生事件)。v2.24.0–v2.29.0 六个补打 tag 首推全被吞——删远端后**逐个重推**,
   六个 Release 工作流全部正常触发。教训入 charter:补 tag 永远 ≤3 个/次。
2. **CI 端 ModelScope 同步每推必红(secret 已配仍红)**:runner 裸
   `pip install modelscope` 装到新版 SDK,`login()` 的 `access_token` 关键字
   参数被移除(`LegacyHubApi.login() got an unexpected keyword argument`),
   本机旧版无感。`sync_modelscope_readme.py` 改兼容调用:先位置参数(新旧通吃),
   TypeError 再回退关键字。

- 门禁绿(5 预期 skip);版本 2.29→2.30 lockstep。
