# Launch-post publishing checklist

v0.8 完成后,launch post 的 EN + ZH 版都已更新到 current state
(`docs/launch-post-en.md` + `docs/launch-post-zh.md`)。这份 checklist
告诉你**实际发布到哪些平台 + 每个平台的优化建议 + 发布顺序**。

我(Claude)不能替你提交到这些平台 — 每个都需要你的实名账户 + 实
名验证。你来发,我负责文字 + 后续 issue 回复脚手架。

---

## ⏱ 发布顺序(2 周)

### Week 0(发布前 1 周准备)

- [ ] **截 4 张关键截图**(每张 1280×800,优化到 ≤200KB):
  - `results-v0.8-hero.png` — workspace 全景 + Library sidebar 展开
    + 一些 keep 的卡片 + Inspector 半开
  - `lightbox-rgb-readout.png` — 1:1 模式 + RGB 读数 + 一张高质量
    sample photo
  - `style-clone-v2.png` — Inspector 三 chip(📐 评分 / 🔭 视觉 /
    🎨 综合)+ λ 芯片
  - `share-modal-qr.png` — 分享链接 modal,QR + 短链复制按钮
- [ ] 把截图放到 `docs/screenshots/v0.8/`(也镜像到 README 引用)
- [ ] 重新生成 ModelScope studio(v0.8-P2-4 task #113)
- [ ] 验证 README badges 都正常(GitHub stars / version / license / CI)

### Week 1 — 中文社区

| 平台 | 标题建议 | 估计 ROI |
|---|---|---|
| **即刻** | "做了一个本地的 AI 选片工具 — PixCull v0.8 |
                    给摄影师省 1 个晚上的 Lr catalog 时间" | 🌶🌶🌶 (摄影师密度高) |
| **知乎专栏** | "为什么我做了一个不上云的 AI 选片工具 — PixCull 的设计思考" | 🌶🌶🌶 (长尾搜索) |
| **微博** | 用 `#开源`#摄影`#AI` 三个 tag + 1 张 hero 图 | 🌶🌶 |
| **小红书** | 摄影师人群,文案侧重"省时间"+ 2-3 张 before/after 对比 | 🌶🌶 (新平台,要测) |
| **掘金** | tech-tilted 版本,侧重"vanilla JS + zero-build + 单文件 10k 行" | 🌶 (开发者社群,转化间接) |

### Week 1.5 — 英文社区

| 平台 | 标题建议 | 估计 ROI |
|---|---|---|
| **Hacker News** | "Show HN: PixCull — local-first AI photo culling (Apache-2)" | 🌶🌶🌶🌶 (单点最高 — 一次上首页 ≈ 500 stars) |
| **dev.to** | "I built a local AI photo culling tool because the SaaS ones upload my client's photos" | 🌶🌶🌶 |
| **Reddit r/photography** | "Built a free Lightroom-companion that AI-culls without uploading anywhere" | 🌶🌶🌶 (摄影师,但严格 anti-self-promo 规则) |
| **Reddit r/programming** | "Show: zero-build vanilla JS web UI (10k line single file)" | 🌶🌶 (技术) |
| **Reddit r/photo_critique / r/weddingphotography** | softer self-promo,需先发几条 comment 建立 karma | 🌶🌶 |
| **X / Twitter** | thread with screenshots + signature lines from blog | 🌶 (没大 following 不行) |
| **Mastodon photog community** | indieweb / privacy-focused 受众 — 强对路 | 🌶 (小但精准) |

### Week 2 — 摄影师圈精准 outreach

- [ ] DM **3-5 个有影响力的婚礼摄影师**(VCG / 图虫 / Fearless 签约的)
- [ ] DM **2 个相机 KOL**(老李 / 阿涛 / 看见摄影)— 不要直接 pitch
  产品,先 ask "想给你看个 prototype 听下反馈"
- [ ] 给 **Camera & Imaging Products Association (CIPA)** 邮件 list 投
  一篇 1-page tech brief
- [ ] 给 **PetaPixel / DPReview / Fstoppers** 编辑发 pitch(包含一张
  你的 keepers 作品 + 一段 60s 录屏)

---

## 📝 每个平台的标题 + 第一段优化

### Hacker News(最重要)

**标题**:`Show HN: PixCull – local-first AI photo culling (Apache-2)`

**第一段**(顶帖 OP comment):
> Hi HN — I'm a wedding/event photographer who used to be an AI
> architect at Tencent / SenseTime. After watching every existing
> "AI culling" SaaS require uploading client photos to their cloud
> (in violation of every wedding contract I sign), I built PixCull
> as the local-only tool I wished existed.
>
> Key bits:
> - Apache-2, runs on M2 Pro at ~1s/photo, no cloud at all
> - LR/Capture One XMP round-trip
> - 6-axis rubric scoring + style-clone (CLIP centroid) so it
>   learns YOUR keep preferences after ~10 references
> - Multi-shooter LAN sync, tethered live scoring,
>   client-share short links + QR
> - 10k line vanilla JS single-file UI, no build tooling
>
> Repo: https://github.com/ChrisChen667788/pixcull
>
> v0.8 just shipped (22 slices since launch). Most curious about:
> what's the corner-case rubric misjudges most for YOUR vertical?

### 即刻

**标题**:`做了一个本地的 AI 选片工具,给摄影师省 1 个晚上的 Lr time`

**第一段**:
> 拍婚礼一晚 1500 张,平时在 Lr Library Module 挑片 6 小时是基本款。
> 市面上 AI culling SaaS 全要上传客户照片(直接违反合同),所以我做
> 了一个本地版的 — PixCull v0.8 刚发。

(配图:results-v0.8-hero.png + style-clone-v2.png)

### 知乎专栏

**标题**:`不上云的 AI 选片是怎么实现的 — PixCull 的设计思考与开源决定`

**封面图**:results-v0.8-hero.png

**第一段**:
> 三年前我从腾讯辞职做职业摄影,直接撞上了这个问题:每场婚礼后
> 6 小时的 Lr catalog 选片。我用 AI 架构师的本能想:这是个可以自
> 动化的问题。但市面上每家 SaaS 都要把客户照片上传到他们的云 —
> 这直接违反我签的每一份婚礼合同。
>
> 所以我自己做了一个,叫 PixCull。两年迭代到 v0.8,完全开源
> (Apache-2),今天写一下设计思路 + 为什么选这条路。

---

## 🛡 准备好回应的 5 个常见质疑

1. **"为什么不直接用 LR 自带的 People / Smart Preview?"**
   答:LR 的智能是"找特征",PixCull 的智能是"打分 + 学你的偏好"。
   完全互补,不是 replacement。Lr 双向 round-trip 已支持。
2. **"你的模型比 ImagenRanker / Aftershoot 哪个准?"**
   答:没做过 head-to-head benchmark(他们不开源,没法对比 weights)。
   但 PixCull 的差异点是 *学你的个人风格*,这是 SaaS 解决不了的
   隐私结构问题。
3. **"开源会被薅羊毛 / 商业化怎么活?"**
   答:Apache-2 + 客户付定制 + 团队订阅(v0.9 + 多人协作 + 私有
   cloud 后端)是路径。短期不做收费。
4. **"性能瓶颈在哪?"**
   答:CLIP encoding 是首次跑 ~50ms/photo(后续走 cache),其它都
   亚秒。M2 Pro 上 5000 张约 90 分钟首跑,后续 ms 级。
5. **"我的照片真的不上传任何地方吗?"**
   答:跑 `nettop -m tcp -p $(pgrep -f serve_demo)` 自己验证。
   除非你点了 DeepSeek meta-judge(可选,要 API key)
   ,所有数据 100% 留在本机的 `/tmp/pixcull_demo/`。

---

## 📊 KPIs to watch(发布后 30 天)

| 指标 | 目标 | 怎么测 |
|---|---|---|
| GitHub stars | 500 | github.com/ChrisChen667788/pixcull |
| brew installs | 200 | brew tap analytics(等 v0.8-P0-3 cert ready) |
| ModelScope studio plays | 1000 | studio.modelscope.cn dashboard |
| dev.to article views | 5000 | dev.to author dashboard |
| HN front page | 1 次 | hckrnews.com |
| Real user feedback issues | 10 个非 bot issues | github.com/.../issues |

---

## 🚫 不做的事(scope discipline)

- 不付费推 SEO / 不买广告
- 不夸张性能数据(说"~1s/photo on M2 Pro"足够,不说"5x faster than X")
- 不诋毁竞品(SaaS culling 有他们的价值;privacy-conscious 用户找
  PixCull,scale-conscious 用户找 SaaS — 各取所需)
- 不承诺自己来不及做的功能(v0.9 / v1.0 charter 已经塞满)
