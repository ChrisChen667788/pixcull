# v2.32 — 跨 run 全库检索(Library Search)

> 方案见 `docs/ROADMAP-v2.32-library-search-plan.md`。单 run 语义搜索回答
> "这次拍摄里那张逆光的在哪";本版回答"**我所有拍摄里**那张在哪"。

## P0 — 索引后端 + CLI ✅

**`pixcull/scoring/library_index.py`**(append_run / search / status / prune):

- **不用 ANN**:实测 brute-force 10 万张 8ms、百万张 34.5ms,仍只是每次查询
  必付的 CLIP 文本编码(17.4ms)的 ~2 倍。先撞的墙是**内存**(百万张 1.9GB),
  所以未来的优化方向是**压缩**(int8/PQ)而非 ANN 图;纯 numpy 也守住了 v2.31
  刚打通的零编译依赖 `pip install`。
- **单一 `vectors.npy` + mmap**,而非 N 个 per-run npz 加载再 vstack:实测
  10 万张打开 **18ms vs 174ms**,且 mmap 不占常驻内存。
- **增量靠复用各 run 已有的 `embeddings.npz`** —— 建索引是**搬运不是重编码**
  (10 万张重编码要数小时)。身份键 `(run_id, filename, mtime)`,所以重跑幂等、
  且**重新评分过的照片会重新索引**而邻居不动。
- **存活性是一等状态**:文件不在盘上的命中返回 `stale=True`,**不静默丢弃**。
  外置盘离线时用户需要听到的是"找到了,但文件不可达",不是"没这张照片"。

**CLI**:`pixcull library index | status | search | prune`。`prune` 在只是
"盘没插"时**拒绝直接执行**(需 `--yes`),因为那会误删可恢复的条目。

**隐私**:索引存**真实绝对路径**,只落 `~/.pixcull/library/`,`.gitignore`
另加一道保险防本地误拷。

**验收(121 张真实照片)**:建索引 → 幂等重跑(+0,121 unchanged)→ 语义检索
**排序正确**(匹配内容的查询 0.288,不相关查询 0.17–0.20,低分正确表达"库里
没有这类照片")。13 个单测覆盖真正会坏的地方:幂等、mtime 重索引、失效不丢弃、
prune 后行仍对齐、维度不符、manifest 半行截断、归一化。

**顺手修的坑**:`np.save()` 会给不以 `.npy` 结尾的路径**自动追加 `.npy`**,
导致原子写的 `vectors.npy.tmp` 实际落在 `...tmp.npy`、rename 报 FileNotFound
——与 semantic_search.py 注释里记录的是同一个坑。两处写入改走文件句柄。

## P1 — `/library` 检索页面 ✅

- 走 v2.28 的 `pages/*.html` 模板抽取模式(不内联)+ v2.29 玻璃 token;
  两个 API:`/api/v1/library/status`(索引规模 + 失效数)、
  `/api/v1/library/search?q=&k=`(跨库命中)。
- **按 run 分组呈现** —— 跨库检索问的就是"来自哪次拍摄",每组带"打开这次
  拍摄 →"跳回 `/results/<run_id>`。
- **失效条目灰显标注**("照片当前不可达 / 离线")而非隐藏。
- **空库不是空结果**:未建索引时提示 `pixcull library index` 怎么建。
- 验收:页面 200、状态显示真实 121 张、检索 40 命中按 run 分组、跳转链接正确、
  零控制台错误、暗色玻璃 `blur(16px) saturate(1.3)` + 玻璃边生效。

**顺手修的 v2.29 遗漏**:玻璃 token 当时只进了 results.css 的 token 模块,
**共享 `_DESIGN_TOKENS_CSS`(所有独立页面用)漏了**——导致 /library、/tether、
/history、upload、admin 的 chrome 玻璃**静默失效**。已补齐(含
`prefers-reduced-transparency` 兜底),守卫测试防再漏。

## 已知既有行为(未在本轮扩大范围)

所有独立页面(/library、/history、/tether…)都不设 `data-theme`,而共享 blob
的亮色主题依赖 `html[data-theme="light"]` ——**亮色主题在这些页面一直不生效**,
是 v2.32 之前就存在的行为,不是本轮引入。/library 与其余独立页保持一致;
若要修,应作为独立切片统一处理(涉及 5+ 页面)。

- 门禁绿(5 预期 skip);版本 2.31.1 → 2.32.1 lockstep。
