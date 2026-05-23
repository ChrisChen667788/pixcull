# v0.8 charter — 分发 · 协作 · 风格 clone V2 · 国际化

## 上下文(2026-05-23)

v0.7 shipped 11 slices(P0 + P1 + P2 全做完):UI/UX 收尾(A/B 比较窗
+ Annotation rubric)、5k+ 稳定性、Loupe RGB、Inspector mobile、视图
预设 v2、客户分享链接、风格 clone V1、Tethered live、Sparkle 基础设施、
历史时间线。打开 `/results/<run>` 第一眼已经看不出是单文件工程。

但 v0.7 关心的是 **"看起来像产品 + 在自己机器上跑得动"**。要让 PixCull
真正成为公开发布、能被多个用户、多种语言、多个角色协作使用的产品,
还差四个主线:

1. **分发**:`brew install --cask pixcull` 一键、Sparkle 自更新、
   Windows / Linux 也能装 → 真正"敢公开发布"
2. **协作**:二摄、编辑、客户都能参与同一 run → 真正的 pro workflow
3. **风格 clone V2**:从 median-of-axes 进化到 CLIP-embedding centroid
   → 不再只是"评分像",而是"视觉像"
4. **国际化**:EN / JA 至少做完 → 海外摄影师能用

v0.8 主线:**"敢公开发布 + 协作起来 + 风格 V2 + i18n"**。

## 诊断:为什么这四个主线现在做

### 1. 分发

v0.7-P2-3 给了 Sparkle infra + signing cookbook 但没真的签包。原因
是 Apple Developer ID 需要 $99/年 + 1-3 天身份验证 — 那是用户行动
而非代码工作。同时 brew tap、Win MSI、Linux AppImage 都没动。v0.8
要把这些真的做完:

- 写到 `docs/APPLE-DEVELOPER-SETUP.md` 检查列表的状态
- 建 `homebrew-pixcull` tap 仓库 + cask formula
- Win MSI / Linux AppImage 的签名 + 自更新通道

### 2. 协作

INFRA-3(多人同事件合并)在 task 列表里被 marked "defer to follow-up"
然后两个迭代过去了都没做。但产品的差异化故事("二摄 + 主摄 + 编辑
同时挑同一个婚礼")没这块就不成立。v0.8 要把这块真做出来 — 至少
做到"Wi-Fi LAN 上 2-3 个客户端同步标注 + 冲突调解"。

### 3. 风格 clone V2

v0.7-P2-1 V1 用 axis 中位数学风格,优势是 0 依赖、零延迟、可解释,
劣势是只能学到"我喜欢高分照片"。真正的"风格"是视觉的 — 一个学浪琴
味的婚礼摄影师 vs 一个学 Annie Leibovitz 味的摄影师,他们的 axis 分布
可能一样,但视觉中心完全不同。CLIP embedding centroid + cosine distance
是正确路径。已有 P-AI-2(CLIP 语义搜索)做的基础,V2 复用同一份
embedding cache。

### 4. 国际化

PixCull 全程中文 UI。即使加几行 EN 翻译,海外摄影师上手成本立刻
降一档。同时这是为 v0.9+ 扩到 JA / KO / ES 打基础。i18n 框架越早
做越好(后期改字符串千倍工作量)。

## v0.8 工作范围

### P0(必须做)

#### v0.8-P0-1 · i18n 基础设施 + 中/英切换器
- 新模块 `pixcull/i18n.py`(服务端,key → 翻译 map)
- `pixcull/locale/zh_CN.json` + `pixcull/locale/en_US.json`(初始
  ~80 个最常见字符串覆盖率)
- results.html 加 `data-i18n="key"` 属性的迁移(在 results.html
  hardcoded 字符串里逐个加 attr,再用一个小 JS 字典 swap)
- localStorage[`pixcull_lang`] 持久化用户选择 + 切换器在 workspace-bar
- 切换瞬时(整页 in-place 更新),不是 reload

#### v0.8-P0-2 · INFRA-3 真实落地:LAN 协作
- 服务端从单 process state 迁到 SQLite(annotations / buckets /
  view_presets / style_profile 全部走 db)
- mDNS / Bonjour 广播:同一 LAN 上其他 PixCull 实例可发现
- "Join an event" 流程:输入主机 IP / scan QR,远端 fetch 同一 run
- 标注冲突调解:同一 photo 两人不同 decision → "review needed" 状态
  + 一个调解小 modal 显示两位的标注 + 时间戳

#### v0.8-P0-3 · macOS 签名包发布 + brew tap
- 等用户跑完 docs/APPLE-DEVELOPER-SETUP.md(那是用户行动)
- 建 `homebrew-pixcull` tap 仓库
- 写 `Casks/pixcull.rb` 配合 Sparkle appcast
- v0.8 release tag 真正可以 `brew install --cask`

### P1(应该做)

#### v0.8-P1-1 · 风格 clone V2(CLIP embedding)
- 复用 P-AI-2 的 CLIP embedding cache(embeddings.npz)
- profile = mean / median 的参考 embedding 向量
- distance = 1 - cosine(row_emb, profile_emb),归一化到 [0,1]
- 与 V1 的 axis-MAD 距离做加权融合(`λ * V1 + (1-λ) * V2`,λ 用户
  可调,默认 0.3 / 0.7)
- Inspector 加 "视觉距离 vs 评分距离" 双 chip 显示

#### v0.8-P1-2 · Windows MSI + Linux AppImage 签名
- Windows:py2exe / cx_Freeze 打包 + Authenticode 签名(SignPath
  免费给开源项目)+ Squirrel.Windows 自更新通道
- Linux:AppImage + zsync delta-update,通过 AppImageUpdate 自更新

#### v0.8-P1-3 · 二维码 / 短链 客户分享(P1-4 v2)
- 当前 `/share/<run>/<token>` URL 太长(~80 字符 + 防猜测 token)
  → 加一个短链 issuer `/s/<6-char>` 转发到完整 URL
- 在 share 链接弹窗里直接生成二维码(`qrcode.js` inline,无服务端
  依赖)— 婚礼现场用 iPad 给客户扫码看片

#### v0.8-P1-4 · EN 翻译完整覆盖
- P0-1 只做了 ~80 个字符串(基础)。P1-4 做剩余 ~400 个字符串
- 引入 fluent / poeditor 或 GitHub-issue-based 翻译流程

### P2(想做)

#### v0.8-P2-1 · 日语翻译
- 与 P1-4 复用同一 i18n 框架。zh_CN → ja_JP key 重映射

#### v0.8-P2-2 · CSV / JSON export 完整化
- 当前导出仅 XMP / zip 相册。加结构化 CSV / JSON 全字段导出 + Lr
  collection import 模板

#### v0.8-P2-3 · 「Why I built this」博客发表
- v0.7 charter 已经写了草稿,v0.8 投到 HackerNews / dev.to / 知乎
  + 反馈循环(community input feed back to roadmap)

#### v0.8-P2-4 · ModelScope studio 升级
- 当前 Gradio demo 卡在 v0.3。升级到 v0.7 UI(同步 ROADMAP-v0.6 + v0.7
  P0 P1 改动)+ 加风格 clone 演示

## 建议外部资源 / 灵感参考

- **Linear / Notion** — i18n + 协作的产品标杆
- **Photo Mechanic Plus** — 同行业协作功能的标杆
- **Capture One Sessions** — pro 协作流的功能形态
- **CLIP / OpenCLIP** — 风格 V2 的 embedding 来源
- **mDNS / Bonjour (zeroconf)** — Python `zeroconf` 库
- **homebrew-cask docs** — <https://docs.brew.sh/Cask-Cookbook>

## 不做的事(scope discipline)

- 不重写 Web stack(继续 vanilla JS + zero-build)
- 不引入 npm / build tooling(i18n 用纯 JSON + 小 JS shim,不上 i18next 全家桶)
- 不动 ML pipeline 内核 — v0.8 关心分发 / 协作 / i18n,模型保持 v0.7
- 不做 ja 之外的语言 — JA 之后再考虑 KO / ES
- 不做"云端协作"(服务端在云上)— 全部 LAN 局域网,本地优先

## 验收标准

v0.8 release 完成的标志:

- **任何 macOS 用户**`brew install --cask pixcull` 一键装,首次启动后
  Sparkle 自动检查更新
- **二摄 + 主摄**在同一 Wi-Fi LAN 上,二摄 iPad 实时同步主摄 Mac 的
  标注 — 改动 ≤ 2s 反映到对方
- **海外摄影师**打开页面看到正确的 EN 翻译,切换器在 1s 内切回中文
- **风格 V2**给一张参考照片,Inspector 显示视觉距离;V1 + V2 加权
  融合控件可调 λ
- **Win + Linux 用户**有官方安装包 + 自更新通道

## 建议执行顺序(预计 5-6 周)

| 顺序 | 任务 | 估时 | 理由 |
|---|---|---|---|
| 1 | **v0.8-P0-1** i18n 基础设施 | 3-4 天 | 越早越好,先打基础 |
| 2 | **v0.8-P1-1** 风格 clone V2 | 3-4 天 | 独立 + 复用 P-AI-2 CLIP cache |
| 3 | **v0.8-P0-2** INFRA-3 LAN 协作 | 1.5-2 周 | 最大块,sqlite + mDNS + 冲突调解 |
| 4 | **v0.8-P1-3** 短链 + 二维码 | 1-2 天 | 小型独立 |
| 5 | **v0.8-P0-3** macOS 包 + brew tap | 1 周 | 等用户 Apple 验证完后启动 |
| 6 | **v0.8-P1-4** EN 全量翻译 | 3-5 天 | 内容工作,可分批 |
| 7 | **v0.8-P1-2** Win / Linux | 1 周 | 等用户配置 SignPath / GPG |
| 8 | **v0.8-P2-x** | 视情况 | 收尾 |

---

charter timestamp: 2026-05-23
expected start: 紧接 v0.7 release
expected duration: 5-6 周(v0.8 release Q3 2026)
predecessor: docs/ROADMAP-v0.7-charter.md
