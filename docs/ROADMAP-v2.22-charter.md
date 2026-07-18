# v2.22 — 审计候选三连 + gallery 新皮肤重摄

> 承接 DESIGN-AUDIT-2030Q3 的排序队列(原 v2.21 候选,因设计翻新插队顺延):
> ① i18n 缺口收口 ② 发布轨道 ④ CSS 拆分,外加 v2.21 遗留的 gallery 重摄。

## P0 — i18n 缺口收口(审计推荐 ①)✅

- **9 个新键 × 13 个 locale**(workspace.resolve_maybes / stats.unreviewed /
  stats.all_done / hydration.loading / hydration.incomplete + 4 个 toast 键),
  164 → 173 键,全部人工母语级翻译(非机器占位)。
- **九处硬编码中文接 `_t()`**:决议按钮、待审/完成 chip、水合进度/降级 chip、
  4 条收尾 toast。`toast.resolve_mode_enter` 带 `{n}` 参数占位。
- **捡出并修复一个会让整个修复失效的启动时序 bug**:统计条在 locale 异步拉取
  完成**之前**构建,`_t()` 彼时拿空表回退中文,且无人事后重建 —— 非 zh 用户
  即使拉到了翻译也看不到。修法:`_applyLang()` 应用完 DOM 后重建
  reviewProgress chip + resolveMaybes 按钮(outerHTML 换持委托监听,v2.15 老路)。
  浏览器实测:en_US 下 chip = "To review 6"、按钮 = "◐ Resolve maybes"。
- **删除 modules/20-undo-stack.js 死模块**(审计发现:包装从未被赋值的
  `window.setDecision`,守卫永不触发,出生即惰性;真撤销是主闭包
  pushUndo/performUndo)。29 → 28 模块,标记同步移除。
- 守卫:test_i18n.py 三条新测试(9 键全 locale 齐全、{n} 占位不丢、
  call site 不回退裸字面量)。

## P1 — 发布轨道(审计 ②)✅

- **`.github/workflows/release.yml`**:v* tag 触发 → build wheel → 干净 venv
  烟测 → `gh release create`(附 wheel + auto notes)。**零外部 secret**
  (仅内建 GITHUB_TOKEN),幂等(tag 已存在则 --clobber 重传)。
- **sync-modelscope.yml 红灯止血**:缺 `MODELSCOPE_TOKEN` 从 `exit 1` 改
  `exit 0 + ::warning::` —— 每推必红的噪音消失,secret 配好后自动转真同步。
- **pixcull.spec 版本单源化**:CFBundleVersion 硬编码 4.0.0(与 pyproject
  2.19.0 两个宇宙)→ 构建时从 pyproject.toml 读取。
- pyproject + `__init__` 回退 **2.19.0 → 2.22.0**(lockstep 守卫绿);
  Makefile 补 `wheel` 进 `.PHONY`。
- **Owner 一步解锁**:`git tag v2.22.0 && git push origin v2.22.0` → 首个
  真实 GitHub Release,README 徽章复活。

## P2 — CSS 拆分(审计 ④)✅

- `build_results_html.py` 新增 **`_assemble_css()`**,与 `_assemble_js()` 同
  契约(`@@CSS:<file>@@` 标记、孤儿/未解析双向报错)。
- 首批抽取:**tokens.css(370 行,设计 token 全块)+ lightbox.css(651 行)**
  → results.css 5,817 → 4,796 行。
- **验收:构建产物字节级一致**(hash 前后相同,构建器判定 already current)。
- 守卫:test_module_boundaries.py 新增 CSS 标记纪律 + 花括号平衡断言。

## P3 — gallery 新皮肤重摄 ✅(18/19 除外,见下)

- **外置盘在线**窗口:重找回博物馆原片(佳能 2025-02 目录;旧 relicdemo 的
  7 张确认款 + 同批补齐 12 张 = 19 张 staged 重建 run,9822 仍是榜首)。
- **本机前台单张 Playwright 可行**(被杀的是后台/长批)——分 4 批重摄,
  与旧脚本同框架(1440×900@2x、reduced-motion、卡片就绪等待)。
- **20 张重摄完成**:01–17 + 20–22,全部 Studio Neutral 暗色皮肤 + 真实文物
  数据;12 保持亮色主题展示位;04 的 A/B 需 Shift+点击两次配对(驱动修了
  两轮);跨模态摆拍(marquee/confidence/heatmap)的注入样式同步换新 token。
- **18/19(视频两张)保留旧图**:视频 demo 数据已被 /tmp 回收;盘上 GoPro
  素材抽帧检查发现**清晰人脸**——未经 owner 明确批准不进公开截图(卫生
  红线),且候选片段仅 1.9s 撑不起 reel 演示。待 owner 指定可公开片段后补摄。
- 决策多样性:标注 API 种 1 cull + 2 maybe(真实人工决策路径,个性化 chip
  显示 3/50)。

## 遗留 / owner 动作

1. **推 tag `v2.22.0`** → 触发首个 GitHub Release(P1 已铺好轨)。
2. **ModelScope SDK token 重登**(本机已过期):README 文字走 git 可同步,
   但**新截图资产传不上去**——重登后 `make modelscope-sync` 补推 20 张新图,
   否则 ModelScope 模型卡继续显示旧皮肤图。
3. **补配仓库 secret `MODELSCOPE_TOKEN`**(CI 侧同步,现在只是安静跳过)。
4. 18/19 视频截图:owner 指定一段可公开视频素材(无人脸/无敏感 GPS)。
5. **外置盘在线窗口别浪费**:门③ 的 ~50 条 keep↔maybe 真实分歧标注随时可做
   (决议队列已就绪)。
