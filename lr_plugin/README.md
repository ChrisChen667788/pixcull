# PixCull · Lightroom Classic Plugin

为 Lightroom Classic 14.x 写的本地插件,把"分析选中照片"放进 LR 的 Library 菜单。

## 安装

1. 下载 / 拷贝整个 `PixCull.lrplugin` 文件夹(注意是文件夹,不是单文件)
2. Lightroom Classic → File → Plug-in Manager → Add → 选 `PixCull.lrplugin`
3. 看到状态变成 ✅ Installed and running 即可

## 用法

1. 启动 PixCull.app(顶部菜单栏出现 PixCull 图标 = 服务在跑)
2. 在 LR 的 Library 选若干照片
3. Library 菜单 → "PixCull · 分析选中照片"
4. **V19 新增**:弹窗里选业务垂类 — 婚纱 / 拍鸟 / 儿童 等(或留"自动检测")。选了之后服务端会用该垂类的:
   - 调过的 keep/cull 阈值(V17.4 自动调参产物)
   - AI 生成的专属点评话术(V17.5 DeepSeek 产物)
   - tolerated_flags(V17.2 — 比如儿童容忍 motion_blur_on_face)
   插件记住你上次选的,下次默认勾上。
5. 弹窗确认后,浏览器自动打开 PixCull 结果页
6. **V21.2 新增**:回到 LR,Library 菜单 → "PixCull · 写回 LR 星级"
   - 把刚分析完的 run 决策写回 LR 星级:
     - **keep** → 5★ + 标记(flag = pick)
     - **maybe** → 3★ + 无标记
     - **cull** → 1★ + 排除(flag = reject)
   - 通过文件绝对路径匹配(不依赖文件名),DSC_0001.jpg 跨 shoot
     重名时也准确
   - 整批操作走 catalog:withWriteAccessDo,**⌘Z 一键撤销**
   - 默认用最近一次分析的 run_id(AnalyzeSelected 自动记)。
     要写回更早的 run 时插件会弹窗让你粘贴 run_id

## 设置

Library 菜单 → "PixCull · 设置"

修改 PixCull 服务地址,用于:
- 端口被占用时(8771 / 8772)
- 跑在 LAN 上的另一台 Mac (`http://192.168.x.x:8770`)
- 跑在 Docker 上的远程服务

## 工作原理

不复制原图,只把"该文件夹的绝对路径"通过 HTTP POST 发给 PixCull 的
`/scan_local` 端点。PixCull 直接索引原图,分析结果只在 `/tmp` 里。
你的照片永远不会离开本机。

## 支持的版本

- Lightroom Classic 6.0 — 14.x
- macOS / Windows(只在 Mac 上测过)

## 调试

如果点击菜单后没反应:
- 看 Lightroom Classic → Help → Console — 应该有 PixCull 的 print/dialog 信息
- 确认 PixCull.app 在跑(`curl http://127.0.0.1:8770/` 应该 200)
- 端口被占用?在"PixCull · 设置"里改服务地址
