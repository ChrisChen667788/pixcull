# v0.12 charter — Pro motion + interaction depth (Thesis B)

## 上下文(v0.11 release 后)

v0.11 closed v0.10's biggest infrastructure debts: real distribution
pipeline ready, goldenset builder shipped, WebRTC LAN signaling in
place, license CLI minting tier-aware tokens, marquee + scrubber +
hero-reveal landed.  `docs/DESIGN-AUDIT-2027Q1.md` scores the
average at 4.3 / 5 (up from 4.0).

But four gaps remain:

1. Keyboard bindings are still hard-coded
2. Lightbox runs single-viewport (no second monitor)
3. Inspector reads but never writes back to V3 training
4. License CLI exists but the payment funnel doesn't

v0.12 main theme: **"Pro motion + interaction depth — push every
remaining surface to Pixelmator / Affinity / DaVinci ceiling."**

## v0.12 工作范围

### P0(必须做)

#### v0.12-P0-1 · 模块化键盘快捷键自定义(Raycast 级)
**估时**: 2 周

- `/settings/shortcuts` 完整 GUI:可视化冲突检测、reset to defaults、
  import/export JSON、per-surface 作用域(grid / lightbox / inspector
  互不污染)
- `pixcull/shortcuts.py` — registry + persistence
- 持久化到 `~/.pixcull/shortcuts.json`,跨 run 生效

#### v0.12-P0-2 · Lightbox 全屏 power-mode + multi-monitor
**估时**: 1.5 周

- 第二屏 reference / first-pass 大图 + 主屏 grid
- `window.open` + `BroadcastChannel` 双向同步;关掉副屏不破协作状态
- 副屏自带 5-axis attribution preview (vibe with v0.13-P0-1 heatmap)

#### v0.12-P0-3 · Inspector 直接编辑评分 + 实时回写 V3
**估时**: 1.5 周

- 在 inspector chip 上拖滑块改 rubric → 立即更新 score_final
- 触发 active-learning 队列 + active-learning v2 (v0.11-P1-4) reward signal
- 写入 annotations.jsonl 时附 `model_decision_before` 字段供 hard-example mining

#### v0.12-P0-4 · 商业化第二步:Stripe / 微信支付 channel 接入
**估时**: 1.5 周

- v0.11 license CLI 的 self-serve 流:`pixcull.dev/upgrade` →
  Stripe checkout / 微信扫码 → 邮件下发 license JSON
- 不上 dashboard(纯交付,无续费 UI);
- Webhook endpoint 接收 payment.succeeded → 触发 issue_license.py
- 通用 `scripts/issue_license_from_webhook.py` 监听 Stripe / WeChat

### P1(应该做)

#### v0.12-P1-1 · Drag-and-drop 重排 buckets / portfolio order
**估时**: 1 周

HTML5 drag API + 触屏 long-press,iPad 一致

#### v0.12-P1-2 · Inspector "compare with neighbor" 实时分屏
**估时**: 1 周

当前照片 vs 同 burst 的另一张,inspector 一键切两栏

#### v0.12-P1-3 · Lightbox EXIF / histogram / focus point overlay
**估时**: 4 天

按 `H` 切换;读已有 EXIF cache,不重新解码

#### v0.12-P1-4 · 触觉反馈 / haptic on iOS Companion
**估时**: 3 天

keep / cull 切换走 `UIImpactFeedbackGenerator.medium`;符合 Apple HIG

#### v0.12-P1-5 · Onboarding 3D motion 续集
**估时**: 1 周

- v0.11-P1-5 已经做了 /upload + /history reveal;v0.12 补上
  annotation-modal 的 "rubric explainer" 3D card flip(首次开 modal 触发)
- 持久化 `localStorage["pixcull_seen_rubric_intro"]`

### P2(锦上添花)

#### v0.12-P2-1 · Vision Pro / visionOS 的空间 lightbox(spike,3 天)
研究投入;不一定 ship

#### v0.12-P2-2 · PT / NL / TR / RU / AR 翻译(1 周)
继 v0.11-P2-2 DE/FR/IT 之后,扩充到 13 种语言

#### v0.12-P2-3 · DESIGN-AUDIT-2027Q2 + v0.13 charter(3-4 天)

## 不做的事(scope discipline)

- **不上 dashboard**:license issuer + webhook + 邮件下发就够
- **不重写 ML**:rescorer v3 留给 v0.13 退役 / v1.0 大改
- **不引入 React / Vue**:vanilla JS 撑得住
- **不上 cloud 备份**:本地优先承诺
- **不做 Android Companion**:iOS 一直追平 web 就够

## 验收标准

v0.12 release 完成的标志:

- `/settings/shortcuts` 可视化重映射,所有 ≥ 2 槽位
- 第二屏 lightbox 跑通(双屏同步零拖延)
- Inspector 改分 → V3 训练队列收到 reward signal
- 支付通道 self-serve(Stripe + 微信至少一个)
- Compare-with-neighbor 分屏 + EXIF/histogram overlay 落地
- iOS Companion 触觉反馈
- DESIGN-AUDIT-2027Q2 起草 + v0.13 charter

## 建议外部资源 / 灵感参考

- **Raycast** — keyboard customisation 标杆
- **Lightroom Classic Second Window** — 双屏 reference 标杆
- **DaVinci Resolve Color page Inspector** — Inspector 直接编辑标杆
- **Stripe Atlas** — 商业化 stub / pricing tier 设计参考
- **Apple HIG (haptics)** — UIImpactFeedbackGenerator best-practices

## 建议执行顺序(预计 5-7 周)

| 顺序 | 任务 | 估时 | 理由 |
|---|---|---|---|
| 1 | **P0-1** Keyboard customisation | 2 周 | 独立 scope, foundation for other slices |
| 2 | **P0-3** Inspector direct-edit | 1.5 周 | 复用现有 inspector 逻辑 |
| 3 | **P0-2** Multi-monitor | 1.5 周 | BroadcastChannel + window.open spike |
| 4 | **P0-4** Payment channel | 1.5 周 | 等 Stripe / 微信支付 SDK |
| 5 | **P1-1** Drag-reorder | 1 周 | independent |
| 6 | **P1-2** Compare neighbor | 1 周 | 复用 burst-aware compare logic |
| 7 | **P1-3** EXIF overlay | 4 天 | 复用 exif_audit cache |
| 8 | **P1-4** iOS haptic | 3 天 | Swift only — independent path |
| 9 | **P1-5** 3D motion continuation | 1 周 | finish v0.11-P1-5 third piece |
| 10 | **P2-x** | 视情况 | 收尾 + v0.13 scoping |

---

charter timestamp: 2027 Q1(v0.11 release 后立即起草)
expected start: v0.11.0 release tag 推送后
expected duration: 5-7 周(v0.12 release 2027 Q2 mid)
predecessor: docs/ROADMAP-v0.11-charter.md
related: docs/DESIGN-AUDIT-2027Q1.md(v0.12 的依据)
