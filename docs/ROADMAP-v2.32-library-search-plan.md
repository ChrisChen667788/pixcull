# v2.32 方案 — 跨 run 全库语义检索(Library Search)

> owner 指定方向。这是**真功能**(不是索引优化):让摄影师问"我所有拍摄里,
> 那张逆光牵手的在哪",跨越全部 run 找回照片。以下方案基于**实测数据**与现有
> 代码事实,不是纸面设计。

## 一、实测:这个功能真正的难点不是检索

用合成向量在本机测了跨库聚合与规模上限(float32,D=512,CLIP ViT-B/32):

| 全库规模 | brute-force 查询 | 向量内存 | 对比 CLIP 文本编码(17.4ms) |
|---:|---:|---:|---:|
| 100,000 张(40 runs) | **8.0 ms** | 195 MB | 0.5× |
| 300,000 张 | 22.5 ms | 586 MB | 1.3× |
| 1,000,000 张 | 34.5 ms | 1.9 GB | 2.0× |
| 2,000,000 张 | 57.1 ms | 3.9 GB | 3.3× |

聚合方式对比(100k 张 / 40 runs):

| 方式 | 首次打开 | 查询 |
|---|---:|---:|
| A. 逐 `run/output/embeddings.npz` 加载再 vstack | 174 ms | 6.0 ms |
| B. 合并成单一 `library.npy` + `mmap` | **18.4 ms** | 8.1 ms |

**三条结论,直接决定架构:**

1. **检索仍然不是瓶颈**,即使到百万级(34.5ms)也只是 CLIP 编码的 2 倍。
   → **v2.32 首版不引入 ANN**(这也修正了 VECTOR-INDEX-EVAL 里"跨库即需 ANN"
   的预判——实测把触发点推到了更远)。
2. **先撞墙的是内存,不是速度**:百万级 1.9GB 常驻不可接受。
   → ANN 的真实价值在**压缩**(PQ/int8 量化),不在提速;留作 P2 触发式优化。
3. **合并索引 + mmap 打开快 9.5 倍**(18ms vs 174ms),且不需要把全部向量读进
   常驻内存 → **架构选 B**。

## 二、真正的难点(方案要解决的是这些)

跨库检索的复杂度不在"算相似度",在于:

1. **库的存活性**:run 会被删除/移动/外置盘离线。索引里的条目可能指向已消失的
   照片——**必须能优雅地标记失效而不是报错**。
2. **增量维护**:每跑完一个 run 就要把它并进全库索引,不能每次全量重建
   (100k 张重新 CLIP 编码 = 数小时)。
3. **一致性**:run 内 `embeddings.npz` 与全库索引的漂移(run 重跑、照片增删)。
4. **结果呈现**:跨 run 结果无法复用现有的单 run 网格——需要新的"来自哪次拍摄"
   分组视图 + 跳转回原 run 的路径。
5. **隐私/边界**:全库索引记录**真实文件路径**,是本机私有数据,绝不可进仓库、
   不可进任何同步/上报路径(仓库卫生红线)。

## 三、架构

### 存储:`~/.pixcull/library/`

```
~/.pixcull/library/
  vectors.npy        float32 (N, 512) — L2 归一化,mmap 打开
  manifest.jsonl     每行一条:{run_id, filename, abs_path, mtime, row, indexed_at}
  meta.json          {schema, model, dim, n_rows, built_at}
```

- **vectors.npy + mmap**:实测打开 18ms、查询 8ms@100k;不常驻内存。
- **manifest.jsonl 行序 == vectors 行序**(`row` 字段冗余存一份做自检),
  append-only 便于增量。
- 放 `~/.pixcull/`(与 `personal_profile.json`、`models/` 同处),**天然在仓库外**,
  满足隐私红线;`.gitignore` 再加一道保险。

### 增量:复用 run 内已有的 `embeddings.npz`

关键洞察:**全库索引不需要重新编码**——每个 run 首次语义搜索时已经生成了
`output/embeddings.npz`。索引构建 = 把这些 npz **搬运并追加**进全库:

- `pixcull library index` — 扫描所有 run,把尚未入库的 run 的 npz 追加进
  `vectors.npy`(np.lib.format 追加或分块重写),manifest 追加对应行。
  **没有 npz 的 run**:可选 `--encode-missing` 现场编码(耗时,显式选择)。
- 幂等:以 `(run_id, filename, mtime)` 为键跳过已索引项。
- `pixcull library status` — 显示已索引 run 数/照片数/磁盘占用/失效条目数。

### 检索:`pixcull library search "query"` + `/library` 页面

- 复用 `encode_query()`(17.4ms,占大头)+ `vectors @ q` + argpartition。
- **存活性过滤**:结果按 `abs_path` 存在性校验,失效条目标记为"照片已移动/删除"
  而非静默丢弃(用户需要知道"找到了但文件不在了")。
- **按 run 分组呈现**:结果先按相似度排序,再按 run 分组显示"来自 2025-02 婚礼
  (3 张)",每张可跳回 `/results/<run_id>` 定位。

## 四、切片

### P0 — 索引与 CLI(纯后端,可独立验证)
- `pixcull/scoring/library_index.py`:`build/append/load/search/prune` 五个函数,
  纯 numpy + jsonl,单元测试覆盖(含失效条目、重复追加幂等、空库)。
- `pixcull library index | status | search` 三个 CLI 子命令。
- 验收:用真实 run 建索引 → CLI 搜到结果 → 删掉一张照片后标记失效不报错。

### P1 — `/library` 检索页面
- 新页面(走 v2.28 的 `templates/pages/*.html` 抽取模式,不再内联)。
- 搜索框 + 按 run 分组的结果网格 + 跳回原 run;失效条目灰显标注。
- 复用 Studio Neutral + v2.29 玻璃 token,不新造设计语言。

### P2 — 触发式优化(**不预先做**)
- **内存**:库 > 30 万张(≈600MB)时引入 int8 量化或 PQ 压缩(4-8× 压缩,
  召回损失可控);这才是 ANN 真正的价值点。
- **速度**:库 > 100 万张且用户抱怨延迟时才考虑 HNSW。
- 触发前不引入 faiss —— 保住 `pip install pixcull` 的零编译依赖体验。

## 五、风险与边界

| 风险 | 处理 |
|---|---|
| 全库索引含真实文件路径 | 只写 `~/.pixcull/`,永不进仓库/同步;gitignore 加保险 |
| 外置盘离线 → 大量失效 | 失效是**标记**不是删除;盘回来自动恢复(按 abs_path 复检) |
| run 重跑导致向量漂移 | 以 `(run_id, filename, mtime)` 为键;mtime 变化即重新索引该条 |
| 首次索引耗时 | 复用已有 npz 时几乎瞬时;`--encode-missing` 才慢,且显式选择 + 进度条 |
| 索引与 run 删除不同步 | `pixcull library prune` 清理失效条目;status 显示失效计数 |

## 六、为什么这个顺序

先 P0(后端 + CLI)可以**完全独立验证**——不碰前端就能证明索引/检索/失效处理
正确;P1 再做 UI。这样如果 P1 的呈现设计需要迭代,P0 的正确性已经钉死了。

---

**数据可复现**:本文所有基准为本机(Apple silicon)numpy float32 D=512 实测,
方法见 `docs/VECTOR-INDEX-EVAL.md` 同款。
