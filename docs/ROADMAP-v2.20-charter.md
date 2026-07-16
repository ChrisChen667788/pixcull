# ROADMAP v2.20 — 视频主题收官(P3)+ 三尾巴 charter

## A. 视频玻璃盒 P3 — reel 反馈回路 + why 提音频(已交付,视频主题收官)

**why 提音频**:`compose_why` 接收 audio_events——窗口与检测事件重叠时,话术加入
「现场笑声/现场掌声/配乐律动」(最强重叠者胜,权重随置信度)。IO 包装层自动从
`audio_events.json` 加载。

**Keep/Cull 反馈回路(照片侧 personal_learn 的视频版)**:
- 审片页 setDec 除 localStorage 外**同步 POST `/video/reel_decision/<run>`**
  (fire-and-forget)→ 追加 `<run>/reel_decisions.jsonl`(每 rank 末行胜)。
- 每次 POST 后 `_rebuild_reel_profile()` 走全部 run:决议 join 该候选的 v2.17
  子信号 → `learn_reel_profile()`(keep 均值−cull 均值,需双边对比才学)→ 写
  `~/.pixcull/reel_profile.json`。
- `pixcull reel` 下次运行 `load_reel_profile()`(**≥20 条真实决议**的硬激活门,
  同照片侧)→ `_profile_tilt()` 按「信号相对全片中位 × 偏好」温和倾斜 rank 分,
  **cap ±0.15**——轻推不覆盖。
- 至此视频主题(v2.17 玻璃盒 → v2.19 音频上时间线 → v2.20 反馈回路)**闭环收官**:
  看得懂为什么、听得见听到什么、学得会你的口味。

## B. 三尾巴(已交付)

- **#2 `_axisWhyLow` 接真信号**:moment 兜底升级(闭眼瞬间/连拍非峰值帧/非决定性
  瞬间置信 x/表情平淡·微笑强度 x);aesthetic 接 CLIP-IQA 与 LAION 分。payload 行补
  `face_max_smile/clipiqa/laion_aes` 三键。
- **#3 Lr 同步 reload 保位**:reload 前把滚动位置+聚焦卡存 sessionStorage,启动后
  恢复——1,500 张网格不再被甩回顶部。
- **#8 ⌘K 面板模块化**:359 行散装顶层声明包成 `modules/26-cmdk-palette.js`
  (整体重缩进 +2,内部名对外不可见);边界 lint 顺势补 PAYLOAD **解构**共享词表
  (rows/run_id/summary)。**29 个模块**,results.js 主体 9,390 行。

## 验证

reel 单测 +4(音频重叠话术/学习需双边对比/激活门/倾斜 cap ±15% 且真实生效)·
端点集成测(POST → jsonl → 档案重建,monkeypatch 档案路径)· 无头 E2E(⌘K 模块化后
开/搜/关正常 31 项、setDec 点击→服务端 jsonl 落盘、零 JS 错误)· 模块 lint 全绿 ·
完整门禁 exit=0。
