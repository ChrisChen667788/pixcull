# v2.46 charter — 说话人标签进网页面板;顺手撞出一个自伤的交互

v2.44.3 的顺延项:说话人分离 CLI 和 JSON 都有了,页面还没有。

---

## 1. 数据早就送到了,只是没人用

`_serve_video_data` 一直在发完整的 `transcript.to_dict()`,里面就含 `speaker`。
面板的 JS 里 `speaker` 出现 **0 次** —— 又一例"做出来了但够不着",只是这次
距离只有一层 JS。

## 2. 加了什么

- 每行时间戳后一个**说话人 chip**,按 id 取色(4 色循环);
- 面板头在**识别出多于一人时**显示「N 人」;
- 被划掉的行,chip 一起压暗。

**没有标签就没有 chip。** Whisper 从不产出说话人;Paraformer 在分不出时
报 `None` 而不是 `0`(v2.44.3 的决定)。所以**缺少 chip 表示"未知"**,
这在两种情形下都为真 —— 显示一个「说话人 0」则是在报告模型没做出的结论。

## 3. 撞出一个自伤:chip 被我上一版的修复冲掉了

第一版把 chip 放进**文本 span**里。真机一看:面板头正确显示「2 人」,
**chip 数却是 0**。

现场量:

```
renderTranscript() 后   chip 数 = 23
paintEdit()      后     chip 数 = 0
```

原因是 v2.45.1 我刚把 `paintEdit` 改成「**比较当前显示的文本**」(那是修
撤销不生效的正确做法)。而 chip 的文字算进 `textContent`:显示的是
`"0新郎新娘…"`、服务端说 `"新郎新娘…"`,判定不同 → 用纯文本覆盖,
**连 chip 一起抹掉**。

两个改动各自都对,**交互起来是错的**。修法是把 chip 放到**时间戳 span**
里,让文本 span 的 `textContent` 保持是纯台词 —— 也就是让
`paintEdit` 的不变量继续成立,而不是给它开例外。

## 4. 真机双向验证

| run | 面板头 | chip |
|---|---|---|
| 24 轮双人对话(59s,过 20 段门槛) | `paraformer · zh · 2 人` | **23 个,两色** |
| 同一份转录去掉 speaker 字段 | `whisper · zh` | **0 个** |

并复验剪一刀之后 **chip 仍在**(就是上面那个回归)。

## 5. 验收

- `tests/test_video_review_css.py` 5 → **8 条**,新增三条都针对本版的坑:
  空值守卫必须同时查 `undefined` 和 `null`、chip 必须在时间戳 span 内、
  `paintEdit` 必须比较显示内容。
- **三次变异全部正确变红**(守卫只查 undefined / chip 挪回文本 span /
  paintEdit 退回比较原文)。
- 版本 2.45.1 → 2.46.0 lockstep。

## 6. 过程记录:`--extract-only` 够不够用,分场景

建 demo run 时用 `--extract-only` 结果网页打不开:`/video/data/` 要
`temporal.json`,而抽帧不写它。**v2.45 的 e2e 用 extract-only 是对的**
(剪辑链路只需要帧 manifest 和 source_path),**网页则必须跑完整评分**。
两者需求不同,不是其中一个写错了。
