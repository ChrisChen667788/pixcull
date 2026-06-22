# DESIGN-AUDIT 2030Q2 — v2.13 收口后的全局体检 + v2.14 选向

> 5 视角各自**真读代码/文档**给当前 v2.13 状态打分(多 agent 审计 workflow 产出),
> 不吹不黑。评分前先认账:透明度主题(v2.8→v2.13)确实成熟了,但产品最弱的几层
> 都是**地基级**而非装饰级——而且互相拖累。

## 总评:**3.0 / 5**

PixCull 有一套真正精巧的 AI 评分后端 + 成熟的透明度/可解释 UX,但产品被结构性地劈成
两半:**能力很强 ↔ 谁都装不上**。没有任何渠道有可下载产物;主前端是个 11,572 行的
单文件 IIFE(v2.13 一个不变量被破就同时炸出 9 个同类 bug,而 v2.5 就承诺的拆分拖了 9
个版本没做);号称差异化的「学习型智能栈」从未在**真实人工标注**上训练过。这三层
(发行、前端模块化、真实学习)互相压制:没有真实用户 → 没有真实纠正数据 → rescorer
永远训练不起来——而没真实用户,部分正是因为非开发者根本装不上。

## 各维度

| 维度 | 分 | 最大短板 |
|---|---|---|
| 核心 culling 主循环 + 可解释 UX | 3.5 | **无「审完」收尾信号**:1500 张婚礼批量逐张标完后,产品从不告诉你这一遍审完了、不显示未审数、也没有自然的「完事 → 写 XMP 回 Lightroom」出口 |
| 视频 / reel / 音频 / GPS | 3.5 | **视频侧没有照片侧的玻璃盒**:时序评分只有数字 HUD 条,没有逐窗「为什么低」的话术、没有音频事件叠层、没有 keep/cull → 权重的反馈回路 |
| 触达 / 发行 / onboarding / mobile | 2.5 | **零可下载产物**:Homebrew cask 的 SHA 是占位符、App Store 清单未勾、无 PyPI 包、无 CI 出安装包;唯一安装路径是 `git clone + pip install -e`,把所有非开发者摄影师挡在门外 |
| 评分智能 / 个性化 / 学习 | 3.1 | **rescorer 从未用真实人工标注训练过**:128 样本金标集太窄(一个摄影师、一天),文档显示 maybe/keep 带(误差最集中处)在所有模型族上都还是随机噪声;最重要的智能升级是纯脚手架、无训练产物 |
| 架构 / 技术债 / 可维护性 | 2.5 | `serve_demo.py` 仍 18,212 行 god-object(含 ~7,800 行内联 HTML/JS/CSS 散在 7 个裸字符串块);`results.js` 11,572 行单闭包 IIFE 无模块边界——v2.13 一处不变量破就同时炸 9 个不相关功能;**v2.5 承诺的拆分拖了 9 个版本没做** |

## v2.14 候选主题(workflow 综合排序)

### ① 前端拆分 + 可维护性(Frontend modularity)· 工作量 M ·【综合推荐】
- **为什么**:v2.13 这轮**实证**了单闭包 11.5k 行 results.js 的代价——一个不变量
  (build* vs render() 谁负责侧栏状态)被破,就在网格/lightbox/侧栏/撤销/同步/预设/
  收藏/Selects/⌘K 九处同时炸。422 个顶层声明 + 14+ 个 setup*() IIFE 挤在一个共享闭包;
  每加一个功能,下一个同类 bug 就更可能。serve_demo.py 18k 行还内嵌 ~7,800 行裸 HTML。
  这俩是架构 2.5 分的根因,且**不需要任何新产品能力,只是抽取+封装已能工作的代码**。
- **首切片 P0**:从 serve_demo.py 抽出最大的 `_VERTICALS_HTML`(~1,854 行)到
  `templates/verticals.html`(复用 v2.5 已验证的 `_read_template()` 模式)+ 加 golden
  测试;同时把 results.js 里 3–4 个最自洽的子系统(撤销栈 / 多 tab 同步 / onboarding /
  ⌘K 命令面板)抽到 `src/modules/*.js` 显式导出,经现有 `make results-html` 装配;给
  `test_results_build.py` 加「模块边界 lint」(禁跨模块共享闭包写)把不变量机器化。
- **风险**:golden 测试要求产物字节级不变——抽取必须保持渲染完全一致;撤销/同步与
  网格/lightbox 共享状态,边界划错会引回归。缓解:先做零逻辑抽取(HTML 块、onboarding)
  再碰有状态 JS。

### ② 发行物 + 首个可下载包(Ship the first artifact)· 工作量 M
- **为什么**:13 个语言包、iOS 伴侣 app、Homebrew cask、WiX 安装器、PyInstaller spec、
  公证清单……全是真代码,却全锁在「开发者安装墙」后。今天**零个非开发者摄影师**能装。
  这卡死了所有下游回路:没真实用户 → 没真实纠正 → rescorer 拿不到它需要的 400 样本。
  一个真·可运行·已签名的下载,是整个产品的总解锁。
- **首切片 P0**:接一条 GitHub Actions 发布流水线(tag 触发)→ PyInstaller 打 .app →
  签名公证 → .dmg 发到 GitHub Release → 回填 Homebrew cask 的真 SHA + URL;并把
  `pyproject.toml` 版本对齐。第二刀:英文 USER-GUIDE + 修 results.js 里 3 处硬编码中文
  onboarding 串走 i18n shim。
- **风险**:Apple 公证需有效开发者账号($99/年)+ CI 里的签名证书;PyInstaller spec
  从未生产验证过,把 torch/transformers/onnxruntime 正确打进 .app 是已知脆弱点。
  缓解:先本机验证 PyInstaller;若公证受阻,退而求其次先发 PyPI wheel。

### ③ 真实标注 + 激活智能栈(Real-data learning)· 工作量 M
- **为什么**:每个智能模块(轴 rescorer、二元 rescorer adjudicate、轴权个性化)都建好了
  却**惰性**——训练管线从未跑过真实人工标注。金标集 128 样本(一摄一日);
  RESCORER-V3 那次训练 200 行只产出 1 个 maybe(因 ground truth = 模型自己的判定)。
  产品最响亮的「瞬间(决定性瞬间)」轴,三个 rubric check 在非婚礼场景全返回 None。
  补这条不需要新模型架构,只需一次专注标注 + 一行配置。
- **首切片 P0**:用现有 `pick_next_to_label.py` 不确定性优先队列做一次 400 样本标注
  (按场景分层、偏 landscape/portrait/wedding 的 maybe),跑 `check_v1_2_trigger.py` 确认
  三道门(≥400 行、landscape AUC≥0.70、Δacc≥+0.03)全绿;若过,把 rescorer 从 off 翻到
  adjudicate(一行配置,代码自 v1.2 就 ready)。
- **风险**:标注需 owner 亲自看真实照片(400 样本约 3–5 小时);若 AUC 仍不达标,瓶颈
  可能是 moment 轴 stub,需另起子任务接 wedding_moment_confidence。轴权改动在每次 run 的
  热路径上,上线前需 golden-CSV 回归测试。

### ④ 收尾闭环 + maybe 决议(Session-close + maybe-resolution)· 工作量 S
- **为什么**:核心 cull UX **没有「审完」时刻**、也没有专门的 maybe 决议流。逐张标完
  1500 张后,工作条永远显示 keep/maybe/cull 总数,却从不显示「还剩 N 张没决定」,也没有
  自然的「我满意了 → 写 XMP」出口。maybe 带最需要人判断,而 rescorer_prob_keep 数据已有,
  却没有「按置信度顺序复审我的 maybe」模式。纯 UX 编排,不要新 AI,**最低风险**。
- **首切片 P0**:工作条加「未审」计数(n_total − 已人工确认),归零时脉冲打勾
  (「全部已审 ✓」);旁边加「决议 maybe」按钮 → 进 Selects 模式按 rescorer_prob_keep
  距 0.5 升序排(最模糊的 maybe 排最前),给一个清晰的收尾队列 + 完成感 + 通往已实现但
  藏起来的 Lr XMP 导出。
- **风险**:低。需精确定义「已人工确认」(keep/cull 清楚,maybe 算已审以免逼着二选一);
  rescorer_prob_keep 在 adjudicate 关时缺失,回退到 score_final 距 0.5。

## 推荐

**① 前端拆分 + 可维护性** —— v2.13 这轮已**经验性证明**单闭包 11,572 行 results.js
正在跨不相关功能持续制造同类 bug;这笔债 v2.5 就说要还、拖了 9 个版本越滚越大;还掉它
是**安全添加其它任何主题的前提**(否则继续引同类回归)。它不需要新能力,只需抽取+封装。

> 注:②③④ 都是真实高价值方向,且彼此解锁(发行 → 真实用户 → 真实标注 → 智能)。但
> ① 是地基:先把前端拆稳,后面三个主题加起来都更安全。最终选向交 owner。

## 方法论延续

v2.8「敢删」→ v2.9–v2.13「敢亮 + 让用户找得到看得懂 + 把根因查透」→ v2.14 候选「把地基
夯实 / 让人装得上 / 让智能真学起来 / 让一遍审得完」。这轮体检最大的认账:
**做了很多能力,但最弱的是地基——而地基决定了能力能不能到达真实用户手里。**
