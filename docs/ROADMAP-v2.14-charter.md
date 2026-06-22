# ROADMAP v2.14 — 真实标注 + 激活智能栈 charter

> 承接 DESIGN-AUDIT-2030Q2(总分 3/5)。审计认账:号称差异化的「学习型智能栈」
> **从未在真实人工标注上训练过**,且若干评分轴是 stub——即便有了真实标注也学不动。
> 本主题:把智能栈从「脚手架」变成「真在学」。

## 硬约束(先认账)

400 样本的**真实人工标注必须 owner 亲自做**——那是你对自己照片的主观判断。
**不能伪造**:RESCORER-V3 那次正是用「模型自己的判定」当 ground truth,200 行只产出
1 个 maybe、AUC 0.497(随机),整轮训练作废(见 `docs/RESCORER-V3-RESULTS.md`)。
所以「把 rescorer 翻到 adjudicate」这一步**依赖你的标注 session**,我不替你点。

但「激活智能栈」里有大量**我能自主做、不需要新标注的真代码**——本轮先把这些做掉,
让你之后的标注 session 一来就能真正学到东西。

## P0-1 — moment 轴去 stub(本轮已交付)

**问题**:`moment`(决定性瞬间,产品最响亮的轴)在评分数学里是惰性的:
- fusion:`moment = raw.get("moment_score", 0.5)`,而 worker **从不写** `moment_score`
  → 对**每一张照片**恒等于 0.5。
- rubric:`action_at_peak` / `emotion_present` 直接 `return None # 需人工标注`。
- 后果:moment 是一个**常数特征**。常数对 rescorer **零信息**——即便有了真实标注,
  这条轴也永远学不动。**所以去 stub 是「激活智能栈」的前提,不是锦上添花。**

**做了什么**(只用诚实存在的信号,不伪造):
- `worker.py`:写真实 `moment_score`——wedding 场景用 `wedding_moment_confidence`
  (分类器已估计「是否情绪/决定性峰值」∈[0,1]);有脸时用 `closed_eyes`(眨眼=坏瞬间
  0.40,睁眼=可用 0.60,保守);**无信号(风光/无脸)留 None** → fusion 保留刻意的
  中性 0.5,**风光帧与 v2.13 字节级一致**(端到端 A/B 实证)。
- `fusion.py`:`comp`/`moment` 经 `_coalesce()` 把 None **和 NaN** 归 0.5。
- `rubric_decompose.py`:`emotion_present` 在 wedding 场景从 `wedding_moment_confidence`
  真评估(≥0.5);`action_at_peak` 仍诚实 None(stills 无信号,不伪造)。

**端到端回归救下的真 bug**:`fuse_score` 是用 `row.to_dict()` 从 **pandas DataFrame**
取值的——worker 写的 `None` 在 float 列里变成 **NaN**,`x is None` 抓不到,NaN 穿过
加权和后 `min(1.0, NaN)` **clamp 成 1.0** → 每张无信号照片 score_final=1.0 = **恒 keep**。
单测因传 Python `None` 没复现这个,是端到端 A/B(stash 我的改动跑基线对比)抓到的。
已用 `_coalesce`(None+NaN)修复 + 加 NaN 回归守卫测试。

**验证**:`tests/test_moment_axis.py` 8 项(含 NaN 守卫)· landscape A/B:6 帧里 5 帧与
纯 v2.13 基线 score_final **完全一致**,唯一变化是 sunset(检出脸 → moment 0.6 → +0.01,
决策仍 keep)——正是「唯一有真信号的帧得到小而正确的提升」。完整门禁全绿。

## P0-2 — 标注 session 启用(owner 执行,我备好工具)

工具链已在仓库:`scripts/pick_next_to_label.py`(不确定性优先队列)、
`scripts/check_v1_2_trigger.py`(三道门:≥400 行 / landscape AUC≥0.70 / Δacc≥+0.03)。
**待办(owner)**:用真实照片做一次 ~400 样本标注(按场景分层,偏 landscape/portrait
的 maybe 短板),跑 check_v1_2_trigger;若三门绿,把 rescorer 配置从 `off` 翻到
`adjudicate`(一行)。我可在你标完后协助跑门 + 翻配置 + golden-CSV 回归。

## P1(后续,纯代码、我可做)

- **axis_weights 接进 orchestrator**:`personal_learn.py` 已算逐轴权重(keep-cull 分歧),
  但 orchestrator 只用 `personalized.py` 的标量 `keep_threshold_shift`。把逐轴重加权接进
  per-row fusion(≥50 纠正才激活),让「重视构图胜于技术」的用户得到轴级个性化而非全局
  阈值微移。**注意**:动 fusion 热路径,上线前必须 golden-CSV 回归(就像本轮 moment)。
- **moment 轴深化**:若标注后 moment 仍弱,考虑把 `wedding_moment_confidence` 推广到
  非婚礼场景的表情/峰值代理,或接一个轻量表情检测器(让 `action_at_peak`/非婚礼
  `emotion_present` 不再 None)。

## 方法论延续

v2.13「把根因查透」→ v2.14「**让评分轴非常数、让智能真能学**」。本轮最大的教训复刻了
v2.13 的精神:**单测过 ≠ 没 bug——DataFrame 的 NaN 强转只有端到端 A/B 抓得到。**
任何动评分热路径的改动,必须 stash-基线 A/B + golden 回归,而不是只靠单测。
