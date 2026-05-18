<div align="center">
  <img src="docs/assets/github-hero.svg" alt="PixCull — AI photo culling for professional photographers" width="100%" />
</div>

<p align="center">
  <a href="https://github.com/ChrisChen667788/pixcull/actions/workflows/tests.yml"><img alt="tests" src="https://img.shields.io/github/actions/workflow/status/ChrisChen667788/pixcull/tests.yml?branch=main&label=tests&style=flat-square" /></a>
  <a href="./LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square" /></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%20%7C%203.12-3776AB.svg?style=flat-square&logo=python&logoColor=white" />
  <img alt="Platform" src="https://img.shields.io/badge/macOS-Apple%20Silicon%20%26%20Intel-000.svg?style=flat-square&logo=apple" />
  <img alt="Local-first" src="https://img.shields.io/badge/local--first-photos%20never%20upload-34d399.svg?style=flat-square" />
  <a href="https://github.com/ChrisChen667788/pixcull/stargazers"><img alt="stars" src="https://img.shields.io/github/stars/ChrisChen667788/pixcull?style=flat-square" /></a>
</p>

<p align="center">
  <b>English</b> ·
  <a href="#中文">简体中文</a> ·
  <a href="https://www.modelscope.cn/profile/haozi667788">ModelScope</a>
</p>

<p align="center">
  <i>The local-first AI culling tool for working photographers.<br/>
  Six calibrated axes, photographer-grade XMP / IPTC / gallery export,<br/>
  Lightroom &amp; Capture One ready, no photo ever leaves your disk.</i>
</p>

---

## Why PixCull

A 1,500-frame wedding takes a human ~6 hours to cull. AI-assist tools
exist, but the popular ones make three trade-offs working photographers
shouldn't have to swallow:

- **They upload your photos.** Wedding contracts and journalism NDAs
  routinely forbid third-party cloud processing of client images.
  Most "AI culling" SaaS apps need an upload to even start.
- **They give you a score, not a reason.** A single 0..1 number tells
  you nothing about *why* a frame got picked. Defending a culling
  decision to a client — or learning from your own taste — needs an
  audit trail.
- **They live outside your tooling.** Lightroom, Capture One, Photo
  Mechanic, your tethered shoot — that's where the work happens. A
  walled-garden web app forces a context switch on every batch.

PixCull is the alternative that flips all three:

- **Local-first.** RAW decode, scoring, faces, GPS — everything runs
  on your machine. The optional DeepSeek meta-judge runs against
  *your* API token; the photos stay on disk either way.
- **6-axis rubric.** Every frame gets stars on technical, subject,
  composition, light, moment, and aesthetic — each with a short
  rationale and (for V5.2+ advice) a canon citation (Adams' Zone
  System, Cartier-Bresson decisive-moment, etc).
- **Sidecar-native.** Verdicts ship as XMP files Lightroom and
  Capture One pick up natively. IPTC captions, standalone HTML
  galleries, Lr plugin, iOS swipe companion — all included.

## Who it helps

- **Wedding &amp; event photographers** shooting 1,000+ frames a day who
  need to triage by tomorrow morning and defend the pick to the
  client without breaking NDA.
- **Sports / action shooters** running tethered to Lightroom — PixCull
  watches the tether folder and emits a live keep/maybe/cull verdict
  per shutter click.
- **Photojournalists** under embargo or IP contract who literally
  cannot upload to a SaaS culling service.
- **Studios with second shooters** who need to merge coverage of the
  same moment from multiple cameras and reconcile face IDs across
  cards.
- **Wildlife / landscape photographers** who shoot bursts of the same
  scene and want the burst-peak picked automatically without
  losing the run-up frames.
- **Self-taught photographers** who want the tool to *explain*
  decisions — strengths, weaknesses, suggestions — not just rank.

## What you get today

1. **6-axis rubric scoring.** Technical, subject, composition, light,
   moment, aesthetic. Each axis: 1–5 stars with rationale.
   Calibrated against thousands of human labels; per-axis rescorer
   trained on the same data.
2. **Per-genre verticals.** Wedding · wildlife · sports · landscape ·
   portrait · event · journalism · commercial · still-life. Each
   vertical adjusts the keep/maybe thresholds and weights the axes
   to taste (e.g. wildlife rewards moment-axis sharpness even when
   composition slips, weddings reward expression even when light is
   marginal).
3. **V20 advice envelope.** Every photo carries a short verdict, a
   list of strengths cited to canon (Adams Zone System, Cartier-
   Bresson decisive moment, Rule of Thirds, etc.), a list of
   weaknesses, and a list of concrete suggestions. Pros use it to
   defend picks to clients; learners use it as a teacher.
4. **Local face clustering.** InsightFace ArcFace embeddings →
   DBSCAN clustering → cross-run face library that recognizes the
   same bride / kid / pet across all your shoots. Avatars + inline
   renaming in the UI.
5. **GPS location clustering.** Haversine DBSCAN groups photos by
   capture spot (~100 m radius). "Pick one per location" surfaces
   the best frame from each.
6. **Burst-peak ranking.** Sub-second bursts get a calibrated peak
   pick (best focus, expression, action moment).
7. **Cull-reason taxonomy.** When you cull, optionally tag *why* —
   `focus_miss`, `eyes_closed`, `motion_blur`, `framing`,
   `duplicate`, `exposure`, `other`. Powers a filter pill and
   builds a richer training signal.
8. **Similar-photos lookup.** Composite signature (burst-cluster +
   scene + face overlap + GPS + rubric proximity) ranks the top-5
   visually similar frames; one click jumps to them, Shift+click
   pins for compare.
9. **Free-pick A/B compare.** Click ⇆ on any two photos →
   side-by-side with synced 1:1 zoom across both cells. Built for
   "which one of these two near-dupes do I keep?".
10. **1:1 focus check.** Click any photo in the lightbox to pixel-
    peep at 100%, drag to pan, mouse-wheel to fine-tune. Auto-loads
    hi-res when zoom activates.
11. **XMP / IPTC / gallery export.** XMP sidecars for Lightroom &amp;
    Capture One, IPTC Caption-Abstract auto-composed from
    scene + faces + location + advice (free) or LLM-polished
    (DeepSeek, INFRA-4 budgeted), standalone HTML gallery as a zip
    you can email to a client.
12. **iOS swipe companion.** SwiftUI app for swipe-style triage on
    your phone while the laptop runs the heavy work. Talks to the
    `/api/v1/` namespace.
13. **Lr / Capture One tether mode.** Point it at the tether
    destination folder; PixCull watches and emits live verdicts as
    the camera shoots. Partial `scores.csv` survives Ctrl-C.
14. **Multi-machine sync.** Symlink-based folder mirror over
    iCloud / Dropbox / NAS — your face library + verticals +
    LLM-spend ledger follow you between studio &amp; laptop.
15. **Active-learning queue.** The next photos most worth labeling,
    ranked by rescorer disagreement + uncertainty + threshold-
    proximity. Your personalized model improves silently as you
    label.
16. **Multi-user profiles.** Studio with two shooters? Each user has
    their own verticals + face library; shared team verticals for
    house style.

## Why it's different from a generic AI culling app

| | PixCull | typical SaaS culling | Lightroom AI Select |
|---|---|---|---|
| Photos leave your disk | **No** | Yes (upload required) | No, but vendor-locked |
| Scoring rationale | **6-axis stars + canon citations** | Single 0..1 score | "Best of this group" |
| Workflow integration | **XMP sidecars + Lr plugin + iOS + tether** | Web app only | Lightroom only |
| Per-genre tuning | **9 verticals + extensible** | One model | Hidden |
| Open source | **MIT** | Closed | Closed, subscription |
| Active learning | **Built-in** | Closed re-train cycle | None visible |
| Face library across runs | **Yes (V22.2)** | Per-batch | Per-catalog |
| Burst peak picker | **Yes** | Yes | Yes (Stack) |
| Cull-reason taxonomy | **Yes (taxonomy + filter)** | No | No |
| 1:1 focus check + sync | **Lightbox + compare** | Limited | Yes |
| Hackable | **Plain Python + plain JS** | No | No |

## Screenshots

The UI is one Jinja-free HTML template
(`pixcull/report/templates/results.html`) and one SwiftUI app
(`mobile/PixCullCompanion/`). Both are dark, mouse-and-keyboard
optimized, and zero-build (no webpack / no Xcode workspace).

> **Note** — placeholder visuals only at first push. Pull request a
> screenshot drop here once you've put PixCull on a real shoot.

| Surface | Description |
|---|---|
| `/` upload page | Drag-drop a folder; live progress as scoring runs. Vertical chooser + active user switcher. |
| `/results/<run>` | The main culling surface. 3-col grid, swipe-style hotkeys, lightbox with rubric stars + V20 advice + GPS map + face clusters + similar photos + sticky decision toolbar. |
| `/results/<run>` lightbox 1:1 | Click any photo to zoom to 100%; drag to pan; mouse-wheel to fine-tune. Hi-res image swaps in on the first zoom. |
| `/results/<run>` A/B compare | Pin any 2 photos via the ⇆ button (or Shift-click a thumb); compare modal opens with synced 1:1 zoom across both cells. |
| `/admin` | Storage info; run management; license token; sync configuration. |
| `/verticals` | Per-genre policy editor; promote a sample to the team bank. |
| iOS companion | SwiftUI grid + per-photo swipe annotator + rich lightbox (axes + advice + GPS + face clusters). |

## Quick start

```bash
# 1. Clone
git clone https://github.com/ChrisChen667788/pixcull.git
cd pixcull

# 2. Python 3.11 or 3.12 (mediapipe pins numpy<2 which forces 3.12-max)
python3.12 -m venv .venv
source .venv/bin/activate

# 3. Install (this pulls torch CPU + InsightFace ONNX + MediaPipe)
pip install -e ".[dev]"

# 4. Run the demo server
python scripts/serve_demo.py
# → open http://127.0.0.1:8770
```

Drop a folder of JPG / RAW / HEIC into the upload page; first run
warms the models (~30 s on Apple Silicon), subsequent batches score
at roughly 1 s / photo on M2 Pro.

### Tether mode (Lr / Capture One)

```bash
python scripts/pixcull_tether.py \
    --vertical wedding \
    ~/Pictures/Lightroom-Tether/2026-05-16-wedding
```

PixCull watches the folder, scores each frame within ~2 s of the
shutter click, and writes a live `scores.csv`. Ctrl-C to stop;
partial results are preserved.

### Standalone macOS app

A signed + notarized `.app` bundle (PyInstaller + Apple Developer
ID) lives at `app/`. See `app/RELEASE.md` for the build / notarize /
Sparkle-update pipeline.

## Configuration

| What | Where | Default |
|---|---|---|
| Server port | `--port` flag on `scripts/serve_demo.py` | `8770` |
| API key (for LAN deploy) | `PIXCULL_API_KEY` env / `X-PixCull-API-Key` header | unset |
| CORS allowlist | `PIXCULL_API_CORS_ORIGINS` env (comma-sep) | `*` if unset |
| Active user | `PIXCULL_USER` env / `X-PixCull-User` header / cookie | none |
| App data dir | `~/Library/Application Support/PixCull` (macOS) | per-platform |
| DeepSeek API key (optional) | `DEEPSEEK_API_KEY` env / `config.json` in app data | unset |
| Sync target (optional) | `pixcull/sync.py` `configure_sync_for_user(path)` | none |

## Repository structure

```
pixcull/
├── pixcull/                    # the actual Python package
│   ├── scoring/                # 6-axis rubric, scene templates, style modes
│   ├── pipeline/               # orchestrator, worker, face / GPS clustering, advice
│   ├── detectors/              # blur, eye-state, exposure, composition, etc.
│   ├── io/                     # RAW loader, XMP / IPTC writers, EXIF
│   ├── db/                     # annotations.jsonl + scores.csv schema helpers
│   ├── report/templates/       # the results.html web UI (zero-build, vanilla JS)
│   ├── license/                # local license-token state machine
│   ├── verticals.py            # per-genre scoring policy
│   ├── sync.py                 # INFRA-2 multi-machine folder mirror
│   └── tether.py               # P2.2 Lr/C1 tether watcher
├── scripts/                    # runnable entry points
│   ├── serve_demo.py           # the HTTP server + web UI host (10k lines)
│   ├── pixcull_tether.py       # the tether CLI
│   ├── train_rescorer.py       # per-axis rescorer training
│   └── ...                     # ~30 maintenance + analysis scripts
├── mobile/PixCullCompanion/    # SwiftUI iOS app (Swift Package)
├── lr_plugin/PixCull.lrplugin/ # Lightroom plugin (Lua)
├── app/                        # PyInstaller spec for the .app bundle
├── tests/                      # pytest suite (240+ tests)
├── training.csv                # sanitized rubric ground truth (130 rows)
├── training_axis.csv           # sanitized per-axis ground truth (3,000 rows)
├── ROADMAP.md                  # the next ~12 months of work
└── pyproject.toml              # MIT, Python 3.11–3.12
```

## Roadmap

The full [ROADMAP.md](ROADMAP.md) has the running plan with rough
sizing. The current focus areas:

- **Photo evaluation intelligence.** Reject-reason taxonomy →
  rubric model retraining (so your `cull because eyes_closed`
  becomes a real signal); per-axis confidence intervals; meta-judge
  inconsistency detection.
- **Pro-grade workflows.** Tighter Lr / Capture One round-trip;
  Photo Mechanic-equivalent culling hotkeys; auto-IPTC keywords
  from face labels + locations + advice.
- **Mobile companion V0.4+.** Pull-to-refresh, swipe-down dismiss,
  haptic feedback on quick-label, photo-library import in addition
  to server-side runs.

## Security and privacy

PixCull is local-first by design. The default `serve_demo.py` binds
to `127.0.0.1` only; the optional LAN deploy is gated by an
`X-PixCull-API-Key` header you set via `PIXCULL_API_KEY`.

See [SECURITY.md](SECURITY.md) for the full threat model and
disclosure policy. TL;DR: trusted local user, untrusted image input
(Pillow is pinned ≥ 10.2), no telemetry, optional DeepSeek calls go
straight to DeepSeek with *your* token (we never proxy).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs welcome; bug reports
welcome (use the issue template); the highest-leverage first PRs
are listed in the contributing doc.

## License

[MIT](LICENSE). Use it commercially, fork it freely, send a
pull request.

## About

PixCull started as a single-developer project to stop personally
spending an evening per shoot in Lightroom's catalog. Eighteen
months and a lot of small commits later, it's the AI culling tool
I wish had existed when I picked up my first camera. Open-sourcing
it under MIT so the next photographer doesn't have to rebuild it
from scratch.

— [@ChrisChen667788](https://github.com/ChrisChen667788)

---

<a id="中文"></a>

<div align="center">
  <img src="docs/assets/github-hero.svg" alt="PixCull — 摄影师本地优先的 AI 选片工具" width="100%" />
</div>

<p align="center">
  <a href="#pixcull-ai-photo-culling-for-professional-photographers">English</a> ·
  <b>简体中文</b> ·
  <a href="https://www.modelscope.cn/profile/haozi667788">ModelScope</a>
</p>

<p align="center">
  <i>专业摄影师的本地优先 AI 选片工具。<br/>
  6 维评分,XMP / IPTC / 相册一键导出,Lightroom &amp; Capture One 直通,照片永远不出本机。</i>
</p>

## 为什么有这个项目

一场 1,500 张的婚礼,人工选片平均要花一个晚上。市面上的 AI 选片工具
存在,但主流方案都让职业摄影师作出三个不该接受的妥协:

- **它们会把你的照片上传。** 婚礼合同和新闻摄影的 NDA 都明令禁止把
  客户照片送到第三方云上。绝大多数 "AI 选片" SaaS 不上传就跑不起来。
- **它们只给一个分数,没有理由。** 0..1 的总分告诉不了你为什么这张
  入选。给客户解释、或者从自己的选择中学习,都需要审计轨迹。
- **它们活在你工作流之外。** Lightroom、Capture One、Photo Mechanic、
  tether 拍摄 —— 真正的工作发生在这些地方。封闭的 Web App 每批都
  逼你切换上下文。

PixCull 把这三件事全部翻过来:

- **本地优先。** RAW 解码、评分、人脸、GPS —— 全在你电脑上跑。
  可选的 DeepSeek meta-judge 走的是 *你的* API token;不论哪种情况
  照片都在你的硬盘上。
- **6 维评分细则。** 每张照片在 技术 / 主体 / 构图 / 光线 / 瞬间 / 美感
  六个维度上都打 1-5 星,每个维度都有简短的理由 (V5.2+ 还附带摄影
  正典引用 —— Adams 的 Zone System、Cartier-Bresson 的决定性瞬间等等)。
- **Sidecar 原生。** 评分以 XMP 文件输出,Lightroom 和 Capture One
  直接识别。IPTC 标题、独立 HTML 相册、Lr 插件、iOS 滑动伴侣 App —— 都内置。

## 适合谁

- **婚礼 / 活动摄影师** —— 每天 1,000+ 张,明早就要交,而且要在
  不破坏 NDA 的前提下能给客户解释为什么这张入选。
- **体育 / 动作摄影师** —— tether 接 Lightroom,PixCull 监控
  tether 目录,每张快门 ~2 s 给出 keep/maybe/cull 实时判断。
- **新闻摄影师** —— 在 embargo 或 IP 合同下根本不能上传到 SaaS。
- **多人摄影工作室** —— 多个二摄拍同一时刻,需要跨相机合并覆盖、
  跨卡同步人脸 ID。
- **野生 / 风光摄影师** —— 同场景连拍一组,需要自动选峰值帧而又不
  丢失起跑那几张。
- **自学摄影爱好者** —— 想要工具 *解释* 评判 —— 优点、缺点、改进
  建议 —— 而不是只给排序。

## 现在就能用的能力

1. **6 维评分细则。** 技术 / 主体 / 构图 / 光线 / 瞬间 / 美感,每维 1-5
   星,带理由。用数千条人工标注校准,每维都有独立的 rescorer 模型。
2. **9 种细分领域 (verticals)。** 婚礼 · 野生 · 体育 · 风光 · 人像 ·
   活动 · 新闻 · 商业 · 静物。每种领域调整 keep/maybe 阈值并按品味重
   加权 (比如野生奖励瞬间维度的清晰度,即使构图不那么稳;婚礼奖励表
   情,即使光线一般)。
3. **V20 建议信封。** 每张照片附带:简短 verdict、引用摄影正典的
   strengths 列表 (Adams Zone System、决定性瞬间、三分法 等等)、
   weaknesses 列表、具体可执行的 suggestions 列表。
4. **本地人脸聚类。** InsightFace ArcFace embedding → DBSCAN →
   跨 run 的人脸库,识别同一个新娘 / 孩子 / 宠物 跨越所有拍摄。
5. **GPS 位置聚类。** Haversine DBSCAN 按拍摄地点 (~100 m 半径) 分组。
   "每个地点选一张" 凸显每个地点的最佳。
6. **连拍峰值排序。** 亚秒级的连拍组自动选峰值帧 (最佳对焦、表情、
   动作瞬间)。
7. **Cull 原因分类。** Cull 时可选标 *为什么*:`focus_miss` (焦点不准)、
   `eyes_closed` (闭眼)、`motion_blur` (模糊抖动)、`framing` (构图差)、
   `duplicate` (与更佳重复)、`exposure` (曝光问题)、`other`。驱动一个
   筛选条目,并建立更丰富的训练信号。
8. **类似照片查找。** 复合特征 (连拍组 + 场景 + 人脸重叠 + GPS + 评分
   邻近) 排序前 5 张视觉相似帧;点击跳转,Shift+ 点击 加入 A/B 对比。
9. **自选 A/B 对比。** 在任意两张照片上点 ⇆ 按钮 →
   并排比较,两张图同步 1:1 缩放、平移、滚轮缩放。专为
   "这两张相似的我到底留哪个" 设计。
10. **1:1 焦点检查。** 大图窗中点任意位置 1:1 放大,拖动平移,滚轮细
    调。首次缩放时自动加载高分辨率原图。
11. **XMP / IPTC / 相册 导出。** XMP sidecar 进 Lr/C1,IPTC Caption-
    Abstract 由 场景+人物+地点+建议 自动合成 (免费) 或 DeepSeek 润色
    (INFRA-4 budget 内),独立 HTML 相册打包成 zip 直接发客户。
12. **iOS 滑动伴侣 App。** SwiftUI 写的手机端滑动选片 App,后台跑笔记
    本上的重活。走 `/api/v1/` 接口。
13. **Lr / C1 Tether 模式。** 指向 tether 目录;PixCull 监控,每个快门
    ~2 s 内给出实时 verdict,partial scores.csv 在 Ctrl-C 后保留。
14. **跨机同步 (INFRA-2)。** 基于符号链接的目录镜像,走 iCloud / Dropbox /
    NAS —— 人脸库 + 细分领域 + LLM 花费账本跟着你在工作室 ↔ 笔记本之间
    切换。
15. **主动学习队列 (P2.4)。** 按 rescorer 分歧度 + 不确定度 + 阈值附
    近度 排序的 "下一张最值得标的照片"。你的个性化模型在你标注的过程
    中静默改进。
16. **多用户 profile (V28)。** 工作室里两个二摄?各有自己的 vertical +
    人脸库;共享 team vertical 用于工作室主基调。

## 和其他 AI 选片工具的对比

| | PixCull | 主流 SaaS 选片 | Lightroom AI Select |
|---|---|---|---|
| 照片要不要离开本机 | **不需要** | 必须上传 | 不离开但厂商锁定 |
| 评分理由 | **6 维 + 正典引用** | 单一 0..1 分 | "这组的最佳" |
| 工作流融入度 | **XMP + Lr 插件 + iOS + tether** | 仅 Web App | 仅 Lightroom |
| 按拍摄类型调权 | **9 种 vertical + 可扩展** | 单一模型 | 不透明 |
| 开源 | **MIT** | 闭源 | 闭源、订阅制 |
| 主动学习 | **内置** | 闭源再训练循环 | 不可见 |
| 跨 run 人脸库 | **支持 (V22.2)** | 每批独立 | 每个 catalog 独立 |
| 连拍峰值选择 | **支持** | 支持 | 支持 (Stack) |
| Cull 原因分类 | **支持 (分类 + 筛选)** | 不支持 | 不支持 |
| 1:1 焦点检查 + 同步 | **大图窗 + 比较窗** | 有限 | 支持 |
| 可定制 | **纯 Python + 纯 JS** | 不可定制 | 不可定制 |

## 截图

UI 是一个零构建的 HTML 模板 (`pixcull/report/templates/results.html`)
加一个 SwiftUI App (`mobile/PixCullCompanion/`)。两者都是黑色主题、
键鼠优先、无 webpack / 无 Xcode workspace。

> **提示** —— 首次 push 时只放占位图。等 PixCull 真上过一场拍摄,
> 欢迎 PR 一张真实截图替换。

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/ChrisChen667788/pixcull.git
cd pixcull

# 2. Python 3.11 或 3.12 (mediapipe 把 numpy 钉死在 <2,所以 3.12 是上限)
python3.12 -m venv .venv
source .venv/bin/activate

# 3. 安装 (会拉 torch CPU + InsightFace ONNX + MediaPipe)
pip install -e ".[dev]"

# 4. 跑起来
python scripts/serve_demo.py
# → 浏览器开 http://127.0.0.1:8770
```

把一个 JPG / RAW / HEIC 的文件夹拖到上传页;首次约 30 秒预热模型
(Apple Silicon),之后每张 ~1 秒 (M2 Pro 实测)。

### Tether 实时选片 (Lr / Capture One)

```bash
python scripts/pixcull_tether.py \
    --vertical wedding \
    ~/Pictures/Lightroom-Tether/2026-05-16-wedding
```

PixCull 监控目录,每张快门 ~2 秒内出 verdict,实时写 `scores.csv`。
Ctrl-C 退出,部分结果保留。

### macOS 独立 App

`app/` 下有签名 + 公证过的 `.app` 打包配置 (PyInstaller + Apple
Developer ID)。`app/RELEASE.md` 里有完整的构建 / 公证 / Sparkle 更
新 pipeline。

## 配置项

| 内容 | 位置 | 默认值 |
|---|---|---|
| 端口 | `scripts/serve_demo.py --port` | `8770` |
| API key (LAN 部署) | `PIXCULL_API_KEY` 环境变量 / `X-PixCull-API-Key` 头 | 未设置 |
| CORS 白名单 | `PIXCULL_API_CORS_ORIGINS` (逗号分隔) | 未设置时 `*` |
| 当前用户 | `PIXCULL_USER` env / `X-PixCull-User` 头 / cookie | 无 |
| App 数据目录 | `~/Library/Application Support/PixCull` (macOS) | 因平台而异 |
| DeepSeek API key (可选) | `DEEPSEEK_API_KEY` env / app-data 下 `config.json` | 未设置 |
| 同步目标 (可选) | `pixcull/sync.py::configure_sync_for_user(path)` | 无 |

## 仓库结构

```
pixcull/
├── pixcull/                    # Python 包本体
│   ├── scoring/                # 6 维评分 + 场景模板 + 风格模式
│   ├── pipeline/               # 编排器 + worker + 人脸/GPS 聚类 + 建议
│   ├── detectors/              # 模糊 / 闭眼 / 曝光 / 构图 / ... 检测器
│   ├── io/                     # RAW 加载 + XMP / IPTC 写 + EXIF
│   ├── db/                     # annotations.jsonl + scores.csv schema
│   ├── report/templates/       # results.html 主 UI (零构建,vanilla JS)
│   ├── license/                # 本地 license token 状态机
│   ├── verticals.py            # 按拍摄类型的评分策略
│   ├── sync.py                 # 多机同步 (folder mirror)
│   └── tether.py               # Lr/C1 tether 监控
├── scripts/                    # CLI 入口
│   ├── serve_demo.py           # HTTP 服务 + Web UI 主程序 (10k 行)
│   ├── pixcull_tether.py       # Tether CLI
│   ├── train_rescorer.py       # rescorer 训练脚本
│   └── ...                     # ~30 个维护 + 分析脚本
├── mobile/PixCullCompanion/    # SwiftUI iOS App (Swift Package)
├── lr_plugin/PixCull.lrplugin/ # Lightroom 插件 (Lua)
├── app/                        # PyInstaller 打包配置
├── tests/                      # pytest 测试套 (240+ 用例)
├── training.csv                # 脱敏后的 rubric ground truth (130 行)
├── training_axis.csv           # 脱敏后的 per-axis ground truth (3,000 行)
├── ROADMAP.md                  # 未来 12 个月规划
└── pyproject.toml              # MIT,Python 3.11–3.12
```

## 路线图

完整 [ROADMAP.md](ROADMAP.md) 在仓库根。当前重点:

- **照片评价智能化。** Cull 原因 → rubric 模型再训练 (让你的
  "因为闭眼 cull" 变成真实信号);各维度的置信区间;meta-judge 矛
  盾检测。
- **专业工作流。** 更紧的 Lr / C1 round-trip;Photo Mechanic 级别
  的选片快捷键;从 人脸标签 + 地点 + 建议 自动生成 IPTC 关键字。
- **iOS 伴侣 V0.4+。** 下拉刷新、下滑关闭、快速标注的触感反馈、
  本地相册导入 (除了从服务器同步)。

## 安全与隐私

PixCull 默认本地优先。`serve_demo.py` 只绑定 `127.0.0.1`;LAN 部
署由 `PIXCULL_API_KEY` 环境变量设置 `X-PixCull-API-Key` 头进行
控制。

完整威胁模型和漏洞披露政策见 [SECURITY.md](SECURITY.md)。
TL;DR:可信本地用户,不可信图像输入 (Pillow 钉在 ≥ 10.2);无遥
测;可选的 DeepSeek 调用走的是 *你的* token,我们绝不代理转发。

## 参与贡献

详见 [CONTRIBUTING.md](CONTRIBUTING.md)。欢迎 PR;欢迎报 bug
(用 issue 模板);最容易上手的几个 PR 类型在贡献指南里。

## 协议

[MIT](LICENSE)。可商用、自由 fork、欢迎 PR。

## 作者

PixCull 始于一个简单想法:不要再花一个晚上在 Lightroom catalog
里挑片。十八个月、无数个小 commit 之后,它变成了我刚摸相机时就
希望存在的 AI 选片工具。MIT 开源,让下一个摄影师不用再从头造一遍。

— [@ChrisChen667788](https://github.com/ChrisChen667788) · [ModelScope @haozi667788](https://www.modelscope.cn/profile/haozi667788)
