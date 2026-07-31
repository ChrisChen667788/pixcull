# v2.43.2 charter — 第一次真跑 Paraformer,掉出三个 bug

owner 点的顺延项:「Paraformer 适配器仍未真机验证」。

v2.43 写了这个适配器,v2.43.1 只验了 Whisper 那一半。这一版把 Paraformer
装上真跑 —— **结果是它一行都没正常工作过**,而且三个缺陷各自属于纯单测
原理上看不见的那一类。

---

## 0. 先量硬件,再决定装哪儿

| | |
|---|---|
| 内置盘可用 | **14 GiB(99% 满)** —— 比 v2.43.1 时的 17 GiB 更紧 |
| 外置盘 A(模型库所在) | 29 GiB 可用 |
| **外置盘 B(v2.43.1 时没注意到)** | **69 GiB 可用** |

`funasr` 增量重测:**27 个新包,numpy 不在其中**。装完实测 numpy 仍是
1.26.4,mediapipe / cv2 / torch / transformers / mlx_whisper 全部可导入
—— v2.42 那次把 numpy 顶到 2.x 的坑没复发。

pip 用 `--no-cache-dir`(内置盘 99% 满,不能让 wheel 缓存翻倍占用)。
模型权重全部导向外置盘:`MODELSCOPE_CACHE=/Volumes/<drive>/pixcull-models/modelscope`
—— 实测生效,**内置盘可用量在整个过程中没有下降**。

## 1. Bug ①:引擎"装上了"却一用就裸崩

`pip install "pixcull[asr]"` 之后:

```
import funasr                 -> 成功        (_has() 的判据)
from funasr import AutoModel  -> ModuleNotFoundError: No module named 'torchaudio'
```

funasr 1.4.0 在 `funasr/utils/load_utils.py` 里**无条件** `import torchaudio`,
却没把它写进自己的 requirements;而它的 `__init__.py` 是**惰性导入**,所以
顶层包导得进去,一取属性就炸。

后果精确复现过:

```
available_engines()    = ['paraformer', 'whisper']   <- 谎报
resolve_engine('auto') = paraformer                  <- 选中它
_transcribe_paraformer -> ModuleNotFoundError 裸崩    <- 不是设计的干净报错
```

这正是 DESIGN-AUDIT-2031Q1 命名的**「宣传了但够不着」**第五例。

**两处都修 —— 根因 + 防线:**

- 根因:`[asr]` extra 替 funasr 补声明 `torchaudio>=2.0`;
- 防线:`_ENGINE_PROBES` 改为探**适配器真正会调的入口**(`funasr.AutoModel`、
  `mlx_whisper.transcribe`、…),而不是顶层包。惰性导入的包永远可以撒谎,
  而我们控制不了上游下一步会 import 什么。

修复在**真实坏态上**验过(装 torchaudio 之前,那个复现机会一次性):
`auto` 正确回落到 whisper,显式点名 paraformer 给出带安装提示的
`TranscriptionUnavailable`。

## 2. Bug ②:时间戳全是 0,SRT 不可用

适配器读 `sentence_info`。真跑一次,返回的键是:

```
item keys = ['key', 'text', 'timestamp']
sentence_info: MISSING
```

`sentence_info` 只在配了说话人模型时才出现。于是执行**直接掉进第三层
兜底** `Segment(0.0, 0.0, text)` —— 内容对,时间全零:

```
1
00:00:00,000 --> 00:00:00,000
今天我们在这里拍摄婚礼，请新郎新娘站到中间灯光准备好了吗？
```

**SRT 不可用,「点文字跳时间轴」是空操作** —— v2.43 的核心卖点一直没生效。

### 真实结构(探针实测,不是照文档猜)

`timestamp` = 每字一对 `[start_ms, end_ms]`:

- 单位 **毫秒**(最大 6535,音频 6.66s);
- `len(timestamp)` == **去标点后**的字数(27 对 vs 原文 29 字,差的两个是
  标点模型插入的逗号和问号)。

### 改法:三层契约,中间那层补上

1. `sentence_info` 存在就用(更丰富,带 `spk`)—— 将来开说话人分离免费升级;
2. **`timestamp` + 标点 → 分句**(新增 `segments_from_char_timestamps`);
3. 都没有才退回无时间戳文本。

断句规则:句末标点(。！？)**总是**断;子句标点(,、;:)只在已积累
≥10 字时才断 —— 否则「好,」会变成没人读得了的两字字幕。

### 每字对齐这个不变量,在运行时校验而不是假设

中英混合时 Paraformer 按**词**出 span,不是按字母。实测:

```
19 个 timestamp / 29 个非标点字符  -> 不变量破裂
```

守卫触发,返回**整句一段**、用模型真实报告的首尾边界 `[0.05, 5.28]`。
粗,但每个时间戳都是模型真给的 —— 强于瞎对齐把字幕放到错误的帧上。

## 3. Bug ③:每次调用都重建模型,重读 1.6 GB

三段连跑的耗时暴露的:**63.5s / 59.0s / 56.0s** —— 热调用没有变快。
`_transcribe_paraformer` 每次都 `AutoModel(...)`,而那是 Paraformer-Large
+ FSMN-VAD + CT-Punc 合计 1.6 GB 从 USB 重读一遍,换约 2 秒的实际推理。

加进程级缓存后:**60.6s / 1.3s / 1.4s**(约 43×)。

不做 LRU:只有一种配置,在 32 GB 机器上为了"支持多配置"同时驻留两份
1.6 GB 是错的取舍。

## 4. 顺带发现:Whisper 中文吐繁体

同素材对比时发现的,不在原计划内,但对中文摄影师是实际问题:

```
修前: 第一條被選鏡頭有點陡    CER 52.4%
修后: 第一条背选镜头有点抖    CER  4.8%
```

加简体引导 `initial_prompt`,**且只在调用方明确说了是中文时生效** ——
自动检测语言时加中文提示会污染语种判断。

## 5. 正面对比(推翻了本模块自己写过的一句话)

`transcribe.py` 原本写着「Whisper 在中文上弱于 Paraformer(据公开对比)」。
那是引用,不是测量。本机实测:

| | Paraformer | MLX-Whisper |
|---|---|---|
| 冷启 | 60.6s | **19.8s** |
| 热调用 | 1.3s | **0.5s** |
| CER 第 1 段 | 0.0% | 0.0% |
| CER 第 2 段 | 9.5% | **4.8%** |
| CER 中英混合 | **10.7%** | 17.9% |
| 分段粒度 | **2 段(按子句)** | 1 段(整片) |

**结论和原文相反:纯中文准确率上 Whisper 赢,而且快得多。**
Paraformer 赢在**分段粒度**(这恰是「点文字跳时间轴」真正需要的)和
中英混合。所以 `auto` 仍然优先 Paraformer,**但理由改成粒度,不是准确率**。

**这张表要窄读**:3 段 macOS TTS、约 17 秒音频、无噪声无口音单说话人。
足以推翻一句从未测量过的断言;**不足以**在真实婚礼素材上给两个引擎排名。

## 6. 验收

- 门禁 **1611 passed, 5 skipped**(仍是预期的 2 face + 3 zeroconf)。
- `tests/test_transcribe.py` 23 → **34**:每字时间戳映射(用**实测数据**做
  fixture)、不变量破裂时的守卫、句末 vs 子句断句、惰性导入谎报、
  `torchaudio` 声明、简体引导只对中文生效、模型只构建一次。
- **变异测试三次,全部由红转绿确认**:移除守卫 → IndexError;句末标点不再
  强制断句 → 分段数不符;`available_engines` 退回只探顶层包 → 两条测试红。
- **新增真引擎测试** `tests/test_transcribe_real_engine.py`(marked `slow`):
  权重在就必须跑、不许 skip —— 这一版三个 bug 全部只有真跑才看得见。
  无权重时 4 条干净 skip 并给出可操作提示;`-m "not slow"` 完全不收集。
- CLI 端到端实跑(合成含硬切的视频):`1 shot boundaries` → 2 行 SRT,
  时间码真实,`shot_index` 正确(第 2 句起于 2.57s,早于 3.0s 的切点,
  仍属 shot 0)。
- 自己写文档引入的 `SyntaxWarning`(reST 表格里的 `\`)已修,
  `python -W error::SyntaxWarning` 判定通过。
- 版本 2.43.1 → 2.43.2,`pyproject.toml` 与 `pixcull/__init__.py` lockstep。

## 7. 顺延

- **说话人分离仍未验证** —— 需要 `spk_model`(cam++),它才会产出
  `sentence_info`(即上面的第一层)。`Segment.speaker` 字段与第一层代码
  都在,但没真跑过,不算数。
- 真实婚礼素材上的引擎对比(§5 那张表只覆盖干净 TTS)。
- owner 侧:`PYPI_API_TOKEN`、~50 条真实分歧标注。
