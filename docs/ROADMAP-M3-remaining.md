# M3 迁移 — 排期(已全部实现,v2.52 收口)

> **状态 2026-08-12:v2.48 → v2.52 全部落地,门禁 1900 passed / 9 skipped / 0 failed。**
> 唯一没做成的是 **v2.49 的测量本身** —— 它需要真实 MiniMax key 调 M3,
> 而我不代收代管密钥。工具已完整可用,差一条命令:
>
> ```
> pixcull m3 doctor --image <照片> --video <片段.mp4>
> pixcull m3 eval --labels ~/pixcull_label_run/training_combined.csv \
>                 --scores <某次 run>/scores.csv
> ```
>
> **报告的结论允许是「不该翻默认值」。** 若测出 M3 并不更准,
> v2.50 的默认值应该改回 `off`,并把 v2.50 改写过的文案再改回去 ——
> `tests/test_claims_match_reality.py` 会强制这两件事同步。


v2.48 已收口(4 个提交)。下面是**还剩 4 个版本**,以及每个版本的全部开发任务。

排期里有一个刻意的顺序调整:**先测量,再翻默认值**。v2.48 把 M3 造成了
一个能用的判官,但**没有任何证据表明它比规则栈更准**。在拿到那个证据之前
改写产品定位,是拿公开承诺去赌一个未验证的假设。所以 v2.49 是测量版,
v2.50 才是定位版,且 v2.50 以 v2.49 的结论为前置条件。

---

## v2.48 — 已完成 ✅

| 切片 | 内容 | 状态 |
|---|---|---|
| P0 | M3 适配器:正确契约、限速、缓存、重试、预算、`m3 doctor` | ✅ `cb2ab53` |
| — | `--speakers` 不再关掉逐字剪辑 | ✅ `e5a4410` |
| P2 | VLM 阶段并发化 + 四处「够不到」修复 | ✅ `2559e76` |
| P1 | 判官获得真实裁决权(能力就位,默认仍关) | ✅ `bd4fed8` |

门禁 1799 passed / 9 skipped / 0 failed;三轮变异测试 8/8 + 3/3 + 8/8。

---

## v2.49 — 测量:M3 到底比规则栈强多少

**这是翻默认值的前置条件,不是可选项。**

现在无人知道 M3 的判决是否更准。owner 手上有 608 行人工校正集
(`~/pixcull_label_run`),那是唯一能回答这个问题的东西。

### 开发任务

1. **`pixcull eval-vlm` 子命令** — 在标注集上跑 shadow 模式,输出混淆矩阵:
   规则栈 vs M3 vs 人工标注。指标:keep/cull 的 precision、recall、F1,
   以及**分歧样本清单**(规则说 cull、M3 说 keep 的那些,逐张列出)。
2. **成本与时延实测** — 608 张的真实 token 消耗、wall-clock、缓存命中率。
   把 charter 里 `~15 分钟 / ~¥13` 的估算换成实测数字。
3. **自洽性守卫的真实触发率** — `vlm_incoherent` 到底拦下了多少、拦对没有。
   若触发率 <1%,说明守卫是死代码;若 >10%,说明 prompt 有问题。
4. **分垂类拆解** — 婚礼 / 儿童 / 风光分别看。M3 很可能在「时刻」类
   垂类赢很多、在「技术」类垂类持平或输。这决定 P5 该怎么写文案。
5. **`vlm_kept_despite` 的人工复核** — 抽 30 张 M3 推翻硬性 cull 的图,
   owner 亲自判「这次推翻是对的吗」。这是唯一能验证「证据融合」是否
   真的работает 的方法。
6. **eval 报告落 `docs/M3-EVAL.md`**,数字进 README 的对比表。

### 前置(owner)

- `pixcull m3 doctor --image <photo> --video <clip.mp4>` 跑一次
- 新 MiniMax key(旧的已在对话里泄露,必须吊销)

### 出口判据

M3 在 keep/cull 上的 F1 **显著高于**规则栈,或在某几个垂类上显著更高。
若持平 → v2.50 不翻默认值,M3 保持 opt-in,定位不改。**这个结论是允许的,
也是可能的。**

---

## v2.50 — 定位:说真话(条件性)

**只有 v2.49 给出正面结论才执行。** 这一版把默认值翻成 M3,同时把 47 处
公开声明改对。**两件事必须同一个提交** —— 先翻默认值,README 就成了谎;
先改声明,README 又谎向另一边。

### 开发任务

1. **默认值翻转** — `run_pipeline(vlm_authority="primary")`、launcher、
   serve_app、CLI 四处联动。
2. **首次上传同意闸门** — 第一次要传照片时必须明示并等确认。不是勾选框
   的默认打钩,是必须主动点。婚礼合同禁止第三方云处理是真实存在的约束。
3. **每张照片的「云端分析」标识** — results.html 加角标,让摄影师一眼
   看出哪些图出过网。`vlm_kept_despite` 也要在灯箱里露出。
4. **47 处声明改写**(清单已在 `ROADMAP-v2.48-m3-charter.md`):
   - `pyproject.toml` — description + 去掉 `local-first` / `on-device-ai` keywords
   - `README.md` — 徽章、hero、特性列表、对比表、Mermaid 图,中英各一套
   - `README-PYPI.md` — 「No photo ever leaves your disk.」是全仓最强承诺
   - `modelscope/README.md` — YAML tags、徽章、对比表
   - `pixcull/locale/*.json` — **13 个语言**的 `tour.foot`「100% 本地运行」
   - `pixcull/report/templates/pages/upload.html` — hero + 特性卡
   - `results.html` — `tour.foot` 兜底文案 + 一条 JS 注释
   - `SECURITY.md` — 威胁模型 + safe-to-share 清单
   - `docs/launch-post-en.md` — **整篇竞争论证建立在不上传之上**,要重写
5. **保留一条真实的本地路径** — `--vlm-mode off` 必须继续完整可用,并在
   文档里明写。这不是妥协,是 NDA 客户的唯一出路,也是对比表里
   仍然成立的一格。
6. **GitHub ⇄ ModelScope 同步** + 截图重摄(带云端角标的新 UI)。

---

## v2.51 — M3 写建议

`photo_advice.py` 1576 行,**零 LLM 调用**,纯模板。全产品最弱的一层,
也是 M3 最明显能赢的地方。

### 开发任务

1. **`build_advice()` 接 M3**(seam 在 `photo_advice.py:1469`),
   **必须保持 9 键输出形状**,否则 `caption_gen.compose_caption()`、
   XMP 导出、灯箱引证面板三处静默坏掉。
2. **`strengths` 必须是 `list[str]`** —— `compose_caption` 对
   `strengths[0]` 做正则,拿到 dict 会静默丢字段不报错。
3. **`strengths_detail` / `weaknesses_detail` 的 `source` 字段**要保留,
   否则灯箱里的「Adams · Zone System」引证会变空白。
4. **`_build_results()` 的串行循环要并发化**(`serve_app.py:1736`)——
   现在每行同步调一次 `build_advice()`,接上 M3 后 500 张就是 500 次串行往返。
5. **模板路径保留为离线兜底**,无 key 时行为不变。
6. **M3 的建议文字要进 XMP/IPTC**(复检发现的缺口):现在
   `vlm_overall_rationale` 只在 CSV 和 JSONL 里,Lightroom 用户看到的
   仍是模板文案。

---

## v2.52 — 视频内容理解

`reel.py` 的候选排序是 `mean_final + max_temporal`,**100% 代理指标**。
宣誓的片段和有人整理麦克风的片段,只要机位抖动和人脸数接近就同分。

### 开发任务

1. **`clip_to_tempfile()`** — 从 `reel_assembly.py` 的 ffmpeg
   filter_complex 里抽出可复用的「切一段成文件」函数。
2. **50 MB 闸门 + 转码** — 1–3 秒候选在 1080p/20Mbps 是 7.5 MB(安全),
   4K ProRes 是 **187 MB**(必爆)。需要 H.264 转码兜底。
3. **`run_reel_detection()` 里插入 M3 重排**,在 `detect_reel_candidates()`
   和 `enrich()` 之间。需要把 source video path 一路传下去(现在没有任何
   评分记录带它)。
4. **`ReelCandidate` 加字段**承接 M3 的数值评分 + `to_dict()` 序列化,
   消费方(审片页、灯箱)同步。
5. **`enrich()` 接 M3 视频配文**,替换 BLIP 单帧路径。`PIXCULL_REEL_VLM`
   要能区分 `blip` / `minimax`,不能破坏现有 `on` 的语义。
6. **`reel_caption.py` 的 `reset()` 测试钩子**要清掉新的 M3 句柄,
   否则测试间会串。

### 前置

`pixcull m3 doctor --video` 必须先跑过 —— 否则 `score_video()` 拒绝运行。

---

## 跨版本的 owner 待办

| 事项 | 阻塞什么 |
|---|---|
| 吊销泄露的 MiniMax key,重发 | 全部 |
| `pixcull m3 doctor --image --video` 跑一次 | v2.49、v2.52 |
| 608 行标注集就位 | v2.49 |
| 抽 30 张 `vlm_kept_despite` 人工复核 | v2.49 出口判据 |
| 决定是否重写 git 历史清除客户姓名 | 独立 |
