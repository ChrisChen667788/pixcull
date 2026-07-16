  (function _initMultiTab() {
    if (typeof BroadcastChannel === "undefined") return;
    const _TAB_ID = (typeof crypto !== "undefined" && crypto.randomUUID)
      ? crypto.randomUUID()
      : (Date.now() + "-" + Math.random().toString(36).slice(2, 10));
    let _bc;
    try { _bc = new BroadcastChannel("pixcull-tab-coord:" + run_id); }
    catch (e) { return; }

    const _seenTabs = new Set();
    let _bannerEl = null;

    function _showBanner() {
      if (_bannerEl) {
        _bannerEl.classList.remove("hidden");
        return;
      }
      _bannerEl = document.createElement("div");
      _bannerEl.className = "multi-tab-banner";
      _bannerEl.setAttribute("role", "status");
      _bannerEl.setAttribute("aria-live", "polite");
      _bannerEl.innerHTML = `
        <span class="mtb-icon"><svg class="icon"><use href="#icon-alert"/></svg></span>
        <span class="mtb-msg">同一批结果已在其它 tab 打开 — 标注会双向同步,但建议只在一个 tab 内编辑以避免覆盖</span>
        <button class="mtb-close" type="button" aria-label="关闭多 tab 提示">✕</button>`;
      document.body.appendChild(_bannerEl);
      _bannerEl.querySelector(".mtb-close").addEventListener("click", () => {
        _bannerEl.classList.add("hidden");
      });
    }

    function _hideBannerIfAlone() {
      if (_seenTabs.size === 0 && _bannerEl) {
        _bannerEl.remove();
        _bannerEl = null;
      }
    }

    _bc.addEventListener("message", e => {
      const m = e.data || {};
      if (!m.type || !m.from || m.from === _TAB_ID) return;

      if (m.type === "hello") {
        _seenTabs.add(m.from);
        // Echo back so the newcomer learns about us too
        try { _bc.postMessage({type: "echo", from: _TAB_ID}); } catch (e) {}
        _showBanner();
      }
      else if (m.type === "echo") {
        _seenTabs.add(m.from);
        _showBanner();
      }
      else if (m.type === "bye") {
        _seenTabs.delete(m.from);
        _hideBannerIfAlone();
      }
      else if (m.type === "annot" && m.fn) {
        // Sibling tab labeled fn → reflect locally so the user sees
        // the change live in this tab.
        const r = rows.find(x => x.filename === m.fn);
        // v2.15-P0 — a sibling tab's label means a HUMAN reviewed this photo:
        // keep this tab's 待审 chip in sync. Deliberately outside the
        // decision-changed guard below — a sibling CONFIRM (prev === new)
        // still counts as reviewed, mirroring the local labeling paths.
        if (r && typeof _markReviewed === "function") _markReviewed(m.fn);
        if (r && r.decision !== m.dec) {
          r.decision = m.dec;
          r.rubric_human_labeled = true;
          if (m.dec !== "cull") r.cull_reason = "";
          try { render(); } catch (err) {}
          try {
            if (typeof toast === "function") {
              toast(`其它 tab 标注:${m.fn.length > 40 ? m.fn.slice(0,38)+"…" : m.fn} → ${m.dec}`,
                    "info", 2400);
            }
          } catch (err) {}
        }
      }
    });

    _pixMultiTab.broadcastAnnotation = function (fn, dec) {
      try { _bc.postMessage({type: "annot", from: _TAB_ID, fn, dec}); }
      catch (e) {}
    };

    // Announce ourselves; existing tabs will reply with "echo".
    try { _bc.postMessage({type: "hello", from: _TAB_ID}); } catch (e) {}
    // Politely depart on unload so the survivor can drop the banner.
    window.addEventListener("beforeunload", () => {
      try { _bc.postMessage({type: "bye", from: _TAB_ID}); } catch (e) {}
    });
  })();
