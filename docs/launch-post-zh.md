# 我开源了一个本地优先的 AI 选片工具 —— 18 个月写下来给职业摄影师用

*一个周末项目长成了我刚摸相机时就希望存在的工具,今天 MIT 开源。*

## 痛点没人愿意承认

一场婚礼 1500 张。一次川西行 600 张。一个野生动物的早晨随便 2000+。

每一张照片都要在摄影师脑子里过两遍判断:
- **第一遍**:这张要不要留?决策很快(几百 ms),但累。一个晚上 6 小时
  泡在 Lightroom 的 library 模块里,是结束完一场拍摄的正常代价。
- **第二遍**:留下来的连拍五张几乎一样,发哪张?这一遍更难,是真在
  做美感判断。

第一遍是 AI 现在真能解决的:连拍峰值、对焦命中、闭眼、曝光合理 —— 都
是工程已经解决的问题,关键是把它们接对。市场已经开始嗅到了 —— 现在
至少有 5 个商业 AI 选片 SaaS,每月 ¥150 - ¥300。

但它们每一个都让职业摄影师吞下不该吞的三个妥协。

## 妥协一:必须把照片上传到你不掌控的云

婚礼合同里明令禁止把客户照片送到第三方云上做处理。新闻摄影的 NDA 更严。
体育摄影有 embargo 窗口。拍国家保护级野生动物的人 *根本不能* 共享 GPS
位置 —— 那是 EXIF 里的,EXIF 是上传文件的一部分。

SaaS 卖点是 "你照片在我们这儿很安全"。现实是:它们在别人服务器上,
受人家公司商业模式 + 训练 pipeline + 法律辖区的支配。对很多真实工作
流来说,这就是 deal-breaker。

## 妥协二:只给一个分数,不给理由

主流的 AI 选片产品输出的是单一 0..1 置信度分数,按降序排好,等你信。

但客户问 "为啥这张你没选呢?" —— 或者你自己想从选择里学习提升 ——
0.43 这个数字毫无用处。你要的是:

- 哪一维弱?清晰度?构图?光线?瞬间?
- 这张相比同连拍组的兄弟差在哪?
- 经典摄影怎么说? Cartier-Bresson 的决定性瞬间?Adams 的 Zone System?
  Rule of Space?

只给分数能让你完成交付,但学不到东西。每一场拍摄都是一次浪费的学习机会。

## 妥协三:活在你工作流外

Lightroom、Capture One、Photo Mechanic —— 真正的工作发生在这些地方。
catalog 操作、调色参数、color label、关键字、IPTC、客户相册。

封闭的 Web App 每批都逼你切换上下文。职业摄影师的反应很合理:
"这工具不写 XMP sidecar、Lr catalog 看不到它的决策,那我宁可直接打开
Lightroom 手选。"

## PixCull

PixCull 是我 18 个月写出来的替代方案。
**本地优先、6 维评分细则、原生 XMP sidecar + iOS 滑动伴侣 + Lr/C1
tether 模式 + 多用户 profile + 多人同事件合并。** MIT 开源。
源码在 [github.com/ChrisChen667788/pixcull](https://github.com/ChrisChen667788/pixcull)。

它与众不同的地方:

- **本地优先**。RAW 解码、评分(CLIP + InsightFace + MediaPipe + 6 维
  rescorer)、人脸、GPS 聚类 —— 全在你电脑上跑。可选的 DeepSeek
  meta-judge 走 *你的* API key。照片永远不出本机。

- **6 维评分**。每张图打 技术 / 主体 / 构图 / 光线 / 瞬间 / 美感
  六维星级,每维都有理由和经典摄影正典的引用(Adams Zone System、
  三分法、决定性瞬间 等等)。大图窗里还能看 4 源对比
  (自动规则 / 训练模型 / 本地 VLM / DeepSeek),立刻知道评分系统
  在哪一维不确定。

- **Sidecar 原生**。XMP 文件落到 Lightroom 期待的位置。IPTC 标题由
  场景 + 人物标签 + 地点 + 建议 自动组合。独立 HTML 相册一键打包。
  iOS 滑动伴侣 App。Lr/C1 tether 监控器。

- **理由都摆在台面上**。"因为焦点不准而 cull" 是一等公民的分类法。
  分类选择器按你的历史频次排序(用得多的排前面 → 鼠标移动少)。
  每一维都显示 ± 标准差,让你看到哪些维度评分准、哪些是猜的。
  admin 页 显示 *你的* 选片偏好画像 —— 你 keep 时vs cull 时各维
  的平均星级差,就是你心里那把无形的尺。

## 写它学到的东西

**rescorer 比 rubric 重要程度低**。花了 6 周训了 6 维回归头,以为是
关键。最后做出来的 *建议信封* —— 简短 verdict + 引用经典的优点/缺点
—— 才是让用户 *信任* 工具的东西。数字建立不了信任,跟你自己会写出来
的句子一样的句子才能。

**职业摄影师都是极端 power user**。我 V2.0 出 1/2/3 keep/maybe/cull
快捷键。立刻收到反馈:"F 呢?Photo Mechanic 里 F 是 flag。`[` `]` 呢?
G 跳 cluster 呢?Backspace undo 加回退呢?" Photo Mechanic 训练了
20 年的肌肉记忆。PixCull 现在全部对齐。

**大图窗里的 1:1 缩放是必须**。没有 100% 焦点检查,这工具就是不能
用来认真选片。两周才做对 —— 因为 A/B 对比同步缩放需要归一化的
平移坐标系才能处理不同长宽比。

**开源逼迫你诚实**。pre-launch 审计:内部战略文档要拿走。私人照片
训练标签要脱敏(sha1 hash 文件名)。"哪些对外能见的" 这个练习不舒服
但很有用 —— *它会暴露出你最初就不该收集的数据*。诚实的瞬间。

## 故意不做的

- **修图/调色** —— Lightroom + Capture One 在做。PixCull 写 XMP,
  Lr 的 develop 模块负责颜色。
- **云托管** —— 用 iCloud / Dropbox / NAS 做 folder mirror 同步
  (INFRA-2)。再往上是别人的事。
- **跨工具多人合并** —— PixCull 内部多 run 合并已经支持(INFRA-3);
  跨工具是 5 年级问题。
- **LAION 级别的自动 tag** —— 建议是经典引用,不是 embedding 自动
  tag。单词信噪比更高,覆盖面更小。

## 怎么试

```bash
git clone https://github.com/ChrisChen667788/pixcull.git
cd pixcull
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/serve_demo.py
# 浏览器开 http://127.0.0.1:8770
```

首次预热模型 ~30 秒(Apple Silicon),之后每张 ~1 秒(M2 Pro 实测)。
不想装 Python 的话也支持 Docker:

```bash
docker compose up --build
```

## v0.7 - v0.8 新增的(从这篇 draft 写完到现在又发了 22 个 slice)

- **风格 clone V1 + V2** — 给我 5-20 张你以前 keep 的照片,产品学你
  的个人风格(V1 是 axis-MAD,V2 是 CLIP embedding 中心)。新一批照片
  按"像我风格的优先"排序,Inspector 显示 "🎨 风格距离" 芯片。模型纯
  本地,在 `<run>/output/style_profile.json`。
- **Tethered live scoring** — 监听 Lr/C1 tether 文件夹,新 RAW 进来
  即刻分析,grid 实时更新。二摄"现场给客户预览"的场景。
- **LAN 协作** — 主摄发链接,二摄/编辑打开,每 5s 同步你的标注;
  俩人标同一张冲突时打 ⚠ 标记。纯局域网,不上云。
- **客户分享链接 + 二维码** — 不用打 zip 了,主摄一键生成短链 + QR,
  客户手机扫码就能在浏览器看精选。带摄影师水印 + 客户姓名 header。
- **LR-Library + LR-Develop 风格 UX** — 左边 8 组可折叠 filter
  侧栏(decision / scene / style / faces / location / bursts /
  cull-reason / active-learning),右边 9 段可折叠 Inspector,
  手机端 bottom-sheet。
- **i18n** — workspace 顶部一个芯片切换 中 / EN / あ。154 个字符串
  已多语化,剩下的 v0.9 继续。
- **Loupe RGB readout** — 1:1 缩放模式光标位置浮显 R/G/B/Hex/Y
  数字。LR / PS 同款。
- **按住 Space 出 cheat sheet**(macOS Finder 模式)— 按住 350ms
  浮出当前 context 的快捷键条;tap-Space 仍是切换 lightbox。
- **结构化 CSV / JSON 导出** — 在 scores.csv 基础上 join 注解 +
  风格距离 + bucket 归属,一行一个 filename 全字段。
- **5k+ 张稳定性** — IndexedDB 标注 adapter,observer 节流,自适应
  懒加载。16GB M2 Pro 跑 5000 张稳。

97 个 unit test 通过(i18n / sync / style / shortlink / QR /
CLI audit / 5k smoke)。Charter 在
`docs/ROADMAP-v0.4-charter.md` → `-v0.7-` → `-v0.8-`。

## 希望你能给我反馈的

如果你拿到自己的拍摄数据上跑,有几件事最帮我:

1. **rubric 哪里明显判错?** 4 源分歧度已经暴露(inconsistency 徽章),
   但我想知道你拍的题材里哪类误判最常见,可以做有针对性的再训练。

2. **还差哪个工作流的对接?** Lr 双向 round-trip 已经做了(读 Lr 编辑
   后的 xmp:Rating 回 PixCull 标注)。Capture One? Bridge? DigiKam?
   告诉我你 PixCull 之后用的下一个工具,我给你写 bridge。

3. **README 里你没看到但想看到的是什么?**

4. **风格 clone V2 真的学到你的风格了吗?** 给它 10-20 张你以前的
   keep,跑一场新活动,告诉我"像我风格的优先"这个排序是不是真的把
   你会 keep 的片子排前面 — 还是只把同维度评分高的排前面。

GitHub issues 开着 + bug 模板已就绪:
https://github.com/ChrisChen667788/pixcull/issues

也欢迎在即刻 / 知乎 / 微博找我聊聊真实场景的需求。

— Chris Chen
前腾讯 / 商汤 / 海康 AI 架构师,
视觉中国 + 图虫签约摄影师,
受不了一场拍摄后再花一晚上在 Lr catalog 里挑片的人

GitHub: [@ChrisChen667788](https://github.com/ChrisChen667788)
ModelScope: [@haozi667788](https://www.modelscope.cn/profile/haozi667788)
