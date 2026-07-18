  (function _slashMenuInit() {
    let menuEl = null;
    let activeTextarea = null;
    let cursorIdx = 0;     // index of the "/" that opened the menu
    let filterText = "";
    let selectedIndex = 0;

    const ALL_COMMANDS = [
      { key: "keep",    label: "标 5★(keep)",
        run: ta => _setAxisStarsFromTextarea(ta, 5) },
      { key: "cull",    label: "标 1★(cull)",
        run: ta => _setAxisStarsFromTextarea(ta, 1) },
      { key: "maybe",   label: "标 3★(maybe)",
        run: ta => _setAxisStarsFromTextarea(ta, 3) },
      { key: "cite",    label: "插入正典引用模板",
        run: ta => _insertAt(ta, " [cite: source · year] ") },
      { key: "explain", label: "重新拉 DeepSeek 解释",
        run: () => showToast("DeepSeek explanation refresh queued", "info") },
    ];

    function _setAxisStarsFromTextarea(ta, stars) {
      // The textarea lives inside .axis-row[data-axis="..."]; find
      // it + click the matching star.  Lets `/keep` mark the
      // current axis as 5★ without breaking the keyboard flow.
      const axisRow = ta.closest(".axis-row");
      if (!axisRow) return;
      const starEl = axisRow.querySelector(`.star[data-v="${stars}"]`);
      if (starEl) starEl.click();
    }

    function _insertAt(ta, text) {
      const start = ta.selectionStart || 0;
      const end   = ta.selectionEnd   || start;
      ta.value = ta.value.slice(0, start) + text + ta.value.slice(end);
      const newPos = start + text.length;
      ta.setSelectionRange(newPos, newPos);
      ta.focus();
    }

    function _closeMenu() {
      if (menuEl) {
        menuEl.remove();
        menuEl = null;
      }
      activeTextarea = null;
      filterText = "";
      selectedIndex = 0;
    }

    function _filtered() {
      if (!filterText) return ALL_COMMANDS;
      const f = filterText.toLowerCase();
      return ALL_COMMANDS.filter(c =>
        c.key.startsWith(f) || c.label.toLowerCase().includes(f));
    }

    function _renderMenu() {
      if (!activeTextarea) return;
      const items = _filtered();
      if (items.length === 0) { _closeMenu(); return; }
      if (selectedIndex >= items.length) selectedIndex = 0;
      if (!menuEl) {
        menuEl = document.createElement("div");
        menuEl.className = "slash-menu";
        menuEl.style.cssText = (
          "position:absolute;z-index:1500;" +
          "background:var(--surface-2);" +
          "border:1px solid var(--border-hi, var(--border));" +
          "border-radius:var(--radius-md, 8px);" +
          "box-shadow:var(--shadow-lg);" +
          "padding:4px 0;min-width:200px;" +
          "font-size:12px;"
        );
        document.body.appendChild(menuEl);
      }
      menuEl.innerHTML = items.map((c, i) =>
        `<div class="slash-item${i === selectedIndex ? " sel" : ""}" ` +
        ` style="padding:6px 12px;cursor:pointer;` +
        ` ${i === selectedIndex ? "background:var(--accent-soft, rgba(213,181,132,0.16));" : ""}"` +
        ` data-key="${c.key}">` +
        `  <span style="color:var(--accent);margin-right:6px">/</span>` +
        `  <b>${c.key}</b>` +
        `  <span style="color:var(--muted);margin-left:8px">${c.label}</span>` +
        `</div>`
      ).join("");
      // Position near the textarea
      const r = activeTextarea.getBoundingClientRect();
      menuEl.style.left = (r.left + window.scrollX) + "px";
      menuEl.style.top  = (r.bottom + window.scrollY + 4) + "px";
      // Wire click → run
      menuEl.querySelectorAll(".slash-item").forEach((el, i) => {
        el.addEventListener("mouseenter", () => {
          selectedIndex = i;
          _renderMenu();
        });
        el.addEventListener("click", () => {
          _runItem(_filtered()[i]);
        });
      });
    }

    function _runItem(cmd) {
      if (!cmd || !activeTextarea) return _closeMenu();
      const ta = activeTextarea;
      // Drop the "/filter" text that opened the menu first.
      ta.value = ta.value.slice(0, cursorIdx)
               + ta.value.slice(cursorIdx + 1 + filterText.length);
      ta.setSelectionRange(cursorIdx, cursorIdx);
      _closeMenu();
      try { cmd.run(ta); } catch (_e) {}
    }

    document.addEventListener("input", (e) => {
      const ta = e.target;
      if (!ta || ta.tagName !== "TEXTAREA") return;
      if (!ta.dataset.slashmenu) return;
      const pos = ta.selectionStart;
      const v = ta.value;
      // Find the most recent "/" preceded by start-of-text or a newline.
      let i = pos - 1;
      while (i >= 0 && v[i] !== "/" && v[i] !== "\n") i--;
      if (i < 0 || v[i] !== "/" || (i > 0 && v[i - 1] !== "\n")) {
        _closeMenu();
        return;
      }
      // Capture the filter text between / and the cursor
      activeTextarea = ta;
      cursorIdx = i;
      filterText = v.slice(i + 1, pos);
      selectedIndex = 0;
      _renderMenu();
    });

    document.addEventListener("keydown", (e) => {
      if (!menuEl || !activeTextarea) return;
      if (e.key === "Escape") { e.preventDefault(); _closeMenu(); return; }
      const items = _filtered();
      if (e.key === "ArrowDown") {
        e.preventDefault();
        selectedIndex = (selectedIndex + 1) % items.length;
        _renderMenu();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        selectedIndex = (selectedIndex - 1 + items.length) % items.length;
        _renderMenu();
      } else if (e.key === "Enter") {
        e.preventDefault();
        _runItem(items[selectedIndex]);
      }
    });

    document.addEventListener("click", (e) => {
      if (!menuEl) return;
      if (e.target.closest(".slash-menu")) return;
      if (e.target === activeTextarea) return;
      _closeMenu();
    });
  })();
