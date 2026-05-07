# PixCull V10.0 — 竞品调研 + 6 维升级方案

> 调研日期 2026-05;采样:Photo Mechanic / Narrative Select / Aftershoot /
> Excire Foto / Adobe Lightroom AI / 国内白鹭 / Picpick AI

## 1. 市场矩阵

| 产品 | 模式 | 价格 (USD) | AI 位置 | 关键功能 | 不足 |
|---|---|---|---|---|---|
| **Photo Mechanic 6** | 桌面工具,行业标杆(纸媒、体育) | $150 永久 + $100/年订阅版(Plus) | 无 AI | 极快 RAW 浏览、IPTC 元数据、tag 工作流 | 完全靠人眼,不评分;CR3/HEIF 兼容慢 |
| **Narrative Select** | 桌面 AI 分拣,主打婚礼/活动 | $10-60/月 (Lite-Ultra) | 云 + 本地混合 | 闭眼/对焦/模糊检测,Scenes 分组,Close-ups Panel | 订阅制,无离线评分模型;不告诉你"为什么" |
| **Aftershoot** | 桌面 AI 分拣 + AI 调色 | $9.99-19.99/月 | 云推理 | 个性化训练(学你的 picking pattern),婚礼场景模板 | 数据上传;无中文支持;美感判断不透明 |
| **Excire Foto 2025** | 桌面 DAM + AI 标签 | ~$99 永久 / $59 升级 | **纯本地** AI | 自然语言搜图,人脸命名,GPS,统计分析 | 评分粒度浅(仅单一 Aesthetic 分);UI 老旧;无 LR-style XMP |
| **Adobe Lightroom AI** | 订阅 ($9.99-19.99/月) | $9.99-19.99/月 | 云 + 本地 | AI Denoise / AI Masking / Generative Remove / 主体识别 | 不做"分拣评分",不告诉你哪些片子该删 |
| **PixCull (当前)** | 桌面 .app + Web UI,开源 | **¥0** + ¥0.003/张 (DeepSeek API 可选) | **本地 VLM + 可选 API** | 6 轴 rubric · 14 题材 · 7 风格 · 经典摄影 canon · 学习重打分器 · 矛盾警示 | 体积大 (1.3 GB);首次设置门槛;无云同步;无原生 LR plugin |

## 2. PixCull 现有优势(超过商业产品的部分)

| 维度 | PixCull 已具备 | 同行最强者 | 差距 |
|---|---|---|---|
| **评分透明度** | 6 轴 + 失分项指名 + DeepSeek 矛盾警示 | Narrative: 仅"keep/cull"无 why | ✅ **PixCull 领先** |
| **经典摄影理论嵌入** | Cartier-Bresson + Adams Zone + 14 题材策略 | 全部商业产品都没明确做 | ✅ **PixCull 唯一** |
| **风格感知** | mono / low_key / long_exposure 自动识别+评分调整 | Aftershoot 有"black and white" preset | ✅ **PixCull 领先** |
| **隐私 / 离线** | 100% 本地 + 可选 API | Excire 100% 本地;Narrative 云依赖 | ⚖️ **追平 Excire,优于 Narrative/Aftershoot** |
| **价格** | 开源免费 | $9.99-60/月 | ✅ **碾压** |
| **自适应训练** | 用户标注→重训练 rescorer | Aftershoot 个性化模型 | ⚖️ **追平,但 UX 没对方丝滑** |
| **中文 + 中国摄影师友好** | UI 全中文 + DeepSeek 中文推理 | 国外产品全英文 | ✅ **PixCull 唯一** |

## 3. PixCull 现有劣势(同行做得更好的)

| 维度 | 同行更强 | PixCull 当前 |
|---|---|---|
| **RAW 浏览速度** | Photo Mechanic 秒级缩略图 | 需要走 pipeline,~3s/张冷启动 |
| **个性化学习** | Aftershoot 学摄影师 picking pattern,几次后准 | V2.1 rescorer 数据稀疏,需 ≥100 标注才显效 |
| **UI 设计感** | Narrative 像 Apple 系产品 | 已升级,但仍显工程师感 |
| **集成度** | LR/Capture One 直接 plugin | 仅 XMP 文件交换 |
| **批量处理速度** | Aftershoot 10000 张 / 30 min | PixCull 50 张 / 90min(VLM+meta) |
| **云同步 + 多设备** | Lightroom CC 自动 | 无 |
| **专业模板** | Aftershoot 内置婚礼/产品/运动 preset | 14 题材策略已有,但没一键 preset |
| **体积** | Narrative ~200 MB | 1.3 GB (PyInstaller bundle) |

## 4. 6 维升级方案

### 4.1 功能(Functionality) ⭐⭐⭐⭐⭐

**短期(V11 - 1 周内)**
- ✅ V9.0-V9.3 已完成:排序/筛选/聚类/键盘/批量
- 🔄 **专业 preset 一键开** — 婚礼模板、新闻摄影模板、产品摄影模板、风光模板、街拍模板。每个 preset 自动设置 strictness、绑定题材、调整 rescorer 阈值
- 🔄 **Lightroom 实时 plugin** — 通过 LR Classic SDK 写一个 .lrplugin,直接在 LR 内调用 PixCull,免去导入/导出
- 🔄 **导出 Capture One Smart Album** — 按 keep/maybe/cull 自动建虚拟相册

**中期(V12 - 1 月)**
- 🔄 **个性化 picking 模型** — 像 Aftershoot 学习你的偏好。每次手动覆盖 PixCull 的 keep→cull 都成为新训练数据;后台自动周期 retrain
- 🔄 **自然语言搜索** — 集成 CLIP embedding,支持"找出有逆光的人像"、"夜景里有流水的"
- 🔄 **智能命名/重命名** — 用 VLM 给每张图生成 IPTC keywords + 描述

**长期(V13+)**
- 🔄 **Video 支持** — 视频片段评分(用第一帧+sample 帧)
- 🔄 **协作模式** — 多人同时标注一组图(LAN 多客户端共享 _RUNS)

### 4.2 性能(Performance) ⭐⭐⭐⭐

**核心瓶颈**:VLM 串行 ~10s/张 + Meta 串行 ~10s/张 = 20s/张。50 张 17 分钟。

**优化路径**:
- 🔄 **异步并发 VLM** — 把 5 张图打成 batch 一次过 VLM(Qwen3-VL 支持 batch),理论 2-3× 提速
- 🔄 **Meta judge 并发** — DeepSeek API 支持并发 5+ 请求/s,改成 asyncio,50 张 meta 从 8 min → 2 min
- 🔄 **VLM 缓存** — 同一张图 hash 后入 sqlite,重跑命中缓存
- 🔄 **缩略图预生成 + 预加载** — 进结果页前先 batch 生成所有缩略图(用 GPU pipeline),Safari 直接用
- 🔄 **DINOv2 embedding 缓存** — 只算一次,重跑 cluster 直接用缓存
- 🔄 **PyInstaller --onefile + UPX** — bundle 1.3 GB → ~700 MB(LZMA 压缩)

### 4.3 设计感(Design) ⭐⭐⭐

**当前**:V8.1 已升级渐变 + 玻璃模糊 + 卡片浮起。但还有 polish 空间。

**升级**:
- 🔄 **Onboarding tour** — 首次打开放一个 30s 的 "如何用 PixCull" tooltip 序列
- 🔄 **专门的 "review" 模式** — 单图大图 + 浮动 6 轴 + 3 个候选标签(像 Tinder 左滑右滑),最适合无键盘的 trackpad 用户
- 🔄 **真正的 .icns 应用图标** — 当前是单色光圈,做个真正的相机+光圈+评分气泡组合 icon
- 🔄 **暗色 / 亮色 / 系统主题切换** — 当前只有暗色
- 🔄 **可调字号 + 行距** — 摄影师群体年龄多元,40+ 用户需要更大字号
- 🔄 **Drag-and-drop 大文件夹支持** — 直接拖文件夹到 dock 图标启动
- 🔄 **进度页用真实视觉化** — 不只进度条,显示当前 VLM 正在分析的 thumbnail + 分数动画

### 4.4 用户友好度(UX) ⭐⭐⭐⭐

**问题**:摄影师不想读"V8.0 风格感知评分"这种工程语言。

**升级**:
- 🔄 **"为什么这张被剔除" — 一键解释** — 卡片底部有个 "?" 按钮,点击展开人话:"这张技术 4.5★(锐度 OK 但局部过曝),美感 2★(LAION 美学评分仅 4.2/10)。建议:RAW 后期降高光、提阴影。"
- 🔄 **撤销 (Cmd+Z)** — 批量打分一不小心错了能撤回
- 🔄 **结果页的"今日总结"卡片** — "你这次拍了 50 张,我推荐你保留 12 张:8 张达到了作品集级,4 张是合格的 social 用片"
- 🔄 **错误提示中文化** — 当前还有"413 Entity too large"这种 raw HTTP 错误冒出
- 🔄 **首次设置移到 web UI** — 不再依赖 AppleScript dialog,直接在浏览器里完成 API key 配置 + 模型下载选项
- 🔄 **离线手册 + 视频教程** — 内置 ~/Library/Application Support/PixCull/docs/

### 4.5 商业价值(Commercial Value) ⭐⭐⭐

**当前**:开源 + 免费,无变现路径。

**机会**:
- 🔄 **Pro 订阅模式** — 免费版限 100 张/月;Pro($4.99/月)无限 + 优先支持 + 高级 preset
- 🔄 **托管 API 服务** — 用户没本地 GPU?上传图片到 PixCull 云,5 倍价格利润空间
- 🔄 **企业团队版** — $99/月支持多用户协作 + 共享标签库 + 审计日志
- 🔄 **婚礼摄影师包** — 婚礼专属 preset + LR plugin + 模板,$29 一次性买断
- 🔄 **GitHub Sponsors / Patreon** — 不强求订阅,接受赞助
- 🔄 **培训课程** — "用 AI 高效分拣 1000 张婚礼照片" 视频课程,售卖
- 🔄 **白标 OEM** — 给摄影机构 / 影楼私有化部署,订阅式 license

**预期**:
- 个人 Pro 1000 用户 × $4.99/月 = $5K/月
- 企业 30 客户 × $99/月 = $3K/月
- **稳定后 $8-15K/月被动收入**

### 4.6 稳定性(Stability) ⭐⭐⭐⭐

**已修**:
- ✅ V8.4: send_error UTF-8 崩溃
- ✅ V7.1: clip vocab 漏打包

**待加固**:
- 🔄 **崩溃自动恢复** — server 进程死后菜单栏 watcher 自动重启
- 🔄 **核心代码 95% 测试覆盖率** — 当前测试只覆盖 V1.2 rescorer,后续每个版本必带 unit + integration test
- 🔄 **Sentry / 自建错误上报** — 用户出错自动收集 stacktrace(opt-in)
- 🔄 **API 调用 retry + circuit breaker** — DeepSeek 限流时自动等待重试,不要让一张图崩整个 batch
- 🔄 **磁盘空间预警 + 自动清理策略** — 当前已有,但没在 .app 启动时检查
- 🔄 **数据迁移工具** — V8 → V9 schema 改变时自动迁移已有 run

## 5. 落地优先级矩阵

```
                高价值
                  │
   ▲ V11 个性化模型           ▲ V11 LR plugin
   ▲ V11 异步并发 VLM         ▲ V12 自然语言搜索
   ▲ V12 异常自动恢复
                  │
─ 低工作量 ─────┼────── 高工作量 ─
                  │
   ▲ V10.1 撤销快捷键        ▲ V13 视频支持
   ▲ V10.1 真 .icns          ▲ V14 协作多人
   ▲ V10.1 onboarding tour
                  │
                低价值
```

## 6. 推荐路线图(下 3 个月)

| 版本 | 周期 | 重点 |
|---|---|---|
| **V10.1** | 1 周 | 撤销 / 真 .icns / onboarding tour / 错误提示中文化 |
| **V11.0** | 2-3 周 | 异步并发 VLM (3× 提速) + 个性化 picking 模型 + 6 个 preset |
| **V11.1** | 1 周 | LR Classic plugin (打通 PixCull ↔ LR 工作流) |
| **V11.2** | 1 周 | 撤销 / 自然语言搜索 / Sentry 错误上报 |
| **V12.0** | 2 周 | Pro 订阅基础设施(支付 / license / quota) |
| **V12.1** | 1 周 | 婚礼/产品/街拍三大 preset 包(¥29-99 一次性) |

## 7. 立即可做的"赢点"(本回合后下一个 commit 即可)

1. **真 .icns 应用图标** — 当前单色 → 设计成相机+光圈+✓气泡
2. **撤销 (Cmd+Z) 批量操作** — 1 行 JS 加 undo stack
3. **首次启动 Welcome tour** — 5-step 浏览器内引导
4. **错误中文化** — 把所有英文 message 翻译

要我开做哪个 / 几个,告诉我。

---

> _本调研基于 Wikipedia + 各公司 marketing 页 (2026-05);具体定价以厂商最新公示为准。_
