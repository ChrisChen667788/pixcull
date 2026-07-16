  // v2.20(#8) — the last loose subsystem gets its module walls:
  // everything ⌘K lives here; internals are invisible outside.
  (function setupCmdkPalette() {
    // ============================================================
    // v0.9-P0-4 — Cmd+K command palette.
    //
    // Linear/Raycast/Notion-grade keyboard-first action entry.
    // Builds a static action registry on boot, augmented at
    // open-time with dynamic items (view presets, buckets) read
    // from localStorage.  Fuzzy matcher is a simple subsequence
    // scorer with contiguous + prefix bonuses — no library, ~60
    // lines.  Keyboard: ⌘K / Ctrl+K opens; ↑↓ moves; ↵ fires;
    // Esc closes; click on a row fires.
    // ============================================================
    const cmdkModal   = document.getElementById("cmdkModal");
    const cmdkInput   = document.getElementById("cmdkInput");
    const cmdkResults = document.getElementById("cmdkResults");
    const _CMDK_RECENT_KEY = "pixcull_cmdk_recent";
    let _cmdkOpen = false;
    let _cmdkItems = [];        // current filtered+sorted items
    let _cmdkActiveIdx = 0;

    // --- Static action registry (built once) ---
    // group ordering shapes the "primary surface" of the palette;
    // dynamic items (presets / buckets) appended at open-time.
    function _cmdkStaticActions() {
      return [
        // Decisions
        { id: "dec.all",   label: "筛选: 全部", group: "筛选",
          hint: "all", icon: "○",
          run: () => _cmdkPickDecision("all") },
        { id: "dec.keep",  label: "筛选: 仅 keep", group: "筛选",
          hint: "1", icon: "●",
          run: () => _cmdkPickDecision("keep") },
        { id: "dec.maybe", label: "筛选: 仅 maybe", group: "筛选",
          hint: "2", icon: "●",
          run: () => _cmdkPickDecision("maybe") },
        { id: "dec.cull",  label: "筛选: 仅 cull", group: "筛选",
          hint: "3", icon: "●",
          run: () => _cmdkPickDecision("cull") },
        { id: "filter.reset", label: "重置所有筛选", group: "筛选",
          hint: "", icon: "↺",
          run: () => _cmdkResetFilters() },
        // Sort
        { id: "sort.default",     label: "排序: 默认",          group: "排序",
          hint: "", icon: "≡", run: () => _cmdkPickSort("default") },
        { id: "sort.score_desc",  label: "排序: 总分高 → 低",    group: "排序",
          hint: "", icon: "↓", run: () => _cmdkPickSort("score_desc") },
        { id: "sort.score_asc",   label: "排序: 总分低 → 高",    group: "排序",
          hint: "", icon: "↑", run: () => _cmdkPickSort("score_asc") },
        { id: "sort.cluster",     label: "排序: 按连拍聚类",      group: "排序",
          hint: "", icon: "⫶", run: () => _cmdkPickSort("cluster") },
        { id: "sort.style_dist",  label: "排序: 🎨 像我风格的优先", group: "排序",
          hint: "", icon: "🎨", run: () => _cmdkPickSort("style_distance_asc") },
        // Language
        { id: "lang.zh", label: "切换语言: 中文",   group: "语言",
          hint: "", icon: "中", run: () => _cmdkApplyLang("zh_CN") },
        { id: "lang.en", label: "Switch language: English", group: "语言",
          hint: "", icon: "EN", run: () => _cmdkApplyLang("en_US") },
        { id: "lang.ja", label: "言語切替: 日本語",   group: "语言",
          hint: "", icon: "あ", run: () => _cmdkApplyLang("ja_JP") },
        // Actions
        { id: "act.train_style", label: "🎨 训练风格模型", group: "操作",
          hint: "", icon: "🎨",
          run: () => document.getElementById("styleTrainBtn")?.click() },
        { id: "act.share_link",  label: "🔗 生成客户分享链接", group: "操作",
          hint: "", icon: "🔗",
          run: () => document.getElementById("shareLinkBtn")?.click() },
        { id: "act.sync_event",  label: "📡 生成协作会话", group: "操作",
          hint: "", icon: "📡",
          run: () => document.getElementById("syncEventBtn")?.click() },
        { id: "act.toggle_library", label: "切换 Library 侧栏", group: "操作",
          hint: "B", icon: "▣",
          run: () => document.getElementById("lpCollapseBtn")?.click() },
        { id: "act.toggle_buckets", label: "打开 / 关闭 桶面板", group: "操作",
          hint: "", icon: "🪣",
          run: () => document.getElementById("bucketsToggleBtn")?.click() },
        { id: "act.shortcuts",   label: "显示所有快捷键", group: "操作",
          hint: "?", icon: "⌨",
          run: () => showShortcuts() },
        // Export
        { id: "exp.xmp",   label: "导出: 下载 XMP zip", group: "导出",
          hint: "", icon: "↓",
          run: () => document.getElementById("exportZipBtn")?.click() },
        { id: "exp.csv",   label: "导出: 下载 CSV",     group: "导出",
          hint: "", icon: "↓",
          run: () => document.getElementById("csvBtn")?.click() },
        { id: "exp.json",  label: "导出: 结构化 JSON",  group: "导出",
          hint: "", icon: "↓",
          run: () => document.getElementById("jsonStructuredBtn")?.click() },
        { id: "exp.gallery", label: "导出: HTML 相册",   group: "导出",
          hint: "", icon: "📔",
          run: () => document.getElementById("galleryBtn")?.click() },
        // Navigation
        { id: "nav.history", label: "去: 🕒 历史时间线", group: "导航",
          hint: "", icon: "↗", run: () => { location.href = "/history"; } },
        { id: "nav.tether",  label: "去: 📡 Tethered Live", group: "导航",
          hint: "", icon: "↗", run: () => { location.href = "/tether"; } },
        { id: "nav.upload",  label: "去: 上传新一批",  group: "导航",
          hint: "", icon: "↗", run: () => { location.href = "/"; } },
        { id: "nav.admin",   label: "去: 存储管理",     group: "导航",
          hint: "", icon: "↗", run: () => { location.href = "/admin"; } },
      ];
    }

    // Dynamic items: view presets + bucket assignments — read at
    // open-time so palette stays fresh as the user creates more.
    function _cmdkDynamicActions() {
      const out = [];
      // View presets
      try {
        const presets = JSON.parse(
          localStorage.getItem("pixcull_view_presets_v1") || "{}");
        Object.keys(presets).sort().forEach(name => {
          out.push({
            id: "preset." + name,
            label: "应用视图预设: " + name,
            group: "视图预设",
            hint: "",
            icon: "★",
            run: () => {
              if (typeof _applyView === "function") _applyView(presets[name]);
              else showToast("视图预设应用失败 — _applyView 未定义", "error");
            },
          });
        });
      } catch (_e) {}
      // Buckets
      try {
        const buckets = JSON.parse(
          localStorage.getItem(`pixcull_buckets:${run_id}`) || "{}");
        Object.keys(buckets).sort().forEach(name => {
          const n = (buckets[name] || []).length;
          out.push({
            id: "bucket." + name,
            label: `筛选: 桶 “${name}” (${n} 张)`,
            group: "桶",
            hint: "",
            icon: "🪣",
            run: () => {
              // Reuse the existing "filter by bucket" handler logic
              if (typeof filterState !== "undefined") {
                filterState.semSearch = {
                  q: `🪣 ${name}`,
                  filenames: new Set(buckets[name] || []),
                };
                const sin = document.getElementById("semSearchInput");
                const sclr = document.getElementById("semSearchClearBtn");
                if (sin) sin.value = `🪣 ${name}`;
                if (sclr) sclr.style.display = "";
                render();
              }
            },
          });
        });
      } catch (_e) {}
      return out;
    }

    // --- Fuzzy matcher (subsequence + contiguous + prefix bonuses) ---
    function _cmdkScore(query, target) {
      if (!query) return 0.001;   // tiny non-zero to keep stable order
      const q = query.toLowerCase();
      const t = target.toLowerCase();
      if (t === q) return 1000;                                  // exact
      if (t.startsWith(q)) return 800 - (t.length - q.length);   // prefix
      if (t.includes(q))   return 600 - (t.length - q.length);   // substring
      // Subsequence + contiguous bonus
      let qi = 0, score = 0, lastMatch = -2;
      for (let ti = 0; ti < t.length && qi < q.length; ti++) {
        if (t[ti] === q[qi]) {
          score += 10;
          if (ti === lastMatch + 1) score += 18;  // contiguous bonus
          if (ti === 0) score += 12;              // start-of-string bonus
          lastMatch = ti;
          qi++;
        }
      }
      return qi === q.length ? score : 0;
    }

    function _cmdkSnapshot() {
      // The visible action set at any given open: static + dynamic
      return _cmdkStaticActions().concat(_cmdkDynamicActions());
    }

    function _cmdkReadRecent() {
      try {
        return JSON.parse(localStorage.getItem(_CMDK_RECENT_KEY) || "[]")
          .slice(0, 5);
      } catch (_e) { return []; }
    }
    function _cmdkPushRecent(id) {
      try {
        const cur = _cmdkReadRecent().filter(x => x !== id);
        cur.unshift(id);
        localStorage.setItem(_CMDK_RECENT_KEY,
                              JSON.stringify(cur.slice(0, 5)));
      } catch (_e) {}
    }

    function _cmdkRender(query) {
      const all = _cmdkSnapshot();
      let items;
      if (!query || !query.trim()) {
        // Empty query → recent-used first, then full list grouped
        const recents = _cmdkReadRecent();
        const recentObjs = recents
          .map(id => all.find(a => a.id === id))
          .filter(Boolean)
          .map(a => Object.assign({}, a, { _recent: true }));
        const recentIds = new Set(recents);
        items = recentObjs.concat(all.filter(a => !recentIds.has(a.id)));
      } else {
        items = all
          .map(a => Object.assign({}, a, { _s: _cmdkScore(query, a.label) }))
          .filter(a => a._s > 0)
          .sort((a, b) => b._s - a._s);
      }
      _cmdkItems = items;
      if (!items.length) {
        cmdkResults.innerHTML = `<div class="cmdk-empty">无匹配的操作 · 试试 “导出” / “排序” / “风格”</div>`;
        _cmdkActiveIdx = 0;
        return;
      }
      // Group-render (only when no query active, to preserve grouping
      // semantics — when querying, ranked-flat is the right UX)
      const rows = [];
      if (!query || !query.trim()) {
        let lastGroup = null;
        items.forEach((it, i) => {
          const g = it._recent ? "最近" : it.group;
          if (g !== lastGroup) {
            rows.push(`<div class="cmdk-group">${esc(g)}</div>`);
            lastGroup = g;
          }
          rows.push(_cmdkItemHtml(it, i));
        });
      } else {
        items.forEach((it, i) => rows.push(_cmdkItemHtml(it, i)));
      }
      cmdkResults.innerHTML = rows.join("");
      _cmdkActiveIdx = 0;
      _cmdkApplyActive();
    }

    function _cmdkItemHtml(it, i) {
      const hint = it.hint ? `<span class="cmdk-item-hint">${esc(it.hint)}</span>` : "";
      return `<div class="cmdk-item" data-idx="${i}" role="option">
        <span class="cmdk-item-icon">${esc(it.icon || "•")}</span>
        <span class="cmdk-item-label">${esc(it.label)}</span>
        ${hint}
      </div>`;
    }

    function _cmdkApplyActive() {
      cmdkResults.querySelectorAll(".cmdk-item").forEach(el => {
        el.classList.toggle("active",
          parseInt(el.dataset.idx, 10) === _cmdkActiveIdx);
      });
      // Scroll active into view
      const a = cmdkResults.querySelector(".cmdk-item.active");
      if (a) a.scrollIntoView({ block: "nearest" });
    }

    function openCmdk() {
      _cmdkOpen = true;
      cmdkModal.classList.add("show");
      cmdkModal.setAttribute("aria-hidden", "false");
      cmdkInput.value = "";
      _cmdkRender("");
      // Defer focus so the keydown that triggered ⌘K doesn't leak in
      setTimeout(() => cmdkInput.focus(), 30);
    }
    function closeCmdk() {
      _cmdkOpen = false;
      cmdkModal.classList.remove("show");
      cmdkModal.setAttribute("aria-hidden", "true");
    }
    function _cmdkFire(idx) {
      const it = _cmdkItems[idx];
      if (!it) return;
      _cmdkPushRecent(it.id);
      closeCmdk();
      try { it.run(); }
      catch (e) { showToast("执行失败: " + e.message, "error"); }
    }

    // --- Helper closures used by the registered actions ---
    function _cmdkPickDecision(d) {
      const pill = document.querySelector(`#decisionPills .pill[data-d="${d}"]`);
      if (pill) pill.click();
    }
    function _cmdkPickSort(s) {
      const sortSel = document.getElementById("sortBy");
      if (sortSel) {
        sortSel.value = s;
        sortSel.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }
    function _cmdkApplyLang(lang) {
      if (typeof _applyLang === "function") _applyLang(lang);
    }
    function _cmdkResetFilters() {
      if (typeof filterState !== "undefined") {
        _exitResolveMaybesSilently();   // v2.15 — ⌘K reset replaces the filter
        filterState.decision = "all";
        filterState.scenes = new Set();
        filterState.styles = new Set();
        filterState.faceClusters = new Set();
        filterState.locationClusters = new Set();
        filterState.cullReason = null;
        filterState.burstPeakOnly = false;
        filterState.locationBestOnly = false;
        filterState.weddingMoments = new Set();
        filterState.semSearch = null;
        document.querySelectorAll("#decisionPills .pill").forEach(el =>
          el.classList.toggle("active", el.dataset.d === "all"));
        _rebuildFilterControls();   // clear burst/location/face/view pill highlights too
        render();
      }
    }

    // --- Wiring ---
    cmdkInput?.addEventListener("input", () => _cmdkRender(cmdkInput.value));
    cmdkInput?.addEventListener("keydown", e => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (_cmdkItems.length) {
          _cmdkActiveIdx = (_cmdkActiveIdx + 1) % _cmdkItems.length;
          _cmdkApplyActive();
        }
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        if (_cmdkItems.length) {
          _cmdkActiveIdx = (_cmdkActiveIdx - 1 + _cmdkItems.length) % _cmdkItems.length;
          _cmdkApplyActive();
        }
      } else if (e.key === "Enter") {
        e.preventDefault();
        _cmdkFire(_cmdkActiveIdx);
      } else if (e.key === "Escape") {
        e.preventDefault();
        closeCmdk();
      }
    });
    cmdkResults?.addEventListener("click", e => {
      const it = e.target.closest(".cmdk-item");
      if (!it) return;
      _cmdkFire(parseInt(it.dataset.idx, 10));
    });
    cmdkModal?.addEventListener("click", e => {
      if (e.target === cmdkModal) closeCmdk();
    });
    // Global ⌘K / Ctrl+K toggle (works from any focus state).
    document.addEventListener("keydown", e => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k"
          && !e.shiftKey && !e.altKey) {
        e.preventDefault();
        _cmdkOpen ? closeCmdk() : openCmdk();
      }
    });
  })();
