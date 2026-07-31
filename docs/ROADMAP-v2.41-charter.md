# v2.41 charter — 一条端到端旅程,把四次事故都变成可复现的红灯

DESIGN-AUDIT-2031Q1 的首要建议。**不是"加个冒烟测试"这么泛,而是针对一个
已被点名的、重复出现四次的失效模式。**

---

## 1. 要防的是什么

审计的原话:本仓库最主要的缺陷类型是**"宣传了但到不了"** —— 功能是活的、
单元测试全绿,但**某一条真实用户路径够不到它**:

| 版本 | 事故 | 当时的表象 |
|---|---|---|
| v2.34 | `library index` 一张没入库 | 打印 "nothing resolvable",**退出码 0** |
| v2.36 | `/timeline` 50 张缩略图全碎 | 页面 **HTTP 200**,图 50 个 404 |
| v2.35 | 浅色主题从未生效 | 页面 **HTTP 200**,只是没有 light 块 |
| v2.40 | `pixcull export` 无输出 | **静默退出 1** |

**四次全部瞒过了单元测试**,因为单元测试测的是函数,而坏掉的是**旅程**。

## 2. 因此这个文件遵守两条规则

**(1) 走真实入口。** 用 `subprocess` 跑安装好的 CLI、用 HTTP 请求打真实
服务器 —— 不是 import 一个函数进来调。四次里有三次在进程内部根本看不见。

**(2) 断言内容,不断言状态码。** 四次事故里**每一次都返回 200 或安静退出**。
只看退出码的冒烟会一路绿着穿过全部四次。

所以断言的是:结果页里**每个文件名都在**、API 行数对得上、**缩略图字节能
被认出是 JPEG/PNG**、每个独立页面**含 light 块与主题引导**、导出的 sidecar
**能被自家 `read_xmp` 读回且星级/色标往返一致**。

## 3. 验收方式:把四次事故逐个重演

不是"写完跑通就算"。**逐个把当年的 bug 注回去,确认这条冒烟变红:**

| 重演 | 注入的变异 | 结果 |
|---|---|---|
| v2.34 | `_run_path_map` 不再读 scores.csv 的 `path` 列 | ❌ **2 条**测试红(export + library) |
| v2.35 | 共享 tokens 里删掉 `html[data-theme="light"]` 块 | ❌ `/history rendered without the light-theme block` |
| v2.36 | `_resolve_image_source` 永远返回 None | ❌ `thumb img0 → 404` |
| v2.40 | `export` 变回 `raise typer.Exit(1)` | ❌ **2 条**测试红 |

**四次全部被抓。**

### 过程中发现自己的变异是无效的(值得记)

第一次重演 v2.35 时我把 `_read_template` 里的 tokens 注入关掉,**测试却全绿**。
第一反应是"冒烟有洞",但查下去是**变异本身无效**:v2.35 收口时把注入收进了
`_read_template`,而**各调用点原有的 `.replace()` 被保留为无害空操作** ——
关掉其中一处,另一处照样注入。改成删掉 tokens 里的 light 块(等价于当年那
5 个页面的真实状态)后立刻变红。

**教训:变异测试变绿时,先怀疑变异,再怀疑测试。**

## 4. 分层:hermetic 与 slow

- **hermetic(4 条,默认跑)**:从"流水线刚跑完的样子"开始 —— 合成
  scores.csv + 真实 JPEG → 真 `pixcull serve` 子进程 → 真 `pixcull export`
  子进程。**不加载任何模型**,所以能进普通 CI 通道。
- **`@pytest.mark.slow`(1 条)**:补上 `pixcull run` 那一半 —— 真跑流水线。
  需要权重,所以按 v2.40 的模型门禁把关:**权重在缓存里就必须跑**,不在才
  skip(本机实测 43s / 3 张)。

CI 里作为**独立步骤**跑,而不是混在全量套件里 —— 红灯时能一眼看出是"旅程断
了"还是"某个单元坏了"。

另有一条 `test_serve_starts_from_a_clean_env`:模拟 pip 用户装完的**第一次**
`pixcull serve`(零 run、零库),`/` `/history` `/library` 都必须 200。

## 5. 验收

- 门禁绿:**1559 passed, 5 skipped, 1 deselected**(deselected = slow 那条)。
- slow 那条单独跑:**1 passed, 43.18s**。
- 四次事故重演全部变红(见 §3)。
- 版本 2.40.2 → 2.41.0 lockstep。

## 6. 顺延

- 镜头切分(PySceneDetect)、ASR/按文字剪(FunClip)—— 审计推荐 ③④。
- owner 侧:`PYPI_API_TOKEN`(链接已给)、~50 条真实分歧标注。
