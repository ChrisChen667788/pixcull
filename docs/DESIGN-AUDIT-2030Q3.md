# DESIGN-AUDIT 2030Q3 — v2.14–v2.20 七版收口后的全局复检 + v2.21 选向

> 5 视角各自**真读代码/文档/CI 记录**给当前 v2.20 状态重新打分(多 agent 审计
> workflow 产出,6 agents / 318 次工具调用,每个断言都在正文文件里核对过行号)。
> Q2 的四个主题(收尾闭环、真实标注、前端拆分、视频玻璃盒+发行物)全部按承诺
> 落地——本次体检回答的问题是:**兑现之后,水位到底涨了多少,下一块短板在哪。**

## 总评:**3.1 / 5**(Q2:3.0)

只涨 0.1 不是做得少,是**诚实**:v2.14–v2.20 在五个维度上全有真实、可文件核验的
进步(收尾闭环带活跃计数与 XMP 出口;29 个受机器 lint 的 JS 模块,主体 11.8k→9.4k;
moment 轴非退化 + 个性化档案真实激活,holdout F1 0.801)。但两件事**结构性卡死**,
再多纯代码投入也推不动:① rescorer 的 adjudicate 门需要 owner 提供真实 keep↔maybe
分歧标注(608 行「认可式」标注让规则栈对自己 acc=1.000,+3pp 门槛无从谈起);
② 自 v0.7.0 之后的所有版本(含 v2.14–v2.20 七个)**零 git tag、零 GitHub Release、
零附件产物**,README 徽章永远停在 v0.7.0。本轮**最扎心的纯代码发现**:v2.15 收尾
闭环——Q2 亲自钦点的最大短板修复——新增的 9 条动态 UI 文案全部是 results.js 里的
硬编码中文,完全绕过了那套 164 键、13 语言、CI 把关的 `_t()` 基础设施:**英文/日文
用户看到的"完工时刻"整屏是中文**。发布卫生是代码进步最多、绝对分却最低的维度。

## 各维度(Q2 → Q3)

| 维度 | Q2 | Q3 | 最大短板 |
|---|---|---|---|
| 核心 culling 主循环 + 可解释 UX | 3.5 | **3.8** | v2.15–v2.20 新增的 9 条动态文案(待审计数/完成 chip/决议按钮/水合进度/4 条收尾 toast,results.js 569 · 1588 · 1615 · 1752 · 1757 · 1774 · 1794 · 1836 · 1844 行)硬编码中文,绕过 13 语言 `_t()` shim——**Q2 钦点短板的修复对非中文用户不可见** |
| 评分智能 / 个性化 / 学习 | 3.1 | **3.5** | 门③结构性卡死:608 行训练集是「认可」不是「纠正」,规则栈对自己 acc=1.000,rescorer 无法 +3pp;**无纯代码解**——需 owner 从未筛选目录里补 ~50 条真实 keep↔maybe 分歧标注,否则整个学习头对包括 owner 在内的所有用户零收益 |
| 发布与 CI 卫生(新维度) | — | **2.0** | **无 Release 工作流**:v0.7.0 之后所有版本无 tag、无 GitHub Release、无产物附件;README 徽章永久停在 v0.7.0;wheel 2.19.0 本地已建未发布;sync-modelscope.yml 因缺 `MODELSCOPE_TOKEN` secret **每次推送必红**;pixcull.spec 的 CFBundleVersion 4.0.0 与 pyproject 2.19.0 脱钩 |
| 触达 / 发行 / onboarding | 2.5 | **2.8** | `pip install pixcull` 对所有非开发者仍然失败(wheel 未上传);USER-GUIDE 纯中文;10-onboarding.js 首访即弹 5 条硬编码中文(此时语言切换器还没露面);JS 启动默认 zh_CN、无 `navigator.language` 探测;语言循环只暴露 13 个 locale 中的 3 个 |
| 架构 / 技术债 / 可维护性 | 2.5 | **3.2** | results.css 是 5,797 行的**唯一从未做过任何抽取的源产物**——比 29 个 JS 模块加起来(2,535 行)还大;构建脚本有 `_assemble_js()` 却没有 `_assemble_css()`;改 lightbox 动画或筛选 chip 样式要在 5,800 行里裸滚 |

> 视频维度不再单列:v2.17–v2.20 玻璃盒三部曲(逐窗信号 → why-low → 音频车道 →
> 口味档案反馈回路)已收口,本轮换入「发布与 CI 卫生」——它是 gh run 记录里
> 唯一每次推送都亮红灯的地方,值得一个专属视角。

## 各维度已兑现(抽样,全部文件核验)

- **UX 3.8**:v2.15 收尾闭环完整(待审计数逐张递减 → 完成 chip 一键 XMP;决议队列
  最拿不准优先);v2.18 渐进水合 5k run HTML −60~84%;v2.20 Lr 同步刷新保滚动+焦点。
- **智能 3.5**:moment 轴去 stub(NaN→1.0 修复 + 微笑/wedding 置信真信号);
  轴级个性化接进融合(≥50 纠正激活、预算保持重归一);个人档案首次真实激活
  (keep 阈值 −0.060,holdout F1 0.801 vs 通用 0.799);v2.20 reel 口味档案
  (≥20 决议激活、倾斜 cap ±15%)。
- **发布 2.0**:tests.yml 三层流水线(导入烟测→密闭 pytest→定时 realmodel)整个
  v2.14–v2.20 期间全绿;版本 pyproject⇄`__init__` 单源化有守卫测试;wheel 已可
  一命令构建。分数低不是没做事,是**没有任何东西真正发出去**。
- **触达 2.8**:13 语言 locale 文件 + LRU 服务端端点;en_US 182 键的翻译基底
  真实完整——缺的是接线,不是基建。
- **架构 3.2**:serve_demo 18,225→12,906(−29%);results.js 11,800→9,390 + 29 模块
  机器 lint;do_GET 258 行 if/elif → 声明式路由表。

## 本轮新捡出的具体缺陷(纯代码,可直接修)

1. **9 条收尾/水合文案绕过 i18n**(见上表 UX 行,行号已核)。
2. **modules/20-undo-stack.js 是死代码**:它包装 `window.setDecision` 建 50 深撤销栈,
   但全仓**没有任何人**把 `setDecision` 挂到 window 上(已 grep 核验)——守卫
   `typeof window.setDecision === "function"` 永远为假,模块静默不生效。真正在跑的
   撤销是主闭包的 pushUndo/performUndo(上限 20)。两边都注册 ⌘Z,无害但纯属尸位。
   要么接线要么删除,且补一条端到端 ⌘Z 回归测试。
3. **sync-modelscope.yml 缺 secret 时 `exit 1`**:owner 没配 `MODELSCOPE_TOKEN` 前,
   每次推送这条工作流都红。纯代码缓解:改为 `exit 0` + `::warning::` 注解,
   等 secret 配好自动转真同步。
4. **app/pixcull.spec 版本硬编码 4.0.0**、Makefile `wheel` 不在 `.PHONY`、
   Homebrew cask 指向从未发布的 v0.8.0 DMG(SHA256 还是占位符)。
5. **自由配对比较严格两两**:第三张点击会重锚为新 A,丢失前一对;比较 modal 内部
   本就支持 n 格,只是 free-pick 入口只会链对。

## Owner 动作清单(按解锁价值排序,均无纯代码替代)

1. **~50 条真实 keep↔maybe 分歧标注**(需接外置盘,从未筛选目录选片)——这是
   adjudicate 激活的**唯一**闸门;不补,整个学习头对所有用户零收益。
   v2.15 决议队列 + shadow 分歧队列已把标注目标排好序,只欠人。
2. **给仓库配 `MODELSCOPE_TOKEN` secret**(Settings → Secrets → Actions;token 取自
   modelscope.cn/my/myaccesstoken)——止住每推必红;纯设置,零代码。
3. **推 tag `v2.19.0` / `v2.20.0`**(等 release.yml 合入后)——触发首批真实
   GitHub Release,修复 README 徽章,解锁 Homebrew tap。
4. **`twine upload dist_wheel/pixcull-2.19.0-py3-none-any.whl`**(需 PyPI 凭据)——
   wheel 已建好验证过,只差这一条命令,非开发者摄影师就能 `pip install pixcull`。

## v2.21 候选主题(workflow 综合排序)

### ① i18n 缺口收口:把 v2.15–v2.20 的收尾/水合文案接进 `_t()` · 工作量 S ·【综合推荐】
- **为什么**:v2.15 收尾闭环是 Q2 钦点短板的修复,却对非中文用户不可见。基础设施
  完备(164 键 × 13 语言、CI 键齐全性守卫、调用点纪律成熟),每条文案就是一次
  `_t('key')` 替换 + 优雅回退;零新机制,直接补完前两个季度一直在铺的故事。
- **首切片 P0**:9 个新键(workspace.stats.unreviewed / all_done、
  workspace.resolve_maybes、workspace.hydration.loading / incomplete、4 个 toast 键)
  加进全部 13 个 locale 文件;替换 results.js 九处硬编码(行号见上);把这 9 键
  纳入 test_i18n.py 现有键齐全性守卫。顺手处理缺陷 2(undo 死模块:接线或删)。
- **风险**:低。`_t()` 缺键优雅回退;键齐全性测试兜住 locale 文件手误;zh_CN
  用户零行为变化。

### ② 发布轨道:tag 触发的 GitHub Release 工作流 + sync 红灯止血 · 工作量 S
- **为什么**:v0.7.0 之后所有版本无 tag 无 Release 无产物,徽章永久过期。一个
  `release.yml`(v* tag 触发,只用内建 `GITHUB_TOKEN`,零外部 secret)即可修徽章、
  建立可 pip 安装的产物历史、解锁 Homebrew tap;sync-modelscope 红灯止血是 5 行
  纯代码,不必等 owner 配 secret。
- **首切片 P0**:`.github/workflows/release.yml`(checkout → setup-python 3.12 →
  `python -m build --wheel` → `gh release create $GITHUB_REF_NAME dist_wheel/*.whl
  --generate-notes`);同一改动里把 sync-modelscope.yml 缺 token 的 `exit 1` 改
  `exit 0` + `::warning::`;顺手对齐 pixcull.spec 版本、补 `.PHONY`。
- **风险**:工作流本身零 secret;但**首个 Release 要 owner 推 tag 才见效**
  (owner 动作 3);`gh release create` 对已存在 tag 幂等。

### ③ 英文首跑路径:navigator.language 启动探测 + onboarding i18n + 全语言循环 · 工作量 S
- **为什么**:非中文摄影师的**第一次**接触整屏中文:onboarding 卡片 5 条硬编码
  中文在语言切换器可达之前就弹出;JS 启动默认 zh_CN 不看浏览器语言;语言循环只有
  3/13。三个缺陷互相叠加——单修任何一个,另两个仍把体验按在地上。
- **首切片 P0**:`_getStoredLang()` 的 zh_CN 兜底改为 `navigator.language`
  归一化(映射表 pixcull/i18n.py 已有,~3 行);10-onboarding.js 5 条文案走
  `_t()`(新增 onboard.* 键 + 12 个 locale stub);`I18N_CYCLE` 从 3 扩到 13。
- **风险**:低。`_t()` 缺键回退;循环扩容是单行数组改动,无服务端依赖。

### ④ CSS @layer 拆分:补完模块化三部曲 · 工作量 S
- **为什么**:results.css(5,797 行)是全源码树**唯一**没做过任何抽取的产物——JS
  侧从 11.8k IIFE 拆到 9,390 + 29 模块,CSS 侧还是一整坨,比全部 JS 模块合计还大。
  拼接基建现成:`_assemble_js()` 加个 `_assemble_css()` 直接类比,golden-hash
  测试自动兜住任何字节漂移,v2.16 的风险/收益模式原样复刻。
- **首切片 P0**:build_results_html.py 加 `_assemble_css()`(`@@CSS:file.css@@`
  标记 + 孤儿标记 lint);先抽 design-tokens 块(~430 行)和 lightbox 块(~600 行)
  到 `src/modules/*.css`;`make results-html` 后断言 golden hash 字节一致;
  test_module_boundaries.py 加 CSS 标记纪律断言。
- **风险**:零行为变化——纯机械抽取,hash 验证;29 模块的 JS 先例无一回归。

## 推荐

综合排序推荐 **①(i18n 缺口收口)** 起步:S 工作量、零风险、直接补完 Q2→Q3 两个
季度的主线叙事。①+③ 同属"国际化收口",文件高度重叠(results.js + locale/*.json +
一个模块),**可以合并为一个 v2.21 打包做掉**——合并后总工作量仍是 S+。②(发布
轨道)是解锁 owner 动作 3/4 的前置,建议紧随其后或并轮做;④ 是无依赖的机械活,
适合任何一轮的"顺手第二刀"。

## 方法论延续

与 Q2 相同:5 视角(UX / 智能 / 发布卫生 / 触达 / 架构深度)各自真读代码打分,
综合 agent 汇总排序;所有行号/行数/tag/CI 结论在合入本文档前由主会话二次核验
(9 处硬编码行号逐行打印核对;`window.setDecision` 赋值全仓 grep;tag 列表、
I18N_CYCLE、`_assemble_css` 缺位均实测)。下一次体检建议在 v2.21–v2.2x 主题
收口后进行,重点复查:发布维度是否脱离 2 分档(有无第一个真实 Release)、
门③是否随 owner 标注解锁。
