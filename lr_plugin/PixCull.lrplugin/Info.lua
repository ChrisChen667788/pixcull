--[[
PixCull · Lightroom Classic plugin metadata.

Adds 'PixCull → Analyze Selected Photos' under Library and
Develop module's File menu. The action posts the selected
images' folder paths to the local PixCull HTTP server at
127.0.0.1:8770 (configurable in settings.lua) and opens the
results page in the user's default browser.

Tested with Lightroom Classic 14.x on macOS.
Apple-internal SDK version doesn't matter — we use only stable
2.0+ APIs (LrApplication / LrTasks / LrHttp / LrShell).
]]

return {
    LrSdkVersion = 10.0,
    LrSdkMinimumVersion = 6.0,

    LrToolkitIdentifier = "dev.pixcull.lr",
    LrPluginName = "PixCull",
    LrPluginInfoUrl = "https://github.com/your-account/pixcull",

    -- Library menu entry
    LrLibraryMenuItems = {
        {
            title = "PixCull · 分析选中照片",
            file = "AnalyzeSelected.lua",
        },
        {
            title = "PixCull · 打开结果页",
            file = "OpenResults.lua",
        },
        {
            title = "PixCull · 设置",
            file = "Settings.lua",
        },
    },

    -- Library menu help
    LrHelpMenuItems = {
        {
            title = "PixCull 插件帮助",
            file = "Help.lua",
        },
    },

    VERSION = { major = 19, minor = 0, revision = 0, build = 0 },
    -- V19 (this rev): vertical picker in the analyze dialog so the
    --   server applies per-business-type policy + AI話術. Inherits
    --   V18 face/scene/rescorer fixes for free since it just calls
    --   /scan_local on the local server.
    -- V11.3: original release.
}
