  (function setupMarqueeSelect() {
    const gridEl = document.getElementById("grid");
    const bulkBar = document.getElementById("bulkToolbar");
    const bulkCount = document.getElementById("bulkCount");
    if (!gridEl || !bulkBar) return;

    const selected = new Set();
    let marquee = null;
    let originX = 0, originY = 0;
    let lastSelection = new Set();

    function _updateBulkBar() {
      const n = selected.size;
      if (n === 0) {
        bulkBar.classList.remove("show");
        bulkBar.setAttribute("aria-hidden", "true");
      } else {
        bulkBar.classList.add("show");
        bulkBar.setAttribute("aria-hidden", "false");
        bulkCount.textContent = `${n} 张已选`;
      }
    }

    function _clearSelection() {
      selected.clear();
      for (const c of gridEl.querySelectorAll(".card.marquee-selected")) {
        c.classList.remove("marquee-selected");
      }
      _updateBulkBar();
    }

    function _applySelection(fns) {
      // Reset all currently selected → apply only the new set
      for (const c of gridEl.querySelectorAll(".card.marquee-selected")) {
        c.classList.remove("marquee-selected");
      }
      selected.clear();
      for (const fn of fns) {
        selected.add(fn);
        const c = gridEl.querySelector(
          `.card[data-fn="${CSS.escape(fn)}"]`);
        if (c) c.classList.add("marquee-selected");
      }
      _updateBulkBar();
    }

    function _rectFor(ev) {
      const r = gridEl.getBoundingClientRect();
      const x = ev.clientX - r.left + gridEl.scrollLeft;
      const y = ev.clientY - r.top + gridEl.scrollTop;
      const left   = Math.min(originX, x);
      const top    = Math.min(originY, y);
      const width  = Math.abs(x - originX);
      const height = Math.abs(y - originY);
      return { left, top, width, height };
    }

    function _intersectCards(rect) {
      const out = [];
      const gridRect = gridEl.getBoundingClientRect();
      for (const card of gridEl.querySelectorAll(".card")) {
        const c = card.getBoundingClientRect();
        // Convert to grid-local coords (same basis as `rect`).
        const cLeft = c.left - gridRect.left + gridEl.scrollLeft;
        const cTop  = c.top  - gridRect.top  + gridEl.scrollTop;
        const cR    = cLeft + c.width;
        const cB    = cTop  + c.height;
        const rR    = rect.left + rect.width;
        const rB    = rect.top  + rect.height;
        const intersects = !(cR < rect.left || cLeft > rR ||
                             cB < rect.top  || cTop  > rB);
        if (intersects && card.dataset.fn) out.push(card.dataset.fn);
      }
      return out;
    }

    gridEl.addEventListener("mousedown", ev => {
      // Only fire on plain left-click in grid empty space (not on a card).
      if (ev.button !== 0) return;
      if (ev.target.closest(".card")) return;
      // Cmd/Ctrl/Shift mouseDown extends — we capture the current
      // selection so the marquee operates additively
      const extend = ev.shiftKey || ev.metaKey || ev.ctrlKey;
      lastSelection = extend ? new Set(selected) : new Set();
      const r = gridEl.getBoundingClientRect();
      originX = ev.clientX - r.left + gridEl.scrollLeft;
      originY = ev.clientY - r.top + gridEl.scrollTop;
      marquee = document.createElement("div");
      marquee.className = "grid-marquee";
      marquee.style.left = originX + "px";
      marquee.style.top  = originY + "px";
      marquee.style.width = "0px";
      marquee.style.height = "0px";
      gridEl.appendChild(marquee);
      ev.preventDefault();
    });

    window.addEventListener("mousemove", ev => {
      if (!marquee) return;
      const rect = _rectFor(ev);
      marquee.style.left = rect.left + "px";
      marquee.style.top  = rect.top  + "px";
      marquee.style.width = rect.width + "px";
      marquee.style.height = rect.height + "px";
      const hit = _intersectCards(rect);
      const combined = new Set([...lastSelection, ...hit]);
      _applySelection(combined);
    });

    window.addEventListener("mouseup", () => {
      if (!marquee) return;
      // Discard tiny drags (treat as click → clear) — saves us from
      // accidental click-to-clear when the user double-clicks empty
      // space.
      const w = parseFloat(marquee.style.width || "0");
      const h = parseFloat(marquee.style.height || "0");
      if (w < 6 && h < 6) _clearSelection();
      try { marquee.remove(); } catch (e) {}
      marquee = null;
    });

    // Escape clears
    document.addEventListener("keydown", ev => {
      if (ev.key === "Escape" && selected.size > 0) {
        _clearSelection();
      }
      // Cmd/Ctrl+A selects all visible (Lightroom parity)
      if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === "a") {
        // Don't fight with form inputs
        if (ev.target.matches("input,textarea,[contenteditable=true]")) return;
        ev.preventDefault();
        const all = Array.from(gridEl.querySelectorAll(".card"))
          .map(c => c.dataset.fn).filter(Boolean);
        _applySelection(new Set(all));
      }
    });

    // Bulk-bar button wiring.  We dispatch a CustomEvent on document
    // so the page-level keep/cull/bucket handlers can react without
    // this module needing to know their internals.
    bulkBar.addEventListener("click", ev => {
      const b = ev.target.closest(".bulk-btn");
      if (!b) return;
      const action = b.dataset.action;
      if (action === "clear") { _clearSelection(); return; }
      // Snapshot the selection — the action handler may mutate the
      // DOM and re-render cards, clearing the Set we hold.
      const fns = Array.from(selected);
      const detail = { action, filenames: fns };
      document.dispatchEvent(
        new CustomEvent("pixcull:bulk-action", { detail }));
      // For keep/maybe/cull we can apply optimistically by calling
      // the per-card decision endpoint.  If the page already wires
      // a custom listener (preferred), this is a no-op for it.
      if (["keep", "maybe", "cull"].includes(action)) {
        _bulkDecideFallback(fns, action);
      }
      _clearSelection();
    });

    // Fallback bulk decide — uses the same /set_decision endpoint
    // that the per-card buttons use. If the page already wires a
    // bulk-action handler, the dispatched event preceded this; we
    // run anyway and the server is idempotent (last write wins).
    async function _bulkDecideFallback(fns, action) {
      if (typeof window.run_id !== "string") return;
      const rid = window.run_id;
      for (const fn of fns) {
        try {
          await fetch(`/set_decision/${rid}/` +
                      encodeURIComponent(fn), {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ decision: action }),
          });
          // Update the card's decision class so the user sees feedback
          const card = gridEl.querySelector(
            `.card[data-fn="${CSS.escape(fn)}"]`);
          if (card) {
            card.classList.remove("dec-keep", "dec-maybe", "dec-cull");
            card.classList.add("dec-" + action);
          }
          // v2.15-P0 — the fallback used to patch ONLY the card DOM: the
          // rows[] entry and header tallies went stale, so the next
          // render() silently reverted the visual state (the v2.13 bug
          // class). Sync the in-memory row + stats + review progress too.
          try {
            const row = (typeof rows !== "undefined" ? rows : [])
              .find(x => x && x.filename === fn);
            if (row) {
              if (typeof _shiftStatCounts === "function") {
                _shiftStatCounts(row.decision, action);
              }
              row.decision = action;
              row.rubric_human_labeled = true;
              if (action !== "cull") row.cull_reason = "";
            }
            if (typeof _markReviewed === "function") _markReviewed(fn);
          } catch (_e) { /* stats best-effort; server state is canonical */ }
        } catch (e) { /* swallow — next attempt will see fresh state */ }
      }
      // Surface a toast — uses page-level toast() if present, else
      // a one-liner alert (which we don't want, so swallow silently).
      if (typeof window.toast === "function") {
        window.toast(`已将 ${fns.length} 张标记为 ${action}`, "info");
      }
    }

    // Expose API so other modules can opt into the same selection
    window.PixCullMarquee = {
      selected: () => new Set(selected),
      clear: _clearSelection,
      apply: fns => _applySelection(new Set(fns)),
    };
  })();
