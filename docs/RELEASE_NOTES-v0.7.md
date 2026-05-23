# PixCull v0.7 — UI/UX 收尾 + 大批量可用性 + LR-parity

**Release date**: 2026-05-23
**Charter**: [docs/ROADMAP-v0.7-charter.md](ROADMAP-v0.7-charter.md)

After v0.4 → v0.6 三轮 UI/UX 重做(design tokens · LR Library
sidebar · LR Develop Inspector · LR Loupe filmstrip · 设计 token
统一 · drag-reorder buckets · hold-Space cheat sheet),v0.7 主线
是 **"把最后几面 demo-look 收尾 + 大批量稳得住 + LR-parity 补齐 +
风格 clone + tethered live"**。打开 `/results/<run>` 第一眼应该
完全看不出这是单文件 vanilla JS 工程。

## ✨ Highlights

### A/B 比较窗(cmpModal)LR Compare-style 重设计
对称双图布局 + 中央分隔条可拖、像素读数 overlay、design-token
meta-line、`.pill` 决策按钮、移动端 swiper 上下叠加。

### Annotation rubric modal 重设计
`★★★★★` 视觉星条(可点击 + 半星)、维度 hint 用 inline pill、
顶部进度条、cull-reason 内嵌、Tab 换维 + 1-5 直接打星 + Enter 提交。

### 5k+ 张大批量稳定性 audit
LocalStorage → IndexedDB 适配层、MutationObserver throttle、自适应
缩略图懒加载 rootMargin、新增 `/admin/perf` 调试页、内存基准线。

### Loupe RGB readout
Lightbox 按 `Z` 进 1:1,光标位置浮 R/G/B/Hex/Y 读数(canvas 取样,
零服务端往返)。

### Inspector mobile bottom-sheet
≤640px 时 info-pane 变 LR Mobile-Library 风格抽屉:140px peek + 80vh
展开 + scrim + drag handle。状态共享同一 `pixcull_inspector_state`
localStorage。

### 视图预设 v2 — starter presets + JSON import / export
4 个内置 starter("★ 起 · 仪式 only" / "废片二审" / "连拍峰值 only" /
"高置信 keep"),JSON `pixcull.view_presets/v1` schema,跨 run / 浏览器
迁移。

### 客户分享链接 `/share/<run>/<token>`
Token-gated 只读 HTML 页(`secrets.token_urlsafe(16)`),只展示 keeps
+ 摄影师 logo + 客户姓名水印。无需客户安装 PixCull。`X-Robots-Tag
noindex,nofollow` + private Cache-Control。

### 风格 clone V1
新模块 `pixcull/style/clone.py`:median-of-axes profile + scene
penalty。给 5-20 张精修参考样本,学摄影师的风格中心 → 下次同类活动
跑 PixCull 时,把"和你过去风格不像"的片子降分。Inspector 加 4-tier
颜色编码 "风格距离" 徽章,新增 "🎨 像我风格的优先" 排序。Phase 2
(CLIP)留 v0.8。

### Tethered live scoring
监听文件夹 + 现场实时分析。`/tether` 控制面板 + 2s 轮询的 status
cards + 新片落地 `<3s` 出现在 grid。后端复用既有 P2.2 模块,
top-level routes 跳过 `/api/v1` auth gate 简化控制面板访问。

### Sparkle 自更新基础设施
`scripts/build_appcast.py`(Sparkle 2.0 EdDSA appcast 生成器)+
release schema(`docs/sparkle/releases.example.json`)+ 完整 macOS
signing/notarization cookbook(`docs/macos-signing.md`)。
**Note**: 实际签包 + 发布需要 Apple Developer ID($99/年)——
infra 已就位,等申请到 cert 即可走流程。

### 历史时间线 `/history`
扫 `_DEMO_ROOT` 列出所有跑过的 run,卡片网格,decision 三段进度条
(keep/maybe/cull),源标签(scan/upload/event),mtime 排序。
Upload-page footer 加 🕒 历史 入口。

## 🧪 Tests

| 模块 | 通过 |
|---|---|
| `tests/test_cli_audit_smoke.py` | 19/19 |
| `tests/test_style_clone.py` (新增 v0.7-P2-1) | 10/10 |
| `tests/test_build_appcast.py` (新增 v0.7-P2-3) | 6/6 |
| `tests/test_5k_scale.py` | 2/2 |
| **合计** | **37/37** |

## 📁 New files

```
docs/ROADMAP-v0.7-charter.md          (v0.4 charter 对仗)
docs/RELEASE_NOTES-v0.7.md            (this file)
docs/macos-signing.md                 (Sparkle + codesign + notarytool cookbook)
docs/sparkle/releases.example.json    (Sparkle appcast schema sample)
pixcull/style/__init__.py             (style-clone package)
pixcull/style/clone.py                (median-of-axes profile + distance)
scripts/build_appcast.py              (Sparkle 2.0 appcast generator)
tests/test_style_clone.py             (10 unit tests)
tests/test_build_appcast.py           (6 unit tests)
```

## 🛠 Commit chain (v0.7-P0 → v0.7-P2)

```
v0.7-P0-1  A/B 比较窗(cmpModal)重设计
v0.7-P0-2  Annotation rubric modal 重设计
v0.7-P0-3  5k+ 张大批量稳定性 audit
v0.7-P1-1  Loupe RGB readout in lightbox 1:1 mode
v0.7-P1-2  Inspector mobile 重做 — bottom-sheet
v0.7-P1-3  视图预设 v2 — starter presets + JSON import / export
v0.7-P1-4  客户交付分享链接 (/share/<run>/<token>)
v0.7-P2-1  style-clone V1 — learn personal-style profile from keeps
v0.7-P2-2  tethered live scoring UI + top-level routes
v0.7-P2-3  Sparkle auto-update infra + macOS signing cookbook
v0.7-P2-4  history timeline (/history)
```

## ⚠️ Breaking / Migration notes

None. v0.7 is purely additive — every existing route, localStorage
key, scores.csv column, and JSON schema is preserved.  Earlier
runs continue to open in `/results/<run_id>` with the v0.6 UX;
upgrading hydrates new affordances (drawer state, presets v2,
style distances) without overwriting prior state.

## 🚀 Upgrade

```sh
git pull
# No new Python deps. No build step (zero-build vanilla JS).
# Restart the server:
python scripts/serve_demo.py
```

To get the new `/admin/perf` page or `/history` you only need to
restart the server — no DB migration, no cache invalidation.

## 🔮 Coming next — v0.8 preview

| 主线 | 内容 |
|---|---|
| 分发 | macOS DMG + Sparkle auto-update **shipping**(needs Developer ID)· Win MSI + Linux AppImage 签名 |
| 协作 | INFRA-3 真实落地:二摄 / 编辑同时标同一 run(Wi-Fi LAN) |
| 模型 | 风格 clone V2(CLIP embedding centroid + 余弦)· Rescorer V3 · DNG sidecar history |
| 国际化 | EN/JA 双语界面 + 切换器 · 行业 case study(婚礼 / 体育 / 写真) |

Full v0.8 charter to land separately.
