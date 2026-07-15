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
    const tip = document.createElement("div");
    tip.className = "onboard-tip";
    tip.setAttribute("role", "complementary");
    tip.setAttribute("aria-label", "新用户提示");
    tip.innerHTML = `
      <div class="onb-head">
        <span class="onb-icon"><svg class="icon"><use href="#icon-sparkles"/></svg></span>
        <span class="onb-title">新手提示</span>
        <button class="onb-close" type="button" aria-label="关闭提示">✕</button>
      </div>
      <ul class="onb-list">
        <li><kbd>1</kbd> / <kbd>2</kbd> / <kbd>3</kbd> 标 keep / maybe / cull<b>并自动跳下一张</b>(连标 ~1-2 秒/张;⏩ 可关)</li>
        <li><kbd>?</kbd> 看所有快捷键(根据当前视图自动高亮)</li>
        <li>右上角 <b>🪣 桶</b>:拖卡片进去整理交付包</li>
      </ul>
      <button class="onb-dismiss" type="button">知道了,不再提示</button>`;
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
