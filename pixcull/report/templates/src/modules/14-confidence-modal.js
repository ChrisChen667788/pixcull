  (function setupConfidenceModal() {
    const KEY = `pixcull_dismiss_confidence_modal:${run_id}`;
    const grid = document.getElementById("grid");
    if (!grid) return;
    let popover = null;
    let activeCard = null;
    let dismissed = false;
    try { dismissed = localStorage.getItem(KEY) === "1"; }
    catch (_e) {}
    if (dismissed) return;

    function _isUncertain(row) {
      const s = row && row.score_final;
      if (typeof s !== "number") return false;
      return s >= 0.45 && s <= 0.55;
    }

    function _explainRow(row) {
      // Two short lines.  Higher-fidelity reasons come from
      // v0.13-P0-1 attribution + burst-neighbor lookup; for now
      // we derive from data already on the row.
      const reasons = [];
      const burst = row.burst_cluster;
      const score = row.score_final;
      const probKeep = row.rescorer_prob_keep;
      if (typeof probKeep === "number") {
        const conf = Math.round(Math.max(probKeep, 1 - probKeep) * 100);
        reasons.push(`${conf}% sure`);
      } else {
        reasons.push("低置信度");
      }
      if (burst && typeof window.rows !== "undefined") {
        const neighbours = (window.rows || rows).filter(r =>
          r.burst_cluster === burst && r.filename !== row.filename);
        if (neighbours.length) {
          const top = neighbours.reduce((a, b) =>
            (a.score_final || 0) > (b.score_final || 0) ? a : b);
          const delta = (top.score_final || 0) - score;
          if (delta > 0.005) {
            reasons.push(`同组邻居高 ${delta.toFixed(2)}`);
          }
        }
      }
      const axes = row && row.rubric_axes;
      if (axes && typeof axes === "object") {
        const sorted = Object.entries(axes)
          .filter(([_, a]) => a && typeof a.stars === "number")
          .sort((a, b) => a[1].stars - b[1].stars);
        if (sorted.length) {
          reasons.push(`最弱轴 · ${sorted[0][0]} ${sorted[0][1].stars.toFixed(1)}★`);
        }
      }
      return reasons.slice(0, 3);
    }

    function _show(card, row) {
      if (popover) _hide();
      popover = document.createElement("div");
      popover.className = "confidence-popover";
      popover.style.cssText = (
        "position:absolute;z-index:30;" +
        "background:rgba(20,18,14,0.96);color:#fff;" +
        "padding:9px 12px;border-radius:8px;" +
        "font:11.5px/1.5 system-ui;max-width:230px;" +
        "box-shadow:0 6px 20px rgba(0,0,0,0.40);" +
        "border:1px solid rgba(196,185,169,0.30);"
      );
      const reasons = _explainRow(row);
      popover.innerHTML = (
        "<div style='font-weight:600;color:#c4b9a9;margin-bottom:4px'>" +
        "⌬ model 不确定</div>" +
        reasons.map((r, i) => (
          `<div style='color:${i === 0 ? "#fff" : "#aaa"}'>${
            i === 0 ? "" : "· "}${r}</div>`
        )).join("") +
        "<button class='conf-dismiss' style='margin-top:6px;" +
        "background:transparent;color:#666;border:0;cursor:pointer;" +
        "font-size:10.5px;padding:2px 0;text-decoration:underline'>" +
        "不再显示</button>"
      );
      const rect = card.getBoundingClientRect();
      const gridRect = grid.getBoundingClientRect();
      popover.style.left = (rect.left - gridRect.left + grid.scrollLeft +
                            rect.width + 8) + "px";
      popover.style.top  = (rect.top  - gridRect.top  + grid.scrollTop) + "px";
      grid.appendChild(popover);
      activeCard = card;
      popover.querySelector(".conf-dismiss").addEventListener("click",
        ev => {
          ev.stopPropagation();
          try { localStorage.setItem(KEY, "1"); } catch (_e) {}
          dismissed = true;
          _hide();
        });
    }

    function _hide() {
      if (popover) { try { popover.remove(); } catch (_e) {} }
      popover = null;
      activeCard = null;
    }

    grid.addEventListener("mouseover", ev => {
      if (dismissed) return;
      const card = ev.target.closest(".card");
      if (!card || !card.dataset.fn) return;
      if (card === activeCard) return;
      const row = (typeof window.rows !== "undefined" ? window.rows : rows)
        .find(r => r.filename === card.dataset.fn);
      if (!row || !_isUncertain(row)) {
        _hide();
        return;
      }
      _show(card, row);
    });
    grid.addEventListener("mouseleave", _hide);
    // Esc anywhere closes
    document.addEventListener("keydown", ev => {
      if (ev.key === "Escape") _hide();
    });
  })();
