  (function setupExifOverlay() {
    const lb = document.getElementById("lightbox");
    if (!lb) return;
    // Inject the overlay node lazily — keeps it out of the initial
    // DOM weight for users who never press H.
    let panel = null;
    function _ensurePanel() {
      if (panel) return panel;
      panel = document.createElement("div");
      panel.className = "lb-exif-overlay";
      panel.style.cssText = (
        "position:absolute;top:12px;left:12px;z-index:6;" +
        "background:rgba(20,18,14,0.92);color:#fff;" +
        "padding:10px 14px;border-radius:8px;" +
        "font:11.5px/1.4 ui-monospace,SF Mono,Menlo,monospace;" +
        "display:none;min-width:180px;max-width:280px;" +
        "box-shadow:0 8px 24px rgba(0,0,0,0.4);"
      );
      panel.innerHTML = (
        "<div id='lbExifMeta' style='line-height:1.6;color:#cfd5e0'></div>" +
        "<canvas id='lbExifHist' width='220' height='60' " +
        "style='display:block;margin-top:8px;width:220px;height:60px;" +
        "background:rgba(0,0,0,0.5);border-radius:4px'></canvas>"
      );
      lb.appendChild(panel);
      return panel;
    }
    async function _refresh() {
      if (!_lbCurrentFn || !panel || panel.style.display === "none") return;
      const meta = document.getElementById("lbExifMeta");
      const cv = document.getElementById("lbExifHist");
      meta.textContent = "loading…";
      try {
        const r = await fetch(`/exif_audit/${run_id}/${
          encodeURIComponent(_lbCurrentFn)}`);
        if (r.ok) {
          const e = await r.json();
          const lines = [];
          if (e.iso != null) lines.push(`ISO ${e.iso}`);
          if (e.aperture) lines.push(`f/${e.aperture}`);
          if (e.shutter) lines.push(`${e.shutter}s`);
          if (e.focal_length) lines.push(`${e.focal_length}mm`);
          if (e.camera_model) lines.push(e.camera_model);
          meta.textContent = lines.join(" · ") || "no EXIF";
        } else {
          meta.textContent = "no EXIF";
        }
      } catch (_e) {
        meta.textContent = "EXIF unavailable";
      }
      // Histogram: pull the current <img> into a hidden canvas + walk pixels.
      const img = document.getElementById("lbImg");
      if (!img || !img.complete) return;
      const tmp = document.createElement("canvas");
      const W = 160, H = Math.round(160 * (img.naturalHeight / img.naturalWidth || 0.67));
      tmp.width = W; tmp.height = H;
      try {
        const ctx = tmp.getContext("2d");
        ctx.drawImage(img, 0, 0, W, H);
        const data = ctx.getImageData(0, 0, W, H).data;
        const bins = new Array(64).fill(0);
        for (let i = 0; i < data.length; i += 4) {
          const lum = 0.2126 * data[i] + 0.7152 * data[i+1] + 0.0722 * data[i+2];
          bins[Math.min(63, Math.floor(lum / 4))]++;
        }
        const histCtx = cv.getContext("2d");
        histCtx.clearRect(0, 0, cv.width, cv.height);
        const maxB = Math.max(...bins, 1);
        const bw = cv.width / 64;
        histCtx.fillStyle = "rgba(196,185,169,0.75)";
        for (let i = 0; i < 64; i++) {
          const h = (bins[i] / maxB) * cv.height;
          histCtx.fillRect(i * bw, cv.height - h, bw - 0.5, h);
        }
      } catch (_e) { /* tainted canvas — silent */ }
    }
    function _toggle() {
      const p = _ensurePanel();
      const showing = p.style.display !== "none";
      p.style.display = showing ? "none" : "block";
      if (!showing) _refresh();
    }
    document.addEventListener("keydown", ev => {
      if (ev.target.matches("input,textarea,[contenteditable=true]")) return;
      const inLightbox = lb.classList.contains("show");
      if (!inLightbox) return;
      if (ev.key === "h" || ev.key === "H") {
        ev.preventDefault();
        _toggle();
      }
    });
    // Refresh whenever the lightbox navigates
    const origOpen = window.openLightbox;
    if (typeof origOpen === "function") {
      window.openLightbox = function() {
        const r = origOpen.apply(this, arguments);
        if (panel && panel.style.display !== "none") {
          setTimeout(_refresh, 60);
        }
        return r;
      };
    }
  })();
