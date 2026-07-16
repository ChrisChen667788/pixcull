# ROADMAP v2.19 — 音频事件叠层 + 首个发行物(wheel)charter

## A. 视频玻璃盒 P2 — 音频事件时间线叠层(已交付)

audio_events.json(笑声/掌声/音乐,v2.1 学习型 tagger)一直算了没画。现在:
- **数据链**:`/video/data/<id>` 附带完整 `audio`;`/results` 的 `PAYLOAD.video.audio`
  附带精简 events(kind/start/end/conf)。缺文件优雅 None/[]。
- **两个时间线都画**:`/video` 审片页时间线底部车道——按 kind 着色的圆角带 +
  宽度足够时的 emoji 标签(😄 笑声 / 👏 掌声 / 🎵 音乐)+ `<title>` tooltip(区间+置信);
  lightbox 视频 scrubber(modules/05-video-scrub)同款细带(token 填色)。
- 验证:端到端(3 事件 → 两个 payload → 审片页 3 条带 + 标签 + tooltip,零 JS 错误)
  + 模板钩子守卫(两面)。P3(reel keep/cull 反馈回路)仍在队列;reel why 提音频加成
  顺延至 P3 一起。

## B. 发行物·第一步 — wheel 可构建可验证(已交付)

审计触达维 2.5/5 的根因是「零可下载产物」。本步把 **PyPI wheel 变成一条命令**:
- `pyproject` 版本 0.1.0 → **2.19.0**(与迭代对齐);`pixcull.__version__` 单源化
  (importlib.metadata,源码树 fallback)+ `tests/test_version.py` 锁双处一致。
- **`make wheel`** → `dist_wheel/pixcull-2.19.0-py3-none-any.whl`(~4.6MB,gitignore)。
- **内容验证**:7 个 pages 模板 / scene yaml / 校准 json / results+video_review 模板
  全在包内;entry_point `pixcull=pixcull.cli:app` ✓。
- **干净 venv 烟测**:`pip install <wheel> --no-deps numpy` → `import pixcull` ✓、
  `__version__ == 2.19.0` ✓、`importlib.resources` 能读包内模板 ✓。

**owner 发布动作(我不代发)**:`twine upload dist_wheel/*.whl`(需 PyPI 账号/token)
或挂到 GitHub Release。签名 .dmg(需 Apple 开发者账号)仍是主题②后续。
