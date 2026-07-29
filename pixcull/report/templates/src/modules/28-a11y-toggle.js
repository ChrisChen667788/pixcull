  (function setupA11yToggle() {
    // ==================================================================
    // P-UX-23 — color-blind / a11y mode toggle. Tiny floating button at
    // bottom-left flips body.a11y-cb on/off; the CSS rules then remap
    // the keep/maybe/cull palette to Wong's deuteranopia-safe palette
    // (sky-blue / orange / magenta). Combined with the always-on shape
    // glyphs (✓/?/✕) on every decision badge — also added in this
    // ticket — the UI never depends on red/green discrimination.
    //
    // Why a single bool instead of a 3-way picker:
    //   - the deuteranopia-safe palette is also a fine palette for the
    //     ~92% of users with typical color vision, so "off / cb" covers
    //     the real use cases without a confusing options surface
    //   - if anyone needs a different palette they can override via a
    //     userscript / custom CSS; ours is just the audit-passing default
    // ==================================================================
    const _A11Y_PREF_KEY = "pixcull_a11y_pref";
    const a11yToggleBtn = document.getElementById("a11yToggleBtn");

    function _applyA11yPref(pref) {
      const cb = (pref === "cb");
      document.body.classList.toggle("a11y-cb", cb);
      if (a11yToggleBtn) {
        a11yToggleBtn.classList.toggle("on", cb);
        a11yToggleBtn.setAttribute("aria-pressed", cb ? "true" : "false");
      }
    }

    // Apply persisted preference before first paint of grid colors —
    // the CSS class on <body> is purely a paint hint so even setting
    // it after grid render is visually instant, but doing it here
    // avoids a one-frame palette flash on slow devices.
    try {
      const _saved = localStorage.getItem(_A11Y_PREF_KEY);
      if (_saved === "cb") _applyA11yPref("cb");
    } catch (e) { /* localStorage disabled — silently skip */ }

    if (a11yToggleBtn) {
      a11yToggleBtn.addEventListener("click", () => {
        const next = document.body.classList.contains("a11y-cb") ? "" : "cb";
        try { localStorage.setItem(_A11Y_PREF_KEY, next); }
        catch (e) { /* private / disabled — still apply for this tab */ }
        _applyA11yPref(next);
        // Surface the change to the user via the toast system so they
        // know the toggle did something (the palette change can be
        // subtle on darker monitors).
        if (typeof toast === "function") {
          toast(next === "cb"
            ? "色盲友好配色已开启(蓝 / 橙 / 紫 + ✓ / ? / ✕)"
            : "已切换回默认配色", "info");
        }
      });
    }

  })();
