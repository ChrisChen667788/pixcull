  (function setupSmartCollections() {
    const KEY = `pixcull_collections:${run_id}`;
    function _load() {
      try {
        return JSON.parse(localStorage.getItem(KEY) || "[]");
      } catch (_e) { return []; }
    }
    function _save(arr) {
      try { localStorage.setItem(KEY, JSON.stringify(arr)); }
      catch (_e) {}
    }
    function _saveCurrent() {
      const name = prompt(
        "命名当前筛选+排序组合(例如 '客厅 keep · 时间倒序'):",
        ""
      );
      if (name == null || !name.trim()) return;
      const all = _load();
      const item = {
        name: name.trim().slice(0, 64),
        filter: typeof filterState !== "undefined"
                  ? JSON.parse(JSON.stringify(filterState))
                  : null,
        sort: (typeof sortBy === "string") ? sortBy : "",
        ts: Date.now(),
      };
      // Replace if name dup
      const idx = all.findIndex(x => x.name === item.name);
      if (idx >= 0) all[idx] = item;
      else all.push(item);
      _save(all);
      if (typeof window.toast === "function") {
        window.toast(`★ 保存为收藏:${item.name}`, "info");
      }
    }
    function _restore(name) {
      const all = _load();
      const item = all.find(x => x.name === name);
      if (!item) return;
      if (item.filter && typeof filterState === "object") {
        // v2.15 — restoring a collection replaces the whole filter; drop any
        // active maybe-resolution mode so its later exit can't clobber it.
        if (typeof _exitResolveMaybesSilently === "function") {
          _exitResolveMaybesSilently();
        }
        Object.assign(filterState, item.filter);
      }
      if (item.sort && typeof window.sortBy !== "undefined") {
        window.sortBy = item.sort;
      }
      // v2.13 — `window.render` is NEVER exposed, so the old
      // `window.render()` here was a dead no-op: restoring a collection
      // re-wrote filterState but never repainted.  render()/_rebuildFilterControls()
      // are in lexical scope (this nested IIFE lives inside the main one), so
      // call them directly — repaint the grid AND rebuild the sidebar pills +
      // decision/sort controls from the freshly Object.assign-ed filterState.
      document.querySelectorAll("#decisionPills .pill").forEach(el =>
        el.classList.toggle("active", el.dataset.d === filterState.decision));
      const _sortSel = document.getElementById("sortBy");
      if (_sortSel && typeof filterState.sort === "string") _sortSel.value = filterState.sort;
      if (typeof _rebuildFilterControls === "function") _rebuildFilterControls();
      if (typeof render === "function") render();
      if (typeof window.toast === "function") {
        window.toast(`✦ 已恢复收藏:${item.name}`, "info");
      }
    }
    function _delete(name) {
      const all = _load().filter(x => x.name !== name);
      _save(all);
    }
    window.PixCullCollections = {
      list: _load, saveCurrent: _saveCurrent,
      restore: _restore, delete: _delete,
    };
    // Bind ⌘+S as "save current view as collection"
    document.addEventListener("keydown", ev => {
      if (ev.target.matches("input,textarea,[contenteditable=true]")) return;
      if ((ev.metaKey || ev.ctrlKey) && !ev.shiftKey
          && (ev.key === "s" || ev.key === "S")) {
        ev.preventDefault();
        _saveCurrent();
      }
    });
  })();
