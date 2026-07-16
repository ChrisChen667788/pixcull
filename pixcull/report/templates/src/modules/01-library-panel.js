  (function _initLibraryPanel() {
    const panel = document.getElementById("libraryPanel");
    const backdrop = document.getElementById("libraryPanelBackdrop");
    const btn = document.getElementById("lpCollapseBtn");
    if (!panel || !btn) return;
    const _LP_KEY = "pixcull_lib_panel";
    const isMobile = () => window.matchMedia("(max-width: 900px)").matches;

    function _apply(state) {
      if (isMobile()) {
        // Mobile: "open" shows the drawer, anything else hides it
        panel.classList.toggle("open", state === "open");
        if (backdrop) backdrop.classList.toggle("show", state === "open");
        panel.classList.remove("collapsed");
      } else {
        // Desktop: "collapsed" shrinks to rail, default expanded
        panel.classList.toggle("collapsed", state === "collapsed");
        panel.classList.remove("open");
        if (backdrop) backdrop.classList.remove("show");
      }
    }
    let _state = "expanded";
    try { _state = localStorage.getItem(_LP_KEY) || "expanded"; }
    catch (e) {}
    _apply(_state);

    btn.addEventListener("click", () => {
      if (isMobile()) {
        // Mobile click closes the drawer
        _state = "expanded";   // i.e. "not open"
      } else {
        _state = _state === "collapsed" ? "expanded" : "collapsed";
      }
      try { localStorage.setItem(_LP_KEY, _state); } catch (e) {}
      _apply(_state);
    });
    // Mobile: tap backdrop to close
    if (backdrop) {
      backdrop.addEventListener("click", () => {
        _state = "expanded";   // i.e. not "open"
        try { localStorage.setItem(_LP_KEY, _state); } catch (e) {}
        _apply(_state);
      });
    }
    // Keyboard: "B" toggles the panel (LR-style)
    document.addEventListener("keydown", e => {
      // Ignore when typing in inputs
      if (e.target.matches("input, textarea, select")) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "b" || e.key === "B") {
        e.preventDefault();
        if (isMobile()) {
          // Open / close drawer
          _state = panel.classList.contains("open") ? "expanded" : "open";
        } else {
          _state = _state === "collapsed" ? "expanded" : "collapsed";
        }
        try { localStorage.setItem(_LP_KEY, _state); } catch (e) {}
        _apply(_state);
      }
    });
    // Re-apply on viewport changes so the same persisted state
    // makes sense after a resize across the mobile breakpoint.
    window.addEventListener("resize", () => _apply(_state));
  })();
