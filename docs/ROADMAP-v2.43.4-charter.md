# v2.43.4 charter — 发布的 wheel 里没有代码(v2.23 起,九个 Release)

配 `PYPI_API_TOKEN` 之前查另一件事时撞上的。

---

## 1. 症状

下载 GitHub Release 上的 `pixcull-2.40.0-py3-none-any.whl`,拆开:

```
35 个条目,0 个 .py
pixcull/locale/*.json      (13)
pixcull/report/templates/  (16)
pixcull/scoring/data|templates/ (2)
dist-info/                 (5)
```

**`pip install pixcull` 装完是个空壳。** v2.23「PyPI 就绪」以来的**每一个
Release 都是如此**。

## 2. 两个独立错误叠在一起,少一个都不会发生

**① `[tool.hatch.build] include` 是白名单,而且管 sdist。**
它只列了数据文件的 glob,**没有 `*.py`** —— 所以 sdist 里零 Python 代码。
而 `release.yml` 跑的是 `python -m build`(不带 `--wheel`),那会**先建
sdist,再从 sdist 建 wheel**,空壳就这么传递下去了。

**关键在于:手工构建看不出来。** `python -m build --wheel` 直接从源码树
构建,走的是 wheel target 的 `packages = ["pixcull"]`,产出 129 个 `.py`,
一切正常。**人会敲的那条命令,恰好是绕开 sdist 的那条。**

实测三者一致,坐实传播路径:

| | 条目 | `.py` |
|---|---|---|
| 本地 `--wheel`(人工) | 164 | **129** ✅ |
| 本地 `python -m build` 的 sdist | 35 | **0** |
| 由该 sdist 建的 wheel | 35 | **0** |
| CI 发布的 v2.40.0 | 35 | **0** |

**② 冒烟测试测的不是它装的东西。**

```yaml
/tmp/wheel_smoke/bin/pip install dist_wheel/*.whl
/tmp/wheel_smoke/bin/python -c "import pixcull; print(pixcull.__version__)"
```

第二行在**仓库根目录**执行,`python -c` 会把 cwd 放进 `sys.path` ——
`import pixcull` 命中的是**源码树**,那个刚装好的 wheel 从头到尾没被碰过。

内容其实是对的。在中立目录跑坏 wheel:

```
import pixcull                  -> 成功（!）
pixcull.__version__             -> AttributeError   <- 本该在这里挂
```

`import` 之所以还能成功:`locale/ report/ scoring/` 三个目录带着数据文件
存在,Python 3 把 `pixcull` 当成了**隐式命名空间包**。所以只断言 import
不够,必须取一个属性、并跑一次 console script。

## 3. 改法

- `include` 补上 `"pixcull/**/*.py"`,并在注释里写明它管 sdist、以及
  `--wheel` 为何会骗人;
- `release.yml` 的冒烟步骤 `cd /tmp` 再验,并加验 `pixcull.cli` /
  `pixcull.scoring.transcribe` 可导入 + `pixcull --help` 可执行;
- `tests/test_packaging.py`(5 条)**真的构建 sdist + wheel 再拆开看**。

**为什么必须查产物而不是查配置:** 配置看起来是对的,而人工构建出来的
wheel 也确实是对的。只有产物会说实话。

`--no-isolation` 让它 ~0.1s(复用已装的 hatchling),因此放在默认门禁里,
**不挂 `slow` 标记** —— 这条必须每次改动都跑,不是每周跑。`build` 和
`hatchling` 已加进 `dev` extra;缺 hatchling 时**回落到隔离构建而不是
skip**,因为这个仓库已经被"skip 冒充通过"坑过一次。

## 4. 真机验收

干净 venv(Python 3.12)装新 wheel,**从中立目录**运行:

```
import ok, __version__ = 2.43.3
包位置: .../smoke/lib/python3.12/site-packages/pixcull   <- 不是源码树
pixcull --help  -> 正常输出
```

同样的检查跑**旧 wheel**:`AttributeError`,site-packages 里只有
`locale report scoring`。

## 5. 变异测试(以及第一次跑砸了)

移除 `"pixcull/**/*.py"` → `test_sdist_carries_the_python_package` 和
`test_wheel_carries_the_python_package` **双双变红**;还原 → 全绿。

**第一次变异回绿,是我的变异写错了**:替换串漏了行尾逗号,`.replace()`
什么也没换,而脚本无条件打印了"已移除"。和 v2.35 同一类错误 ——
**先怀疑变异,别急着怀疑测试**。修法是在变异脚本里 `assert` 目标命中、
且改后确实消失。

## 6. 影响面(不夸大)

`https://pypi.org/pypi/pixcull/json` → **404**,PyPI 上从未发布过。
所以**没有任何用户通过 `pip install` 装到过空壳** —— 受影响的只是从
GitHub Release 页直接下载 wheel 的人。

**旧 Release 上挂的 wheel 仍是坏的**,且无法就地修复:重跑那些 tag 的
Release 会从当时的提交重新构建,构建出来的还是空壳。v2.43.4 起正确。

## 7. 时机

这件事恰好卡在配 `PYPI_API_TOKEN` 之前。**secret 一加上,下一个 tag 就会
把空壳推上 PyPI,而 PyPI 的版本号不可复用** —— 那会永久占掉一个版本号。
先修后配,顺序不能反。

## 8. 验收

- 门禁 **1627 passed, 5 skipped**。
- `tests/test_packaging.py` 5 条,2.8s,不挂 slow。
- 版本 2.43.3 → 2.43.4 lockstep。
