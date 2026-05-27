# v0.11 charter — Studio-grade infrastructure · ML 落地 + 实时协作 + 商业化前置

## 上下文(2026 Q4 之后)

v0.4 → v0.10 共 57 个 slice、7 个 charter,把 PixCull 从单人脚本变成
"看起来 + 能用 + 工作室级协作齐备"的本地优先 AI 选片工具:

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
- **v0.10**(从 solo 到 studio):LAN 双向 + 冲突 UI · mDNS auto-discovery
  · ML eval harness + benchmark · iOS Companion 追平 · 工作室多账户
  + 主摄 override · 连拍流式 · slash menu · audio-photo sync · KO/ES
  i18n · PWA mode · 摄影正典 +30 · Sentry opt-in

`docs/DESIGN-AUDIT-2026Q4.md` 自检确认 v0.10 把"工作室深度"+ "ML 复评
infrastructure" + "iOS 对齐" + "分发脚手架"全部就位 —— 平均评分从
Q3 的 **1.4** 跳到 Q4 的 **4.0**(满分 5)。

但有三笔历史账还在挂着:

1. **真实分发还在等凭据**:`release_*.sh` 三个脚本 production-ready 半年
   了,但 brew tap + signed MSI + signed AppImage 都因为外部凭据(
   Apple Developer / SignPath / GPG)没真跑过第一遍
2. **ML 评估 harness 只在合成数据上跑过**:`scripts/eval_rescorer.py` +
   `eval_style_v2.py` 框架就绪,但真实 22k+ 标注还没集成进 goldenset
3. **远程协作仍靠 URL 黏贴**:同 LAN 已彻底 zero-config 了,但主摄在
   工作室 + 编辑在家的远程场景,还是要 iMessage 复制粘贴长 URL

v0.11 主线:**"Studio-grade infrastructure — 把脚手架变成真正在跑的
production 流"**。

## 诊断 — 为什么这一轮重点是"落地"+"商业化前置"

v0.10 已经把"工作室能用"的功能层做完了,但每个功能都还差最后一步:
分发只到本地包未到端用户、ML eval 只到 harness 未到真训练、协作只
到 LAN 未到 WAN、多账户只到 profile 未到 license 派发。

这种"差一公里"的 backlog 累积下去会让产品看起来停滞,即便单 commit
节奏没慢。v0.11 不做新主题,**把所有挂账还完**。同时把商业化前置工
作(license CLI、Tier 区分、Studio plan 收费 stub)铺好,为 v1.0
release 做准备。

## v0.11 工作范围

### P0(必须做)

#### v0.11-P0-1 · Goldenset builder + V3 rescorer retrain
**估时**: 2 周

- `scripts/build_goldenset.py` 工具脚本:扫描 `out_wedding_eval/` +
  per-user runs/ 下所有 `rubric_human_labeled=True` 行 +
  `annotations.jsonl` 末次决定,合并为 `goldenset/v0.11/ground_truth.csv`
- 跑 `train_rescorer.py` 重训,产物 `models/rescorer_v3.joblib`
- 跑 `eval_rescorer.py` 对比 v2:目标 recall@5 ≥ baseline + 3%
- 跑 `eval_style_v2.py` 在 multi-vertical goldenset 上确定 λ 默认
  (consume v0.10-P0-3 的 benchmark 数据)
- 默认 λ 调整(如果 benchmark 表明 0.3 不再是最优)
- CI 接入 `ci_rescorer_regression.py` —— PR-on-v3 要通过 gate

输出物:`docs/RESCORER-V3-RESULTS.md`(eval markdown)+ updated
`STYLE-V2-BENCHMARK.md`(实际跑分)+ `models/rescorer_v3.joblib`
in release artifacts。

#### v0.11-P0-2 · 真实分发首跑(brew tap + signed MSI + signed AppImage)
**估时**: 1-2 周(其中大半是等凭据 + 用户操作)

- macOS:用户完成 Apple Developer enrollment → 跑
  `release_macos.sh 0.11.0` → 推 `homebrew-pixcull` tap → 确认
  `brew install --cask pixcull` 成功
- Windows:申请 SignPath OSS approval → 跑 `release_windows.sh` →
  上 GitHub release → 验证 SmartScreen 不弹 yellow
- Linux:生成 GPG release key → 跑 `release_linux_appimage.sh` →
  AppImageUpdate 增量升级验证
- v0.11.0 release tag 三个签名 artifact + 同一份 appcast.xml
- README 更新安装段落 + GPG fingerprint
- 一份 "launch v0.11" 推广帖(类似 v0.8 的 "Why I built this" v2)

#### v0.11-P0-3 · 远程 LAN 协作 — WebRTC over mDNS
**估时**: 2-3 周

v0.10-P0-2 在同 LAN 用 mDNS 解决了 zero-config,但跨 LAN 仍要靠 URL
黏贴。v0.11 走"Tailscale-lite 自己实现"路线:

- mDNS service announcement 带上节点的 STUN/ICE 候选地址(用
  google STUN 公共服务,免费)
- WebRTC datachannel 替代 5s HTTP polling — 真正的实时
  presence + sub-100ms conflict resolution
- 同 LAN:直接 RTCDataChannel(零延迟);跨 LAN:STUN/ICE
  穿透 NAT(~80% 成功率,reasonable 默认)
- ICE 失败 fallback 到现有 HTTP polling(图 not WebRTC fail 就
  break collaboration)
- Privacy 保证:STUN 仅用于公网 IP 发现,不流量,不上传内容

实操难度:WebRTC 完整 ICE/SDP 在 vanilla JS 是 ~400 行;
Python aiortc 服务端 ~150 行。建议先做 spike(2-3 天)确认可行性
再正式 commit。

#### v0.11-P0-4 · License delivery CLI — 商业化第一步
**估时**: 1 周

为 v1.0 释出"Studio plan"做铺垫。即便目前还没收费,基础设施先就位:

- `scripts/issue_license.py` —— 生成 ed25519 签名的 license JSON
  (`{user_id, tier, expires_at, signature}`),tier 候选 `free` /
  `studio` / `team-5` / `team-20`
- `pixcull/license.py` —— 客户端校验 + 缓存 license
- 启动时检查 `~/.pixcull/license.json`,签名错或过期 → 退到 free tier
- Free tier 限制:单用户 profile;Studio tier 解锁多账户(v0.10-P1-1)
  + team taste aggregation
- 关键:**所有功能在 free tier 仍 100% 可用**(本地优先承诺) ——
  Studio tier 只解锁 multi-user 协作面 + 优先支持 + 商业 brand kit
- 暂不接入任何支付 channel(Stripe / 微信支付 v0.12 再上)

### P1(应该做)

#### v0.11-P1-1 · 拖动 timeline scrubber(lightbox)
**估时**: 1 周

DaVinci Resolve 灵感:lightbox 底部加一个 1px 高的 timeline 进度条,
按住拖动可在当前批次的所有照片间无缝 scrub(预加载相邻 ±5 张)。
婚礼摄影师查看连拍组的核心 micro-interaction;比 ←→ 翻页快 3x。

#### v0.11-P1-2 · 大批量 marquee select + 操作
**估时**: 1 周

当前必须单点 / shift-click 多选。v0.11 加 marquee:在 grid 空白处
按住拖框,松开后所有框内 cards 被选中,可批量打 keep/cull、
入桶、删除、导出。Lightroom Library 模块的标杆体验。

#### v0.11-P1-3 · 每 vertical λ 运行时覆盖
**估时**: 4-5 天

消费 v0.10-P0-3 的 style V2 benchmark 结果。当用户的 keep refs 中某
个 vertical 占比 ≥ 60%,自动用该 vertical 的推荐 λ(而不是全局
默认)。Inspector "视觉距离"chip 加个 ⓘ 显示当前 λ 来源。

#### v0.11-P1-4 · 主动学习 v2 — 对抗样本挖矿
**估时**: 1 周

当前 active learning(/api/v1/runs/<id>/next_to_label)按"4 个评分源
分歧度"排序。v0.11 加第二维度:从历史人工标注中挑出"模型预测最确定
但用户改了的"反例,优先复现这些边界。本地 hard-example mining。

#### v0.11-P1-5 · Onboarding 3D motion
**估时**: 1.5 周

v0.9 hero reveal 只在 /results 触发。v0.11 把"signature moment"概念
推广到 /(upload page)+ /history 时间线开场 + first-time
annotation modal 的"评分系统介绍"3D card flip。仍然 vanilla CSS +
prefers-reduced-motion 退化。

### P2(锦上添花)

#### v0.11-P2-1 · 一键 launch-PixCull dock 图标(macOS)
**估时**: 3-4 天

`release_macos.sh` 已经签 + 通知 + brew tap 就绪后,加一个一键
"Add to Dock + Login Items" Quick Action。Photographers 每天打开
3-5 次,值得 1 click 而不是 finder → Applications → drag。

#### v0.11-P2-2 · DE / FR / IT 翻译
**估时**: 1 周

继 v0.10-P1-5 KO + ES 后,把欧洲三大语言补全。POEditor 或 GitHub-
issue 翻译流程。

#### v0.11-P2-3 · DESIGN-AUDIT-2027Q1 + v0.12 charter
**估时**: 3-4 天

v0.11 完成后做下一轮自审,起草 v0.12 charter。预期 v0.12 会从
Thesis B / Thesis C(参考 docs/DESIGN-AUDIT-2026Q4.md §"v0.11
scoping")挑一个。

## 不做的事(scope discipline)

- **不做支付 channel**:license issuer 就位,支付 v0.12 再上
- **不重写 ML 训练 pipeline**:沿用 train_rescorer.py 的 sklearn
  pipeline + GradientBoosting,不上 PyTorch retrain
- **不引入 React / Vue**:vanilla JS 在 v0.10 已经撑过 14k 行 results.html
  + 2k 行新增,继续撑得住
- **不上 cloud 备份**:本地优先承诺,license 也只在本地校验
- **不做 Android Companion**:iOS V0.7 刚追平 web,Android 等 v0.12

## 验收标准

v0.11 release 完成的标志:

- **`brew install --cask pixcull` 真的能装**,Sparkle 自更新跑通
- **GitHub release v0.11.0 有三个签名 artifact**(.dmg / .msi /
  .AppImage)+ 一份合并 appcast.xml
- **rescorer V3 在真实 22k+ goldenset 上 recall@5 ≥ baseline + 3%**
- **WebRTC LAN datachannel** 替代了 5s HTTP polling,sub-100ms
  presence
- **license CLI 能发 + client 能校**,即便没人付费,基础设施就位
- **DaVinci-style timeline scrubber + marquee select** 在 lightbox/grid
- **/admin 看到 license tier 标签**("Studio plan · 5 users")
- 文档落地:`RESCORER-V3-RESULTS.md` 真跑分填进、
  `LICENSE-PROTOCOL.md` 写完、`DESIGN-AUDIT-2027Q1.md` 起草

## 建议外部资源 / 灵感参考

- **Tailscale** — mDNS + STUN/ICE 的 zero-config WAN 标杆
- **DaVinci Resolve** — timeline scrubber + media management UX
- **Lightroom Library** — marquee select + bulk ops 标杆
- **1Password** — license key delivery 流程参考
- **Stripe Atlas** — 商业化 stub / pricing tier 设计参考
- **WebRTC samples** (webrtc.github.io) — ICE 实现样板

## 建议执行顺序(预计 6-8 周)

| 顺序 | 任务 | 估时 | 理由 |
|---|---|---|---|
| 1 | **v0.11-P0-2** 真实分发 | 1-2 周 | 凭据到位就跑 — 任何一天都能 unblock 用户 |
| 2 | **v0.11-P0-1** Goldenset + V3 retrain | 2 周 | 真实 ML 数据落地 — v0.10 最大的 follow-through |
| 3 | **v0.11-P0-4** License CLI | 1 周 | 不阻塞,但越早越好 — v1.0 前置 |
| 4 | **v0.11-P0-3** WebRTC LAN | 2-3 周 | 高风险 spike,放后期 |
| 5 | **v0.11-P1-3** Per-vertical λ | 4-5 天 | 消费 P0-1 的 benchmark 数据,顺手做 |
| 6 | **v0.11-P1-1** Timeline scrubber | 1 周 | 独立小项 |
| 7 | **v0.11-P1-2** Marquee select | 1 周 | 独立小项 |
| 8 | **v0.11-P1-4** Active learning v2 | 1 周 | 复用 P0-1 的 goldenset |
| 9 | **v0.11-P1-5** Onboarding 3D motion | 1.5 周 | 体验 polish |
| 10 | **v0.11-P2-x** | 视情况 | 收尾 + v0.12 scoping |

---

charter timestamp: 2026 Q4(v0.10 release 后立即起草)
expected start: v0.10 release tag 推送后
expected duration: 6-8 周(v0.11 release 2027 Q1)
predecessor: docs/ROADMAP-v0.10-charter.md
related: docs/DESIGN-AUDIT-2026Q4.md(v0.11 的依据)
