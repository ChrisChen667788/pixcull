--[[ Open the PixCull web UI in the default browser. ]]

local LrShell = import "LrShell"
local LrPrefs = import "LrPrefs"

local prefs = LrPrefs.prefsForPlugin()
local SERVER_URL = prefs.serverUrl or "http://127.0.0.1:8770"

LrShell.openPathsInApp({SERVER_URL .. "/"}, "")
