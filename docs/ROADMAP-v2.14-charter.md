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

## P1 — axis_weights 轴级个性化接线(已交付)

**问题**:`personal_learn.py` 已算逐轴权重(各轴 keep-mean−cull-mean 差),但 orchestrator
只用 `personalized.py` 的**标量** `keep_threshold_shift`——「重视构图胜于技术」的用户和
其他人拿到完全一样的轴权融合。

**做了什么**:
- `fusion.py`:`fuse_score` 加可选 `axis_pref` + `_personalize_weights()` 助手——把 rubric
  轴偏好映射到 5 个 fusion 维(sharpness←technical / exposure←light / 其余 1:1;subject 无
  对应维),按夹紧倍率 **[0.5, 2.0]** 倾斜每维权重、再**重归一化保持权重总和不变**(只改
  分布不改尺度)。`axis_pref=None`(默认,所有其它调用方)→ **完全不变**。
- `orchestrator.py`:profile 激活(≥50 纠正)时算 `_axis_pref = axis_weights(_pp)` 传入
  fuse_score,并在 banner 打印「axis-weighted toward <最重轴>」。
- 设计哲学与 ±0.08 阈值上限一致:**轻度倾斜而非覆盖**;退化/等权 profile 是 no-op。

**验证**(严格遵循 [[评分热路径]] 纪律):
- 单测 `tests/test_personal_axis_weights.py` 7 项(无 pref 兼容 / 等权 no-op / 倾斜方向 /
  夹紧不塌缩 / 总和守恒 / axis_weights→fuse_score 真接线)。
- **无 profile 端到端 A/B**:samples 逐帧 score_final **字节级一致**(axis_pref=None no-op
  成立,默认用户零影响)。
- **激活路径**(合成 composition-lover profile、keep_threshold_shift=0 隔离纯轴效应,用完
  即删不污染本机):构图强帧提分、构图弱的 eagle keep→maybe——倾斜方向正确。
- 完整门禁全绿。

## P1.1 — moment 轴深化(已交付)

P0-1 让 moment 非常数,但 `action_at_peak` 仍恒 None、`emotion_present` 仅婚礼可评。
本轮接入两个**已存在的真实信号**(不伪造、不新增模型):
- **`action_at_peak` ← 连拍峰值**:真连拍(size≥2)里 burst-peak ranker 加冕的那帧
  (`burst_peak_reason` 非空)就是捕捉到的动作峰值 → True;输掉的帧 → False;单张
  (`is_burst_peak` trivially True 但无 reason)→ None(无动作序列可言,不伪造)。
- **`emotion_present` ← 微笑**:非婚礼场景用 MediaPipe `face_max_smile` blendshape
  (≥0.30 = 表情在场);无脸/无信号 → None。
- **`moment_score`(worker)并入 smile**:睁眼中性脸仍 0.60(不回归),满笑升到 0.85;
  闭眼 0.40。

验证:`tests/test_moment_axis.py`(burst-peak 真连拍判定 4 例 + 非婚礼 smile 4 例)·
landscape A/B:**decision/score_final 全不变**(rubric 星不喂 score_final;合成图无微笑→
worker moment_score 不变),唯一变化是 sunset 误检脸的 `rubric_moment_stars` 4.25→2.16
(无笑中性脸 moment 星正确下降,真实数据上合理)· 完整门禁全绿。

> 注:这些 rubric 星(moment 现已含表情/动作)是 adjudicate 翻开后 rescorer 的**特征**——
> 这正是「去 stub 让它可学」的闭环:特征非常数了,真实标注一来就能学到这条轴。

## P0-2 — 标注 session(owner 执行,工具+手册已备)

运行手册:[`docs/LABELING-SESSION.md`](LABELING-SESSION.md)——逐条命令(shadow 采集 →
`pick_next_to_label` 优先队列 → 标 ≥400 条 → `export_training_set` →
`check_v1_2_trigger` 三门 → 训练 → `--rescorer-mode adjudicate`)。**真实标注必须你来**;
标完我接手跑门禁+训练+off/adjudicate golden A/B+翻默认。axis_weights(P1)与 moment 轴
(P0-1/P1.1)都已接好线、可学——**只等这一批真实标签做总开关**。

## P2 — 航拍主题(aerial scene,已交付)

owner 要求:DJI 航拍素材后续归到「航拍」主题。纯视觉 CLIP 难把航拍风光和地面风光分开,
所以走**确定性 EXIF 覆盖**:
- `io/exif.py`:`read_exif_make_model()` + `is_drone_camera()`——按**机型 Model 码**识别
  (DJI 相机模块 `FC####`;Mavic 2 Pro / Mavic 3 报 Make="Hasselblad" + Model
  `L1D-20c`/`L2D-20c`),**只匹配机型不匹配 Make**,避开真·哈苏中画幅(X1D/907X);兜底
  认 `DJI_` 文件名。
- `worker.py`:场景分类后,若判定为无人机 → 覆盖 `scene="aerial"`(仿 stilllife rerank
  模式)。**不动 CLIP 的 SCENE_PROMPTS**,所以非无人机照零扰动(不引入 softmax 漂移)。
- `genre_strategies.py` 加 aerial 策略(俯瞰构图/图案/光影主导,抑制人脸·瞬间类 check);
  `scene_templates.yaml` 加 aerial 模板(同风光,用默认权重)。

验证:`tests/test_aerial_scene.py` 7 项(DJI make / FC 码 / 哈苏-DJI 机型 / 真哈苏排除 /
普通相机 / DJI_ 文件名 / 下游注册)· **端到端 A/B**:16 张真实 DJI 航拍**全部归 aerial**,
10 张佳能非DJI 场景**字节级不变、零误判**· 完整门禁全绿。

## 方法论延续

v2.13「把根因查透」→ v2.14「**让评分轴非常数、让智能真能学**」。本轮最大的教训复刻了
v2.13 的精神:**单测过 ≠ 没 bug——DataFrame 的 NaN 强转只有端到端 A/B 抓得到。**
任何动评分热路径的改动,必须 stash-基线 A/B + golden 回归,而不是只靠单测。
