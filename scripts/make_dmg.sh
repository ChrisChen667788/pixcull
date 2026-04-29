#!/usr/bin/env bash
# Wrap dist/PixCull.app into a drag-to-Applications DMG.
#
# Output:  dist/PixCull.dmg
#
# Run AFTER scripts/build_app.sh produces dist/PixCull.app.
# Independent of notarization — you can ship this DMG unsigned for
# personal use, but Gatekeeper will require right-click → Open the
# first launch on a non-developer machine.
set -euo pipefail

cd "$(dirname "$0")/.."

APP=dist/PixCull.app
DMG=dist/PixCull.dmg
STAGE=dist/_dmg_stage

if [ ! -d "$APP" ]; then
    echo "ERROR: $APP not found. Run scripts/build_app.sh first."
    exit 1
fi

echo "=== Staging DMG contents ==="
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

# Make a tiny README so the DMG window has explanation text
cat > "$STAGE/读我.txt" <<'EOF'
PixCull · 安装说明

1. 把 PixCull.app 拖到 Applications 文件夹
2. 在 Launchpad 里启动(首次右键 → 打开,绕过 Gatekeeper)
3. 顶部菜单栏出现 PixCull 图标 → 浏览器自动打开 demo
4. 拖照片或选本地文件夹 → 自动 keep/maybe/cull 评分

数据 · 模型缓存 · 日志:
  ~/Library/Application Support/PixCull/

完全卸载:
  rm -rf /Applications/PixCull.app ~/Library/Application\ Support/PixCull
EOF

echo "=== Building DMG ==="
hdiutil create -volname "PixCull" \
    -srcfolder "$STAGE" \
    -ov -format UDZO \
    "$DMG"

rm -rf "$STAGE"

SZ=$(du -sh "$DMG" | awk '{print $1}')
echo ""
echo "✓ Built $DMG  ($SZ)"
echo ""
echo "Distribution checklist (optional, for non-personal use):"
echo "  [ ] codesign --deep --force -s 'Developer ID Application: …' dist/PixCull.app"
echo "  [ ] codesign --force -s 'Developer ID Application: …' dist/PixCull.dmg"
echo "  [ ] xcrun notarytool submit dist/PixCull.dmg --keychain-profile … --wait"
echo "  [ ] xcrun stapler staple dist/PixCull.dmg"
