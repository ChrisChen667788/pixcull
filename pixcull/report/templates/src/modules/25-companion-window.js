  (function setupCompanionWindow() {
    const btn = document.getElementById("lbCompanionToggle");
    if (!btn || typeof BroadcastChannel !== "function") return;
    const channelName = `pixcull-companion:${run_id}`;
    const ch = new BroadcastChannel(channelName);
    let companion = null;

    function _post(kind, payload) {
      try { ch.postMessage({ kind, payload, t: Date.now() }); }
      catch (e) {}
    }

    // The primary window listens for companion-side decisions so the
    // photographer can keep / cull from the second monitor and have
    // the grid stay in sync.
    ch.addEventListener("message", ev => {
      const d = ev.data || {};
      if (d.kind === "nav" && typeof d.payload === "string") {
        if (typeof window.openLightbox === "function"
            && d.payload !== _lbCurrentFn) {
          window.openLightbox(d.payload);
        }
      } else if (d.kind === "request-state") {
        // Companion just opened; send it the current photo + zoom
        if (_lbCurrentFn) _post("nav", _lbCurrentFn);
      }
    });

    // Wrap openLightbox so every nav fan-outs to the companion
    if (typeof window.openLightbox === "function") {
      const orig = window.openLightbox;
      window.openLightbox = function(fn) {
        const r = orig.apply(this, arguments);
        if (companion && !companion.closed) {
          _post("nav", fn);
        }
        return r;
      };
    }

    btn.addEventListener("click", () => {
      if (companion && !companion.closed) {
        companion.focus();
        return;
      }
      // Companion uses a query param to know its role + which channel
      // to join.  /companion is served by serve_demo (companion HTML).
      const u = `/companion?run_id=${encodeURIComponent(run_id)}` +
                (_lbCurrentFn ? `&fn=${encodeURIComponent(_lbCurrentFn)}` : "");
      companion = window.open(u, "pixcull-companion",
        "popup=yes,width=1400,height=900");
      if (!companion) {
        if (typeof window.toast === "function") {
          window.toast("浏览器阻止了副屏弹窗 — 检查弹窗设置", "warn");
        }
        return;
      }
      // Give the new window a moment to attach to the channel before
      // pushing the current photo.  request-state from the companion
      // covers the race the other way.
      setTimeout(() => {
        if (_lbCurrentFn) _post("nav", _lbCurrentFn);
      }, 400);
    });
  })();
