# v2.42 charter — 镜头切分:reel 候选不再横跨硬切

DESIGN-AUDIT-2031Q1 推荐 ③。也是本轮开源调研里**许可证过关**的两个之一。

---

## 1. 缺口是真的(审计不是照着名字猜的)

`pixcull.detectors.scene.SceneDetector` 名字里有 "scene",但它是 **CLIP
场景分类**(风光 / 人像 / 活动 / …)—— 回答"这是什么样的画面",不是"这里
切镜头了吗"。全栈 grep 下来**没有任何镜头切变检测**。

后果很具体:`sliding_windows` 在整段素材上扫固定长度的窗口,所以**一个候选
可能横跨一个硬切**。把它剪进 reel,成片中间会跳一下 —— 这是自动成片最显眼
的一种"不对劲"。

实测(20 秒素材、切点在 7s 与 13s):**原实现有 18 个候选横跨切点**。

## 2. 改法:在每个镜头**内部**扫,而不是跨整段扫

`sliding_windows(..., cut_points=[...])` 先按切点把时间轴切成镜头段,再在
每段内跑原有的扫窗逻辑。

**验收的第一条是那个"负向性质"**:`cut_points` 为 None 或 `[]` 时,输出必须
与改动前**完全相同**(实测 111 个窗口,`base == none_ == empty`)。这不是
锦上添花的断言 —— 镜头检测是可选依赖,**默认安装的用户什么都不该被改变**。

有切点时:**横跨切点的候选 0 个**(原本 18 个),且每个镜头段都仍有候选产出。

## 3. 可选依赖 + 优雅降级

PySceneDetect(**BSD-3**)放在 `pixcull[shots]`,理由:

- v2.31 好不容易换来"零编译依赖的 `pip install`",值得守住;
- 它基于 OpenCV,而 OpenCV **本来就是核心依赖** —— 没有引入新的重依赖;
- 装不上时 `detect_cuts()` 返回 `[]`,reel 行为退回 v2.42 之前 ——
  与音频 tagger(ONNX→DSP)、reel 字幕(VLM→模板)**同一套契约**。

### 装的时候撞到一个真坑

`pip install scenedetect` 之后启动就打警告:**numpy 被升到 2.5.1**。
而 `pyproject.toml` 明确钉着 `numpy>=1.26,<2` —— 因为 mediapipe(人脸检测)
和 rescorer 的 joblib 在 numpy 2.x 下会坏。scenedetect 自己**没有声明上界**,
所以裸装会把 numpy 拉到最新。

已还原到 1.26.4 并复验 scenedetect 0.7.1 与之**共存正常**。`[shots]` extra
写在 pyproject 里时,核心的 `numpy<2` 约束会同时生效,所以
`pip install pixcull[shots]` 不会重演;**但直接裸装 scenedetect 会**,已在
extra 上方注释写明。

## 4. 验收

- 真视频实测:合成 3 个视觉迥异的镜头 × 3 秒,切点在 **3.0s / 6.0s**,
  检出 **[3.0, 6.0]** —— 精确命中。
- 门禁绿:**1575 passed, 5 skipped, 2 deselected**(deselected = 两条 slow)。
- 新增 `tests/test_shot_boundaries.py`(17 条),其中一条是**前提守卫**:
  断言"不给切点时原扫窗确实会横跨" —— 如果哪天它自己不横跨了,这个功能就
  在解决一个不存在的问题,应当重新评估。另有近距切点合并(闪光/路人穿帧不
  该切出没法用的碎片)、段间无缝无重叠、缺 extra 时不抛异常、坏视频返回空。
- 版本 2.41.0 → 2.42.0 lockstep。

## 5. 顺延

- **ASR / 按文字剪(FunClip 路线)** —— 审计推荐 ④,体量 M–L,应排在本版
  之后(先有正确的镜头边界,按文字剪才落得准)。
- owner 侧:`PYPI_API_TOKEN`(链接已给)、~50 条真实分歧标注。
