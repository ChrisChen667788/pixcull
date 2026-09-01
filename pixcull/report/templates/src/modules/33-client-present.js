    (function setupClientPresent() {
      // ==================================================================
      // v2.97 — 客户在场模式.
      //
      // Measured before building this: 539 pieces of judgement text on a
      // single screen. Every card carries "保留" and "综合分 0.95"; the
      // stats bar reads "保留 4152 · 待定 244 · 剔除 673".
      //
      // A client sitting beside the photographer reads the machine's
      // verdict on their own wedding photographs, and a number on each
      // one. It turns choosing pictures into defending them — "why is
      // that one only 0.62?" — and 673 of their photographs are labelled
      // 剔除 on a bar at the top of the screen.
      //
      // This hides judgement, not information. Filenames, dates, scenes,
      // the burst-peak badge and every navigation control stay: the
      // photographer is still driving, and needs to.
      //
      // The mode PERSISTS. A reload with the client still in the room
      // must not put the scores back, and the indicator exists so the
      // photographer cannot forget it is on and wonder later where their
      // numbers went.
      //
      // The guard for this is NOT the CSS — a badge added next year would
      // leak. It is tests/test_client_present.py, which walks the live
      // DOM for judgement text with the mode on and requires zero.
      // ==================================================================
      const KEY = "pixcull_client_present";
      const root = document.documentElement;

      function _apply(on) {
        root.classList.toggle("pc-client", !!on);
        const btn = document.getElementById("clientPresentBtn");
        if (btn) {
          btn.setAttribute("aria-pressed", on ? "true" : "false");
          btn.title = on
            ? "客户在场模式:已隐藏全部判决与评分(⇧C 退出)"
            : "客户在场模式:隐藏判决与评分,给客户看(⇧C)";
        }
        const ind = document.getElementById("clientPresentIndicator");
        if (ind) ind.hidden = !on;
      }

      function _toggle() {
        const next = !root.classList.contains("pc-client");
        try { localStorage.setItem(KEY, next ? "1" : "0"); } catch (_e) {}
        _apply(next);
      }

      let stored = null;
      try { stored = localStorage.getItem(KEY); } catch (_e) {}
      // The class goes on <html> immediately, so a restored session never
      // paints the verdicts for a frame in front of the client.
      root.classList.toggle("pc-client", stored === "1");

      // The button and the indicator sit AFTER this script in the
      // document, so they do not exist yet. Binding here silently did
      // nothing on a reload: the mode came back and the indicator did
      // not, which is the worse half — the photographer loses the only
      // sign that their numbers are hidden on purpose.
      function _wire() {
        _apply(root.classList.contains("pc-client"));
        document.getElementById("clientPresentBtn")
          ?.addEventListener("click", _toggle);
        document.getElementById("clientPresentExit")
          ?.addEventListener("click", _toggle);
      }
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", _wire, {once: true});
      } else {
        _wire();
      }

      document.addEventListener("keydown", (e) => {
        // Shift+C. Not a bare letter: the cull loop uses single keys and
        // a stray keystroke in front of a client must not re-expose the
        // verdicts.
        if (e.shiftKey && !e.metaKey && !e.ctrlKey && !e.altKey
            && (e.key === "C" || e.code === "KeyC")) {
          const t = e.target;
          const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA"
                               || t.isContentEditable);
          if (typing) return;
          e.preventDefault();
          _toggle();
        }
      });

      window.PixCullClientPresent = { toggle: _toggle, isOn: () =>
        root.classList.contains("pc-client") };
    })();
