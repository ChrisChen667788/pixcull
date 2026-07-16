  (function _populateRunTag() {
    const n = rows.length;
    const shortId = (run_id || "").slice(0, 12);
    const text = `${n} 张 · ${shortId}`;
    const newEl = document.getElementById("runPill");
    if (newEl) {
      newEl.textContent = text;
      newEl.style.display = "inline-flex";
      newEl.title = `run id: ${run_id}`;
    }
    const legacy = document.getElementById("runTag");
    if (legacy) {
      legacy.textContent = text;
      legacy.style.display = "inline-flex";
    }
    document.title = `PixCull · ${n} 张 · ${shortId}`;
  })();
