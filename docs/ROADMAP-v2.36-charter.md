# v2.36 charter — 真实视频素材上台,顺带挖出"CLI 挑完视频就没法看"

**主题:** 关掉 owner 动作清单第 4 条(可公开视频素材),重摄 gallery 18/19。
**意外:** 为了拍这两张图,发现**用 CLI 挑完一段视频后,审片台根本认不出
这个 run** —— 一个此前没人碰到的真 bug。

---

## 0. 素材:owner 授权自有 GoPro 素材

Q4 审计的第 4 条要求"无人脸 / 无敏感 GPS 的可公开视频素材"。owner
2026-07-30 授权使用自己的 GoPro 素材(个人素材、已获授权)。

在发布任何一帧之前逐项核过:

| 项 | 做法 | 结果 |
|---|---|---|
| GPS | `parse_telemetry()` 读 GPMF | 6 个候选片段**全部无 GPS 采样** |
| 人脸 | 抽 38 帧过 PixCull 自己的 `FaceDetector`,再逐帧目视复核 | 检出 14 帧,**目视全为误检**(毛领/针织纹样);主体全程背对镜头 |
| 车牌 / 路人 | 目视 4 个候选的抽帧联片 | **弃用其中一段**(婚礼车队,有车牌+路人);选用的片段无可读车牌 |
| 路径 / 盘名 | 剪出工作副本时 `-map_metadata -1`,改中性文件名 | 页面只显示 `winter-sled.mp4`,不含盘名/原路径/设备标签 |

选定其中一段的 8–103s(冬季雪道雪橇,白桦林+蓝天,主体背对),
95s / 50 帧 / 20 个 reel 候选。

**为什么这值得换:** 原来的 18/19 用的是一段库存素材,它的 reel 候选缩略
图**必须模糊成一团**才能对外 —— 那恰好把这个功能最该展示的东西(候选带
长什么样)糊掉了。现在缩略图是真帧。

## 1. 撞出来的真 bug:视频 run 在审片台里不存在

拍 `/timeline/<run>` 时,**50 个缩略图全是碎图**,50 个 `/thumb/` 请求
全 404。

根因两层,都不是布局问题(我先换成惯例的 `<run>/output/` 布局验证过,
一样坏):

**① `_reload_run_from_disk` 认不出视频 run。** 它要求 `output/manifest.json`
存在(scan 模式)**或** `input/` 目录存在(upload 模式),否则返回
`None`。而 `pixcull video` 两个都不产出 —— 它的帧在
`video_frames/<clip>_<hash>/`。于是这个 run 根本没被 reload:
`/api/v1/runs` 报 0 个 run,每个 `/thumb` 404,整条时间线碎成 50 张破图。

**② `_resolve_image_source` 不查 scores.csv 的 `path` 列。** 和 v2.34 修
`pixcull library index` 时**同一个根因** —— 那一列是流水线为每张图亲手记
下的绝对路径,是这个布局下唯一权威来源,偏偏两处都没查它。

### 修法

- `_reload_run_from_disk` 改用 **`scores.csv` 作为"这是一个 run"的标志**,
  并同时接受两种布局:`<run>/output/scores.csv` 和 `<run>/scores.csv`
  (后者就是 `pixcull video --output <dir>` 产出的形状)。新增 `mode="csv"`。
- `_resolve_image_source` 末尾兜底查 scores.csv 的 `path` 列。
  **按 mtime 缓存**:这个函数是**每张缩略图调一次**的,内联解析 CSV 就是
  画一条时间线要解析 50 遍(真实拍摄要上千遍)—— 和 v2.34 修掉的
  "逐张照片重读 manifest.json"是同一个坑。
- 识别不能放松到"任何目录都是 run":专门测了没有 scores.csv 的目录仍返回
  `None`,scan / upload 两个旧模式的优先级与行为完全不变。

## 2. 验收

- `/timeline/wintersled` 真实浏览器复验:**缩略图 50/50 加载,4xx/5xx = 0**
  (修之前 0/50,50 个 404)。
- 新增 `tests/test_video_run_serving.py`(9 条)。**做过变异验证**:把
  `mode="csv"` 识别分支改成 `elif False`,恰好且仅有 4 条视频相关测试变红,
  scan / upload / 缓存三条仍绿 —— 证明它们不是空过。
- 门禁绿:**1425 passed, 5 skipped**(2 face fixture + 3 zeroconf,预期)。
- 重摄并安装:`18-video-review.png`(Original)、`19-video-grade.png`
  (Kodak Vision3)、**新增 `23-video-timeline.png`**(照片+视频同轴时间线,
  50 帧全部可点)。
- 顺手改正 README 里 19 的图注:原文写"此处 B&W",实际截的是 Kodak Vision3。
- 版本 2.35.1 → 2.36.0 lockstep;CLAUDE.md 截图登记表更新(下一个空位 24),
  并把这批素材的授权与脱敏结论写进去。

## 3. 顺延

- **baby face-Close-ups 那张(原 23 号预留)仍未拍** —— 功能已验证,但本机
  headless 抓图会被杀,需本地跑
  `scripts/brand/capture_real_screenshots.sh`。它现在不占 23 号(23 已给
  video-timeline),排到 24。
- owner 侧仍缺:`PYPI_API_TOKEN`、~50 条真实 keep↔maybe 分歧标注。
- `append_run` 全量重写 `vectors.npy`(30 万张以上再改分片追加)。
- 独立页面要不要也放主题切换控件(产品判断)。
