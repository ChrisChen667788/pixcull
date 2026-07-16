  (function _initSceneAnomalyBanner() {
    if (!rows || rows.length < 10) return;     // too few to judge

    // Count scenes
    const counts = new Map();
    for (const r of rows) {
      const s = r.scene || "(missing)";
      counts.set(s, (counts.get(s) || 0) + 1);
    }
    const n = rows.length;
    const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]);
    const [topScene, topN]       = sorted[0] || [null, 0];
    const [secondScene, secondN] = sorted[1] || [null, 0];
    const topPct    = topN / n;
    const top2Pct   = (topN + secondN) / n;
    const unknownN  = counts.get("unknown") || 0;
    const unknownPct = unknownN / n;

    let reason = null;
    if (topPct > 0.60) {
      reason = `单一场景 <b>${topScene}</b> 占了 <b>${(topPct*100).toFixed(0)}%</b> ` +
               `(${topN} / ${n})。如果与实际场景相符则忽略;否则建议重判场景。`;
    } else if (top2Pct > 0.95 && n >= 30) {
      reason = `<b>${topScene}</b> + <b>${secondScene}</b> 占了 <b>${(top2Pct*100).toFixed(0)}%</b>。` +
               `可能 scene 分类器把多种场景误归到这两类;先抽查再大批量标注。`;
    } else if (unknownPct > 0.30) {
      reason = `场景分类器在 <b>${(unknownPct*100).toFixed(0)}%</b> 的图片上 abstain ` +
               `(标为 unknown)。这一批光线 / 场景对 CLIP 来说不典型,人工复核优先。`;
    }
    if (!reason) return;

    const banner = document.createElement("div");
    banner.className = "scene-anomaly-banner";
    banner.setAttribute("role", "status");
    banner.setAttribute("aria-live", "polite");
    banner.innerHTML = `
      <span class="sab-icon"><svg class="icon"><use href="#icon-chart"/></svg></span>
      <span class="sab-msg">${reason}</span>
      <button class="sab-toggle" type="button">查看分布详情</button>
      <button class="sab-close" type="button" aria-label="关闭场景分布提示">✕</button>`;
    document.body.appendChild(banner);

    // P-UX-28 — pie chart panel.  Lazy-built on first click.
    let pieEl = null;
    function _buildPiePanel() {
      // Generate distinct hues evenly spaced around the wheel
      const entries = sorted;   // [[name, count], ...]
      const total   = n;
      const N       = entries.length;
      const hue = i => Math.round((i * 360) / N);
      const fill = i => `hsl(${hue(i)}, 62%, 55%)`;

      // Build SVG pie via cumulative-angle-to-arc math.  conic-
      // gradient would be simpler but doesn't support per-segment
      // titles + a screenreader-friendly title on hover.
      const cx = 70, cy = 70, r = 60;
      let acc = 0;
      const slices = entries.map(([name, cnt], i) => {
        const frac = cnt / total;
        const a0   = acc * 2 * Math.PI - Math.PI / 2;
        const a1   = (acc + frac) * 2 * Math.PI - Math.PI / 2;
        acc += frac;
        const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0);
        const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
        const large = frac > 0.5 ? 1 : 0;
        const d = `M${cx},${cy} L${x0.toFixed(2)},${y0.toFixed(2)} ` +
                  `A${r},${r} 0 ${large} 1 ${x1.toFixed(2)},${y1.toFixed(2)} Z`;
        const title = `${esc(name)}: ${cnt} (${(frac * 100).toFixed(1)}%)`;
        return `<path d="${d}" fill="${fill(i)}" stroke="#0b0d10" stroke-width="1">` +
               `<title>${title}</title></path>`;
      }).join("");
      const legend = entries.map(([name, cnt], i) => {
        const frac = cnt / total;
        return `<div class="sdp-legend-row">
          <span class="sdp-swatch" style="background:${fill(i)}"></span>
          <span class="sdp-name">${esc(name)}</span>
          <span class="sdp-pct">${cnt} · ${(frac*100).toFixed(1)}%</span>
        </div>`;
      }).join("");
      const panel = document.createElement("div");
      panel.className = "scene-distribution-panel";
      panel.innerHTML = `
        <h4>场景分布 (共 ${total} 张)</h4>
        <div class="sdp-content">
          <svg viewBox="0 0 140 140" aria-label="场景分布饼图">
            ${slices}
          </svg>
          <div class="sdp-legend">${legend}</div>
        </div>`;
      document.body.appendChild(panel);
      return panel;
    }

    banner.querySelector(".sab-toggle").addEventListener("click", () => {
      if (!pieEl) pieEl = _buildPiePanel();
      pieEl.classList.toggle("show");
    });
    const close = () => {
      banner.classList.add("hidden");
      // P-UX-28 — also hide the expanded pie panel if open
      if (pieEl) pieEl.classList.remove("show");
      // Persist dismissal per-run so reopening the same tab
      // doesn't re-prompt
      try {
        localStorage.setItem("pixcull_scene_anomaly_dismissed:" + run_id, "1");
      } catch (_e) {}
    };
    banner.querySelector(".sab-close").addEventListener("click", close);
    // Auto-dismiss when the user starts annotating (first 1/2/3/f)
    function _onFirstAnnot(e) {
      const k = e.key;
      if (k === "1" || k === "2" || k === "3" ||
          k === "f" || k === "F") {
        document.removeEventListener("keydown", _onFirstAnnot, true);
        close();
      }
    }
    document.addEventListener("keydown", _onFirstAnnot, true);

    // Honor persisted dismissal (same run reopened)
    try {
      if (localStorage.getItem("pixcull_scene_anomaly_dismissed:" + run_id) === "1") {
        banner.classList.add("hidden");
      }
    } catch (_e) {}
  })();
