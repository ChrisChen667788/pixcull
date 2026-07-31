# v2.43.1 charter — 按真实硬件选 ASR 引擎,并真机验证两次

v2.43 把转录做完了但**没跑过真语音**(本机当时没装任何引擎),charter 里
如实记着这条顺延。owner 要求:按本机硬件选引擎、装到外置盘、跑两次真机测试。

---

## 1. 先量硬件,再选引擎

| | |
|---|---|
| 芯片 | **Apple M1 Max**(8 性能 + 2 能效核) |
| 内存 | 32 GB |
| 内置盘可用 | **17 GiB** |
| 外置盘可用 | **31 GiB**(3.6 TiB 已满 100%) |

**两块盘都很紧**,这直接决定了选型。

### 增量安装量实测(不是照 71 个依赖那张表猜)

torch / transformers 等本来就装着,所以真正要问的是**增量**:

| 候选 | 新增包数 |
|---|---|
| `funasr`(Paraformer) | **28 个**(aliyun SDK、hydra、librosa、umap-learn、cryptography…) |
| `mlx-whisper` | **2 个**(`mlx` 已在) |

叠加 M1 Max 是 Apple Silicon —— **MLX 走 Metal GPU,是这块芯片的原生路径**
(实测 `mlx.core.default_device()` = `Device(gpu, 0)`)。

**结论:选 mlx-whisper。** 与 owner 原本"Paraformer 优先"的偏好不同,理由是
硬件与磁盘的实际约束;Paraformer 的 `[asr]` extra 保留,盘宽裕时仍可装。

## 2. 权重放外置盘

包装在内置(2 个包,很小),**1.5 GB 的权重放外置**:

```
export HF_HOME="/Volumes/<你的盘>/pixcull-models/hf"
```

已确认 `weights.safetensors` 落在外置盘,内置盘可用空间**未减少**(仍 17 GiB)。

**并且 numpy 没被动**(仍 1.26.4)—— v2.42 那次 scenedetect 把 numpy 升到
2.x 弄坏 mediapipe 的坑,这次核心 pin 顶住了。

## 3. 两次真机测试

用 macOS 内置 TTS 合成**真实语音**(不是正弦波,那证明不了任何事)。

**测试 1 —— 中文**

```
说:  今天我们在这里拍摄婚礼。请新郎新娘站到中间。灯光准备好了吗
识别:今天我们在这里拍摄婚礼,请新郎新娘站到中间,灯光准备好了吗?
```
**一字不差**,且自动补了标点。

**测试 2 —— 英文**,正确切成 3 段,时间戳合理:

```
[0.00-1.96] Today we are shooting the wedding ceremony.
[2.40-3.54] Please move to the center.
[3.88-4.76] Is the lighting ready?
```

**第三次:整条 CLI 路径**(视频 → 抽音轨 → 转录 → SRT),
`pixcull transcribe talk_zh.mp4 --language zh`,**9.8s 全流程**,SRT 正确。

## 4. 速度:把加载和推理分开量

第一次量到 19.3s,看起来很慢。分开测三次同进程调用:

| | 耗时 |
|---|---|
| 进程内第 1 次 | **12.2s**(从 USB 盘加载 1.5 GB 权重) |
| 第 2 次 | **1.0s** |
| 第 3 次 | **1.0s** |

也就是说:**推理是 5 秒音频 1.0 秒 ≈ 5× 实时**,慢的是外置盘的一次性加载。

**这是把权重放外置盘的真实代价**:CLI 每次是新进程,所以每跑一次付约 12s
加载。对"一个视频转录一次"完全可接受;若要批量处理几十个片段,值得改成
常驻进程或把权重挪回内置盘。**记在这里,不粉饰。**

## 5. 验收

- 门禁绿:**1598 passed, 5 skipped, 2 deselected**。
- 新增 `[asr-mlx]` extra;`available_engines()` 现在认 `mlx_whisper`,
  `_transcribe_whisper` 在 Apple Silicon 上优先走 MLX,其他平台回落
  faster-whisper / openai-whisper。
- 模型可用 `PIXCULL_MLX_WHISPER_MODEL` 覆盖。
- 版本 2.43.0 → 2.43.1 lockstep。

## 6. 仍未验证的

- **Paraformer 适配器**(`_transcribe_paraformer` 的 `sentence_info` /
  `spk` 字段映射)**依然没有真机跑过** —— 本机因磁盘紧张没装 `[asr]`。
  v2.43 charter 记的那条顺延,这一版只消掉了 Whisper 那一半。
- 说话人分离(`speaker` 字段)Whisper 路径不产出,仅 Paraformer 支持。
