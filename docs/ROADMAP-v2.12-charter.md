# ROADMAP v2.12 — 解释再深一层 + 本地发现率埋点 charter

> 承接 v2.11(透明度可发现性)。本轮把「为什么」再往下挖一层(不止点名最弱轴,
> 还说**它为什么低**),并给透明度功能加**本地**使用埋点(看用户到底有没有用到)。

## ① 抓图卡死 —— 已诊断,重定向(不在本机死磕)

诊断结论(v2.12 调查):
- **长轮询理论被推翻**:结果页加载后无任何 in-flight 请求,没有挂住连接的长轮询;
  故 `?nopoll=1` 修不了它。
- **真症状**:点近重复后 `near_dups` 返回 **200(头到达),但响应体不送达无头
  chromium 的页面 fetch**(`r.json()` 永远 pending,toggle 卡「建索引中…」);而
  `curl` 与 Playwright `evaluate-fetch`(被 await 的)都能拿到完整 body。这是
  serve_demo ↔ 无头 chromium 对懒加载 JSON 端点的深层投递怪癖,叠加宿主反复杀抓图
  进程。blind 修 ROI 极低。
- **重定向**:22(滑块)/ 23(婴儿 close-ups)实拍改由**本机**一条命令补
  (`bash scripts/brand/capture_real_screenshots.sh relicdemo`——有真显示、无宿主
  杀手、大概率无此无头怪癖)。功能本身已全验证。未来若要根治,方向是
  `?capture=1`:服务端把 near_dups/faces 结果**内联进 PAYLOAD**,彻底绕开运行时
  fetch(留作后续,属较大改动)。

## ② glass-box「该轴为何低」微解释(P0)

- **What**:v2.11 的逐轴归因已能点名最弱轴(「光线 2.5★ 拖后腿」);本轮在 glass-box
  **展开区**补一句**为什么低**——把最弱轴映射到该行已有的**确定性原始信号**:
  - 光线低 → 高光过曝 X% / 暗部欠曝 X% / 整体偏暗/亮(`highlight_clip_pct` /
    `shadow_clip_pct` / `mean_luma`)
  - 技术低 → 运动模糊(flag)/ 锐度不足(`laplacian_global`)
  - 构图低 → 地平线倾斜 X°(`horizon_tilt_deg`)
  - 主体低 → 无明确主体 / 闭眼 / 被遮挡(flags)/ 主体占比过小(`subject_fraction`)
  - 其余 → 通用兜底
- **Why**:从「哪轴低」到「为什么低」,把判定的可解释性落到可核对的具体信号。
- **纯前端**:全部取自现有 row 字段;信号缺失时优雅兜底「该轴评分偏低」。

## ③ 透明度发现率埋点(P1,本地优先、零外发)

- **What**:`_track(name)` 本地计数器(localStorage),记录透明度功能的首次使用 +
  累计次数:近重复折叠 / 时序场景 / glass-box 展开 / 人脸 Close-ups。
- **Why**:v2.11 修了可发现性,但「修了 ≠ 用户真的用了」。给个**本地、可自查**的
  度量(`localStorage.pixcull_metrics`),让 owner 能看到这些功能到底有没有被点开。
- **隐私**:**绝不外发**——本地优先工具,埋点只写 localStorage,无任何网络请求。

## P2 收口

- 审计补记 + README(双端,文字描述 ②③)+ 同步;22/23 截图标注「本机补」。

## 验证

② 的映射逻辑 node 单测 + 真 run 集成;③ Playwright 断言点击后 localStorage 计数
增加且无网络请求;`make results-html` + golden + 逐文件 runner 门禁。
