# v2.40 charter — 门禁不再说谎;CLI 兑现它承诺的事

**主题:** 一条"测试静默 skip"的风险项修完后,顺着同一个思路(**"绿"到底
代表什么**)往下查,挖出两个从 V0.5 就存在的静默 stub —— 其中一个正是
包描述里印着的头号卖点。

---

## 1. skip 不再能掩盖回归

v2.39 记下的风险:真模型测试用 `except Exception: pytest.skip(...)` 兜底,
把两种完全不同的情况混为一谈:

- 模型**真的不在这台机器上**(新克隆、离线 CI)→ skip 是对的;
- 模型**就在本地缓存里**、加载却失败了 → skip 是**错的**,真实回归会伪装
  成 skip,门禁照样绿。

不是假想:v2.39 那轮门禁的 skip 数在 **5 / 6 / 8 之间浮动** —— HF Hub 对
未认证请求限流,同一轮里反复加载就开始失败,于是三条真模型测试悄悄停跑,
**其中包括 v2.34 用来钉住 `image_embeds ≡ get_image_features` 的那条**,
而那是流水线写出的每一个缓存向量唯一的正确性保障。

修法(`tests/_model_gate.py`):**权重在盘上,测试就必须跑。**

- 不在缓存 → skip,理由写明是"这台机器没有权重";
- 在缓存 → 用 `HF_HUB_OFFLINE=1` 加载(网络因此**不可能**把已缓存的模型
  变成失败),此后任何异常都是 `AssertionError`,不是 skip。

`tests/test_model_gate.py`(8 条)专门测这个判定本身 —— 它要是往宽松方向
错了,我们就回到原点。含:未缓存 → skip、已缓存加载成功 → 返回值、
**已缓存但加载失败 → 必须是 FAILURE 而非 skip**、加载确实在 offline 下
发生、env 事后复原、`is_cached` 认得 HF 的目录布局、以及"gate 检查的
repo id 必须仍是生产代码在加载的那个"。

**效果:那三条测试现在真的在跑**(本机两个模型都已缓存),门禁从
1526 → 1542 passed,skip 稳定在 5 条且每条都名副其实。

## 2. `pixcull export` —— 头号卖点其实是个静默 stub

```python
def export(...):
    """Export ratings to XMP sidecars (Lightroom / C1) or CSV. (V0.5+)"""
    raise typer.Exit(code=1)  # TODO(V0.5)
```

**无输出、退出 1**,从 V0.5 至今。而 `pyproject.toml` 的包描述写着
"XMP/IPTC export, Lightroom & Capture One ready",README 头条是 "Lr/C1 直通"。

导出功能**是存在的** —— 但只在 Web 工作台里(`/export/<run>`)。也就是说
v2.31 好不容易为 pip 用户打通的 CLI 路径,走到这里就断了:
`pixcull run` 之后 `pixcull export`,得到的是一个没有任何解释的 exit 1。

现在它跑**和服务端同一套代码**(`write_xmp` / `write_iptc_to_file` /
`build_iptc_fields_from_row`),而不是第二份会漂移的实现:

```
pixcull export <run>/output                    # sidecar 落在每张原图旁(Lr/C1 直接认)
pixcull export <run>/output -t collected       # 收集到 <run>/xmp/
pixcull export <run>/output -t embedded        # IPTC 写进原图(需 exiftool)
pixcull export <run>/output -f csv [-o path]   # 扁平评分表
```

实跑 5 张真 JPEG 验证:sidecar 生成 → **用自家 `read_xmp` 逐张回读**,
keep→5★/Green、maybe→3★/Yellow、cull→1★/Red **全部往返一致**。

退出码也校过:非 run 目录 → 2(并说明该指向哪里)、未知 format/target →
2、**原图全不可达 → 1**(外置盘离线不能看起来像成功)、正常 → 0。

## 3. `pixcull bench` —— 同一个坑,由守卫自动抓出

我为 export 写了一条"**任何命令都不许是无输出的 `raise typer.Exit(1)`**"
的守卫,它**立刻抓出了 `bench`** —— 同样从 V0.5 起就是静默 stub。这正是
写这条守卫的意义:不靠人去逐个读文件。

实现成真正有用的东西:跑真实流水线报吞吐,并把结果换算成用户关心的量纲。

```
0.08 img/s  (3 images in 39.3s, 13.09s each)
    500 photos (small shoot): ~109 min
  1,500 photos (wedding):     ~327 min
  5,000 photos (multi-day):  ~1091 min
```

### 一跑就发现它在污染用户的库

第一次实跑输出里有一行:`Library: +5 photos indexed as 'out'`。
v2.34 起自动入库默认开启,于是 **bench 把它的临时样本写进了用户的跨 run
全库索引** —— 而临时目录跑完就删,那些行会永久变成 `/library` 里的 stale
命中。(我的真实库确实被写进 5 条,已 `library prune --run out` 清除。)

修:bench 期间设 `PIXCULL_NO_AUTO_INDEX=1`,事后复原。

顺带修掉一个"装饰性旋钮":`--workers` 原本想传给 `run_pipeline`,但那个
函数**根本没有这个参数**;真正读取的是 `PIXCULL_WORKERS` 环境变量
(`pipeline/parallel.py::_default_workers`)。改成设置该变量,并有测试钉住
两端不许脱钩 —— 一个不生效的 flag 比没有这个 flag 更糟。

## 4. 验收

- 门禁绿:**1542 passed, 5 skipped**(2 face fixture + 3 zeroconf)。
  那 2 条 face skip 是**正当**的:fixture 是 owner 的真实人像照片,按仓库
  卫生规定不能进公开仓库,skip 理由如实说明了这一点。
- 新增 `tests/test_model_gate.py`(8)、`tests/test_cli_export.py`(16)。
- 全部 15 个 CLI 命令逐个冒烟:`--help` 退出码全 0、无参调用全部给出人话
  提示而非 traceback 或静默;`contact-sheet` 实跑产出 109KB 的 2 页 PDF。

## 5. 顺延

- 去重扫描的 key 索引(v2.39 §2)。
- owner 侧:`PYPI_API_TOKEN`、~50 条真实分歧标注、baby face 截图。
