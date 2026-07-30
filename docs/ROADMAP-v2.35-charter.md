# v2.35 charter — 近重复分组不再每点一次重算,浅色主题第一次真的能用

**主题:** 清掉迭代方案里剩下的两项(近重复 O(N²) / `data-theme` 未设)。
两项都在动手前先测量,**两项的原定方案都被测量推翻了**。

---

## 1. 近重复分组:原计划(时间窗剪枝)是错的

我上一版记的顺延项写着"用**时间窗剪枝**,不是 ANN"。查代码后作废:

`group_near_dups` 服务的是 v2.6-P1 的**跨连拍组**视觉近重复 —— 它存在的
全部理由,就是抓 `cluster_bursts` 因为**时间不相邻**而漏掉的那些近重复。
按时间窗剪枝正好把这个功能的目的剪掉了。

而且我把成本记在了错的地方。它不是流水线里的一次性开销 ——
`_serve_api_v1_near_dups` 是**逐请求**处理器,`threshold` 还是个可由用户
调的查询参数。**滑杆每动一次,整个 O(N²) 重付一遍。**

实测 N=20,000 的耗时构成:

| 环节 | 耗时 |
|---|---|
| matmul | 1.35s |
| `>= threshold` | 0.04s |
| **`np.nonzero`** | **1.15s** |
| Python union 循环 | 0.01s(25,714 对) |

反直觉的是 `np.nonzero` 几乎和 matmul 一样贵 —— 它要走完全部 N² 个布尔
值。而 Python 循环(我原以为是嫌疑犯)只占 0.01s。

于是做了两件事:

**(a) 只算上三角。** 旧代码 `v[block] @ v.T` 把每一对算两遍,然后用
`if gi < c` 把一半**在付过钱之后**丢掉。低于 `start` 的列在更早的行块里
已经覆盖过,切掉它们同时缩小了 matmul **和**那个 mask 扫描:

```
  N=20000:  2.69s → 1.50s  (1.79x)
  N=50000: 14.70s → 7.69s  (1.91x)
```

**验收标准是分组逐组完全一致,不是"差不多"** —— 组边界挪一格就意味着
两张不同的照片被静默折叠。已对 4 种 block × 4 种 (n, threshold) 组合
与旧实现逐组比对通过,并另写了一份**独立的朴素 O(N²) 参考实现**做交叉
验证。

**(b) 缓存分组结果。** 分组是 `(vectors, threshold)` 的纯函数,所以按
向量文件 mtime + threshold 缓存;`pick_heroes` 仍每次现算(它依赖已被
v2.33 缓存的 rows)。沿用 v2.33 的同一套纪律:写入方不需要知道缓存存在,
重新打分改了 mtime 就自然失效,旧世代在写入时立即清掉。

## 2. `data-theme`:真实浏览器验证推翻了我对范围的判断

我原本记的是"没有独立页面设 `data-theme`,浅色主题从未生效"。前半句对,
但**真实浏览器一验,问题比这大**。

用 Playwright 在 `localStorage.pixcull_theme = light / dark` 两种状态下
逐页量 `getComputedStyle(body)`,发现两类完全不同的病:

| 症状 | 页面 | 病因 |
|---|---|---|
| 属性没设 → 浅色永不生效 | `/library` `/history` `/tether` `/admin` `/` | 确实只是没人设 `data-theme` |
| 属性设了**仍然是深色** | `/first_run` `/privacy` `/verticals` `/vertical_bulk` `/admin/disagreement` | 根本没注入共享 tokens,页面里是**手写的 pre-v2.21 调色板**(`--accent: #d5b584`,v2.21 之前的旧编辑金) |

第二类的根因是个**定义顺序事故**:这 5 个页面的模块级常量在
`_DESIGN_TOKENS_CSS` **定义之前**就构建了(12310 vs 12345),所以
`.replace(...)` 会 NameError —— 于是当年根本没写。它们因此整个错过了
v2.21 的 Studio Neutral 改版,`html[data-theme="light"]` 那段规则在它们
页面上**压根不存在**,设不设属性都没用。

`/admin/disagreement` 更彻底:压缩成一行、颜色全是硬编码 hex,连 CSS
变量都没有。

### 修法:两个注入都收进 `_read_template` 一处

- 把 `_DESIGN_TOKENS_CSS` 移到 `_read_template` **之前**,让 import 期的
  调用方也能看见它;
- `_read_template` 现在同时注入**共享 tokens** 和**主题引导脚本**。
  原先"每个调用点各自 `.replace`"的做法,正是十一个页面里十个漏掉的
  原因 —— 收到一处,这类 bug 就没有生存空间了。已有的 `.replace` 调用
  变成无害空操作(标记已被消费)。
- 5 个自带调色板的页面:删掉本地 `:root`,换成标记。**先核过它们用到的
  每一个变量都已在共享的 80 个 token 里**,所以是干净的平移,不是猜。
- `disagreement.html` 的硬编码 hex 全部 token 化(改完页面里已无任何
  硬编码颜色)。
- 引导脚本内联在 `<head>`,首屏绘制前就设好属性(否则会闪一下错的主题),
  并且**严格镜像** `results.js` 里 toggle 的契约:
  `localStorage["pixcull_theme"]` ∈ dark|light|system,其余/读不到都按
  system,system 再由 `prefers-color-scheme` 决定。

### 真实浏览器复验(9 个页面 × 2 种偏好,全绿)

```
light: /  /library  /history  /tether  /admin  /verticals  /privacy
       /admin/disagreement  /admin/perf   → bg rgb(247,247,247) fg rgb(23,23,23)
dark : 同上 9 页                          → bg rgb(22,22,22)   fg rgb(230,230,230)
```

`/first_run` 在 Playwright 里报 Error —— 查明是它自己 `location.href = "/"`
跳转打断了导航,**不是缺陷**;它的 HTML 里 tokens 与引导脚本都在。

## 3. 验收

- 门禁绿:**1416 passed, 5 skipped**(2 face fixture + 3 zeroconf,预期)。
- 新增 `tests/test_standalone_page_theming.py`(48 条,按页参数化):每页
  都必须声明共享 tokens、都**不许**自定义核心色 token、渲染后必须同时
  含 light 块与引导脚本、脚本必须在 `</head>` 之前、引导与 toggle 的
  契约必须一致、不许重复注入、fragment 模板不许被塞脚本。
- `tests/test_near_dup.py` 新增上三角等价性(对独立朴素实现)+ 无自配对;
  `tests/test_results_cache.py` 新增近重复缓存命中/失效/有界。
- ruff:改动文件均回到基线(新增代码区间零问题)。
- 版本 2.34.0 → 2.35.0 lockstep。

## 4. 顺延

- **`append_run` 全量重写 `vectors.npy`**:自动入库每跑完一次重写整个
  向量文件。几万张是几百毫秒,30 万张以上要改分片追加(和 ANN 压缩一起)。
- 独立页面目前只**遵守**主题,没有切换控件(切换在审片工作台里)。要不要
  在这些页面也放一个 toggle,是产品判断,单独排。
- `_render_share_html` / `_serve_bias_audit_page` / `_serve_companion_page`
  仍是内联 f-string 构建器(v2.27 记录的既有取舍),没有走
  `_read_template`,因此不在这次的 token/主题收口范围内 —— 它们是否也该
  收进来,值得单独看一眼。
