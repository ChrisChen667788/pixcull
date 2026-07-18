# v2.23 — 发行主题(PyPI 上架轨)+ 审计队列收尾(英文首跑 / Shadow-queue)

> 承接 v2.22:发布轨道已铺(GitHub Release 自动化),本轮把 `pip install
> pixcull` 真正打通,并清掉 DESIGN-AUDIT-2030Q3 排序队列剩下的两个纯代码主题。

## P0 — PyPI 发行轨 ✅

- **元数据体检**:pyproject 元数据已 PyPI 就绪(name/version/classifiers/
  urls/entry-point 齐全)。新增专用 **`README-PYPI.md`**——仓库 README 依赖
  相对路径截图 + GitHub-only 标记,在 pypi.org 会渲染破损;PyPI 版用
  **绝对 raw.githubusercontent 图 URL** + 精简功能清单,`readme` 字段切到它。
- **打包补漏**:`pixcull/locale/*.json` **原来没进 wheel**——i18n 运行时
  加载 13 个 locale,缺了 `_t()` 会回退成键名。加进 `[tool.hatch.build]`
  include(wheel 实测含 13 locale + results.html)。
- **产物验证**:`make wheel` 出 `pixcull-2.23.0`(wheel + sdist),
  **`twine check` 双双 PASSED**(README-PYPI 渲染无误、元数据合规)。
- **CI 自动发 PyPI**:release.yml 升级——build 改出 wheel+sdist、加
  `twine check`;新增 **`Publish to PyPI` 步骤**(`__token__` +
  `PYPI_API_TOKEN` secret)。**Owner 未配 token 前干净跳过**(warning,
  不 fail release);配好后每个 v* tag 自动上 PyPI。GitHub Release 也附
  sdist。
- **Owner 一步解锁**:去 pypi.org 建 API token → 配成仓库 secret
  `PYPI_API_TOKEN` → 下个 tag 即 `pip install pixcull` 生效。
  (或本机 `twine upload dist_wheel/*` 一次性手发。)

## P1 — 英文首跑路径(审计 ③)✅

审计原话:非中文摄影师的**第一次**接触整屏中文。三个缺陷互相叠加,一并修:

- **`navigator.language` 探测**:`_getStoredLang()` 的 zh_CN 死兜底改为——
  显式存储优先且黏,否则读浏览器语言。新增 **`_normalizeLang()`** 镜像
  `pixcull/i18n.py::_normalize_lang`(en-GB→en_US、pt-PT→pt_BR、zh-Hans→
  zh_CN…),前端探测与 `/api/v1/locale` 端点永不打架(有平价测试守卫)。
- **语言循环 3→13**:`I18N_CYCLE` 从 zh/en/ja 扩到全部 13 个 locale
  (另十个此前从切换器**够不着**);补齐 13 个 chip 标签 + BCP-47 html
  lang;**阿拉伯语加 `dir=rtl`**(字符串本就有,只差可达)。
- **onboarding 走 `_t()`**:10-onboarding.js 5 条硬编码中文串(首访即弹、
  语言切换器可达之前)全部接 `_t()` + 新增 7 个 `onboard.*` 键 × 13 locale。
  用码库现成的 **`data-i18n` 机制**(`_applyLangToDom` 重绘),规避 v2.22
  同款启动时序陷阱(模块在 locale 异步拉取前渲染)。
- **端到端验证**(Playwright 模拟 en-US 浏览器、零存储):自动探测 en_US
  并持久化,onboarding 首卡整屏英文("Getting started" / "Got it, don't
  show again" / "mark keep / maybe / cull…"),收尾 chip "To review 16",
  语言循环推进到「あ」。

## P2 — Shadow-queue 解锁:异议复核队列(审计 ②)✅

审计原话:shadow 分歧队列已算出(rescorer_pred ≠ 规则判定,按 prob 距 0.5
排序)却**从未接入纠正流**——最有价值的标注目标在 run 输出里晾着没人用。

- **工作条加「⚖ 异议复核 N」按钮**(info 钢蓝,区别于 maybe 琥珀):只在
  shadow rescorer 活跃且有分歧时显示;N 是**实时**计数(用户改判到与模型
  一致即消解,从 rows 重算而非固定汇总值)。
- **点击进复核队列**:`filterState.decision="disagree"` 过滤到
  `rescorer_pred && rescorer_pred !== decision`;`sort="disagree"` 按
  **|P(keep)−0.5| 降序**(最有把握的分歧排最前——模型很确定却与规则相反,
  就是最强纠正信号,与 maybe 队列的"最拿不准优先"正好相反)。
- **纠正自动入集**:队列里按 1/2/3 判定走的正是既有 `/annotation` POST
  路径——每次改判自动写进纠正集,零额外机制。清零时脉冲完成 toast。
- **复用 v2.15 队列机制**:snapshot/restore 前置筛选、批量换筛选时静默退出
  (`_exitResolveMaybesSilently` 扩展兼管两个队列)、locale 刷新重建按钮文案。
- **4 个新 i18n 键 × 13 locale**;`toast.disagree_mode_enter` 带 `{n}` 占位。
- **端到端验证**(注入合成 shadow 预测的 shadowdemo run):按钮显示
  "⚖ 异议复核 3",点击后网格精确过滤到 3 张分歧照片(均带 `.rs.dis` 徽章),
  按 P(keep) 0.11/0.16/0.19 降序——最有把握的分歧排最前,符合规格。

**注意**:这解锁的是分歧**复核流**(把标注目标送到用户面前);把 rescorer
从 shadow 翻到 adjudicate 仍**owner-gated**——需要 owner 用这个队列产出
~50 条真实 keep↔maybe 分歧改判(外置盘在线时随时可做),门③过了才翻配置。

## 验收 / 遗留

- 门禁绿(5 预期 skip);twine check PASSED;i18n 键守卫 +29 测试;
  版本 2.22.0 → 2.23.0 lockstep。
- **Owner 动作**:① 配 `PYPI_API_TOKEN` secret(解锁 `pip install`)
  ② 推 tag `v2.23.0`(触发 Release + PyPI 发布)③ 用异议复核队列产出真实
  分歧标注(解锁 adjudicate)④ 18/19 视频截图待可公开素材。
