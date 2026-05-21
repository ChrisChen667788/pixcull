# 婚礼 moment goldenset 工作流(P-PRO-4.2)

P-PRO-4 的 16 个 moment 提示是凭经验设计的;P-PRO-4.2 在真实婚礼数据集上跑了
混淆矩阵 + 三轮提示词调优。本文档记录工作流 + 调优过程,后续在新婚礼集上做
golden set 扩充时按此流程跑即可。

---

## 工具

- `scripts/eval_wedding_moments.py` — 在一个 JPG 文件夹上跑 CLIP zero-shot
  moment 分类,输出 `predictions.csv` + 分布报告
- `pixcull/scoring/wedding_moments.py` — 16 个 moment 词表 + 提示词
- `pixcull/detectors/wedding_moment.py` — `WeddingMomentDetector` 类

## 命令

```bash
# 1. 在新婚礼集上跑分类
python scripts/eval_wedding_moments.py /path/to/wedding/folder --out out_wedding_eval

# 2. 在 spreadsheet 里手动填 ground_truth_moment 列(predictions.csv)

# 3. 算混淆矩阵 + per-class 准召
python scripts/eval_wedding_moments.py x --confusion out_wedding_eval/predictions.csv

# 4. 只看分布(已存在的 predictions.csv 上)
python scripts/eval_wedding_moments.py x --report-only out_wedding_eval/predictions.csv
```

输出 CSV 列:`filename, predicted_moment, predicted_moment_zh, top1_prob,
runner_prob, margin, abstained, ground_truth_moment, top1_key, top2_key, top3_key`。

`ground_truth_moment` 一列留空给摄影师手填(只填非 `unknown` 的标签即可);
filename 列对应原图便于反向定位。

---

## V1 → V2 → V3 调优记录(在 81 张「已调色」交付集上)

### 诊断数据(三轮分布)

| moment           | v1  | v2  | v3  | 备注 |
| ---------------- | --: | --: | --: | --- |
| preparation_bride| 19  | 17  | 19  | v1 23.5% 占比,过度吸附 |
| reception_general| 17  | 20  |  4  | v2 反而变成磁铁;v3 通过收紧"宴席全景"提示降到合理 |
| candid           |  3  | 13  | 14  | v1 召回低,后续提示词加"behind-the-scenes" 显著提升 |
| group_portraits  | 10  |  4  |  5  | v1 吸附了"合影场景下其他时刻" |
| processional     |  7  |  8  |  8  | 稳 |
| preparation_groom|  4  |  6  |  7  | 稳 |
| first_kiss       |  2  |  2  |  2  | 稳 |
| recessional      |  0  |  2  |  2  | v1 完全识别不出;v2 加"applauding guests" 后区分了 processional |
| toast            |  1  |  0  |  3  | v3 收紧"单人举杯"提示后恢复 |
| speeches         |  0  |  0  |  3  | v3 加 "微克风 + 长桌" 后恢复 |
| first_look       |  2  |  2  |  3  | 稳 |
| bouquet_toss     |  3  |  2  |  2  | 稳 |
| ring_exchange    |  2  |  0  |  0  | 该婚礼可能没有戒指特写镜头 |
| vows             |  2  |  0  |  0  | 同上,小型仪式可能无独立宣誓镜头 |
| first_dance      |  0  |  0  |  0  | 同上,可能无第一支舞镜头 |
| cake_cutting     |  0  |  0  |  0  | 同上,可能无切蛋糕镜头 |
| unknown          |  9  |  5  |  9  | abstain 率 |

### 关键指标

| metric                | v1     | v2     | v3     |
| --------------------- | ------ | ------ | ------ |
| 唯一 moment 数        | 12     | 11     | 13     |
| abstain rate          | 11.1%  | 6.2%   | 11.1%  |
| median margin         | 0.428  | 0.549  | 0.391  |

V3 在唯一 moment 数上最高(分布最分散)、abstain 率与 v1 持平,但宣誓 / 切蛋糕 /
第一支舞这三个仪式独立镜头在本婚礼里可能本就不存在(小型仪式)。

### 仍存在的 moment 易混对

| 频繁互换的 moment      | 原因 |
| -------------------- | --- |
| preparation_bride ↔ reception_general | 室内+正装+人脸的特征接近 |
| first_look ↔ first_kiss | 都是亲密肢体接触 + 正装 |
| processional ↔ recessional | 都是"走过道",方向无法仅靠 CLIP 区分 |
| candid ↔ reception_general | candid 在宴席场景里发生时难分 |

### v3 提示词调整原则

1. **添加视觉锚定**:把"a bride getting ready"改成"morning silk robe +
   mirror + styling tools",CLIP 会更倾向于真正的准备场景,而不是任何
   穿白色衣服的女性。
2. **增加上下文道具**:"标准镜头 + 道具列表"远比抽象描述更稳。比如
   first_dance 加 "dance floor + spotlight + embracing while turning"。
3. **明确反差词**:recessional 的 "applauding guests stand and cheer behind"
   把它从 processional 隔离开。
4. **场景全景 vs 特写区分**:reception_general 改成 "wide overview..."
   遏制了磁铁效应。

---

## 下一步:扩张到多婚礼 golden set

单一婚礼(81 张)训练好的提示词对其他婚礼可能不普适。建议:

1. 在 ≥ 3 场不同风格的婚礼上跑 `eval_wedding_moments.py`(中式 / 西式 / 海岛 /
   小型);
2. 每场抽 30 张代表性照片,手填 `ground_truth_moment`;
3. 合并跨婚礼的 ground truth → 算总体混淆矩阵;
4. 跨婚礼一致性低的 moment(<60% accuracy)需要进一步分子类(比如把
   `first_look` 分成 `first_look_outdoor` / `first_look_indoor`)。

### 状态 · 2026-05-21

尝试在第二场婚礼上跑混淆 — 当前可访问的外置盘
(`/Volumes/One Touch 1/`)只有一场婚礼(李慧&李翔)。其他大批量
照片文件夹(2022川西行 / 共青森林公园 / 阿尔山 / 霞浦)都是
风光 / 街景,没有第二场婚礼可用。

**P-PRO-4.3 加入的 6 个中式 moment** 提示词(敬茶 / 跪拜 / 接亲 /
梳头 / 红嫁衣 / 鞭炮)目前**完全没有真实数据验证** — 仅靠
"a kneeling couple serving tea to parents" 这类描述训练 CLIP。
召回率可能差,精确度可能很差(图像没人脸的"敬茶"场景可能
无法检测)。

**unblock 路径**:
- 用户在交付 ≥ 1 场中式婚礼后,把 RAW 或 JPG 文件夹路径告诉这个
  agent;一行命令跑 `eval_wedding_moments.py` 即可出诊断报告。
- 或者:用合成图(stable diffusion / Midjourney 生成"中式婚礼
  敬茶场景")验证 prompt 召回率 — 但合成图与真实婚礼有 visual
  gap,不如真实数据。

中式 moment 的 i18n 已就位(`results.html I18N_WEDDING_MOMENT`),
`MANDATORY_CHINESE` preset 已就位(`MANDATORY_PRESETS["chinese"]`),
`cli_audit --mandatory-preset chinese` 已能输出中式覆盖率报告。
所以**代码侧准备完毕**,只缺数据。

---

## 已知限制

- CLIP zero-shot 没有方向理解(processional / recessional 仅靠"guests
  applauding behind" 区分,如果观众视角不全则失败)。
- 中式婚礼独有的「敬茶」「跪拜」moment 还没纳入词表 —— P-PRO-4.3 计划做
  本地化扩展。
- `mandatory` 标签按西式仪式定义。中式仪式建议自定义 `MANDATORY_OVERRIDES`
  传给 `coverage_audit`(目前是常量;follow-up 改成参数化)。

---

报告时间:2026-05-21
评估数据集:`/Volumes/One Touch 1/李慧&李翔/已调色` (81 张)
评估硬件:Apple Silicon MPS,~0.5s / 张推理
