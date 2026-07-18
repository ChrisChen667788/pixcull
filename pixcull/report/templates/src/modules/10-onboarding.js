  (function _initOnboarding() {
    const KEY = "pixcull_onboarded_v1";
    let done = false;
    try { done = localStorage.getItem(KEY) === "1"; } catch (e) {}
    if (done) return;

    // 1. Pulse the three floating affordances, staggered so the
    //    user's eye is drawn from one to the next.
    setTimeout(() => {
      const targets = [
        ["bucketsToggleBtn", 0],
        ["a11yToggleBtn",    600],
        ["shortcutsHint",    1200],
      ];
      targets.forEach(([id, delay]) => {
        const el = document.getElementById(id);
        if (!el) return;
        setTimeout(() => {
          el.classList.add("onboard-pulse");
          setTimeout(() => el.classList.remove("onboard-pulse"), 5500);
        }, delay);
      });
    }, 900);

    // 2. Tip card with the three highest-value shortcuts. We build
    //    it in JS rather than markup so non-first-time users never
    //    even have it in the DOM.
    // v2.23-P1 — every user-visible string carries a data-i18n* attr so
    // _applyLangToDom() repaints it when the locale applies (the module
    // runs at parse time, before the async locale fetch resolves — the
    // same boot-order trap the v2.22 session-close fix hit; data-i18n is
    // the codebase's idiomatic answer, no re-render call needed here).
    // Initial text uses _t() so a zh (or already-loaded) user is correct
    // on first paint; the <kbd> chips stay outside the translated span.
    const _T = (typeof _t === "function") ? _t : (k, f) => f;
    const tip = document.createElement("div");
    tip.className = "onboard-tip";
    tip.setAttribute("role", "complementary");
    tip.setAttribute("data-i18n-attr-aria-label", "onboard.aria");
    tip.setAttribute("aria-label", _T("onboard.aria", "新用户提示"));
    tip.innerHTML = `
      <div class="onb-head">
        <span class="onb-icon"><svg class="icon"><use href="#icon-sparkles"/></svg></span>
        <span class="onb-title" data-i18n="onboard.title">${_T("onboard.title", "新手提示")}</span>
        <button class="onb-close" type="button" data-i18n-attr-aria-label="onboard.close" aria-label="${_T("onboard.close", "关闭提示")}">✕</button>
      </div>
      <ul class="onb-list">
        <li><kbd>1</kbd> / <kbd>2</kbd> / <kbd>3</kbd> <span data-i18n="onboard.tip1">${_T("onboard.tip1", "标 keep / maybe / cull 并自动跳下一张(连标 ~1-2 秒/张;⏩ 可关)")}</span></li>
        <li><kbd>?</kbd> <span data-i18n="onboard.tip2">${_T("onboard.tip2", "看所有快捷键(根据当前视图自动高亮)")}</span></li>
        <li><span data-i18n="onboard.tip3">${_T("onboard.tip3", "右上角 🪣 桶:拖卡片进去整理交付包")}</span></li>
      </ul>
      <button class="onb-dismiss" type="button" data-i18n="onboard.dismiss">${_T("onboard.dismiss", "知道了,不再提示")}</button>`;
    document.body.appendChild(tip);
    // Show on next paint so the transition runs
    requestAnimationFrame(() => tip.classList.add("show"));

    let dismissed = false;
    function dismiss() {
      if (dismissed) return;
      dismissed = true;
      tip.classList.remove("show");
      setTimeout(() => tip.remove(), 400);
      try { localStorage.setItem(KEY, "1"); } catch (e) {}
    }
    tip.querySelector(".onb-close").addEventListener("click", dismiss);
    tip.querySelector(".onb-dismiss").addEventListener("click", dismiss);

    // 3. Auto-dismiss after the first labeling keystroke — that's
    //    the strongest signal that the user has internalized the
    //    flow. We give a 4-second grace so they can finish reading
    //    the tip first.
    function _onFirstAction(e) {
      const k = e.key;
      if (k === "1" || k === "2" || k === "3" ||
          k === "f" || k === "F" || k === "?") {
        document.removeEventListener("keydown", _onFirstAction, true);
        setTimeout(dismiss, 4000);
      }
    }
    document.addEventListener("keydown", _onFirstAction, true);
  })();
