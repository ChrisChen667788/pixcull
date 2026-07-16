# ROADMAP v2.17 — 视频玻璃盒 charter

> DESIGN-AUDIT-2030Q2 视频维(3.5/5)的 topGap:照片侧 v2.9–v2.12 做透了逐轴玻璃盒
> +「为什么低」,视频侧只有数字 HUD 条——reel 候选凭什么 0.42,拍摄者无从得知。
> 本主题把照片侧方法论**原样复用**到时序评分:确定性、取自窗口自身信号、零新模型。

## P0 — reel 候选逐窗子信号分解 + why-low(已交付)

**生成侧**(`scoring/reel.py`):
- `window_signals(window)`——每窗四值:运镜平稳度/画面稳定度取窗口**均值**(描述整段),
  峰值瞬间取窗口 **max**(峰值信号,一瞬撑起整段——与 compose_why 口径一致),画质=均分。
- `compose_why_low(signals, medians)`——找**相对全片中位**(候选窗口间的中位数)短板最大
  的信号,产出一行话术:「运镜平稳度拖分:0.32,低于全片中位 0.78」;短板 <0.05 不硬凑
  (强窗口不需要借口,返回 "")。与照片侧 `_axisWhyLow` 同一契约。
- `ReelCandidate` 增 `signals` + `why_low` 字段(dataclass 默认值,`to_dict` 自动进
  `reel_candidates.json`);中位数在 `select_candidates` 内对候选池现算,自包含。

**渲染侧**(`video_review.html` reel 面板):候选卡在 why 行下渲染三条带数值的
mini-bar(运镜/稳定/峰值)+ 琥珀色 `▾ why_low` 行;**全部三元守卫**——旧 run 的
reel_candidates.json 无新字段时优雅隐藏,零破坏。样式全部复用该页既有变量。

**验证**:`test_reel.py` +4(聚合口径 mean/mean/max、短板命名、强窗口留白+min_gap、
候选携带字段且 JSON 回环)· `test_video_glassbox.py` 模板钩子守卫 · 无头端到端
(混合新旧格式的 3 候选 run):新卡渲染三条+话术、旧卡 0 条降级、零 JS 错误 ·
完整门禁 exit=0。

## 后续切片

- **P1 — 统一 lightbox 的 reel 色带 tooltip**:results.html 的照片 lightbox 只画时间线
  色带,无候选列表——给色带挂 `why`/`why_low` title(轻);或补候选摘要行。
- **P2 — 音频事件时间线叠层**:audio_events.json 已算(笑声/掌声/音乐),两个时间线
  (video_review + lightbox)都不画;reel 的 why 也从不提音频加成。
- **P3 — reel keep/cull 反馈回路**:候选的 Keep/Cull 目前只写 localStorage;照片侧
  会学(personal_learn),视频侧不学。
