  (function _initTunedBadge() {
    const el = document.getElementById("tunedBadge");
    if (!el) return;
    fetch("/api/v1/users/profile")
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (!d) return;
        if (d.is_active) {
          const axis = d.most_cared_axis || "";
          el.textContent = "🎯 已按你调校" + (axis ? (" · 重" + axis) : "");
          el.style.display = "";
          return;
        }
        // v2.5 — cold-start progress. The moat used to be invisible
        // until 50 corrections; now any progress (≥3, so a first-time
        // visitor isn't nagged) shows how close "tuned to you" is.
        const n = d.n_annotations | 0, min = d.min_annotations | 0;
        if (min > 0 && n >= 3 && n < min) {
          el.textContent = "🎯 个性化 " + n + "/" + min;
          el.title = "每次 keep/cull 纠正都在教 PixCull 你的口味 — 再标 "
            + (min - n) + " 张,新批次就会自动按你的标准校准阈值";
          el.style.opacity = "0.62";
          el.style.display = "";
        }
      })
      .catch(() => {});
  })();
