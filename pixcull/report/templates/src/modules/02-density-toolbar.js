  (function _initDensityToolbar() {
    const _DENSITY_KEY = "pixcull_density";
    const tb = document.querySelector(".density-toolbar");
    if (!tb || !grid) return;
    function _apply(density) {
      grid.classList.remove("density-s", "density-m", "density-l");
      grid.classList.add("density-" + density);
      tb.querySelectorAll("button").forEach(b => {
        b.classList.toggle("active", b.dataset.density === density);
      });
    }
    let saved = "m";
    try { saved = localStorage.getItem(_DENSITY_KEY) || "m"; } catch (e) {}
    if (!["s","m","l"].includes(saved)) saved = "m";
    _apply(saved);
    tb.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", () => {
        const d = btn.dataset.density;
        if (!d) return;
        try { localStorage.setItem(_DENSITY_KEY, d); } catch (e) {}
        _apply(d);
      });
    });
  })();
