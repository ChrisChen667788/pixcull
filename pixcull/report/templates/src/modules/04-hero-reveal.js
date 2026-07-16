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
    const lateObs = new MutationObserver(muts => {
      for (const m of muts) {
        for (const node of m.addedNodes) {
          if (node.nodeType === 1 && node.classList?.contains("card")) {
            // Continue stagger from the current visible count
            const idx = grid.querySelectorAll(".card").length - 1;
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
