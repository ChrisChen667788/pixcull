  (function setupDragReorder() {
    function _wire(sel, persistKey) {
      const containers = document.querySelectorAll(sel);
      if (!containers.length) return;
      let dragged = null;
      containers.forEach(container => {
        // Make every child item draggable.  Setting the attribute on
        // the container alone doesn't work; HTML5 requires per-item.
        container.querySelectorAll(":scope > *").forEach(it => {
          it.setAttribute("draggable", "true");
        });
        container.addEventListener("dragstart", ev => {
          const it = ev.target.closest(":scope > *");
          if (!it) return;
          dragged = it;
          ev.dataTransfer.effectAllowed = "move";
          it.classList.add("dragging");
        });
        container.addEventListener("dragend", ev => {
          const it = ev.target.closest(":scope > *");
          if (it) it.classList.remove("dragging");
          dragged = null;
        });
        container.addEventListener("dragover", ev => {
          ev.preventDefault();
          if (!dragged) return;
          const over = ev.target.closest(":scope > *");
          if (!over || over === dragged) return;
          const rect = over.getBoundingClientRect();
          const before = (ev.clientY - rect.top) < rect.height / 2;
          container.insertBefore(dragged, before ? over : over.nextSibling);
        });
        container.addEventListener("drop", ev => {
          ev.preventDefault();
          // Persist the new order.  The actual API is best-effort —
          // localStorage gives offline behaviour; server endpoint can
          // be wired later (the existing /buckets API supports this).
          const order = Array.from(container.children)
            .map(c => c.dataset.id || c.dataset.fn || c.textContent.trim())
            .filter(Boolean);
          if (persistKey) {
            try { localStorage.setItem(persistKey, JSON.stringify(order)); }
            catch (e) {}
          }
        });
      });
    }
    _wire(".buckets-list", `pixcull_bucket_order:${run_id}`);
    _wire(".share-portfolio-grid", `pixcull_portfolio_order:${run_id}`);
  })();
