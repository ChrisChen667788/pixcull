  (function _initCalmToolbar() {
    const _CALM_KEY = "pixcull_calm";
    const tb = document.querySelector(".calm-toolbar");
    if (!tb || !grid) return;
    function _apply(mode) {
      grid.classList.toggle("dense", mode === "dense");
      tb.querySelectorAll("button").forEach(b => {
        b.classList.toggle("active", b.dataset.calm === mode);
      });
    }
    let saved = "calm";
    try { saved = localStorage.getItem(_CALM_KEY) || "calm"; } catch (e) {}
    if (!["calm", "dense"].includes(saved)) saved = "calm";
    _apply(saved);
    tb.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", () => {
        const m = btn.dataset.calm;
        if (!m) return;
        try { localStorage.setItem(_CALM_KEY, m); } catch (e) {}
        _apply(m);
      });
    });
  })();
