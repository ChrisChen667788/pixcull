# v0.10 charter — From solo to studio · 工作室深度 + ML 复评 + Mobile 对齐 + 分发成熟

## 上下文(2026-08-XX,v0.9 收尾后)

v0.4 → v0.9 共 47 个 slice、6 个 charter,把 PixCull 从"单人脚本"
变成"看起来 iconic 的本地优先 AI 选片工具":

- **v0.4–v0.6**(基础设施):design tokens · LR-grade UI · Inspector ·
  buckets · 视图预设 · 大批量稳定性
- **v0.7**(中型新功能):A/B 比较 · annotation modal · loupe RGB ·
  Inspector mobile · 客户分享链接 · 风格 clone V1 · Sparkle infra ·
  /history
- **v0.8**(分发 + 协作 + 多语):i18n · LAN 协作 (pull-only) · CLIP V2
  风格 · 短链 + QR · EN + JA · 结构化导出 · ModelScope v0.8
- **v0.9**(brand + 标志性时刻 + 键盘优先 + craft polish):signature
  motion / hero reveal / brand identity / Cmd+K / 作品集 /share /
  card hover + modal 差异化 / multiplayer presence / executive PDF /
  AI 视觉化 / iPad 手势 / light theme V2 / 列表式 admin perf / 5 个新
  empty-state SVG

v0.9 的 design-audit 自我检验已通过 ——"watch-worthy 的 2 秒 reveal
moment、Cmd+K 命令面板、brand gradient 横跨所有 surface、客户拿到的
是作品集而不是 dashboard、iPad swipe / pinch 流畅"全部达成。

但 v0.9 的"不做的事"里挂了三笔账,加上 v0.8-P0-2d 一笔账,v0.10 该
偿还:

1. **LAN 协作只是 pull**(v0.8-P0-2d 推迟)—— 两人改同一张照片时,
   "另一人晚到的标注覆盖我刚标的"只能靠人眼 + 标"⚠ 冲突"chip 提醒,
   缺真正的 last-write-wins 合并 / 用户可选 winner 的 UI。
2. **ML 内核 4 个版本没动过**—— 风格 V2 (CLIP centroid) 加权 0.7
   *混进了 V1 的 axis-MAD 距离,但从来没在多摄影师 goldenset 上跑过
   recall@k benchmark。rescorer 也仍是 v0.6 训练的版本。
3. **iOS Companion 没追上 v0.9 web**—— presence / 作品集 share /
   executive PDF / brand gradient 数字 / iPad swipe — iOS 都还在
   v0.8 状态。
4. **分发已基础就位但实际没运行**—— v0.8-P0-3 brew tap 和 v0.8-P1-2
   Win MSI / Linux AppImage 脚本都准备好了,等用户的 Apple Developer
   / SignPath / GPG 凭据生效后跑通第一个 release。

v0.10 主线:**"从 solo 到 studio — 工作室级团队工作流 + ML 复评 +
mobile 对齐 + 分发成熟"**。

## 诊断 — 为什么这一轮重点是"专业深度",不是"视觉"

v0.9 把视觉/IxD 拉到了 Linear / Stripe / Notion 水平。再继续在
brand / motion / 排版上压能做的边际回报递减(用户已经在截图分享了)。

下一轮回报最高的是**专业摄影工作室的真实工作流**:

- **二摄 + 主摄 + 编辑** 同一个事件互相覆盖标注 — v0.8 LAN 只能"看
  到对方刚改了什么",看不到"对方为什么改"+ 无 conflict resolution
- **多场拍摄跨日审计 ML 质量** — 当前没有一种"上一版 rescorer 比
  这一版差 1.2% recall@5"的客观证据
- **iOS 用户拿到的体验 1 个版本落后**—— 摄影师婚礼现场用 iPad 看
  二摄实时反馈,但 v0.9 的 presence 还没在 iOS 渲染
- **想 brew install** 装 PixCull 的用户从 2026 Q3 起就在 GitHub
  issues 里追问,但我们等 Apple Developer 凭据完成

这四件事都是"产品看起来漂亮 → 产品在真实工作室里运转"的临界跨越。

## v0.10 工作范围

### P0(必须做)

#### v0.10-P0-1 · LAN 协作双向推 + 冲突解决 UI ✅
**估时**: 2 周 · **实际**: 同次 commit · **已发布**

完成 v0.8-P0-2 charter 里推迟的 **v0.8-P0-2d**:

- **双向推送**:collaborators 端的 annotation edit 通过同一个 event
  token 推回 host(POST `/api/v1/sync/event/<token>/push`)— host 再
  fanout 给其他 peers。host 失联时,collaborators 之间 mesh 直连
  fallback。
- **真正的 conflict resolution UI**:不再只是 ⚠ chip。当 local 编辑
  时间 > incoming remote 时间 + decision 不同,弹一个 `.conflict-modal`
  并排显示两个版本(本地决定 / 远程决定 + 各自标注人 + 时间),用户
  pick winner 或选"保留两边"(产生新 row 历史)。复用 v0.9-P1-1 的
  `.modal-action` 视觉。
- **离线编辑队列**:网络中断时,本地修改进 `IndexedDB[pixcull_offline_queue]`,
  重连后批量 flush + 命中 conflict 的进 UI 队列等用户处理。

#### v0.10-P0-2 · mDNS auto-discovery for LAN sync ✅
**估时**: 4-5 天 · **实际**: 同次 commit · **已发布**

完成 **v0.8-P0-2c**:WLAN 内部 zero-config 发现 host。host 端通过
`zeroconf` 库广播 `_pixcull-sync._tcp.local.` 服务,name 字段 =
event_id + label;collaborator 打开 results 页时弹一个 toast "在
LAN 内发现 5 个协作会话 → 点击加入",省去"复制粘贴 URL / 扫 QR"。
向后兼容:URL 仍然有效(出差远程协作场景)。

#### v0.10-P0-3 · ML 复评:rescorer V3 + 风格 V2 benchmark
**估时**: 2 周

**rescorer V3**:在累计的 22k 标注数据(v0.6 训练 + 之后所有人工
标注)上重训 GradientBoosting。引入 v0.7+ 之后才有的特征(
burst_peak signal、ICC profile mismatch、wedding moment confidence、
EAR/blink),目标 recall@5 ≥ baseline + 3%。

**风格 V2 benchmark**:在 5 位多元摄影师 goldenset (婚礼/野生/
风光/活动/人像)上跑 V1 (axis-MAD)、V2 (CLIP centroid)、V1+V2 加权
(λ ∈ {0.0, 0.3, 0.5, 0.7, 1.0}),产出 `docs/STYLE-V2-BENCHMARK.md`
(类似 v0.7-P2-1 doc 结构)。客观确认默认 λ 应该是 0.3、0.5 还是
0.7。最终可能调默认值。

输出物:
- `docs/RESCORER-V3-EVAL.md` — confusion matrix + per-axis recall +
  baseline diff
- `docs/STYLE-V2-BENCHMARK.md` — λ 表格 + 各 vertical 推荐值
- 自动化 `python scripts/eval_rescorer.py` + `eval_style_v2.py`
- CI:rescorer 不能比上一版 recall@5 跌 > 1%,自动 fail

#### v0.10-P0-4 · iOS Companion 追上 v0.9
**估时**: 1.5 周

让 iPad / iPhone 端的 PixCullCompanion 渲染 v0.9 在 web 上做的所有
事情:

- **presence pill** in toolbar(复用 LAN event token + 30s heartbeat)
- **作品集 share view**(SwiftUI 重做 Card 网格 + brand gradient
  serif title + 章节分组)
- **executive PDF 预览**(in-app PDFKit viewer,导出按钮 share-sheet)
- **brand gradient 数字** in score badge + rubric stars
- **score radial progress** + 6-axis sparkline
- **iPad swipe / pinch / tap-zoom** in PhotoDetailView(SwiftUI
  gesture modifiers,与 iOS Safari `<lightbox>` 类似但是 native)

iOS V0.6 → V0.7 跨越,本 charter 完成 V0.7 release。

#### v0.10-P0-5 · 跑通真实分发(macOS + Win + Linux)
**估时**: 1 周(等 Apple Developer / SignPath / GPG 凭据)

- macOS:用户完成 Apple Developer enrollment → 跑
  `scripts/release_macos.sh 0.10.0` → 推到 `homebrew-pixcull` tap →
  确认 `brew install --cask pixcull` 成功 + Sparkle 自更新通道生效
- Windows:申请 SignPath OSS approval → 配置项目 → 跑
  `scripts/release_windows.sh 0.10.0` → 拿到签名 MSI + 上 GitHub
  release → 验证 SmartScreen 不弹 yellow
- Linux:生成 GPG release key → 公钥进 `docs/pixcull-releases.asc` →
  跑 `scripts/release_linux_appimage.sh 0.10.0` → AppImageUpdate
  delta 升级链路验证

输出物:
- v0.10.0 release tag 三个签名 artifact + 统一 appcast.xml
- README.md 加 brew / MSI / AppImage 安装说明 + GPG fingerprint
- launch post Phase 2(分发完成)

### P1(应该做)

#### v0.10-P1-1 · 工作室多账户 profile + 团队 taste 合并
**估时**: 1 周

v0.8-P-UX-12 做了 single-user taste profile。v0.10 加 multi-user:

- 同一台 macOS 上多个 user profile(光栅 keyboard switcher,zh-CN
  label "档案"),每个 profile 各自的 face library + cull-reason
  history + axis weights
- 主摄 head-shooter override:在 LAN event 内,head-shooter 的决定
  优先级 > 其他 collaborators(用 conflict-resolution 模态时直接
  采用 head 的版本,加 audit 行)
- 团队 taste profile aggregation:多个 user profile 合并出"工作室
  风格"基线,可在 `/admin/team_taste` 看到 axis-weight 离散度,
  发现"小李偏好高对比、小陈偏好低 saturation"等共识缺口

#### v0.10-P1-2 · 实时鲁棒性:连拍组流式更新
**估时**: 4-5 天

当前 tethered live 是 ~2 秒每张 verdict;P1-2 增加"连拍组流式更新":
新照片进来时,如果落进已有的 burst cluster,立即重跑该 cluster 的
peak-picker 而不是等整批跑完。Inspector 的 burst-peak badge 实时
变化,反映"最佳一张正在转移"。

#### v0.10-P1-3 · Notion-style slash menu
**估时**: 1 周

Cmd+K 已经覆盖了 grid + lightbox 的全局命令。P1-3 加 inspector pane
内的 `/` slash menu:在 advice 文本框里按 `/`,弹出 contextual
options(/rubric refresh、/explain 重新拉 DeepSeek、/cite [canon-id]
插入正典引用、/note 加私 note)。继续 keyboard-first 路线。

#### v0.10-P1-4 · Audio-photo sync(婚礼现场 mic input → ceremony moment)
**估时**: 1.5 周

实验性 feature:婚礼现场 iPhone / Apple Watch mic 录环境音,通过
v0.8 P0-2 LAN event token 流到 PixCull;PixCull 端通过 WhisperKit
(local STT)+ keyword spotting 实时识别"vows / ring exchange /
kiss"短语,把对应时间戳的照片自动 boost 进 `ceremony` 章节。
opt-in,默认关。

#### v0.10-P1-5 · KO + ES 翻译
**估时**: 1 周

继续 v0.8-P0-1 / P1-4 i18n。KO(韩国摄影师社区在小红书有显著占比)
+ ES(拉美 + 西班牙婚礼摄影师)。POEditor / Crowdin 流程,共建翻译
人员的 GitHub-issue-based PR 流。

### P2(锦上添花,视情况)

#### v0.10-P2-1 · PWA 模式
**估时**: 1 周

`<link rel="manifest">` + service worker + IndexedDB 缓存 +
file-system-access API。用户不安装 .app 也能在 Chrome / Safari /
Edge 访问 `pixcull.app`(我们的域名 / GitHub Pages 部署)+ 拖照
入页 + 跑出结果。"零安装试用"路径。注意:CLIP / rescorer ONNX 模
型要从 CDN 加载(~120 MB),首次启动慢,有进度条。

#### v0.10-P2-2 · 摄影正典 v2 — 加 30 条
**估时**: 4-5 天

v0.4 的 advice canon library 是 ~80 条名言 / Adams · HCB · Bresson
风格引用。v2 加 30 条,扩展到当代(Solo Sokolova / Andrew Suryono /
2020s+ 婚礼摄影师 / 川西现代风光)。Inspector 的 canon-cite chip 类
型更丰富。

#### v0.10-P2-3 · Crash reporter + opt-in 遥测
**估时**: 3-4 天

Sentry SDK(免费 100k events/月,够单人 OSS)集成。default off,
设置面板 + 首次启动 prompt 让用户选 "share / minimal / off"。
重点收集 ONNX runtime crash + Sparkle update failure(分发成熟期
最痛的两个);**绝不**收集照片内容 / 文件名(只 stack trace + 系统
metadata)。

#### v0.10-P2-4 · DESIGN-AUDIT-2026Q4 自检 + v0.11 charter 起草
**估时**: 2-3 天

v0.10 完成后做下一轮自我审计 docs/DESIGN-AUDIT-2026Q4.md(对照同样
那批参考产品看哪里仍然差距),写 v0.11 charter 草稿。本 charter 的
延续机制,每个 release 留 last 2-3 天给"下一程 scoping"。

## 不做的事(scope discipline)

- **不引入云端账户**—— 本地优先是品牌承诺,v0.10 的"工作室多账户"
  仍然全本地,不上 server
- **不重写后端为 FastAPI / Django**—— `http.server` + `serve_demo.py`
  够用,跑得动 5k+ 张 (v0.7-P0-3 已 audited)
- **不引入 Electron / Tauri**—— PyInstaller + py2app + linuxdeploy
  已稳定,Electron 会 +200 MB bundle
- **不引入实时协作的 WebSocket / WebRTC**—— v0.10-P0-1 还是 polling
  + LAN HTTP,只是双向。原因:WebRTC 让 LAN-only 承诺变模糊(STUN /
  TURN 走外部 server)。下一轮再评估
- **AI 不引入 cloud LLM 强依赖**—— DeepSeek 仍是 optional;v0.10
  里的 audio-photo sync 用 local WhisperKit,不发音频出机
- **不为 PWA 砍 native app**—— PWA 是 P2 "零安装试用"路径,不是替代

## 验收标准

v0.10 release 完成的标志:

- **两人同时改同一张照片**,网络断 + 重连后,UI 弹 conflict modal
  让用户挑赢家,没有 silent 覆盖
- **LAN 中两台 Mac 打开 results 页**,5 秒内互相发现对方,不需复制
  URL
- **rescorer V3 在 multi-vertical goldenset 上 recall@5 ≥ baseline +
  3%**,CI 自动阻止 < -1% 的回归
- **iOS Companion v0.7** 支持 presence / brand gradient / 作品集
  share / executive PDF / iPad gesture
- **`brew install --cask pixcull` 可用**,Sparkle 自更新生效
- **`scripts/release_windows.sh` + `release_linux_appimage.sh` 都
  跑通真实 release**,GitHub 上有 v0.10.0 的 .dmg / .msi / .AppImage
  三个签名 artifact
- **多档案 user profile** 可切换,每档案独立 face library
- **`/admin/team_taste`** 显示工作室 axis-weight 离散度
- 文档落地:`RESCORER-V3-EVAL.md`、`STYLE-V2-BENCHMARK.md`、
  `WINDOWS-SIGNING-SETUP.md`、`LINUX-SIGNING-SETUP.md` 全部公开

## 建议外部资源 / 灵感参考

- **Figma multiplayer** —— 双向 presence + conflict resolution UI
  标杆(光标 + selection + 实时 cursor)
- **Linear branched issues** —— conflict 时两个版本并排
- **Replicate / Hugging Face evaluate** —— ML benchmark doc 样板
- **Notion AI** —— slash menu inline AI 调用
- **WhisperKit** —— Apple Silicon 本地 STT 唯一可选
- **Tailscale** —— LAN auto-discovery + zero-config 标杆(不直接
  copy 实现,但学其 UX)
- **homebrew / brew tap** —— Cask convention 标杆
- **Sparkle 2 docs** —— multi-platform 自更新 channel 实操

## 建议执行顺序(预计 6-8 周)

| 顺序 | 任务 | 估时 | 理由 |
|---|---|---|---|
| 1 | **v0.10-P0-5** 真实分发 | 1 周 | 解锁所有用户安装路径 — 越早越好,凭据到位就跑 |
| 2 | **v0.10-P0-1** LAN 双向 + conflict UI | 2 周 | v0.8 的最大账单,真实工作室刚需 |
| 3 | **v0.10-P0-2** mDNS auto-discovery | 4-5 天 | 加在 P0-1 之后顺手做,共用 zeroconf 依赖 |
| 4 | **v0.10-P0-3** ML 复评 | 2 周 | 客观证据 — 越早跑 benchmark,后续 calibration 时间窗越宽 |
| 5 | **v0.10-P0-4** iOS Companion 追平 | 1.5 周 | 等 web v0.9 stable + LAN P0-1 稳定后做,共用 token 协议 |
| 6 | **v0.10-P1-1** 工作室多账户 | 1 周 | P0 完成后顺手 — 多账户 + LAN 是一对儿 |
| 7 | **v0.10-P1-2** 连拍流式 | 4-5 天 | 独立小项 |
| 8 | **v0.10-P1-3** Slash menu | 1 周 | 体验 polish |
| 9 | **v0.10-P1-4** Audio sync(实验性) | 1.5 周 | 高风险高回报,留 P1 末尾 |
| 10 | **v0.10-P1-5** KO + ES | 1 周 | 与 i18n 流程稳态后再扩 |
| 11 | **v0.10-P2-x** | 视情况 | 收尾 + 下一轮 scoping |

---

charter timestamp: 2026-08-XX(v0.9 ship 后立即起草)
expected start: v0.9 release tag 推送后
expected duration: 6-8 周(v0.10 release Q1 2027)
predecessor: docs/ROADMAP-v0.9-charter.md
related: docs/DESIGN-AUDIT-2026Q3.md(v0.9 的依据;v0.10 会写新一份)
