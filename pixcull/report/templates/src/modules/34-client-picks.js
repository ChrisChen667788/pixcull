    (function setupClientPicks() {
      // ==================================================================
      // v3.0 — 客户选 · the on-site half.
      //
      // The client is beside the photographer pointing at the screen.
      // `p` records what they point at. It is deliberately NOT the same
      // thing as keep/maybe/cull: those are the photographer's answer to
      // "is this good enough to deliver", and this is the client's answer
      // to "do I want it". They disagree constantly and both are right.
      //
      // Server-side it lands in client_picks.jsonl, never in
      // annotations.jsonl — that index is latest-wins on the whole
      // record, so one line of the client's opinion would erase the
      // photographer's verdict from every reader of it.
      //
      // Fetched separately from the results payload so a pick shows up
      // without touching the results cache.
      //
      // Works while 客户在场模式 is on, because that is exactly when it
      // is used. The marker says 客户选 and carries no verdict, so it is
      // safe on screen in front of them.
      // ==================================================================
      const PICKED = new Set();
      let loaded = false;

      function _paint() {
        document.querySelectorAll(".card[data-fn]").forEach((el) => {
          el.classList.toggle("client-picked", PICKED.has(el.dataset.fn));
        });
        // v3.0.2 — the toggle is BUILT here rather than looked up.
        // The first version called getElementById on an id that was
        // never added to the page, so the count silently did not exist:
        // guarded by `if (chip)`, it never threw and never appeared.
        let chip = document.getElementById("clientPickChip");
        if (!chip && PICKED.size) {
          const stats = document.querySelector(".stats");
          if (stats) {
            chip = document.createElement("button");
            chip.id = "clientPickChip";
            chip.type = "button";
            chip.className = "stat-aux client-pick-chip";
            chip.title = "只看客户选的(再点一次取消)";
            chip.addEventListener("click", () => {
              filterState.clientPicksOnly = !filterState.clientPicksOnly;
              chip.classList.toggle("on", filterState.clientPicksOnly);
              if (typeof render === "function") render();
            });
            stats.appendChild(chip);
          }
        }
        if (chip) {
          chip.hidden = PICKED.size === 0;
          chip.textContent = `客户选 ${PICKED.size}`;
          chip.classList.toggle("on", !!filterState.clientPicksOnly);
        }
      }

      async function _load() {
        try {
          const r = await fetch(`/client_picks/${encodeURIComponent(run_id)}`);
          if (!r.ok) return;
          const d = await r.json();
          PICKED.clear();
          (d.picked || []).forEach((f) => PICKED.add(f));
          loaded = true;
          _paint();
        } catch (_e) { /* offline / older server: the feature is simply absent */ }
      }

      async function _toggle(fn) {
        if (!fn) return;
        const next = !PICKED.has(fn);
        // Optimistic, then reconciled: the photographer is mid-sentence
        // with a client and a round trip is not something to wait on.
        if (next) PICKED.add(fn); else PICKED.delete(fn);
        _paint();
        try {
          const r = await fetch(
            `/client_pick/${encodeURIComponent(run_id)}/${encodeURIComponent(fn)}`,
            {method: "POST", headers: {"Content-Type": "application/json"},
             body: JSON.stringify({picked: next, source: "on-site"})});
          if (!r.ok) throw new Error("HTTP " + r.status);
        } catch (_e) {
          // Put it back. A pick that looks recorded and is not is worse
          // than one that visibly failed — the client is watching.
          if (next) PICKED.delete(fn); else PICKED.add(fn);
          _paint();
          if (typeof showToast === "function") {
            showToast("客户选没能保存,再按一次", "error");
          }
        }
      }

      function _currentFilename() {
        const lb = document.querySelector(".lightbox[data-fn], #lightbox[data-fn]");
        if (lb && lb.dataset.fn) return lb.dataset.fn;
        const f = document.querySelector(".card.focused[data-fn]");
        return f ? f.dataset.fn : null;
      }

      document.addEventListener("keydown", (e) => {
        if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey) return;
        if (e.key !== "p" && e.key !== "P") return;
        const t = e.target;
        if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA"
                  || t.isContentEditable)) return;
        e.preventDefault();
        _toggle(_currentFilename());
      });

      document.addEventListener("click", (e) => {
        const b = e.target.closest?.("[data-client-pick]");
        if (b) { e.preventDefault(); _toggle(b.dataset.clientPick); }
      });

      window.PixCullClientPicks = {
        has: (fn) => PICKED.has(fn),
        all: () => [...PICKED],
        reload: _load,
        toggle: _toggle,
        get loaded() { return loaded; },
      };

      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", _load, {once: true});
      } else {
        _load();
      }
      // The grid re-renders on every filter change and the class is not
      // in the card markup, so it has to be re-applied.
      document.addEventListener("pixcull:rendered", _paint);
    })();
