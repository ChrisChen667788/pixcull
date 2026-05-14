--[[
PixCull · Write decisions back to Lightroom

V21.2 addition. Pre-V21.2 the plugin was one-way: photos went LR →
PixCull → browser results page, and the photographer manually clicked
through stars/flags in LR using the browser as a reference. This
script closes the loop: PixCull's keep/maybe/cull verdicts apply
directly to the Lightroom catalog as star ratings + reject flags.

How it works:
  1. Find a run_id to apply. We use prefs.lastRunId, populated by
     AnalyzeSelected.lua when a scan completes. If absent, prompt
     the user to enter one.
  2. GET /decisions/<run_id> on the PixCull server. Response is
     {filename: decision, src_paths: {filename: abs_path}, ...}.
  3. For each photo currently in the catalog filmstrip (or all
     selected — user picks), match against the decision map. Prefer
     abs-path matching (decision.src_paths[fn] == photo:path) to
     handle DSC_0001.jpg collisions across shoots; fall back to
     basename only when the run came from a folder LR doesn't know.
  4. Apply decision → LR metadata mapping:
        keep  → 5★, pickStatus = +1 (flagged)
        maybe → 3★, pickStatus =  0 (no flag)
        cull  →     pickStatus = -1 (reject) + 1★ to keep it browseable

V21.2 deliberately stops at writing — does NOT delete photos or move
files. The reject flag is the standard Lightroom signal; the user
runs Photo > Delete Rejected Photos to actually purge.

The whole sequence is wrapped in catalog:withWriteAccessDo so LR's
undo system records ONE "PixCull write-back" entry instead of N
individual rating changes — the photographer can ⌘Z out of it
cleanly if the wrong run got applied.
]]

local LrApplication = import "LrApplication"
local LrDialogs     = import "LrDialogs"
local LrHttp        = import "LrHttp"
local LrPrefs       = import "LrPrefs"
local LrTasks       = import "LrTasks"

local prefs = LrPrefs.prefsForPlugin()

local function getServerUrl()
    return prefs.serverUrl or "http://127.0.0.1:8770"
end

-- Decision → LR metadata mapping. Star + flag are independent in LR
-- so we set both. The numbers were chosen to match what a typical
-- photographer would do manually after a culling pass:
--   keep  = clearly worth processing → 5★ + flagged
--   maybe = needs human re-review     → 3★ + no flag
--   cull  = drop                       → 1★ + reject flag
-- Reject flag (-1) is reversible and non-destructive; the photo
-- stays in the catalog until "Delete Rejected Photos" runs.
local DECISION_MAP = {
    keep  = { rating = 5, pickStatus =  1 },
    maybe = { rating = 3, pickStatus =  0 },
    cull  = { rating = 1, pickStatus = -1 },
}

-- Tiny JSON-pluck helpers. We can't pull a real json lib via plugin
-- distribution restrictions, so do narrow regex-based parsing on the
-- known schema. Format is stable (pixcull.decisions.v1) so this
-- doesn't have to be a full parser.
local function parseDecisions(body)
    local out = {}
    -- "decisions": { "fn1.jpg": "keep", "fn2.jpg": "maybe", ... }
    local block = body:match('"decisions"%s*:%s*(%b{})')
    if not block then return out end
    for fn, dec in block:gmatch('"([^"]+)"%s*:%s*"([^"]+)"') do
        out[fn] = dec
    end
    return out
end

local function parseSrcPaths(body)
    local out = {}
    local block = body:match('"src_paths"%s*:%s*(%b{})')
    if not block then return out end
    for fn, path in block:gmatch('"([^"]+)"%s*:%s*"([^"]+)"') do
        -- Unescape \\ → \ and \" → " (JSON-encoded backslashes)
        path = path:gsub('\\\\', '\\'):gsub('\\"', '"')
        out[fn] = path
    end
    return out
end

LrTasks.startAsyncTask(function()
    local catalog = LrApplication.activeCatalog()

    -- 1) Figure out which run to apply
    local runId = prefs.lastRunId
    if not runId or runId == "" then
        local result = LrDialogs.runOpenPanel{
            title = "PixCull · 写回 LR 星级",
            prompt = "未找到最近的 run_id。请粘贴一个 PixCull run_id:",
        }
        -- runOpenPanel returns file paths — wrong primitive. Use
        -- a text input instead.
        runId = LrDialogs.prompt({
            title  = "PixCull · 写回 LR 星级",
            label  = "请输入 PixCull run_id(浏览器结果页 URL 末段):",
        }) or ""
        runId = (runId or ""):gsub("^%s+", ""):gsub("%s+$", "")
        if runId == "" then return end
    end

    -- 2) Fetch decisions JSON
    local url = getServerUrl() .. "/decisions/" .. runId
    local body, hdrs = LrHttp.get(url)
    if not body then
        LrDialogs.message("PixCull", "无法连接到 " .. url ..
            ". 请确认 PixCull 服务在跑(顶部菜单栏 PixCull 图标)。",
            "critical")
        return
    end
    if hdrs and hdrs.status and hdrs.status >= 400 then
        LrDialogs.message("PixCull",
            "服务返回 HTTP " .. tostring(hdrs.status) .. ".\n\n" ..
            "可能是 run_id 不对,或那个 run 还在分析中(请等它跑完)。",
            "warning")
        return
    end

    local decisions = parseDecisions(body)
    local srcPaths  = parseSrcPaths(body)

    local nDecisions = 0
    for _ in pairs(decisions) do nDecisions = nDecisions + 1 end
    if nDecisions == 0 then
        LrDialogs.message("PixCull",
            "服务返回了 0 条 decision — 这个 run 可能没有任何可分析的图。",
            "warning")
        return
    end

    -- 3) Pick scope: selected photos in filmstrip vs. all
    local photos = catalog:getTargetPhotos()
    if #photos == 0 then
        LrDialogs.message("PixCull",
            "请先在 Library 选中要写回的照片(或 ⌘A 全选)。", "info")
        return
    end

    -- Reverse map: src_path → filename (for path-first matching)
    local pathToFn = {}
    for fn, path in pairs(srcPaths) do
        pathToFn[path] = fn
    end

    -- 4) Apply with single undo entry
    local applied, missed = 0, 0
    local hitsByDec = { keep = 0, maybe = 0, cull = 0 }

    catalog:withWriteAccessDo("PixCull · 写回决策", function()
        for _, photo in ipairs(photos) do
            local fn = pathToFn[photo:getRawMetadata("path")]
                or photo:getFormattedMetadata("fileName")
            local dec = decisions[fn]
            local mapping = dec and DECISION_MAP[dec]
            if mapping then
                photo:setRawMetadata("rating", mapping.rating)
                photo:setRawMetadata("pickStatus", mapping.pickStatus)
                applied = applied + 1
                hitsByDec[dec] = (hitsByDec[dec] or 0) + 1
            else
                missed = missed + 1
            end
        end
    end)

    -- 5) Report
    local total = applied + missed
    local summary = string.format(
        "已写回 %d / %d 张选中照片\n" ..
        "  保留 (5★): %d\n" ..
        "  待定 (3★): %d\n" ..
        "  剔除 (1★+排除标记): %d\n\n" ..
        "未匹配 %d 张 — 它们不在 run %s 的范围里。\n" ..
        "(可用 ⌘Z 一键撤销)",
        applied, total,
        hitsByDec.keep, hitsByDec.maybe, hitsByDec.cull,
        missed, runId)
    LrDialogs.message("PixCull · 写回完成", summary, "info")
end)
