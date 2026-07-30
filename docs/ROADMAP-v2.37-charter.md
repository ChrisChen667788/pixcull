# v2.37 charter — 首屏快 3 倍;客户看到的那张脸终于是自家的

**主题:** 三件事,一件性能、一件设计一致性、一件工具诚实性。
三件的共同点:**都是先量、再改,而不是照着上一版记的方案做。**

---

## 1. 大 run 首屏 8.55s → 2.85s(构建 3.97×)

v2.33 的缓存只救第 2 次起的请求。**第一次打开一个 2 万张的拍摄仍要等
8.5 秒**,而那正是摄影师收工回来第一眼看到的东西。

剖析 `_build_results_uncached`(20,000 行):

| 项 | 耗时 | 占比 |
|---|---|---|
| **`Series.get()` × 1,220,000** | **7.09s** | **43%** |
| `Series.__getitem__` × 1,260,000 | 6.83s | |
| `Series.to_dict()` × 40,000 | 3.86s | |
| `iterrows()` 本身 | 1.00s | |
| `build_advice`(真正在干活) | 1.45s | 9% |

循环体每行要碰 **~58 个单元格**(44 个 `r.get()` + 12 个 `r[...]` + 2 个
`to_dict()`)。在 pandas Series 上,每一次都是一趟 `Index.get_loc` 哈希
查找加 Arrow 数组迭代 —— **近一半时间花在"查格子"而不是"用格子"上。**

改法:`df.to_dict("records")` 一次性转换,之后全是纯 dict 查找。

```
构建 6.59s → 1.66s  (3.97×)
HTTP 冷开 8.55s → 2.85s;热路径仍 0.055s
```

**这里有个必须验的行为差异**:`iterrows()` 因为 Series 只能有一个 dtype,
会**悄悄把 int 列升成 float**;`to_dict("records")` 保留各列自己的 dtype。
所以验收标准不是秒表,而是**逐字段 diff**:20000 行 × 52 字段 + summary
**全部完全一致**。两个接收该行的下游函数(`build_advice`、
`detect_style_modes`)先用 AST 核过是只读,才敢直接传 `r` 而不拷贝。

## 2. 客户看到的那个页面,不长得像这个产品

`/share/<run>/<token>` 是摄影师**发给客户**的交付页 —— 整个产品最对外的
一张脸。它此前:

- 用**第三套配色**(`--bg: #0a0a1e`、`--bg-soft: #1a1230`,紫/藏青),
  既不是 Studio Neutral 也不是 v2.21 之前的旧金;
- `color-scheme: dark` **硬锁深色**,主题系统对它完全无效;
- 不注入共享 tokens,因此 `html[data-theme="light"]` 那段规则在它上面
  压根不存在。

另两个内联页(`/admin/bias`、`/companion`)则停在 v2.21 之前的旧金
`#d5b584`。这三个在 v2.35 收口时被跳过,因为它们是 f-string 构建器、
不走 `_read_template`(v2.27 的既有取舍)。

改法:**保留内联构建(不做有风险的模板抽取),但直接内插**
`_DESIGN_TOKENS_CSS` 与 `_THEME_BOOT_HTML`,并把颜色换成 token。
`--font-sans` 顺手补进共享集 —— 共享集此前只有 `--font-serif`,于是每个
页面各自手写同一份 sans 栈。

### 又一次栽在同一个坑上:`rgba()` 躲过 hex grep

第一轮我用 `#[0-9a-fA-F]{6}` 扫颜色,扫完自认为干净。**真实浏览器一截图,
顶部品牌栏还是深藏青** —— 因为它是 `rgba(10,10,30,0.85)`,十六进制的
grep 根本看不见。这正是 v2.3.1 那次泄漏调色板的同一个失效模式。

补扫后共 17 处 rgb/rgba 字面量,按意图分三类处理:

- **必须跟随主题**:品牌栏底色(顺带把 ad-hoc `blur(14px) saturate(140%)`
  换成 v2.29 的 `--glass-filter` + `--glass-edge`)、旧金色的
  focus/glow/badge → `--focus-ring` / `--accent-glow` / `--accent-soft`;
  白色微光 `rgba(255,255,255,0.02)` 在纸白底上等于不存在 → `--surface-2`。
- **刻意不跟随**:灯箱遮罩 `rgba(0,0,0,0.94)` 及其白色控件 —— 看片灯箱
  就该恒深色,浅色灯箱会冲淡正在判的照片;纯黑投影两个主题都成立;
  **品牌 logo 的 SVG 渐变不该随主题反转**。
- **语义色**:danger/warn 淡底改用 `color-mix(var(--c-danger) 12%)`。

真实浏览器复验(9 条路由已在 v2.35 覆盖,这轮补 3 条):

```
分享页 / 偏差审计 / 副屏 × {light, dark} 全绿
浅色 bg rgb(247,247,247) · 深色 bg rgb(22,22,22)
品牌栏 light = srgb(1,1,1)/0.78 · dark = srgb(0.059…)/0.78
```

## 3. 同步脚本会谎报成功

v2.36 发布时实际发生的:

```
[modelscope-sync] ✓ hosted 20/28 referenced assets
[modelscope-sync] ✓ synced haozi667788/pixcull#master     ← exit 0
```

8 个资源以 HTTP 429 `commit lock busy` 失败(我手动跑的同步和推 main
触发的 CI 同步在抢同一把仓库锁),**model card 引用了 8 张并不存在的图,
而最后一行说同步完成**。那个 `✓` 是无条件打的,`hosted N/M` 里的 N 从来
没人跟 M 比过。

改法:

- **重试**瞬时错误(429 / lock busy / 5xx / timeout),2s→4s→8s 退避;
- **不重试**永久错误(403 之类)—— 重试只会让失败更晚暴露;
- 返回 `(uploaded, expected, failed)`,`main()` 在有失败时列出具体文件、
  提示"等 CI 同步跑完再重跑",并 **exit 1**;
- 本地文件缺失单独归类(那是 README 的 bug,不是上传失败),不计入分母。

## 4. 验收

- 门禁绿:**1440 passed, 5 skipped**(2 face fixture + 3 zeroconf,预期)。
- 新增 `tests/test_modelscope_sync_reporting.py`(8 条):瞬时错误被重试、
  永久错误不重试、重试耗尽如实上报、缺失本地文件不计入分母、**用 v2.36
  当天那条真实 429 报文**验分类器、`main()` 在半publish 时返回非零。
  测试内把 `time.sleep` 打桩,12s → 0.04s。
- `tests/test_standalone_page_theming.py` 扩到 55 条:三个内联构建器必须
  内插 tokens + 主题引导、**不得含会破坏主题的颜色字面量(hex 与 rgba
  两种记法都扫)**、分享页不得再被硬锁深色。
  做过变异验证:把品牌栏改回 `rgba(10,10,30,0.85)`,对应用例立刻变红。
  lint 前先剥注释 —— 否则解释"为什么删掉旧调色板"的注释会因为引用了
  `#1a1230` 而把自己告发(第一次跑就是这么红的)。
- 版本 2.36.0 → 2.37.0 lockstep。

## 5. 顺延

- `append_run` 全量重写 `vectors.npy`(30 万张以上再改分片追加)。
- 独立页面要不要加主题**切换控件**(目前只遵守,切换在审片工作台)——
  产品判断。
- 冷启动剩下的 2.85s 里,`build_advice` 已占 ~1.45s,是下一个天花板;
  再快就得改成"先送首屏需要的那几百行、其余懒构建"。
- owner 侧:`PYPI_API_TOKEN`、~50 条真实分歧标注、baby face 那张截图。
