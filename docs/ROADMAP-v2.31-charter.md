# v2.31 — 打包 `pixcull serve`:pip 用户终于能开审片台

> Q4 队列 ③,审计点名的**触达结构性天花板**:即使 owner 配好 PyPI token、
> `pip install pixcull` 通了,pip 用户**仍打不开审片工作台**——README-PYPI 明写
> "serve 得 git clone"。评分流水线上了,差异化的交互 culling UI 没上。

## 根因

服务器住在 `scripts/serve_demo.py`,**8 处**资产路径写死
`Path(__file__).parent.parent`(= "我上面有个仓库根")。git clone 成立,wheel 里
不成立(包内没有仓库根)。

## 方案

**双解析器**分离关注点:
- **`_pkg_root()`** —— 装好的 `pixcull` 包目录(`import pixcull` 反查),永远正确。
  **必需**资产走它:`results.html` 模板、13 语言 locale。
- **`_repo_root()`** —— git 检出根,**wheel 里返回 None**(靠上一级有无
  `pyproject.toml` 判定)。仅**可选/开发**资产走它:`models/`、`samples/`、
  `docs/` 静态、训练 CSV dump、audit 子进程 PYTHONPATH——这些调用点本就有降级。

**实现搬进包**:`pixcull/report/serve_app.py`(12.5k 行,单一真相源);
`scripts/serve_demo.py` 变**薄壳转发**(`python scripts/serve_demo.py` 照旧可用)。

**`pixcull serve` typer 子命令**:`--port/--host/--root/--open|--no-open`;
复用 serve_app 现成的 argparse `main()`(临时改写 argv,不重复 30 个选项);
**pip 用户的 run 默认落 `~/.pixcull/runs`**(没有 /tmp/pixcull_demo 那套约定)。

## 踩到并修的坑

路径加载的测试(10 个文件用 `importlib` 按路径载 serve_demo 再 monkeypatch
`_DEMO_ROOT`/`REEL_PROFILE_PATH`)在薄壳下会**静默失效**:补丁打在壳模块上,
handler 读的却是 serve_app 的全局,两个模块对象不同步。试过 `globals().update`
(复制引用,不同步)和 `sys.modules` 替换(importlib 仍返回原 spec)都不行。
**正解**:测试直接指向包内实现模块——测试本就该测真实现。10 个测试文件已重定向。

## 验收(实测)

- `python -m pixcull serve --help` 正常;仓库内起 `pixcull serve` → landing 200。
- **决定性验证**:干净 py3.12 venv 装 `pixcull-2.31.0` wheel(不碰仓库)→
  `pixcull serve` **真跑起来**:landing 200、`/api/v1/locale` 从**包内**返回 13 语言。
- 新 `tests/test_packaged_serve.py`(5 条):实现模块在包内、必需资产走
  `_pkg_root()`、**包内不得残留任何仓库根假设**、`_repo_root()` 诚实检测检出、
  CLI 暴露 serve、薄壳不得长出第二份实现。
- README-PYPI 删掉"serve 得 git clone",改为 `pixcull serve` 用法。
- 门禁绿(5 预期 skip);版本 2.30→2.31 lockstep。
