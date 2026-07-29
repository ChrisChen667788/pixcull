  (function setupThemeToggle() {
    // ==================================================================
    // v0.4 P2 (1/4) — light / dark theme toggle.
    //
    // State machine: dark → light → system → (back to dark).  Three
    // explicit states because users want a manual override AND a
    // "follow my OS" default.  Persisted in
    // localStorage[pixcull_theme] as "dark" / "light" / "system".
    //
    // Auto-apply on init based on (a) persisted pref, OR (b)
    // prefers-color-scheme media query if no pref.  matchMedia
    // listener catches OS changes while "system" is selected.
    // ==================================================================
    const _THEME_KEY = "pixcull_theme";
    const _themeBtn   = document.getElementById("themeToggleBtn");
    const _themeIcon  = document.getElementById("themeToggleIcon");
    const _themeLabel = document.getElementById("themeToggleLabel");
    const _mqLight = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)");

    function _effectiveTheme(pref) {
      if (pref === "light" || pref === "dark") return pref;
      return (_mqLight && _mqLight.matches) ? "light" : "dark";
    }
    function _renderTheme(pref) {
      const eff = _effectiveTheme(pref);
      document.documentElement.setAttribute("data-theme", eff);
      if (_themeIcon) {
        _themeIcon.firstElementChild.setAttribute(
          "href", eff === "light" ? "#icon-sun" : "#icon-moon"
        );
      }
      if (_themeLabel) {
        _themeLabel.textContent =
          pref === "system" ? "跟随系统"
          : pref === "light" ? "浅色"
          : "深色";
      }
      if (_themeBtn) {
        _themeBtn.setAttribute("aria-pressed",
          eff === "light" ? "true" : "false");
      }
    }
    // Init
    let _themePref = "system";
    try { _themePref = localStorage.getItem(_THEME_KEY) || "system"; }
    catch (e) { /* localStorage disabled — fall back to system */ }
    if (!["dark", "light", "system"].includes(_themePref)) _themePref = "system";
    _renderTheme(_themePref);
    // Listen for OS theme changes while in "system" mode
    if (_mqLight && _mqLight.addEventListener) {
      _mqLight.addEventListener("change", () => {
        if (_themePref === "system") _renderTheme(_themePref);
      });
    }
    if (_themeBtn) {
      _themeBtn.addEventListener("click", () => {
        // Cycle through the three states
        _themePref = _themePref === "dark" ? "light"
                    : _themePref === "light" ? "system"
                    : "dark";
        try { localStorage.setItem(_THEME_KEY, _themePref); } catch (e) {}
        _renderTheme(_themePref);
        if (typeof toast === "function") {
          const label = _themePref === "system" ? "跟随系统"
                      : _themePref === "light" ? "浅色主题"
                      : "深色主题";
          toast(`已切换:${label}`, "info", 1800);
        }
      });
    }

  })();
