  (function _initTour() {
    const btn = document.getElementById("tourBtn");
    const modal = document.getElementById("tourModal");
    if (!btn || !modal) return;
    if (typeof registerModal === "function") registerModal(modal);
    btn.addEventListener("click", () => modal.classList.add("show"));
    const closeBtn = document.getElementById("tourClose");
    if (closeBtn) closeBtn.addEventListener("click",
      () => modal.classList.remove("show"));
    modal.addEventListener("click", e => {
      if (e.target === modal) modal.classList.remove("show");
    });
    // registerModal only wires the focus trap — Escape is per-modal.
    // CAPTURE phase + stopPropagation: the global Escape chain would
    // otherwise ALSO fire on the same keypress and close the lightbox
    // underneath the tour (v2.5 stability sweep).
    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && modal.classList.contains("show")) {
        e.preventDefault(); e.stopPropagation();
        modal.classList.remove("show");
      }
    }, true);
    try {
      if (localStorage.getItem("pixcull_tour_pulse_v1") !== "1") {
        setTimeout(() => {
          btn.classList.add("onboard-pulse");
          setTimeout(() => btn.classList.remove("onboard-pulse"), 5500);
          // Persist only once the pulse actually rendered — setting it
          // eagerly meant a reload inside the 2.2 s delay suppressed the
          // one-shot hint forever (adversarial-review finding).
          try { localStorage.setItem("pixcull_tour_pulse_v1", "1"); } catch (e) {}
        }, 2200);
      }
    } catch (e) {}
  })();
