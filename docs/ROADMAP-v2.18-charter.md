# ROADMAP v2.18 — 5k 性能:渐进水合 charter

> v0.13.5 建好 `/rows` 分页端点时就写明「foundation for virtual scroll in v0.14+」——
> 前端一直没接,5k run 的 /results 页仍整页内联全部行 JSON(多 MB、解析阻塞首屏)。
> 本主题把这笔性能债还上:**服务端首片内联 + 客户端后台分片水合**。

## P0 — 渐进水合(已交付)

**服务端**(`_serve_results`):行数 > 阈值(默认 800,`PIXCULL_INLINE_ROWS` 可调、
0=关闭)时只内联首片,payload 加 `rows_meta:{total, inlined, slice}`。
**summary / face_clusters / locations 仍按全量行计算**——所有计数首屏即正确。
小 run 路径不变(`rows_meta: null`)。

**客户端**(results.js 核心):`_hydrateRows()` 顺序分片 fetch,push 进**同一个
`rows` 数组**(全部模块闭包引用的就是它);工作条显示「加载 N/total…」进度 chip;
水合完成后重算 `_BURST_CLUSTER_SIZES`(同一 Map 对象)、`buildDynamicFilters()` 重建
行派生的侧栏组(场景/风格药丸等)、一次全量 render(),chip 移除。失败时 chip 变
「⚠ 加载不完整 N/total」并说明筛选只作用于已加载部分——诚实降级,不静默装完整。

**捡到一个潜伏路由遮蔽**:`/api/v1/runs/<id>/rows` 自 P2.1 起被 v1 分发器的
**iOS 瘦身版**(6 字段)接管,v0.13.5 的**全字段版** `_serve_runs_rows` 实际一直
不可达。水合需要全字段(缺 rubric/flags 会残 lightbox/玻璃盒)→ 路由表加一行专用
`/results_rows/<id>`(v2.16 路由表的价值:一行表项),iOS 瘦身别名原样保留并加共存
守卫测试。

**实测**(2500 行合成 run):HTML **6.45MB → 2.53MB(−60%;5k 时 ~−84%)**;水合
进度 800→1800→完成,chip 自动消失,终态 2500 卡全渲染(DOM 侧由 v0.13.5 的
placeholder/IntersectionObserver 机制承接),零 JS 错误。

**验证**:`tests/test_hydration.py` 4 项(大 run 只内联首片 + rows_meta、小 run 全内联
不变、`/results_rows/` 全字段分片含尾片钳制、iOS 瘦身别名共存)· 装配后 node --check ·
完整门禁 exit=0。

## 已知取舍与后续

- 水合期间(通常数秒)筛选/排序作用于已加载部分,进度 chip + tooltip 已说明;
  水合完成的 buildDynamicFilters() 会以全量重建药丸组。
- 真·滚动驱动虚拟行(DOM 上限恒定)留作 P1——当前 placeholder 机制在 5k 已可用,
  10k+ 再评估。
