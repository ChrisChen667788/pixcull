# PixCull · App Store / 公网分发 上架准备清单

V13.0 完整化的发布前 checklist。包含 **Mac App Store** + **GitHub
Releases / 个人网站直发** 两个分发渠道,二选一或并行。

## 0. 前置账号 + 工具

- [ ] **Apple Developer Program** 注册,$99/年
- [ ] Xcode + Command Line Tools (`xcode-select --install`)
- [ ] Developer ID Application 证书装入 Keychain
- [ ] App-specific password 用于 notarytool
- [ ] (可选)Sparkle CLI: `brew install --cask sparkle`
- [ ] (可选)Apple ID 已开 2FA + App Store Connect 已注册 PixCull
      bundle id `dev.pixcull.app`

验证 Keychain 里有正确的证书:
```
security find-identity -v -p codesigning
# 应该看到 "Developer ID Application: 你的名字 (TEAMID12345)"
```

## 1. 法务 + 元数据

- [ ] **隐私政策** 准备好(本地处理 / 不上传图片 / 仅 license token
      经云校验)。Apple 强制必须公开 URL。
- [ ] **服务条款** EULA。强调免费版 100张/月、Pro 不限量、无退款政策
      仅在购买后 14 天内适用。
- [ ] **Bundle ID** 唯一:`dev.pixcull.app`(已写在 Info.plist)
- [ ] **Application Category**:`public.app-category.photography` ✅(已设)
- [ ] **App icon**:1024×1024 PNG → .icns(已有,但建议设计师重做更专业版)
- [ ] **截图**:
      - 1280×800 主界面 × 至少 3 张(浅色 / 深色 / 大图模式)
      - 1280×800 结果页 × 至少 3 张(评分 / lightbox 大图 / cluster compare)
- [ ] **预览视频**(可选,但能显著提升下载率): 30 秒展示从扫描到分析到导出 XMP

## 2. 代码层面 — App Store 沙箱兼容(只针对 MAS,直发不需要)

App Store 要求 sandbox + 进一步限制 entitlements。我们的 .app 大量
依赖 .so 加载、外部命令(rembg / pyiqa)、网络访问 —— 全部需要在
entitlements 里显式 allow:

```xml
<key>com.apple.security.app-sandbox</key>
<true/>
<key>com.apple.security.network.client</key>
<true/>                  <!-- HuggingFace, DeepSeek API -->
<key>com.apple.security.files.user-selected.read-write</key>
<true/>                  <!-- 用户选的文件夹 -->
<key>com.apple.security.files.bookmarks.app-scope</key>
<true/>                  <!-- 持久化文件夹访问 -->
<key>com.apple.security.cs.allow-jit</key>
<true/>                  <!-- numba / torch.compile -->
<key>com.apple.security.cs.disable-library-validation</key>
<true/>                  <!-- mlx / pyiqa 加载未签名 .so -->
```

⚠️ MAS 历来对包含 PyInstaller / Python embeddable 的 .app **审核严
苛**(常拒,理由"包含未声明的解释器")。**首次发版强烈建议走直发
+ Sparkle**,等体量稳定再考虑 MAS。

## 3. 直发流程(推荐 V13 路径)

```bash
# 一行命令完成 build + sign + notarize + DMG + appcast 片段
RELEASE_VERSION=13.0.0 ./scripts/release.sh
```

输出:
- `dist/PixCull-13.0.0.dmg`(已签名 + notarized + stapled)
- `dist/PixCull-13.0.0.appcast-fragment.xml`(粘到 sparkle_appcast.xml)

**用户体验**:
1. 在 https://pixcull.dev 点 Download
2. 双击 DMG → 拖 .app 到 /Applications → 双击启动
3. **首次右键打开都不需要**(已 notarize)
4. 顶部菜单栏出现 PixCull;每天后台检查 1 次更新

## 4. MAS 流程(可选)

```bash
# 不同的 entitlements + 沙箱测试
./scripts/release_mas.sh    # TODO V13.1
```

提交到 App Store Connect:
- [ ] 上传 .pkg(从 .app 导出)via Transporter
- [ ] App Store Connect 填写 metadata + 截图 + 隐私详情
- [ ] 等审核 1-3 天

## 5. 营销页面准备

- [ ] **着陆页** https://pixcull.dev:
      - Hero:"AI 摄影分拣 · 经典摄影正典加持 · 离线优先"
      - Demo 视频
      - "For 婚礼摄影师 / 体育摄影师 / 风光摄影师" 三大场景按钮
      - Pro / Studio 价目对比
      - 下载按钮(GitHub release + DMG 直链)
- [ ] **GitHub Repo** 公开:README + screenshots + LICENSE
- [ ] **Product Hunt** 提交(选周二早上 6 点 PT 提交,流量最高)
- [ ] **小红书 / 即刻 / 摄影师群** 软文 5-10 条
- [ ] **YouTube / 抖音** 4-5 分钟功能演示视频 × 中英双语

## 6. 上线后监控

- [ ] **Sentry / 自建错误上报**(opt-in,Pro 用户默认开)
- [ ] **GitHub issues** 模板:bug / feature request
- [ ] **每周** 看 active learning 队列里 disagreement 最高的 10 张图,
      手动评估,据此调 prompt 或 rubric 阈值
- [ ] **每月** 用 silver_label_with_meta_judge 重训公开版 V2.1 rescorer

## 7. 法律灰区

- [ ] **不要**在营销文案里用 "比 Lightroom 强 / 比 Aftershoot 准" 这类
      可能引起对方告 trade dress 的措辞
- [ ] **不要**在截图里包含他人版权的照片(用自己拍的或 unsplash CC0)
- [ ] **DeepSeek API 转售** 不允许 — 我们从用户的 token 路过转发到
      DeepSeek 是合规的(用户自带 key),但如果要做托管 API 服务
      需要联系 DeepSeek 商务获 OEM 授权
- [ ] **GPL 兼容性**:目前依赖里 `imagededup` 是 Apache 2.0,可商用 ✓
      `pyiqa` MIT ✓ `mlx-vlm` MIT ✓ `rembg` MIT ✓ 全部干净

## 关键文件位置

| | |
|---|---|
| Info.plist (.app 元数据) | `app/pixcull.spec` 里的 BUNDLE step |
| 签名 entitlements | `app/entitlements.plist` |
| Sparkle appcast | `app/sparkle_appcast.xml` |
| Sparkle 客户端 | `app/updater.py` |
| 一键发版脚本 | `scripts/release.sh` |
| 通知化脚本 | `app/NOTARIZATION.md` |
| 本清单 | `app/APP_STORE_SUBMISSION.md` |
