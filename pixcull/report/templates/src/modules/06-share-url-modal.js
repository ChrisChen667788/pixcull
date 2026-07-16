  (function _wireShareUrlModal() {
    const modal = document.getElementById("shareUrlModal");
    if (!modal) return;
    const closeBtn = document.getElementById("shareUrlClose");
    function close() {
      modal.classList.remove("show");
      modal.setAttribute("aria-hidden", "true");
    }
    closeBtn?.addEventListener("click", close);
    // Click backdrop (NOT card) → close
    modal.addEventListener("click", e => {
      if (e.target === modal) close();
    });
    // Esc closes
    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && modal.classList.contains("show")) {
        close();
      }
    });
    // Copy buttons (delegated)
    function wireCopy(btnId, inputId) {
      const b = document.getElementById(btnId);
      const inp = document.getElementById(inputId);
      if (!b || !inp) return;
      b.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(inp.value);
          const orig = b.textContent;
          b.textContent = "已复制 ✓";
          b.classList.add("ok");
          setTimeout(() => {
            b.textContent = orig;
            b.classList.remove("ok");
          }, 1400);
        } catch (_e) {
          // Fall back to selectAll so the user can ⌘C manually
          inp.focus();
          inp.select();
        }
      });
    }
    wireCopy("shareUrlShortCopy", "shareUrlShort");
    wireCopy("shareUrlLongCopy",  "shareUrlLong");
  })();
