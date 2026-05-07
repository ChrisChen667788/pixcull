--[[
PixCull · Plugin settings dialog.

Lets the user change the server URL (default 127.0.0.1:8770) in
case they run PixCull on a different port or on a LAN host.
Settings persist via LrPrefs across LR restarts.
]]

local LrFunctionContext = import "LrFunctionContext"
local LrBinding = import "LrBinding"
local LrDialogs = import "LrDialogs"
local LrView = import "LrView"
local LrPrefs = import "LrPrefs"

local prefs = LrPrefs.prefsForPlugin()

LrFunctionContext.callWithContext("PixCullSettings", function(ctx)
    local f = LrView.osFactory()
    local props = LrBinding.makePropertyTable(ctx)
    props.serverUrl = prefs.serverUrl or "http://127.0.0.1:8770"

    local contents = f:column {
        bind_to_object = props,
        spacing = f:control_spacing(),
        f:row {
            f:static_text {
                title = "PixCull 服务地址:",
                width = 100,
            },
            f:edit_field {
                value = LrView.bind("serverUrl"),
                width_in_chars = 30,
                immediate = true,
            },
        },
        f:static_text {
            title = "默认 http://127.0.0.1:8770(本地)。\n"
                 .. "如果 PixCull 跑在 LAN,改成 http://<host-ip>:8770。",
            font = "<system/small>",
            text_color = LrView.kColorTitle,
        },
    }

    local result = LrDialogs.presentModalDialog {
        title = "PixCull 设置",
        contents = contents,
    }

    if result == "ok" then
        prefs.serverUrl = props.serverUrl
        LrDialogs.showBezel("PixCull · 设置已保存")
    end
end)
