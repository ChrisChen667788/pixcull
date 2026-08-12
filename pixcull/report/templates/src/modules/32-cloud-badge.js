(function _initCloudBadge() {
  // v2.50 — mark every frame a cloud model judged.
  //
  // Cloud judging now ships on. A photographer looking at a grid has to
  // be able to tell, without opening anything, which frames left the
  // machine — not because a number changed, but because whether a photo
  // was uploaded is a fact about their client relationship, and the
  // answer "check your CLI flags" is not good enough when they are on
  // the phone to that client.
  //
  // Renders only on rows that actually carry a verdict: an errored or
  // skipped call means nothing was judged, and a badge there would claim
  // an upload that produced nothing.
  const CLOUD = /^(minimax|deepseek|openai|custom):/;

  function decorate(card, row) {
    if (!row || !row.vlm_overall_label) return;
    if (card.querySelector(".cloud-badge")) return;
    const b = document.createElement("span");
    b.className = "cloud-badge";
    b.textContent = "☁";
    b.setAttribute("aria-label", "云端判图");
    // The override is the interesting case: a frame the local detectors
    // wanted to throw away, kept by a judge that had already been shown
    // why they wanted to. Surfacing it is what makes the override
    // reviewable instead of merely invisible.
    const kept = (row.reasons || "").indexOf("vlm_kept_despite") >= 0;
    if (kept) b.classList.add("cloud-badge-override");
    b.title = kept
      ? "MiniMax M3 判图 · 推翻了本机的硬性剔除标记(点开看理由)"
      : "MiniMax M3 判图 — 这张照片上传过";
    card.appendChild(b);
  }

  window.PixCullCloudBadge = { decorate, CLOUD };

  document.addEventListener("pixcull:cards-rendered", function (e) {
    const rows = (e && e.detail && e.detail.rows) || [];
    document.querySelectorAll(".card[data-idx]").forEach(function (card) {
      decorate(card, rows[card.getAttribute("data-idx") | 0]);
    });
  });
})();
