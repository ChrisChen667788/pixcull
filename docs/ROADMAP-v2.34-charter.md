# v2.34 charter — 全库检索从"要手动喂"变成"跑完就有"

**主题:** 让 `/library` 对一个刚装好 PixCull 的人也是有内容的。
**起点:** 迭代方案里排的"跑完自动入库"。做的过程中先撞上了两个**必须
先修的前提**,其中一个是 v2.32 留下的真 bug。

---

## 0. 先说结论:v2.32 的全库检索,对真实 CLI 用户其实是空转的

排查"为什么要手动跑 `library index`"时发现,手动跑了也没用:

```
synthrun: nothing resolvable
library: 0 photos · 0 runs
```

两个独立原因叠在一起:

| # | 问题 | 后果 |
|---|---|---|
| ① | 流水线**从不写** `embeddings.npz` —— 它只在"用户对某次拍摄做过一次语义搜索"时被懒生成 | 新鲜 run 没有向量,`library index` 默认直接跳过 |
| ② | `_resolve_image_path` 只查 `manifest.json` 和 `<run>/input/`,**从不查 scores.csv 自己的 `path` 列** | 而 `pixcull run` 既不写 manifest.json、也没有 input/ 目录 → 一张都解析不出来 |

②是实打实的 bug:`path` 列是流水线**为每张照片亲手记下的绝对路径**,
是这个布局下唯一的权威来源,偏偏是唯一没被查的。

---

## 1. P0 — CLIP 向量本来就算过了,只是被扔掉

`scene.py::analyze()` 对每张照片跑完整 CLIP 前向拿 `logits_per_image`。
而 HF 的 `CLIPModel.forward` 要能算出 logits,**必须先把图像塔投影并
L2 归一化** —— 那个中间结果就是 `out.image_embeds`,和语义搜索用的
`get_image_features` 是同一个 512 维向量。之前只读了 logits,把它丢了。

实测(两张合成图,`SceneDetector.analyze` vs `get_image_features`):

```
  img0: cos = 1.000000
  img1: cos = 1.000000
  image_embeds 原始范数: [1.0, 1.0]   # 已归一化
```

真跑一遍 6 张的流水线,再和"正规重编码"逐张比:**6/6 全部 cos =
1.000000**。

所以 `_write_clip_cache()` 在导出 CSV 前把这些向量落成
`output/embeddings.npz`(格式与 `load_embeddings_cache` 完全一致)。
**零额外推理成本** —— 计算早就发生了。

连带效果:

- 某次拍摄的**首次语义搜索不再重编码整批**(原先每千张数分钟)。
- `library index` 现在每个 run 都有向量可用,不再"默认跳过"。

工程细节:

- 没有向量的行(scene 检测出错)**丢弃而非零填充** —— 零向量会在此后
  每一次查询里"与一切等距",比缺席更糟。
- 非有限值(NaN/Inf)丢弃;维度不齐则整体放弃而不硬 stack。
- 写入走文件句柄:`np.savez` 会给不以 `.npz` 结尾的目标**追加** `.npz`,
  `".npz.tmp"` 会落成 `".npz.tmp.npz"` 然后 rename 失败 —— 这个坑
  `semantic_search.py` 和 `library_index.py` 都已各栽一次,专门测了
  "不留 `*.tmp*` 残留"。
- **整体 best-effort**:缓存是赠品,不能让一次成功的挑片因为赠品写失败
  而报错。专门测了 `open` 抛 OSError 时不向外冒泡。

## 2. P1 — 修 `_resolve_image_path`(v2.32 bug)

换成 `_run_path_map(out_dir)`,权威顺序:

1. **`scores.csv` 的 `path` 列**(新增,唯一对 `pixcull run` 有效的来源);
2. `manifest.json`(demo server 的映射);
3. `<run>/input/<filename>`(demo server 的目录布局)。

顺带修掉一个性能问题:旧实现是**逐张照片**重新解析一次
`manifest.json` —— 2 万张就是 2 万次文件解析。现在每个 run 建一次表。

只返回当下确实存在的路径(建索引需要 mtime);照片在**入索引之后**失踪
由 library 自己的 `stale` 状态负责,那是两件事。

## 3. P2 — 跑完自动入库

`_auto_index_library(output)` 在 CSV 落盘后执行(它要读 `path` 列)。

**默认开启。** 取舍理由:`/library` 这个页面的全部意义就是"搜所有拍摄",
默认关掉等于默认让它看起来是坏的;而现在向量是免费的,入库只是一次
毫秒级搬运。索引**只落 `~/.pixcull/library/`**,从不同步、从不进仓库
—— 它确实记录真实绝对路径,这正是它必须留在本机的原因。
**关掉:`PIXCULL_NO_AUTO_INDEX=1`。**

`run_id` 的推导必须和 `library index` 走 runs 目录时一致,否则同一次
拍摄会以两个名字入库两次:`<root>/<run_id>/output` 布局取父目录名,
否则取输出目录自己的名字。重叠情况下两边得到同一个 `run_id`,
`append_run` 按 `(run_id, filename, mtime)` 幂等 → 不会重复。

## 4. 过程中修掉的一个真陷阱(值得记住)

`append_run(..., library_dir: Path = LIBRARY_DIR)` 的**默认值在 import
时就绑定了**,所以 monkeypatch `LX.LIBRARY_DIR` 根本改不到它 ——
我的测试因此把 6 条合成记录写进了 owner 的**真实** `~/.pixcull/library`。
已 `library prune --run autorun` 清除(该库此前为空,没有 owner 数据受损
—— 这本身也印证了 §0:`library index` 从来没在真实 CLI run 上成功过)。

修法:`_auto_index_library` **显式传** `library_dir=LX.LIBRARY_DIR`。
现在有测试断言"关掉开关时连库目录都不许创建"。

**教训:带默认值的路径参数,在需要可测/可重定向时必须显式传。**

## 5. 验收

真跑 `pixcull run`(6 张合成图)全链路:

```
CLIP cache: 6 vectors → embeddings.npz
✓ Done. Keep=6 Maybe=0 Cull=0
Library: +6 photos indexed as 'out2'
→ library status: 6 photos across 1 runs
→ library search "blue sky over sand": synth00 0.264 / synth01 0.252 / synth05 0.223
```

- 门禁绿:**1364 passed, 5 skipped**(2 face fixture + 3 zeroconf,预期)。
- 新增 `tests/test_clip_cache_freeride.py` 22 条,含一条**真模型**测试钉住
  `image_embeds ≡ get_image_features`(cos > 0.9999)。这条是整片改动的
  承重点:若某次 transformers 升级改了 `image_embeds` 的含义,所有缓存
  向量会静默落到错误空间,语义搜索会返回"看起来合理的胡话"而不是报错。
- ruff:改动的 4 个源文件 89 → 89(未新增,`library_index as LX` 的 N812
  沿用 `cli.py` 既有约定)。
- 版本 2.33.0 → 2.34.0 lockstep。
- 测试跑完后复核真实 `~/.pixcull/library` 仍为 0 photos。

## 6. 顺延

- **近重复 O(N²)**(20k=2.4s / 50k=13s):时间窗剪枝,不是 ANN。
- **`data-theme` 未设**:`/library`、`/history`、`/tether` 等独立页面从未
  应用浅色主题(v2.29 前既存),要跨 5+ 页面单独排一版。
- **`append_run` 全量重写 `vectors.npy`**:自动入库现在每跑完一次就重写
  整个向量文件。几万张量级只是几百毫秒,可忽略;真到 30 万张以上要改成
  分片追加(和 ANN 压缩一起做)。
- `pixcull run --output X`(X 不叫 `output`)这种布局,`library index`
  的目录遍历发现不了,靠自动入库覆盖。两条路径都能工作,只是发现方式
  不同。
