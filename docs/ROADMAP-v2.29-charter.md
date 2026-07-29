# v2.29 — 毛玻璃设计系统(Frosted-Glass,范围采纳落地)

> 落地 DESIGN-AUDIT-2030Q4 的「范围采纳」判定:把散布全 UI 的 ~30 处 ad-hoc
> `backdrop-filter`(blur 2/4/6/8/10/12/20px + saturate 140/180% 各写各的)
> 系统化成**一种材质**,严格限定在 chrome/浮层——照片判读面零玻璃(v2.21
> Studio Neutral / ISO 3664 判色纪律),并补上全仓缺失的 a11y 兜底。

## Token(tokens.css)

- **`--glass-filter`**(panel 档):`blur(16px) saturate(130%)` —— 磨砂面板的
  可见 chrome 面。saturate 从旧 180% 收敛到 130%(2026 实践回撤;Apple 2026 也
  为可读性降低了 Liquid Glass 透明度)。
- **`--glass-scrim-filter`**(scrim 档):`blur(4px)` —— 模态背后的暗化幕布,
  轻、重绘便宜。
- **`--glass-edge`**:暗色 `inset 0 1px 0 rgba(255,255,255,.08)` 顶部高光
  (玻璃边);亮色主题覆盖为 `.65`(8% 白在近白膜上不可见,亮色玻璃靠更强白边
  成立,Apple 亮色材质同法)。
- **`@media (prefers-reduced-transparency: reduce)`**:三个 token 全部置 none,
  且磨砂面板强制回 `--chrome` 实底 —— glassmorphism 的核心可读性风险有了干净
  的一刀切兜底(此前全仓为零)。走 token 的意义正在于此:一处覆盖全局生效。

## 收敛(15 处 chrome 站点 → token)

- **Panel(7)**:header(20px/180%→token,+edge)· toast(+edge 入影栈)·
  cmp-header · cmp-rgb-readout · bulk-toolbar · shortcuts-hint(+edge)·
  kbd-cheat。其中 **cmp-header / cmp-rgb-readout / kbd-cheat 原底色是不透明
  `--chrome`——旧 blur 从来是 no-op**(不透明底挡住 backdrop);改为
  `color-mix(in srgb, var(--chrome) 78–88%, transparent)` 半透明膜后玻璃才真实
  生效(theme-aware,降透明度时被 !important 强制回实底)。
- **Scrim(7)**:share-url-modal · cmdk-modal(旧 10px+sat140 的重 scrim 统一
  为轻 scrim)· presenceModal · cmp-modal · shortcuts-modal · lightbox ·
  library-panel-backdrop。
- **刻意保留 3 处照片区微玻璃**(不 token 化、写进守卫 keeps):卡片决策字形
  (LR 式徽章)、卡片悬停操作钮、lb-faces 渐变尾(2px,透明尾压在照片上——
  危险区已复核,维持现状不扩大)。

## 守卫(test_module_boundaries)

- `test_glass_tokens_defined_with_a11y_fallback`:三 token + 降透明度块 +
  亮色 edge 覆盖必须存在。
- `test_no_raw_backdrop_filter_outside_reviewed_keeps`:**任何新的裸
  `backdrop-filter:` 声明直接红**(只放行 3 处已复核 keeps)——材质必须走
  token,否则 a11y 覆盖够不到它。

## 验收(实测)

- 暗色计算值:header `blur(16px) saturate(1.3)` + edge `rgba(255,255,255,0.08)`;
  ⌘K scrim `blur(4px)`;亮色 edge `0.65`。截图确认工具条滚过 sticky 玻璃
  header 时磨砂透出。
- 降透明度块进入构建产物(grep=1);裸声明清点=3(全为 keeps)。
- 门禁绿(5 预期 skip);版本 2.28→2.29 lockstep;照片卡面/缩略图垫层零改动。
