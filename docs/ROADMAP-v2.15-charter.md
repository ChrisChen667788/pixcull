# ROADMAP v2.15 — 收尾闭环 + maybe 决议 charter

> DESIGN-AUDIT-2030Q2 主题④(owner 指示:先做不依赖外置盘数据的功能优化)。核心 culling
> UX 3.5 分的最大短板:**审完一批照片,产品从不告诉你「审完了」**——工作条只显示
> keep/maybe/cull 总数,从不显示「还剩 N 张没人工确认」,也没有自然的「完事 → 写 XMP 回
> Lightroom」出口;maybe 堆积起来也没有专门的决议工作流。纯 UX 编排,全部用已算好的数据
> (含 v2.14 刚训练的 rescorer 的 P(keep))。

## P0 — 待审计数 + 完成时刻 + 决议队列(已交付)

**后端**(serve_demo `_build_results`):
- row 加 `human_decided`——annotations.jsonl 里该文件名的最新记录带 keep/maybe/cull
  `overall_label` 才算(**仅打 rubric 星不算**:culling pass 关心的是判定)。
- summary 加 `n_human_decided`;`n_total − n_human_decided` = 待审数。

**前端**(results.js / src.html / css):
- **工作条「待审 N」chip**:随每次人工判定实时递减(键盘 1/2/3、lightbox、批量框选都算;
  **重按确认 prev==new 也计入**——人看过了就是已审)。归零 → 翻成 keep-green 的
  **「全部已审 ✓ · 导出 XMP」**,脉冲一次 + 完成 toast,**点击即触发既有(但埋在 ⌘K 里的)
  XMP zip 导出**——收尾有了出口。刷新后从服务端恢复(annotations 持久化)。
- **「◐ 决议 maybe」按钮**(maybe-琥珀色,无 maybe 时隐藏):一键进入决议队列——筛到
  maybe 档 + 按**「最拿不准优先」**排序(`|P(keep)−0.5|` 升序,rescorer 没跑时回退
  `|score_final−0.5|`);进入时焦点已落在最难的第一张,1/2/3 直接判。**maybe 清零自动退出**
  并还原用户原来的 filter+sort(decision 药丸 + 排序下拉同步——v2.13 教训:render() 不会
  替你重建控件)。排序下拉新增「最拿不准优先」,也可单独用。
- **顺手修一个 v2.13 同族既有 bug**:marquee 批量判定 fallback 此前**只改卡片 DOM**,
  rows[]/工作条统计不更新 → 下次 render() 静默回退视觉状态;现在同步 rows + 统计 + 已审。
- 埋点(本地):`resolve_maybes` / `review_all_done` / `review_done_export` 进
  `localStorage.pixcull_metrics`(v2.12 机制)。

**与 v2.14 的闭环**:决议队列产生的 keep↔maybe 人工改判会写进 annotations.jsonl——
**正是三门审计里门③缺的纠正信号**。这不是纯 UX 糖:它是标注数据的生产管线。

## 开发中自抓的两个 bug(诚实记录)

1. **TDZ 中止整页**:review 状态的 `let` 声明在 helpers 区、而 `_updateReviewProgress()`
   在初始化就调用 → ReferenceError 中止整个 IIFE → 网格空白(与 v0.13
   `activeLearningDivider` 事故同款)。修:状态声明提到 stats 构建之前。
2. **outerHTML 换节点丢监听**(v2.13 detached-node 同族):done 转换用 `chip.outerHTML`
   换新节点,init 挂在旧节点的 click 监听随之丢失 → 完成态点不动。修:事件委托挂
   `#stats` 容器。

两个都是**无头端到端验证**抓到的——再次印证「单测/构建绿 ≠ 能用」。

## 验证

- 后端单测 `tests/test_review_progress.py`:`human_decided` 只认 overall_label
  (rubric-only 不算)、`n_human_decided` 计数、待审推导。
- 无头端到端(sampledemo 全流程):待审 6→逐张递减(含 prev==new 确认)→ 决议模式
  (pill=maybe、sort=uncertain、焦点在最不确定帧)→ maybe 清零自动退出 + filter/sort
  还原 → 「全部已审 ✓」完成态 → 点击触发 XMP 导出 → **刷新后完成态从服务端恢复**。
  全程零 JS 错误。
- `make results-html` golden + palette guard(新样式全 token/color-mix)+ 完整门禁绿。
- diff 级对抗式 review workflow(3 lens + verify)结果并入(见提交记录)。
