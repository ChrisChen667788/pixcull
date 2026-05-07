--[[
PixCull · Analyze Selected Photos

What it does:
1. Get the selected catalog photos.
2. Extract the unique parent folders.
3. For each folder, POST /scan_local to the local PixCull
   HTTP server, getting back a {run_id}.
4. Open the first run's results page in the default browser.

Why we POST folder-by-folder rather than per-photo: PixCull's
scan-local mode indexes whole folders (it's how zero-copy
works). If the user selected 5 photos from one folder we just
scan that folder; PixCull's UI then lets them filter to the
exact selection by clicking the scene/decision pills.

Future hook (V12): write the resulting decisions back to LR
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

local prefs = LrPrefs.prefsForPlugin()
local SERVER_URL = prefs.serverUrl or "http://127.0.0.1:8770"

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

    -- Confirm with user before launching analysis
    local confirm = LrDialogs.confirm(
        "PixCull · 准备分析",
        ("将扫描 %d 个文件夹(共 %d 张选中照片)。"
         .. "\n\n服务地址: %s\n\n首张分析约 1 分钟,后续每张 ~10 秒。")
            :format(#folders, #photos, SERVER_URL),
        "开始分析", "取消"
    )
    if confirm ~= "ok" then return end

    -- POST each folder; collect run_ids
    local runIds = {}
    for _, folder in ipairs(folders) do
        local postBody = '{"folder": "' ..
            folder:gsub("\\", "\\\\"):gsub("\"", "\\\"") .. '"}'
        local response, hdrs = LrHttp.post(
            SERVER_URL .. "/scan_local",
            postBody,
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

    LrDialogs.showBezel(
        ("PixCull · 已启动 %d 个分析,浏览器已打开第一个结果"):format(#runIds))
end)
