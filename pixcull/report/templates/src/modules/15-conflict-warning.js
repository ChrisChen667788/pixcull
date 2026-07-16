  (function setupConflictWarning() {
    let _conflictsCache = null;
    async function _loadConflicts() {
      try {
        const r = await fetch(
          `/api/v1/conflicts?run=${encodeURIComponent(run_id)}`);
        if (!r.ok) return;
        const d = await r.json();
        if (d && d.conflicts) _conflictsCache = d.conflicts;
      } catch (_e) {}
    }
    document.addEventListener("DOMContentLoaded", _loadConflicts);
    if (document.readyState !== "loading") _loadConflicts();

    // Hook into the Inspector via DOM-observer:  renderInfoPane is
    // closure-scoped (defined OUTSIDE the IIFE but not on window),
    // so we can't monkey-patch the function — instead we watch the
    // #lbInfo container for content changes and inject a conflict
    // banner when the current photo has a recorded conflict.
    const lbInfo = document.getElementById("lbInfo");
    if (lbInfo) {
      const mo = new MutationObserver(() => {
        if (!_conflictsCache || typeof _lbCurrentFn !== "string") return;
        const conflict = _conflictsCache[_lbCurrentFn];
        if (!conflict) return;
        // Don't re-inject if already there
        if (lbInfo.querySelector(".conflict-warning")) return;
        const prevLabel = {
          keep:  "✓ keep",
          maybe: "? maybe",
          cull:  "✕ cull",
        }[conflict.previous_decision] || conflict.previous_decision;
        const banner = document.createElement("div");
        banner.className = "conflict-warning";
        banner.style.cssText = (
          "margin:8px 0;padding:8px 12px;border-radius:6px;" +
          "background:rgba(245,158,11,0.10);" +
          "border-left:3px solid #f59e0b;font-size:11.5px"
        );
        banner.innerHTML = (
          "<div style='color:#fbbf24;font-weight:600;margin-bottom:2px'>" +
          "⚠ 你之前选了不同决策</div>" +
          "<div style='color:#bbb;line-height:1.5'>" +
          "Run <code style='font-family:ui-monospace,Menlo;" +
          "font-size:10.5px;background:rgba(255,255,255,0.08);" +
          "padding:1px 4px;border-radius:3px'>" +
          (conflict.previous_run_id || "").slice(0, 8) +
          "</code> 标 " + prevLabel + " · 现在标 " +
          conflict.current_decision + " — 改主意了?" +
          "</div>"
        );
        // Insert right after the first <h3> if present, else at top
        const firstH3 = lbInfo.querySelector("h3");
        if (firstH3 && firstH3.nextSibling) {
          firstH3.parentNode.insertBefore(banner, firstH3.nextSibling);
        } else {
          lbInfo.prepend(banner);
        }
      });
      mo.observe(lbInfo, { childList: true, subtree: false });
    }
  })();
