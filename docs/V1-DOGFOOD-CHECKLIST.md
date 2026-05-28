# v1.0 RC Wedding Dogfood Checklist

> 在你下次拍一场真实婚礼时,跟着这份 checklist 把 PixCull v0.13 当作
> 主力选片工具用一遍。每个 ☐ 都是 P0 bug 排查点;跑完整个流程没出
> P0 / P1 issue,v1.0 release gate 的 **dogfood 维度** 即过线
> (`docs/RELEASE-V1.md` § 8)。

预期时间:**婚礼当天 + 第二天上午**,即"拍完→交付"的完整闭环。

---

## D-7(婚礼前一周)· 预热 + 备份

- ☐ 当前 git tag 是 `v0.13.3-RC` 或更新(`git describe --tags`)
- ☐ `pixcull/.venv/bin/python -m pytest tests/ --ignore=tests/test_v1_1_scripts.py` 全绿
- ☐ 启用 opt-in telemetry:在 `~/Library/Application Support/PixCull/config.json` 加 `{"error_reports_enabled": true, "telemetry_mode": "minimal"}`
- ☐ 启动一次 PixCull,确认健康检查通过:`curl http://127.0.0.1:8770/`
- ☐ 跑一个 200-photo dry-run(例如 `100CANON/3J0A8133.JPG`...):时间记下来,作为 baseline
- ☐ 提前做一次 backup:`cp -r ~/Library/Application\ Support/PixCull /Volumes/Backup/pixcull-pre-wedding-$(date +%F)`

## D-1(婚礼前一天)· 设备就绪

- ☐ 笔记本电量 > 90%,带充电器
- ☐ 移动 SSD ≥ 200 GB 空闲,作为 RAW 落地盘
- ☐ Lr / C1 tether 目录配好,PixCull 监控目录设置正确
- ☐ iPad / iPhone 上 PixCull Companion 已登录,Wi-Fi 与笔记本同网段
- ☐ 提前在 `/admin/users` 创建本场的 user_id:`wedding-2026-XX-XX` 或拍摄客户名

## 婚礼当天 · 现场流程

### 上午 · 仪式前(getting ready)

- ☐ 第一张照片落盘后,Tether 模式触发分析(< 2 秒延迟):
  - 若超过 5 秒未出 verdict → **P0**,立即记到 `~/Library/Application Support/PixCull/dogfood-issues.md`
- ☐ 第 100 张时,grid 是否还顺滑(60 FPS)?
  - 卡顿 → **P1**(性能 regression)
- ☐ ⌘K 命令面板:输入"keep"是否能找到批量动作?
- ☐ Lightbox 按 `A` 切换 attribution heatmap:
  - 6 轴 chip 是否出现
  - 任一轴 click 是否叠加 heatmap

### 中午 · 仪式高潮

- ☐ 连拍 burst(8-12 张/秒)的 burst 聚类是否正确:
  - sort=cluster + 同一组应该 ≤ 100ms 内的所有帧
- ☐ Marquee 框选 30+ 张:
  - 底部 bulk toolbar 是否出现
  - bulk keep 是否立即写回 annotations.jsonl
- ☐ 视觉风格 chip(🔭 视觉)是否出现:
  - 没出现 → 还没训练 style profile,跳过到下一项
- ☐ 训练 style profile(用前 50 张 keep)→ 训练用时记下来

### 下午 · 接待 + 仪式后

- ☐ `/admin/perf` 数据表:
  - p99 latency < 5s/张
  - rescorer disagreement > 20%? → 检查 vertical 是不是设错了
- ☐ Confidence modal(maybe-band hover):
  - hover 在分数 0.45-0.55 的卡上,popover 是否在 200ms 内浮出
- ☐ /companion 副屏 lightbox:
  - 主屏点下一张,副屏是否同步翻页(BroadcastChannel)
- ☐ LAN 协作:让助理在另一台机器加入同一 event:
  - 同步延迟 < 100ms(v0.11-P0-3 WebRTC datachannel)
  - 同时改一张照片,冲突解析 UI 是否弹出

### 晚上 · 第一轮初选

- ☐ ⌘K → "训练风格模型":用今天全场 keep 训练 profile
- ☐ 按 style_distance 重排,看是不是符合你的审美
- ☐ 训练一次后,Inspector "🔭 视觉" chip 点开 → per-ref distance 细分是否显示
- ☐ 客户分享链接:`📡 客户分享链接` 生成 → 在另一设备打开,确认链接 work + 缩略图正确

## D+1(婚礼第二天)· 复盘 + 交付

### 数据完整性检查

- ☐ `wc -l ~/Library/Application Support/PixCull/runs/<run-id>/annotations.jsonl` 应该 ≈ 你的实际标注数
- ☐ `wc -l ~/Library/Application Support/PixCull/runs/<run-id>/output/scores.csv` 应该 == 总照片数 + 1(header)
- ☐ 没有任何 `.jsonl.tmp` 残留(标注写盘是 atomic 的)

### Bias 自查

- ☐ 打开 `/admin/bias?force=1`:
  - 没有 > 2σ 的 finding(v1.0 gate 阈值是 2σ,v0.13 是 1.5σ — patches 已收紧)
  - 任意 finding → 检查是不是模型在某 scene 上系统性过严/过松
- ☐ `/admin/bias?user=<wedding-2026-XX-XX>` per-user 视图:
  - 你自己今天的反转率 < 20% → 模型基本对齐你的偏好
  - > 30% → 模型 calibration 跑偏,记下来分析(可能要 `train_rescorer.py` retrain)
- ☐ `/admin/disagreement`:今天的反转条数 → 喂给下一版 goldenset 增量

### 交付

- ☐ 选完最终 deliverable 桶 → 📥 导出 → XMP 写回原图
- ☐ Lr 导入,确认 XMP 评分正常显示
- ☐ 客户分享链接 → 发给客户

### Bug 收集

- ☐ 运行 `python scripts/collect_dogfood_bugs.py --run <run-id> --out /tmp/dogfood-bugs.md`
- ☐ 把 stdout 里的 issues 整理到 `~/Library/Application Support/PixCull/dogfood-issues.md`
- ☐ 致命问题(数据丢失 / 服务挂掉 / pipeline 卡死)→ **P0**,blocking v1.0 release
- ☐ 影响选片效率但不丢数据 → **P1**,patch in v1.0.x
- ☐ Cosmetic / nice-to-have → **P2**,roll into v1.x

## D+7 · 多人复用

如果还有别的摄影师朋友愿意做 dogfood,把这份 checklist 给他们一份(纸质 / iPad PDF / GitHub Wiki 都行)。至少 3 位摄影师独立跑完,**v1.0 release gate 的 dogfood 维度**才算真过线(`docs/RELEASE-V1.md` § 8):

  - ☐ 摄影师 #1 完成全 checklist
  - ☐ 摄影师 #2 完成全 checklist
  - ☐ 摄影师 #3 完成全 checklist

每人产出一份 `dogfood-issues.md`,汇总后:
- 没有跨摄影师重复出现的 P0 → **v1.0 release-ready**
- 有 → 优先 fix → 重跑 checklist 直到清零

## v1.0 dogfood Telemetry 摘要(opt-in)

启用 telemetry 后,匿名收集的指标(全程脱敏,无图片字节):

| 指标 | 类型 | 阈值告警 |
|---|---|---|
| pipeline_latency_per_photo_p99 | 秒 | > 5s |
| rescorer_disagreement_rate | % | > 30% 或 < 5% |
| bias_findings_count | int | > 0 自动通知 |
| annotation_write_failures | int | 任何 > 0 都是 P0 |
| webrtc_connect_success_rate | % | < 80%(LAN/WAN) |

数据落到 `~/Library/Application Support/PixCull/telemetry/<date>.jsonl`,
关闭后立即停止采集 + 30 天自动清空。

## 预期 P0 候选(根据 v0.13 内部测试推测)

- 200+ 张连拍单场,grid 渲染卡顿(虽然测试过 200 张 OK,但 800+ 没真测过)
- WebRTC ICE 失败时 fallback 到 HTTP polling 是否丝滑(测过单元,未跨真 NAT)
- iOS Companion 同步在 5G 切换 Wi-Fi 时的断线 → 重连
- DeepSeek API 限流时的 graceful degrade

跑过一场就能确认上述 4 个是否真存在;不存在则 v1.0 release gate 的 dogfood 维度更稳。

---

charter timestamp: 2027 Q3
predecessor: `docs/RELEASE-V1.md` § 8 (dogfood requirements)
sister docs: `docs/USER-GUIDE.md`(新手版操作流) · `docs/RESCORER-V3-RESULTS.md`(ML eval gate)
