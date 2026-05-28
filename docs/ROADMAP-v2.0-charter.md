# v2.0 charter — Video culling / reel selection (Direction A)

> **Status:** scoping charter, drafted 2027-Q3 ahead of v1.0 release.
> Expected start: 2028 Q1 (after the v1.0 post-release maintenance
> quarter; see `docs/RELEASE-V1.md` § "Post-v1.0 commitments").

## 主题

**"PixCull for video — same rescorer stack, applied to video frames
+ time-aware ranking + auto-extract best 2–3 s reel candidates."**

Wedding / event / lifestyle photographers increasingly shoot photo+video
side-by-side (Canon R5 / Sony A7 IV / DJI Pocket / iPhone Pro all in
one bag).  After-event ingest currently splits:

  * **Stills** → Lightroom / PixCull (this product) → XMP / client gallery
  * **Video** → DaVinci Resolve / FCP / Premiere → manual scrub +
    cut to reel

The **video selection** half is undifferentiated.  No tool does the
photographer-grade "rank every 4 K clip by aesthetic + technical
quality + key moments + face presence + cull the blurry / shaky".
DaVinci Resolve only does *editing*; CapCut does *templating*;
Adobe Sensei *captioning*.  **None of them cull.**

v2.0 fills that gap by re-using the v0.4-v0.13 PixCull rescorer
stack against video frames + adding the time-aware overlays that
distinguish a 2-second highlight from a 2-second yawn.

## v2.0 工作范围

### P0(必须做)

#### v2.0-P0-1 · 视频导入 + 关键帧抽取
**估时**: 2 周

- `pixcull video <path>` CLI 接受 .mp4 / .mov / .mkv / .braw
- 内部用 `ffmpeg` 抽 keyframes(每 1 秒一帧或每 GOP 一帧,可配置)
- 落盘到 `<output_dir>/video_frames/<video_id>/<frame_id>.jpg`
- 每个视频生成一个 `manifest.json`:`{video_id, fps, duration_s,
  frame_count, codec, audio_track_count, ...}`
- 缩略图、scrub 预览跟现有 photo pipeline 共享 `/thumb/` 端点
- 测试覆盖:常见 codec(h.264 / h.265 / ProRes / Canon RAW Light)

输出物:每个视频 = 一个 PixCull "run",视为高密度连拍组

#### v2.0-P0-2 · 视频帧 rescorer + 时间窗聚合
**估时**: 3 周

- 复用现有 6 轴 rubric scorer(技术 / 主体 / 构图 / 光线 / 时刻 / 美感)
  打分每一帧
- **新增时间维度评分**:`score_temporal`
  - 动作连续性:相邻帧 motion vector 的一致性(高 = 顺滑 pan,低 = 抖动)
  - 时间稳定性:帧到帧的 luma / face 位置 / scene 类别的变化平滑度
  - 突发事件:面部表情突变(笑容峰值)+ 主体姿态突变(跳跃峰值)
- 时间窗聚合:对每个 1-second window 取 `mean(score_final per frame)
  + max(score_temporal)`,产生 **per-window 总分**

#### v2.0-P0-3 · Reel candidate detector
**估时**: 2 周

- 滑动窗(1s / 2s / 3s)扫整段视频,找出 top-N 候选
- 候选 ranking:`window_score × confidence × novelty(unlike previous picks)`
- 输出:`<output_dir>/reel_candidates.json`:
  ```json
  [
    {"start_s": 12.3, "end_s": 14.7, "score": 0.89,
     "why": "新郎转身 + 拥抱 + 软光",
     "best_frame_id": "...", "best_frame_score": 0.93},
    ...
  ]
  ```
- 默认产生 10-20 个候选,用户在 UI 里 keep/cull 像照片一样

#### v2.0-P0-4 · 视频 lightbox · 时间线 scrubber V2
**估时**: 2 周

- 现有 v0.11-P1-1 lightbox scrubber 升级到视频原生
- 时间轴显示候选片段的高分山峰
- 拖动 scrubber 时实时切换帧(用 P0-1 提取的关键帧)
- `J/K/L` 键 = 倒退/播放/前进(DaVinci 常用)
- 空格暂停 / 播放
- `I/O` 标记 in / out 点 → 导出该片段

### P1(应该做)

#### v2.0-P1-1 · Reel auto-assembly(自动剪片)
**估时**: 2 周

- 选中的多个 reel candidates 按时间顺序拼接 → 一个 30-90 秒成片
- 简单 cross-fade transitions(无 motion graphics — 那是后期工作)
- 音轨:第一个被选片段的原声 + 自动 fade in/out
- 导出 .mp4(h.264) + `<output_dir>/<reel_id>/edl.xml`(EDL 文件
  → 可直接在 DaVinci / Premiere 重新精剪)

#### v2.0-P1-2 · 与照片 run 的联合视图
**估时**: 1.5 周

- 一场婚礼通常 = 1800 张照片 + 20 段视频
- /results/<run_id> grid 加 "📹 Video" 标签页
- 同一时间轴显示照片 + 视频(按 EXIF capture_time 排序)
- 一键交叉跳转

#### v2.0-P1-3 · 音频内容感知(audio-photo sync 升级)
**估时**: 1.5 周

- v0.10-P1-4 audio-photo sync 已经用语音转文字标 wedding_moment
- v2.0 把这个能力扩到视频原声:
  - 笑声 detection → "moment" 轴加分
  - 鼓掌 → 同上
  - 音乐(婚礼 BGM)→ 时间段标记 + 不可剪断的关键节拍

#### v2.0-P1-4 · 抖动 / 模糊批量剔除
**估时**: 1 周

- 摄影师手持视频常有抖动段 → 用 OpenCV calcOpticalFlowFarneback 跑
  motion variance 检测
- 自动建议:这段 0.5-2.0 秒的 motion 太大,建议丢 / 用 Gyroflow 后处理
- 同样的 Laplacian 锐度检测扩到视频(per-frame)

#### v2.0-P1-5 · GoPro / DJI metadata 解析
**估时**: 4 天

- GPMF stream 解析(GPS + IMU + 拍摄者 highlight)
- 加分:GoPro / DJI Pocket 用户在拍摄时按了 highlight 按钮的片段

### P2(锦上添花)

#### v2.0-P2-1 · 4K / 8K + ProRes / RAW workflow
**估时**: 1 周

- 验证 ffmpeg 抽 4K / 8K / ProRes / Canon RAW Light 帧的耗时和质量
- 大视频文件(> 50GB)的内存使用 profile + 流式处理
- DJI Mavic / Inspire RAW DNG 帧的兼容性

#### v2.0-P2-2 · Color-graded preview overlay
**估时**: 1 周

- Scrubber 上每个候选片段显示一个 LUT-applied 预览缩略图
- 摄影师常用 LUT(Fuji Eterna / Kodak Vision3 / Arri 709A)预置
- 一键应用 / 撤销

#### v2.0-P2-3 · DESIGN-AUDIT-2028Q2 + v2.1 charter
**估时**: 3-4 天

- v2.0 release 后做下一轮自审 + 起草 v2.1 charter

## 不做的事(scope discipline)

- **不做 NLE(non-linear editor)**: PixCull is for cull,不是 cut.
  全功能剪辑留给 DaVinci / FCP / Premiere
- **不做 motion graphics / transitions library**: 不替代 After
  Effects / Premiere Templates
- **不做云上传 / 云剪辑**: 本地优先承诺延续
- **不做实时直播流处理**: 离线 batch only
- **不引入 React / Vue**: vanilla JS 继续撑

## 验收标准

v2.0 release 完成的标志:

- **`pixcull video <path>` CLI 真能跑**:200 张照片 + 20 段 4K 视频
  混合 batch,15 分钟内出完整 ranking
- **Reel candidates 准确率**:5 位真实摄影师标注,top-10 候选与
  人工 reel selection 重合率 ≥ 60%(达不到则推到 v2.1)
- **导出格式**:.mp4 + EDL.xml 进 DaVinci 不报错
- **lightbox scrubber 视频版**:60 FPS 拖动 4K 帧 < 100ms 延迟(在
  M2 Pro 上)
- **照片 + 视频联合视图**:同一 run 内同步过滤 + 排序
- **文档**:`docs/VIDEO-USER-GUIDE.md` 写完 + 录一段 60 秒 demo
- **设计审计**:DESIGN-AUDIT-2028Q2 ≥ 4.5 / 5(沿用 1.0 标杆)

## 建议外部资源 / 灵感参考

- **DaVinci Resolve** — 时间轴 + scrub UX 标杆
- **CapCut / Adobe Premiere Rush** — 简化剪辑流参考
- **GoPro Quik** — auto-reel 自动选片标杆
- **FFmpeg** — 帧抽取 + 转码核心库
- **OpenCV optical flow** — 抖动检测算法
- **GPMF** (GoPro metadata format) — IMU + highlight stream

## 建议执行顺序(预计 12-16 周)

| 顺序 | 任务 | 估时 | 理由 |
|---|---|---|---|
| 1 | **P0-1** 视频导入 + 关键帧 | 2 周 | foundation — 所有后续依赖 ffmpeg + frame extract |
| 2 | **P0-2** 视频帧 rescorer | 3 周 | 复用 photo pipeline 75%,新增时间维度评分 |
| 3 | **P0-3** Reel candidate detector | 2 周 | 依赖 P0-2 评分,核心差异化能力 |
| 4 | **P0-4** Lightbox scrubber V2 | 2 周 | UI 层,可与 P0-3 并行 |
| 5 | **P1-2** 照片 + 视频联合视图 | 1.5 周 | 用户体验关键(混合 batch) |
| 6 | **P1-1** Reel auto-assembly | 2 周 | "wow" 功能 |
| 7 | **P1-4** 抖动检测 | 1 周 | 独立 scope |
| 8 | **P1-3** 音频内容感知升级 | 1.5 周 | 依赖 P1-1 时间线 |
| 9 | **P1-5** GoPro metadata | 4 天 | 独立 scope |
| 10 | **P2-x** | 视情况 | 收尾 + v2.1 scoping |

## 风险登记 + 缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| ffmpeg 抽 4K/8K 帧太慢 | P0-1 失败 | 使用硬件加速(`-hwaccel videotoolbox` on macOS / `cuda` on Linux) |
| 时间维度评分难调 | P0-2 准确率低 | 先发布 v2.0-RC 收集 1-2 个摄影师反馈,再 v2.0 ship |
| 4K 文件内存 OOM | 全 pipeline 崩 | 流式处理 + frame_count 上限(默认 5000 帧/视频)+ admin 警告 |
| `.braw` / Canon RAW Light 编解码licence | P0-1 子项 | 这些 codec 需要厂商 SDK,先支持开放 codec(h.264 / h.265 / ProRes),RAW 推到 v2.1 |
| 用户期望 NLE 功能 | scope creep | charter 明确"不做 NLE";README "v2.0 不替代 DaVinci" |

## 商业化考量

视频选片是 **Studio plan 的强差异化卖点**:

- 一段 30 分钟 4K 婚礼视频,人工 reel selection ≥ 2 小时;
  PixCull v2.0 目标:**15 分钟**
- 这是 free tier 的"试用甜点",Studio plan 解锁:
  - 多视频联合 reel(跨摄相机)
  - 4K+ ProRes / Canon RAW Light 编解码
  - 自动 audio sync 跨多机位
  - 批量 EDL 导出(给后期编辑用)

## 与 v1.x 关系

- v1.0 → v1.x.x 维护期(2027 Q3 - 2027 Q4)期间,**不做 v2 准备工作**
- 2028 Q1 起 v2.0 开发正式开始,**v1.x bug-fix 节奏不变**
- v2.0 ship 后,**v1.x 进入 LTS**,只做 security fixes

## 与方向 B(Generative compositing)、方向 C(Enterprise SSO)的关系

`docs/RELEASE-V1.md` § "v2.0 horizon" 还列了 B/C 两个候选方向:

- 方向 B(generative compositing)依赖 SDXL inpaint + SAM2 + 用户期望
  管理,12-16 周 — **deferred to v3.0**
- 方向 C(enterprise SSO + audit log)需要 billing 工程师 + 企业销售
  渠道,4-6 周 — **deferred to v2.x or v3.0**

按 PMF × 实现成本评估,**A > B > C** 已锁定为 v2 / v3 / v4 的执行顺序。

---

charter timestamp: 2027 Q3(v1.0 release 临近时起草)
expected start: 2028 Q1(post-v1.0 维护期结束后)
expected duration: 12-16 周(v2.0 release 2028 Q2 mid)
predecessor: `docs/RELEASE-V1.md` § "v2.0 horizon"
sister docs: `docs/V1-DOGFOOD-CHECKLIST.md`(v1.0 gate) ·
  `docs/USER-GUIDE.md`(用户文档基线)
