# v2.45 charter — 把视频链路补进端到端冒烟(缺口是我自己开的)

回头清功能/性能/交互待办时先做的一次盘点。

---

## 1. 盘点结果:审计清单已空,但我开了个新缺口

DESIGN-AUDIT-2031Q1 的四条推荐**全部完成**:

| | 项 | 落在 |
|---|---|---|
| ① | owner 配 `PYPI_API_TOKEN` | 已上线,v2.43.4 发布到 PyPI |
| ② | 端到端冒烟进 CI | v2.41 |
| ③ | 镜头切分 | v2.42 |
| ④ | ASR / 按文字剪 | v2.43 – v2.44.3 |

⑤(冷启动懒构建)⑥(ANN 压缩)明确判定"规模到了再说"。

**但是**:把 17 条 CLI 命令逐个对照冒烟覆盖,只有 `run / serve / export /
library` 四条有端到端路径。v2.42–v2.44.3 这**六个版本**加的整块视频能力
—— `video / transcribe / cut`(含 `--render`)—— **一条都没进去**。

审计的核心论点就是"这个仓库反复发布够不着的功能",而这个缺口是我自己开的。

## 2. 为什么偏偏是这条链

不是为了覆盖率。是因为**它是多阶段的**:每条命令吃上一条写下的东西,
而"单独能跑、串起来断"正藏在这里。我在 v2.44 手工跑链路时抓到过两个,
纯单测全绿:

- `load_transcript` 不回读 `char_spans` → 内存里是词级编辑,**存盘再读就
  悄悄退化成段级**;
- 给"有转录但没 `video_frames/`"的 run 出片,报的是帧目录错误,而不是
  "没有源片可切"。

## 3. 加了什么

`tests/test_e2e_smoke.py` +4 条:

- **`video → cut --render`**:断言 `edit.json` 的 `precision == "word"`
  (这条就是上面那个回环 bug 的探针)、EDL 生成、成片存在、**且比源片短**
  —— 等长意味着编辑被忽略、整片重编码了一遍;
- **删光即拒绝**:退出码非 0、错误里有 "keeps nothing"、**不产出 mp4**;
- **无转录时的报错要指出该跑哪条命令**;
- **有引擎则真跑 `transcribe`**(marked slow):纯音调没有语音,所以
  "退出 1 并说 no speech" 才是正确结果,这一点本身也钉住了 —— 它以前是静默。

### 两个成本决策

**用 `--extract-only`,不做全量评分。** 评分要加载 CLIP 和所有检测器,是
另一条链路(`test_full_journey_including_run` 已经为此 gate)。剪辑链路需要
的只是帧 manifest 和里面的 `source_path`,抽帧就写了这两样。fixture 里额外
断言 `source_path` **指向一个真实存在的文件** —— 出片就是靠它找源片的。

**`pixcull video` 只跑一次。** module 级 fixture 建模板,每个测试拷一份
(它们都会往 run 里写)。原本每测跑一次,把这个文件从秒级变成了分钟级。

## 4. CI:装 ffmpeg,否则这四条是静默 skip

`_tiny_video()` 在没有 ffmpeg 时 `pytest.skip`。CI 的 ubuntu runner **不带
ffmpeg**,所以不装的话这四条会**报绿但什么也没测** —— 正是本仓库已经栽过
两次的"skip 冒充通过"。tests.yml 补了安装步骤,E2E 步骤名也改成实际覆盖范围。

## 5. 验收

- 四条**全部通过**。
- **两次变异,均正确变红,且症状与历史 bug 一致**:
  - 撤掉 `load_transcript` 的 `char_spans` 回读 → 报
    `segment 0 has no per-character times`,与我在 v2.44 手工发现时**一字
    不差**;
  - 撤掉"留空即拒绝"守卫 → CLI 打出**绿勾 `✓ 0.0s kept (0 clips)`**,
    然后渲染死于含糊的 `no clips selected for the reel`。这条变异同时说明
    了守卫在防什么。
- 版本 2.44.3 → 2.45.0 lockstep。
- **改动涉及的 7 个测试文件全绿**(transcribe / edit_model / edit_render /
  video_edit_routes / packaging / repo_hygiene / video_review_css)。
- **全量门禁未在本机取得可信结果**:负载一度到 **107**,所有起子进程的
  测试都是 `subprocess.TimeoutExpired after 60 seconds`,不是代码问题。
  机器空闲后需重跑一次全量确认。

### 卫生 lint 在它该起作用的地方起作用了

跑门禁时 `test_no_private_drive_names` **真的红了一条** —— 我在
`ROADMAP-v2.44.3-charter.md` 里描述外置盘卸载事故时,**把真实盘名写了进去**。
v2.43.3 建这条 lint 就是防这个,已脱敏为 `/Volumes/<drive>`。

## 6. 一次不能用的测量,记下来

第一次跑这四条花了 **2335s 墙钟**,看着像测试写得太重。但同一次的
**user 104.89s + sys 42.75s** —— 实际只用了约 2.5 分钟 CPU。

查下来是**机器负载 25–47**(10 核机上):一个 Steam 游戏占 151% CPU,
外加 macOS 存储管理插件两个进程。`python -m pixcull --help` 都要 62 秒。

**慢是环境造成的,不是这个文件的性质**,所以没有据此把测试改薄。
这和 vitest 那次"高负载下 worker 起不来伪装成代码坏了"是同一类 ——
**先看 uptime,再改设计**。

## 7. 剩下的

- 真实婚礼素材上的引擎对比(待 owner 提供素材或自录一段带噪声的模拟音频)。
- 说话人标签接进网页转录面板(CLI 与 JSON 已有)。
- 另外 13 条命令仍无端到端覆盖 —— **不打算逐条补**:冒烟的价值在于覆盖
  *多阶段链路*,给 `scan` 这种单步命令套一层不值。
