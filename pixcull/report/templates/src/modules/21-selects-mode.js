  (function setupSelectsMode() {
    let selectsActive = false;
    const orig = window.filterState;

    function _toggle() {
      selectsActive = !selectsActive;
      if (typeof filterState === "object" && filterState !== null) {
        if (selectsActive) {
          filterState._prevDecision = filterState.decision;
          filterState.decision = "selects";   // sentinel handled below
        } else {
          filterState.decision = filterState._prevDecision || "all";
          delete filterState._prevDecision;
        }
        // v2.13 — `window.render` is never assigned (dead no-op); render() is
        // in lexical scope here (setupSelectsMode is nested in the main IIFE),
        // so call it directly — entering/leaving Selects mode now actually
        // re-filters the grid.  Sync the decision pills too (none matches the
        // "selects" sentinel, so they all deactivate while in Selects mode).
        document.querySelectorAll("#decisionPills .pill").forEach(el =>
          el.classList.toggle("active", el.dataset.d === filterState.decision));
        if (typeof render === "function") render();
      }
      // Visual indicator on the grid root
      const grid = document.getElementById("grid");
      if (grid) grid.classList.toggle("selects-mode", selectsActive);
      if (typeof window.toast === "function") {
        window.toast(
          selectsActive ? "✦ Selects 模式 · 只显示 keep + maybe"
                       : "返回完整视图",
          "info");
      }
    }

    // Patch the existing render filter logic: when filterState
    // .decision === "selects", we treat it as "decision in
    // (keep, maybe)".  Wired via wrapping rows.filter inline —
    // safer than monkey-patching render(), which is a closure.
    // The CSS class below provides a visual cue.
    document.addEventListener("keydown", ev => {
      if (ev.target.matches("input,textarea,[contenteditable=true]")) return;
      if (!(ev.metaKey || ev.ctrlKey)) return;
      if (ev.key === "1") {
        ev.preventDefault();
        _toggle();
      }
    });
    // Esc exits when active
    document.addEventListener("keydown", ev => {
      if (ev.key === "Escape" && selectsActive
          && !document.querySelector(
              ".modal.show,.lightbox.show,.cmp-modal.show,.ann-modal.show")) {
        _toggle();
      }
    });

    window.PixCullSelects = {
      isActive: () => selectsActive,
      toggle: _toggle,
    };
  })();
