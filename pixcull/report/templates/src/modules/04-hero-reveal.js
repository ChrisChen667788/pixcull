  (function _heroReveal() {
    // Skip on slow connections / save-data — animation work is
    // wasted CPU on those clients.
    if (navigator.connection
        && navigator.connection.saveData === true) return;
    document.body.classList.add("hero-revealing");
    // Per-card stagger index.  Set on every initial card whose
    // animation will fire.  IntersectionObserver-materialised
    // placeholders catch up via the MutationObserver below.
    function setStaggerIndices() {
      let i = 0;
      grid.querySelectorAll(".card").forEach(card => {
        card.style.setProperty("--idx", String(i));
        i += 1;
      });
    }
    setStaggerIndices();
    // Late-materialised placeholders (P-UX-18 large-batch streaming)
    // get their --idx set when they swap into real .card elements.
    let _revealCount = null;
    const lateObs = new MutationObserver(muts => {
      for (const m of muts) {
        for (const node of m.addedNodes) {
          if (node.nodeType === 1 && node.classList?.contains("card")) {
            // Continue stagger from the current visible count.
            // v2.68.1 — counted, not re-queried. querySelectorAll here
            // ran once PER ADDED NODE, so a 5k-row streaming render
            // walked the grid thousands of times inside this observer's
            // 2.2s life. Same shape as the two grid observers that
            // froze Safari — smaller, and self-limiting by the
            // teardown, which is why it never showed up.
            if (_revealCount == null) {
              _revealCount = grid.querySelectorAll(".card").length;
            }
            const idx = _revealCount++ - 1;
            // Cap to 64 to match the CSS clamp
            node.style.setProperty("--idx", String(Math.min(idx, 64)));
          }
        }
      }
    });
    lateObs.observe(grid, { childList: true });
    // Tear down after the reveal finishes
    setTimeout(() => {
      document.body.classList.remove("hero-revealing");
      lateObs.disconnect();
    }, 2200);
  })();
