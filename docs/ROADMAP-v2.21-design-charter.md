# v2.21 — "Studio Neutral" 设计全面翻新(调研驱动)

> 起因:owner 判定现版 UI「没有设计感」。本轮先做 6 视角全网调研
> (Narrative Select / Aftershoot / Imagen / FilterPixel / Photo Mechanic 系 /
> Lightroom / Capture One / Linear / Raycast / Vercel / 暗色 UI 色彩科学),
> 再据证据重构设计系统。调研由多 agent workflow 产出,主会话综合定案。

## 调研结论(为什么改)

1. **暖色底是功能性缺陷,不只是审美问题。** ISO 3664 观片环境标准 + 同时对比/
   色彩适应机制:照片周围的有色环境会系统性扭曲判色(暖棕环境让观者把照片看偏冷、
   过度补暖)。因此 **所有** 头部工具的照片区都是中性无彩灰:Capture One 面板
   ~#1a1a1a–#232323(固定暗色)、Lightroom 画布五档中性灰、Aftershoot 近黑、
   Imagen/FilterPixel 中性暗。PixCull 的暖浓缩咖啡底(#161310, h=77°)在业内是孤例。
2. **辅色纪律。** 头部工具全部「结构无彩 + 语义色只表状态」:Lightroom AI 徽章
   绿勾/红叉;Imagen 绿=选/红=弃;Narrative 蓝/灰/红六边形 + 人脸下方绿黄红条。
   PixCull 现状是黄铜同时充当品牌、边框、结构装饰——信号被稀释。
3. **卡片去装饰。** Narrative/Aftershoot/FilterPixel 的缩略图全部图占满、零装饰边,
   状态用小徽章/色条表达。双 bezel 装饰边框在对照组里没有同类。
4. **顶级工具的"设计感"来自纪律而非装饰**(Linear/Raycast/Vercel 拆解):
   4 级中性面梯 + 半透明发丝线、3 权重字阶 + 数字等宽、8pt 间距、统一控件高度、
   120/200/300ms 扁平 ease(overshoot 弹簧只留给签名时刻)、keycap 键位徽章。
5. **CJK 排版**:13 语言产品需要 :lang() 级 CJK 栈与行高(zh 1.6–1.75)。

## 设计方向:Studio Neutral(中性影室)

**论点**:PixCull 是给专业摄影师判片的仪器。仪器的表面必须中性(照片是唯一的
颜色主角);品牌暖意从"满屏棕"收缩为"一道香槟金"(选中环/焦点环/CTA 专用);
设计感来自面梯、发丝线、字阶与运动的纪律。

### Token 方案(OKLCH 三变量机制保留,只换值)

暗色(默认):
- `--base` oklch(0.200 0 0) = **#161616**(中性,c=0)→ 派生面:
  card #1d1d1d · surface-2 #242424 · surface-3 #2e2e2e · chrome #0f0f0f
  (对齐 C1 #1a1a1a–#232323 与 M3/业界 #121212→#1e1e1e→#242424 梯)
- `--contrast` oklch(0.925 0 0) = #e6e6e6(避免纯白眩光);
  fg-2 #c6c6c6 · muted #9b9b9b · muted-soft #707070(全无彩)
- 边框 #262626 / #363636(发丝线,弱化存在感)
- `--accent` oklch(0.790 0.075 78) = **#d5b584 香槟金**(chroma 3× 旧黄铜
  #c4b9a9——旧值 c=0.0254 近乎灰,是"没设计感"的元凶之一);accent-hi #eaca98。
  **只用于**:选中环、焦点环、主 CTA、活跃态。结构一律无彩。
- 语义色(暗色校准:去土、微提亮):keep #63bd7f(原 sage #6faa78)·
  maybe #d6a443(不动,已是好的暗色琥珀)· cull #e0604e(原陶土 #cf6f5b)·
  info #6fa7bd · neutral #9b9b9b
- 阴影转中性 rgba(0,0,0,·);brand-gradient → 香槟金→青铜
- 半径收紧 6/9/13/18 → 5/8/11/14(pro 密度)
- `--ease-out` 由 6% overshoot 弹簧改回扁平 cubic-bezier(0.16,1,0.3,1)
  (200+ 处过渡全体安静下来);`--ease-spring` 保留给签名时刻

亮色(paper → 中性纸):--base oklch(0.975 0 0)=#f7f7f7、--accent 青铜
oklch(0.45 0.075 78)=#6c501f、--contrast #171717;修正 light --c-info 曾错设为
黄铜 #c4b9a9 → #0e7490。阴影去暖转中性。

### 组件重构(P1–P3)

- **卡片**:去双 bezel;图占满卡面、单 1px 发丝线;选中=2px 香槟环;
  底部渐变 scrim 保徽章可读;决策色只出现在徽章/决策条,不再整框染色。
- **Chrome**:顶栏/工作条落 chrome 面(比画布深);控件统一高度与边框;
  侧栏节标题 11px/600/大写字距;活跃筛选 accent-soft。
- **Lightbox**:右面板走面梯(panel/card 分层);keep/maybe/cull 按钮重做
  层级(keep 实心绿、maybe/cull 描边);胶片条对齐新卡片语言。
- **数字等宽**:分数/计数 tabular-nums(评分变化不跳版)。
- **CJK**::lang(zh/ja) 行高与字栈修正。

### 保留清单(现设计做对的)

OKLCH 三变量派生机制 · Geist 品牌字(升格为纪律性字阶)· 5 态语义 chip 架构 ·
色盲备用色板不动 · 键盘优先 + ⌘K · 玻璃盒信息架构 · 亮暗双主题机制。

## 切片与验收

- **P0 token 换血**:results.css 根块 + @supports 回退 + serve_demo
  `_DESIGN_TOKENS_CSS` 副本 + video_review/timeline/pages/*.html + results.js
  内联字面量,**全仓旧色板 hex 清零**(v2.3.1 漏色教训:换肤必须全量)。
- **P1 卡片/网格** · **P2 chrome/侧栏/chips** · **P3 lightbox/toast/杂项**。
- 验收:门禁绿 + 浏览器实测截图逐面走查(grid/lightbox/决议/视频页/独立页)+
  旧色板 hex 全仓 grep = 0。
- 后续(不在本轮):19 图 gallery 与 docs/diagrams 动图按新皮肤重摄/重绘
  (无头抓图被本机杀,需本地跑 capture 脚本)。
