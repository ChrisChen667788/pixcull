# 上传到 ModelScope · 操作指南

GitHub 仓库已就绪。ModelScope 没有提供可编程上传通道(官方推荐
路径是 web 界面 + Git LFS),下面是 5 分钟把 PixCull 发布到你
ModelScope 账号 [@haozi667788](https://www.modelscope.cn/profile/haozi667788)
的步骤。

## 路径 A:作为「模型库 / Model」发布(推荐先做)

最快的路径 —— 项目作为一个代码 + 介绍页放上去。

1. 打开 [modelscope.cn](https://www.modelscope.cn/),登录账号
2. 右上角头像 → **创建** → **新建模型**
3. 表单填:
   - **名称**: `pixcull`
   - **可见性**: 公开
   - **协议**: MIT
   - **任务**: `image-classification` + `image-quality-assessment`
   - **领域**: `cv`
   - **标签**: 把 `modelscope/README.md` 开头 frontmatter 里的 tags
     全部复制过去
4. 创建后,会得到一个空仓库 `haozi667788/pixcull`
5. **本地推送 README**:
   ```bash
   cd /tmp
   git clone https://www.modelscope.cn/haozi667788/pixcull.git pixcull-ms
   cd pixcull-ms

   cp /Users/chenhaorui/Downloads/zero-basics-python/2/pixcull-restored/modelscope/README.md .
   cp /Users/chenhaorui/Downloads/zero-basics-python/2/pixcull-restored/LICENSE .

   git add -A
   git commit -m "Initial release · mirror of github.com/ChrisChen667788/pixcull"
   git push
   ```
6. 完成 ✓ ——
   `https://www.modelscope.cn/models/haozi667788/pixcull`
   现在就有了页面 + 介绍 + 跳转 GitHub 的链接

## 路径 B:创建「创空间 / Studio」可交互演示

> **更新 (2026-05-20)**: 我已经用 ModelScope 的内部 API
> (`POST /api/v1/studios`) 帮你**预创建好**了 Studio 外壳:
> https://www.modelscope.cn/studios/haozi667788/pixcull-demo
>
> 创建参数(MIT · public · CPU · Gradio 4.44.0 · 50 GB disk ·
> 1440min 自动休眠)。你现在只需 **30 秒手动上传 2 个文件**就能
> 让它跑起来:
>
> 1. 打开 https://www.modelscope.cn/studios/haozi667788/pixcull-demo
> 2. 进 "代码" / "Files" 标签
> 3. 拖入 `modelscope/app.py` + `modelscope/requirements.txt`
> 4. 点 "提交并构建" / "Deploy"
> 5. ModelScope 自动 build (~5 min); 然后 https://...../pixcull-demo
>    就是一个可交互的 Gradio 单图评分 demo
>
> 备注:ModelScope SDK 不支持 Studio repo 类型 (HubApi.create_repo
> 显式 reject `studio`),Studio 文件上传也没有公开 HTTP 端点 —
> 上传必须走 web UI。这部分流程截至 2026-05 仍是 ModelScope 平台
> 设计的硬性手动门槛。

### 下面是 ModelScope 没暴露 Studio 创建 SDK 之前的旧路径(已不需要)

完整版需要本机部署,但 Studio 里跑一个 *单张演示* 是吸引点击的
最佳方式。

1. 在 ModelScope 选 **创建** → **创建创空间**
2. 表单:
   - **名称**: `pixcull-demo`
   - **运行环境**: CPU(免费档)
   - **SDK**: Gradio
3. 克隆 Studio 仓库:
   ```bash
   git clone https://www.modelscope.cn/studios/haozi667788/pixcull-demo.git
   cd pixcull-demo
   ```
4. 拷贝 demo 文件:
   ```bash
   cp /Users/chenhaorui/Downloads/zero-basics-python/2/pixcull-restored/modelscope/app.py .
   cp /Users/chenhaorui/Downloads/zero-basics-python/2/pixcull-restored/modelscope/requirements.txt .
   git add app.py requirements.txt
   git commit -m "Initial demo: single-image PixCull rubric scoring"
   git push
   ```
5. ModelScope 自动检测 Gradio 入口、构建、发布到
   `https://www.modelscope.cn/studios/haozi667788/pixcull-demo`
6. **首次构建** ~5 分钟(装 torch + onnx + InsightFace);
   **冷启动** ~30 秒;**热推理** ~3 秒/张

## 路径 C:把 ModelScope 仓库 mirror 到 GitHub

如果想两边同步、只推一次:

```bash
cd /Users/chenhaorui/Downloads/zero-basics-python/2/pixcull-restored
git remote add modelscope https://www.modelscope.cn/haozi667788/pixcull.git
git push modelscope main
```

之后 GitHub 更新时,加一句 `git push modelscope main` 即可。

## 营销建议(让发布更有传播力)

发布之后立刻做这几件事:

### 1. 第一波分发

- 你的 X / 朋友圈 / 即刻 发**一张实物对比截图**的发布帖
  ("AI 选完的一组婚礼连拍,30 秒选出 keep/maybe/cull")
- 小红书 / 即刻 / 微博 发"开源了一个 1500 张/晚的 AI 选片工具"
- **关键**: 发布时附上一张 demo GIF —— 转发率最高的内容形式

### 2. 细分摄影社群

- **国内**: 蜂鸟网、色影无忌 论坛的 "数码与影像" / "婚礼摄影"
  版块;微信群里的 婚礼摄影师群、Lr 用户群、Capture One 群
- **国外**: r/photography、r/postprocessing、Fred Miranda forum 的
  "Software for Photographers"、DPReview 的 "Workflow" 板

### 3. GitHub Topics 的长尾流量

repo 已经打了 20 个 topic。发布 24 小时内,新 repo 在
`topic:photo-culling`、`topic:photography`、
`topic:wedding-photography` 排得很靠前。
主动到这些 topic 页面下点 star 给其他项目,会触发反向推荐流量。

### 4. ProductHunt / HuggingFace 同步

ModelScope Studio 上线后,把同一个 Gradio app 复制到
HuggingFace Spaces(免费 CPU 够跑),挂一个 ProductHunt 发布日。
这是触达国外开发者社群的最大单点流量来源。

### 5. 写一篇技术博客

"How I built a local-first AI culling tool" / "为什么我开源了花了 18 个月写的选片工具"
—— 这类反思帖在 HackerNews / Medium / 知乎 的留存远高于
单纯的功能列表帖。

### 6. README 的迭代时机

发布第 1 周收集第一波反馈,然后更新 README:
- 加上真实截图(而不是占位 SVG)
- 加一张 60 秒的 demo GIF(用 Kap / ScreenFlow 录)
- 在「Why people star it」段补一段「来自社群的早期评价」
- 加一个 "Star history" widget:
  ```markdown
  ## Star History

  [![Star History Chart](https://api.star-history.com/svg?repos=ChrisChen667788/pixcull&type=Date)](https://star-history.com/#ChrisChen667788/pixcull&Date)
  ```
