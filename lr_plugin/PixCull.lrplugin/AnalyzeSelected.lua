--[[
PixCull · Analyze Selected Photos

What it does:
1. Get the selected catalog photos.
2. Extract the unique parent folders.
3. Let the user pick a vertical (婚纱/拍鸟/儿童/...) or leave at
   auto-detect — V19 addition.
4. For each folder, POST /scan_local to the local PixCull
   HTTP server with the chosen vertical, getting back a {run_id}.
5. Open the first run's results page in the default browser.

Why we POST folder-by-folder rather than per-photo: PixCull's
scan-local mode indexes whole folders (it's how zero-copy
works). If the user selected 5 photos from one folder we just
scan that folder; PixCull's UI then lets them filter to the
exact selection by clicking the scene/decision pills.

V19 addition (this revision): the vertical picker. PixCull's
V17.0+ vertical system applies per-business-type scoring policy
(婚纱 ≠ 拍鸟 ≠ 儿童 — each has tuned keep/cull thresholds,
tolerated flags, and AI-generated phrase pools). Selecting one
here means the results page shows business-flavored advice +
tighter thresholds tuned to that vertical's good/bad samples.

The server-side already inherits all of V18 automatically (face
detector restored, documentary scene tightened, rescorer
retrained) — this plugin update is purely the missing user-input
piece.

Future hook (V20+): write the resulting decisions back to LR
via LrPhoto:setRawMetadata('label', '...') so Lightroom's
star ratings update automatically.
]]

local LrTasks       = import "LrTasks"
local LrApplication = import "LrApplication"
local LrHttp        = import "LrHttp"
local LrPathUtils   = import "LrPathUtils"
local LrDialogs     = import "LrDialogs"
local LrShell       = import "LrShell"
local LrPrefs       = import "LrPrefs"
local LrView        = import "LrView"
local LrBinding     = import "LrBinding"
local LrFunctionContext = import "LrFunctionContext"

local prefs = LrPrefs.prefsForPlugin()
local SERVER_URL = prefs.serverUrl or "http://127.0.0.1:8770"

-- V19: list of verticals the user can pick from. Kept in lockstep
-- with pixcull/verticals.py — manual sync, but the registry is
-- stable (10 entries since V17.0).
local VERTICALS = {
    { title = "—  自动检测",  value = "" },
    { title = "🏔  风光摄影",  value = "landscape" },
    { title = "🐅  野生动物",  value = "wildlife" },
    { title = "🦅  拍鸟",      value = "bird" },
    { title = "💒  婚纱摄影",  value = "wedding" },
    { title = "🌅  旅拍写真",  value = "travel" },
    { title = "🎭  cosplay",   value = "cosplay" },
    { title = "👶  儿童摄影",  value = "kids" },
    { title = "🐶  宠物摄影",  value = "pet" },
    { title = "🎪  活动摄影",  value = "event" },
    { title = "⚽  运动摄影",  value = "sports" },
}

-- V19: presentModalDialog with a vertical picker. Returns the
-- selected vertical key (possibly empty string for auto-detect),
-- or nil if the user cancelled.
local function askForVertical(n_folders, n_photos)
    return LrFunctionContext.callWithContext("pixcullAskVertical",
        function(context)
            local f = LrView.osFactory()
            local prop = LrBinding.makePropertyTable(context)
            -- Remember the last choice so the user doesn't have to
            -- re-pick every shoot. Stored in plugin prefs.
            prop.vertical = prefs.lastVertical or ""

            local contents = f:column {
                spacing = f:control_spacing(),
                fill_horizontal = 1,
                bind_to_object = prop,
                f:static_text {
                    title = ("将扫描 %d 个文件夹(共 %d 张选中照片)"):format(
                        n_folders, n_photos),
                },
                f:static_text {
                    title = "服务地址: " .. SERVER_URL,
                    text_color = LrView.kColorBlue,
                },
                f:spacer { height = 6 },
                f:row {
                    f:static_text {
                        title = "垂类(business vertical):",
                        width = 140,
                    },
                    f:popup_menu {
                        value = LrView.bind "vertical",
                        items = VERTICALS,
                        width = 200,
                    },
                },
                f:static_text {
                    title = "选一个会让评分贴合该题材审美\n(下次会记住选择)",
                    text_color = LrView.kColorGrey,
                    fill_horizontal = 1,
                    height_in_lines = 2,
                },
                f:spacer { height = 6 },
                f:static_text {
                    title = "首张分析约 1 分钟,后续每张 ~10 秒。",
                    text_color = LrView.kColorGrey,
                },
            }

            local result = LrDialogs.presentModalDialog {
                title  = "PixCull · 准备分析",
                contents = contents,
                actionVerb = "开始分析",
                cancelVerb = "取消",
            }
            if result ~= "ok" then return nil end
            prefs.lastVertical = prop.vertical
            return prop.vertical or ""
        end)
end

LrTasks.startAsyncTask(function()
    local catalog = LrApplication.activeCatalog()
    local photos = catalog:getTargetPhotos()
    if #photos == 0 then
        LrDialogs.message("PixCull",
            "请先在 Library 选中一张或多张照片再调用此命令。", "info")
        return
    end

    -- Collect unique parent folders
    local folders = {}
    local seen = {}
    for _, photo in ipairs(photos) do
        local path = photo:getRawMetadata("path")
        if path then
            local dir = LrPathUtils.parent(path)
            if dir and not seen[dir] then
                table.insert(folders, dir)
                seen[dir] = true
            end
        end
    end

    if #folders == 0 then
        LrDialogs.message("PixCull",
            "选中的照片缺少文件路径(可能是 Smart Collection 中的代理),"
            .. "请用 'in Library' 视图选择实文件。", "warning")
        return
    end

    -- V19: ask for vertical via a modal with popup picker
    local vertical = askForVertical(#folders, #photos)
    if vertical == nil then return end   -- cancelled

    -- POST each folder; collect run_ids. Body now includes vertical.
    local runIds = {}
    for _, folder in ipairs(folders) do
        local body
        if vertical and vertical ~= "" then
            body = '{"folder": "' ..
                folder:gsub("\\", "\\\\"):gsub("\"", "\\\"") ..
                '", "vertical": "' .. vertical .. '"}'
        else
            body = '{"folder": "' ..
                folder:gsub("\\", "\\\\"):gsub("\"", "\\\"") .. '"}'
        end
        local response, hdrs = LrHttp.post(
            SERVER_URL .. "/scan_local",
            body,
            {{ field = "Content-Type", value = "application/json" }}
        )
        if response then
            local runId = response:match('"run_id"%s*:%s*"([^"]+)"')
            if runId then
                table.insert(runIds, runId)
            end
        end
    end

    if #runIds == 0 then
        LrDialogs.message("PixCull",
            "未能创建任何 run。请确认 PixCull 服务正在运行(查看顶部菜单栏)。",
            "critical")
        return
    end

    -- Open first run's results page
    LrShell.openPathsInApp({SERVER_URL .. "/results/" .. runIds[1]}, "")

    local label
    if vertical and vertical ~= "" then
        label = ("PixCull · 已启动 %d 个 %s 类分析,浏览器已打开第一个结果"):format(
            #runIds, vertical)
    else
        label = ("PixCull · 已启动 %d 个分析(自动检测题材),浏览器已打开第一个结果"):format(
            #runIds)
    end
    LrDialogs.showBezel(label)
end)
