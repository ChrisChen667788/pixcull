  (function setupUndoStack() {
    const MAX = 50;
    const undoStack = [];
    const redoStack = [];

    function _pushUndo(filename, prevDecision, newDecision) {
      if (!filename) return;
      undoStack.push({ filename, prev: prevDecision, next: newDecision,
                       ts: Date.now() });
      if (undoStack.length > MAX) undoStack.shift();
      redoStack.length = 0;   // any new action invalidates redo
    }

    // Wrap setDecision so each call records an undo entry.  We hook
    // via window.setDecision since that's how external buttons +
    // bulk toolbar call into it.
    if (typeof window.setDecision === "function") {
      const orig = window.setDecision;
      window.setDecision = function(fn, dec, ...rest) {
        const row = (typeof rows !== "undefined" ? rows : [])
          .find(r => r && r.filename === fn);
        const prev = row ? row.decision : null;
        _pushUndo(fn, prev, dec);
        return orig.apply(this, [fn, dec, ...rest]);
      };
    }

    async function _undo() {
      if (!undoStack.length) {
        if (typeof window.toast === "function") {
          window.toast("没有可撤销的操作", "info");
        }
        return;
      }
      const e = undoStack.pop();
      redoStack.push(e);
      // Restore the previous decision via the original endpoint
      // directly (bypasses the wrapped setDecision so we don't
      // poison the stack).
      try {
        await fetch(`/set_decision/${run_id}/${encodeURIComponent(e.filename)}`, {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ decision: e.prev || "" }),
        });
        // Update the row + card
        const row = (typeof rows !== "undefined" ? rows : [])
          .find(r => r && r.filename === e.filename);
        if (row) {
          // v2.15-P0 — keep header tallies (and summary.n_maybe, which the
          // maybe-resolution auto-exit reads) in sync with the restore.
          if (typeof _shiftStatCounts === "function") {
            _shiftStatCounts(row.decision, e.prev);
          }
          row.decision = e.prev;
        }
        const card = document.querySelector(
          `#grid .card[data-fn="${CSS.escape(e.filename)}"]`);
        if (card) {
          card.classList.remove("dec-keep", "dec-maybe", "dec-cull");
          if (e.prev) card.classList.add("dec-" + e.prev);
        }
        if (typeof window.toast === "function") {
          window.toast(
            `↩ 撤销 · ${e.filename} 回到 ${e.prev || "未标注"}`, "info");
        }
      } catch (_e) {
        if (typeof window.toast === "function") {
          window.toast("撤销失败 · 服务器无响应", "warn");
        }
      }
    }

    async function _redo() {
      if (!redoStack.length) {
        if (typeof window.toast === "function") {
          window.toast("没有可重做的操作", "info");
        }
        return;
      }
      const e = redoStack.pop();
      undoStack.push(e);
      try {
        await fetch(`/set_decision/${run_id}/${encodeURIComponent(e.filename)}`, {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ decision: e.next || "" }),
        });
        const row = (typeof rows !== "undefined" ? rows : [])
          .find(r => r && r.filename === e.filename);
        if (row) {
          // v2.15-P0 — same tally sync as _undo (see comment there).
          if (typeof _shiftStatCounts === "function") {
            _shiftStatCounts(row.decision, e.next);
          }
          row.decision = e.next;
        }
        const card = document.querySelector(
          `#grid .card[data-fn="${CSS.escape(e.filename)}"]`);
        if (card) {
          card.classList.remove("dec-keep", "dec-maybe", "dec-cull");
          if (e.next) card.classList.add("dec-" + e.next);
        }
        if (typeof window.toast === "function") {
          window.toast(`↪ 重做 · ${e.filename} = ${e.next}`, "info");
        }
      } catch (_e) {}
    }

    document.addEventListener("keydown", ev => {
      if (ev.target.matches("input,textarea,[contenteditable=true]")) return;
      const meta = ev.metaKey || ev.ctrlKey;
      if (!meta) return;
      if (ev.key === "z" || ev.key === "Z") {
        if (ev.shiftKey) {
          ev.preventDefault();
          _redo();
        } else {
          ev.preventDefault();
          _undo();
        }
      }
    });

    window.PixCullUndo = {
      undo: _undo, redo: _redo,
      stack: () => undoStack.slice(),
    };
  })();
