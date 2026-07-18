  (function setupBookmarkAndConflicts() {
    // -- Bookmark state -- localStorage mirror of server state,
    // queried lazily on lightbox open.  Round-trips happen via
    // POST /api/v1/bookmark.
    const _bookmarkCache = new Set();   // run-local Set<filename>
    let _bookmarksLoaded = false;

    async function _loadBookmarks() {
      try {
        const r = await fetch(
          `/api/v1/bookmarks?run=${encodeURIComponent(run_id)}`);
        if (!r.ok) return;
        const d = await r.json();
        if (d && Array.isArray(d.bookmarks)) {
          d.bookmarks.forEach(b => _bookmarkCache.add(b.filename));
          _bookmarksLoaded = true;
          _refreshBookmarkBadges();
        }
      } catch (_e) { /* offline / endpoint missing — ignore */ }
    }

    function _refreshBookmarkBadges() {
      document.querySelectorAll("#grid .card").forEach(c => {
        const fn = c.dataset.fn;
        if (!fn) return;
        const has = _bookmarkCache.has(fn);
        let badge = c.querySelector(".bookmark-badge");
        if (has && !badge) {
          badge = document.createElement("span");
          badge.className = "bookmark-badge";
          badge.title = "已加书签 · 按 B 取消";
          badge.textContent = "★";
          badge.style.cssText = (
            "position:absolute;top:6px;right:6px;width:22px;height:22px;" +
            "display:flex;align-items:center;justify-content:center;" +
            "background:rgba(213,181,132,0.85);color:#fff;" +
            "border-radius:4px;font-size:14px;z-index:2;" +
            "pointer-events:none;box-shadow:0 1px 4px rgba(0,0,0,0.4);"
          );
          c.appendChild(badge);
        } else if (!has && badge) {
          badge.remove();
        }
      });
    }

    async function _toggleBookmark(fn) {
      if (!fn) return;
      try {
        const r = await fetch("/api/v1/bookmark", {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ run_id: run_id, filename: fn }),
        });
        if (!r.ok) throw new Error("HTTP " + r.status);
        const d = await r.json();
        if (d.is_bookmarked) _bookmarkCache.add(fn);
        else _bookmarkCache.delete(fn);
        _refreshBookmarkBadges();
        if (typeof window.toast === "function") {
          window.toast(
            d.is_bookmarked ? "★ 已加书签" : "已移除书签", "info");
        }
      } catch (_e) {
        if (typeof window.toast === "function") {
          window.toast("书签操作失败 — 服务器无响应", "warn");
        }
      }
    }

    // Public on window so other modules can call programmatically
    window.PixCullBookmark = {
      toggle: _toggleBookmark,
      isBookmarked: fn => _bookmarkCache.has(fn),
    };

    // Load bookmarks lazily on page mount
    document.addEventListener("DOMContentLoaded", _loadBookmarks);
    if (document.readyState !== "loading") _loadBookmarks();

    // Wire `B` shortcut — works in grid + lightbox, ignored in inputs
    document.addEventListener("keydown", ev => {
      if (ev.target.matches("input,textarea,[contenteditable=true]")) return;
      if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
      if (ev.key !== "b" && ev.key !== "B") return;
      // Resolve target filename: lightbox > focused card > nothing
      let fn = null;
      if (typeof _lbCurrentFn === "string" && _lbCurrentFn) {
        fn = _lbCurrentFn;
      } else {
        const focused = document.activeElement &&
                        document.activeElement.closest(".card");
        if (focused) fn = focused.dataset.fn;
      }
      if (!fn) return;
      ev.preventDefault();
      _toggleBookmark(fn);
    });

    // Refresh badges after render() (when filters/sort change DOM)
    if (typeof window.MutationObserver === "function") {
      const gridEl = document.getElementById("grid");
      if (gridEl) {
        const mo = new MutationObserver(() => _refreshBookmarkBadges());
        mo.observe(gridEl, { childList: true });
      }
    }
  })();
