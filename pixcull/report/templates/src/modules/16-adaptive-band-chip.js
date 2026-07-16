  (function showAdaptiveBandChip() {
    if (typeof rows !== "object" || !Array.isArray(rows)) return;
    const scores = rows
      .map(r => r && typeof r.score_final === "number" ? r.score_final : null)
      .filter(v => v !== null);
    if (scores.length < 20) return;
    // Quick 25/75 percentile
    const sorted = scores.slice().sort((a,b) => a-b);
    const q25 = sorted[Math.floor(sorted.length * 0.25)];
    const q75 = sorted[Math.floor(sorted.length * 0.75)];
    const adaptiveKeep = 0.5 * q75 + 0.5 * 0.65;
    const adaptiveCull = 0.5 * q25 + 0.5 * 0.40;
    const keep = Math.max(0.55, Math.min(0.80, adaptiveKeep));
    const cull = Math.max(0.20, Math.min(0.55, adaptiveCull));
    // Only surface if either threshold drifted ≥ 0.03 from default
    if (Math.abs(keep - 0.65) < 0.03 && Math.abs(cull - 0.40) < 0.03) return;
    // Inject as a chip near the stats row
    const stats = document.querySelector(".stats");
    if (!stats) return;
    const chip = document.createElement("span");
    chip.className = "adaptive-band-chip";
    chip.title = (
      "v0.13.8 自调:keep ≥ " + keep.toFixed(2) +
      " · cull < " + cull.toFixed(2) +
      "(基于 " + scores.length + " 张评分的 25/75 分位)\n" +
      "本 run 的 score 分布与全局默认偏离 ≥ 0.03,因此适配阈值。"
    );
    chip.style.cssText = (
      "display:inline-flex;align-items:center;gap:6px;" +
      "padding:3px 9px;border-radius:999px;" +
      "background:rgba(196,185,169,0.14);color:#c4b9a9;" +
      "border:1px dashed rgba(196,185,169,0.40);" +
      "font-size:10.5px;font-weight:500;cursor:help;" +
      "margin-left:8px;"
    );
    chip.innerHTML = (
      `<span>⚙ 自调 maybe 区间</span>` +
      `<span style='color:#fff;font-family:ui-monospace,Menlo;font-size:10px'>` +
      `${cull.toFixed(2)}-${keep.toFixed(2)}</span>`
    );
    stats.appendChild(chip);
  })();
