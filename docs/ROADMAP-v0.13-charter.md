# v0.13 charter — AI judgement transparency (Thesis C)

## 上下文(v0.12 release 后)

v0.11 closed v0.10's infrastructure debts; v0.12 pushed every
interactive surface to the Raycast / Lightroom-Second-Window /
DaVinci ceiling.  `docs/DESIGN-AUDIT-2027Q2.md` scores the average
at 4.3 / 5 — but every score on every card is still opaque:

> "You said score_final = 0.74.  Why?"

v0.13 main theme: **"AI judgement transparency — every score on
every card explains itself in one tap, no more 'trust the model'."**

This is the last major theme before v1.0.

## v0.13 工作范围

### P0(必须做)

#### v0.13-P0-1 · Per-axis 像素级 attribution heatmap
**估时**: 2 周

- 6-axis rubric stack:`technical` / `subject` / `composition`
  / `light` / `moment` / `aesthetic`
- 各轴对应的 timm backbone 模型(已存在 `models/rescorer_axis_*`)
- 用 **Integrated Gradients** (50 steps) 生成 256×256 显著度图,
  叠在原图上;Captum 或 ~150 行 torch.autograd 手实现
- Lightbox 按 **`A`** 键切换 → 顶部 6-tab 选轴 → 中间 alpha=0.5
  叠加图
- 缓存:第一次按 `A` 即触发 batch 计算所有 6 轴,后续切换瞬时
- 输出文件:`output/attribution/<axis>/<filename>.png`(共享 gitignore)

#### v0.13-P0-2 · Counterfactual chip("如果换成黄金分割")
**估时**: 2 周

- 离线训练一个 lightweight composition rule classifier(MobileNetV3-Small,
  Rule of Thirds / 居中 / 三分法 / 对角线 4 类,~5k 标注图)
- 对当前照片做 perturbation(裁切重组,生成 N=10 个虚拟变体)
- 用现有 rescorer 评分,取 max delta → chip 显示
  "+0.08 if rule-of-thirds"
- Inspector "构图"chip 旁加可点击 ⓘ 图标 → 展开 counterfactual

#### v0.13-P0-3 · Confidence-weighted decision modal
**估时**: 1.5 周

- 当 model 输出 `0.45 ≤ score_final ≤ 0.55`(maybe 临界区),
  card hover 时浮出轻量 modal
- 内容:`60% sure · top reason: tied burst neighbor 0.02 higher · 2nd reason: face slightly under-exposed`
- "Top reason" 来自 v0.13-P0-1 attribution:取贡献最大的轴 + 其 rationale
- 用户可"记住关闭"(per-run localStorage)

#### v0.13-P0-4 · Bias audit dashboard (`/admin/bias`)
**估时**: 1.5 周

- 全 user / run 的 cull rate per:
  - scene tag(wedding / landscape / portrait / ...)
  - face cluster(主新郎 / 主新娘 / 客人)
  - time-of-day(getting-ready / ceremony / reception)
  - aperture bracket(f/1.4-1.8 / f/2-2.8 / f/4+)
- 红色 highlight 偏离均值 > 1.5σ 的桶
- 提示语:`rescorer 可能在 *夜景人像* 上过严(cull rate 38% vs 全局 22%)`
- 数据源:`~/.pixcull/runs/**/annotations.jsonl` + scores.csv
  (v0.12-P0-3 已经写入 model_decision 字段)
- 缓存:`~/.pixcull/cache/bias_audit.json`,TTL 24h

### P1(应该做)

#### v0.13-P1-1 · "解释为什么这张被分到 cull"自然语言摘要
**估时**: 1.5 周

- 本地 ggml-Q5 Qwen2.5-3B(或 Llama-3.2-3B)跑 ~50 token 摘要
- 模板化输入:top 3 axis attribution 文本 + neighbor delta + similar
  past culls scene
- 输出:"Slightly soft on the bride's eyes; the next frame is 0.04
  sharper."
- 全本地,不上 cloud;每张照片 ~200ms 推理(可接受,因为按需触发)

#### v0.13-P1-2 · Style ref 视觉相似度可视化
**估时**: 1 周

- Inspector chip 点开 → 显示当前照片对每张 ref 的 CLIP cosine
  distance(柱状图 + ref 缩略图)
- 直观看到哪张 ref 在拉分,哪张是 outlier
- 排序按 distance,ref 旁标 "+0.12 contribution"

#### v0.13-P1-3 · Conflict resolution dashboard
**估时**: 1 周

- 人工 keep 但 model cull,或反之 → 记入 `disagreement.jsonl`
  (annotations.jsonl 已经有 model_decision 字段,无需新结构)
- `/admin/disagreement` 列出最近一周的 disagreement 走势
- 链接到 v0.13-P0-4 bias dashboard 的对应桶

#### v0.13-P1-4 · Goldenset 自动扩充
**估时**: 4 天

- 每周(或手动触发)从 disagreement.jsonl 抽 N=200 最有信息量
  (rescorer_prob_keep 接近 0 或 1 但 human 反过来)的 rows
- append 到 `goldenset/v0.13/ground_truth.csv`
- 闭环:用户改判 → goldenset 扩充 → 下版 rescorer 训练
- Cron-like:`scripts/goldenset_auto_augment.py`

#### v0.13-P1-5 · "为什么 keep"也给解释(positive attribution)
**估时**: 1 周

- v0.13-P0-1 默认对 cull / maybe 生成 attribution;P1-5 把它
  扩到 keep 也生效
- 给摄影师 "为什么 model 喜欢这张"的反馈
- 帮助风格自我意识:发现自己潜意识里偏好的轴

### P2(锦上添花)

#### v0.13-P2-1 · 摄影师"标定自己的偏好轴"
**估时**: 1 周

- `/settings/axes` 复用 v0.12 shortcut 持久化方案
- 用户可隐藏某些通用轴(如"sharpness"对纪实摄影师无意义)
- 排除轴后,score_final 重新加权

#### v0.13-P2-2 · Bias 自检报告导出 PDF
**估时**: 3 天

- `/admin/bias` 加"导出 PDF"按钮
- 报告含:全局 cull rate 分布 / 1.5σ 偏离桶 / 趋势图 / 建议行动
- 给 wedding studio 给客户用("我用 AI 但 AI 受过 bias 审计")

#### v0.13-P2-3 · DESIGN-AUDIT-2027Q3 + v1.0 release plan
**估时**: 3-4 天

- v0.13 release 后做最后一轮 design audit
- 起草 v1.0 release gate criteria(`docs/RELEASE-V1.md`)

## 不做的事(scope discipline)

- **不重写 rescorer 训练 pipeline**:沿用 sklearn 直到 v1.0
- **不引入 cloud LLM**:NL explainer 全本地
- **不替换 timm backbone**:axis rescorers 已 production-ready
- **不做 generative editing**:PixCull 是选片,不是修片

## 验收标准

v0.13 release 完成的标志:

- **每张照片在 lightbox 按 `A` 弹出 6-axis attribution heatmap**
- **counterfactual chip 默认开**(Inspector 构图 chip 旁 ⓘ)
- **`/admin/bias` 跑历史 6 个月 audit + 红色高亮偏差桶**
- **所有解释 100% 本地推理**(继续 local-first 承诺)
- **NL explainer + style-ref viz + disagreement dashboard** 都落地
- **goldenset 自动扩充流跑通**,v0.14 训练直接消费 v0.13 增量
- 文档:`docs/EXPLAINABILITY-V1.md` 写完(P0 batch 综合说明)

## 建议外部资源 / 灵感参考

- **Captum** — Integrated Gradients 参考实现
- **Lightroom AI Mask** — Adobe 的 explanation 模型(他们做得不好,我们能做得更好)
- **DataRobot** — bias dashboard 标杆(企业级)
- **ggml** / **llama.cpp** — 本地 LLM 推理框架

## 建议执行顺序(预计 6-8 周)

| 顺序 | 任务 | 估时 | 理由 |
|---|---|---|---|
| 1 | **P0-1** Attribution heatmap | 2 周 | foundation — 所有 explanation 上层依赖 |
| 2 | **P0-4** Bias dashboard | 1.5 周 | 独立 scope,先做不阻塞 P0-2 |
| 3 | **P0-2** Counterfactual | 2 周 | 需要 classifier 训练,scope 较大 |
| 4 | **P0-3** Confidence modal | 1.5 周 | 依赖 P0-1 attribution |
| 5 | **P1-2** Style ref viz | 1 周 | 独立,复用现有 CLIP embedding |
| 6 | **P1-3** Disagreement dashboard | 1 周 | 复用 bias dashboard 框架 |
| 7 | **P1-1** NL explainer | 1.5 周 | 集成 ggml,需要少量 cleanup |
| 8 | **P1-4** Goldenset auto-aug | 4 天 | 独立 scope |
| 9 | **P1-5** Positive attribution | 1 周 | P0-1 的 keep 路径扩展 |
| 10 | **P2-x** | 视情况 | 收尾 + v1.0 plan |

---

charter timestamp: 2027 Q2(v0.12 release 后立即起草)
expected start: v0.12.0 release tag 推送后
expected duration: 6-8 周(v0.13 release 2027 Q3 mid)
predecessor: docs/ROADMAP-v0.12-charter.md
related: docs/DESIGN-AUDIT-2027Q2.md(v0.13 的依据)
