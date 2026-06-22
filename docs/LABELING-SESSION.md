# PixCull 标注 session 运行手册(v2.14-P0-2)

> 「激活智能栈」的总开关:**你的 ≥400 条真实人工标注**。代码侧(P0-1 moment 去 stub、
> P1 轴级个性化、P1.1 moment 深化)都已就绪并让评分轴**可学**;现在缺的只有真实标签。
> **不能用模型自己的判定当标签**——那正是 RESCORER-V3 翻车的原因(200 行只出 1 个 maybe、
> AUC 0.497 随机)。本手册是你自己跑这一遍的命令清单;标完我可接手跑门禁+训练+golden 回归。

所有命令在仓库根、用 `pixcull/.venv/bin/python`。

## 0. 先用 shadow 模式跑你的真实照片(采集 + 不改判定)

```bash
pixcull/.venv/bin/python -m pixcull run /path/to/your/photos \
  -o /path/to/out --rescorer-mode shadow
```
`shadow` = 加载 rescorer、给每张算 P(keep) 附在记录上,但**判定仍由规则栈定**(安全、可长期开)。
产出 `out/scores.csv`(含 `rubric_<axis>_stars` — P0-1/P1.1 后 moment 轴已非常数)。

## 1. 标注(你的主观判断)

**最省事:CSV 表格法(推荐)**——把 scores.csv 转成一张可直接填的表:
```bash
pixcull/.venv/bin/python scripts/make_label_sheet.py out/scores.csv -o label_sheet.csv
```
用 Excel/Numbers 打开 `label_sheet.csv`(已按**不确定性优先**排序——模型最拿不准的
maybe/keep 边界排最前,你的判断最值钱),在 **`manual_label`** 列填 `keep`/`maybe`/`cull`
(留空=跳过),存回 CSV。表里带模型当前判定 + score_final + 各轴星做参考。
> 样例:仓库根的 `label_sheet_DEMO.csv`(由 6 张样例生成)就是这个格式,可先打开看看。

或两条传统路:
- **Web UI**:`PYTHONPATH=. pixcull/.venv/bin/python scripts/serve_demo.py` → 打开 run,
  键盘 1/2/3 标;写入 `annotations.jsonl`。
- **`pick_next_to_label.py`**(已有 gt 时,挑下一批补场景短板):
  `... scripts/pick_next_to_label.py out/scores.csv ground_truth.csv --n 50 --out-csv next.csv`

目标:**≥400 条**,按场景分层,重点补 landscape / portrait 的 maybe(审计 §V1.1 短板)。
填好的 `label_sheet.csv`(`filename` + `manual_label`)就是 ground-truth,交给第 2 步。

## 2. 导出训练集 + 跑「能不能发」门禁

```bash
pixcull/.venv/bin/python scripts/export_training_set.py ...   # 见 --help
pixcull/.venv/bin/python scripts/check_v1_2_trigger.py training.csv
```
三道门(全绿才发):**≥400 行 · landscape AUC ≥ 0.70 · Δacc ≥ +0.03**。
若 landscape AUC 不达标,通常是样本仍不够/偏 → 回第 1 步补标该场景。

## 3. 训练(门禁绿后)

```bash
pixcull/.venv/bin/python scripts/train_rescorer.py ...        # → models/rescorer_v1.joblib
pixcull/.venv/bin/python scripts/train_axis_rescorers.py ...  # 逐轴(含已去 stub 的 moment)
```

## 4. 翻到发布模式 adjudicate

```bash
pixcull/.venv/bin/python -m pixcull run /path/to/photos \
  -o /path/to/out --rescorer-mode adjudicate
```
`adjudicate` 只重排**规则判 maybe** 的中间档(P(keep)≥0.75 升 keep;
maybe_to_cull_threshold 默认 0 = 暂不降级)。规则的 keep/cull 永不动。
要设成默认,改 `config.rescorer.mode`(默认模板),否则每次带 `--rescorer-mode`。

## 我能接手的部分(你标完之后)

- 跑 `check_v1_2_trigger.py` 出三门报告;
- 跑训练出 `rescorer_v1.joblib` + 逐轴模型;
- **off vs adjudicate 的 golden-CSV A/B**(同一批真实 run,逐帧 diff decision/score_final,
  确认 adjudicate 只动 maybe 档、不误伤规则 keep/cull)——遵循
  `[[pixcull-scoring-hotpath-testing]]` 的热路径纪律;
- 达标后把默认 mode 翻成 adjudicate + 更新 README/charter + 同步。

把标注产物(`scores.csv` + `annotations.jsonl`/`ground_truth.csv`,**本地、不进公开仓库**)
准备好,叫我即可。
