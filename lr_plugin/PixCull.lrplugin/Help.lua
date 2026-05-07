--[[ Show plugin help in the default browser via README link. ]]

local LrShell = import "LrShell"
LrShell.openPathsInApp(
    {"https://github.com/your-account/pixcull/blob/main/lr_plugin/README.md"},
    ""
)
