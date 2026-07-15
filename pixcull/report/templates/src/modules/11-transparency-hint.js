  (function _initTransparencyHint() {
    const KEY = "pixcull_seen_transparency_v1";
    try {
      if (localStorage.getItem(KEY) === "1") return;
      if (localStorage.getItem("pixcull_onboarded_v1") !== "1") return; // wait until main onboarding done
    } catch (e) { return; }
    setTimeout(() => {
      const grp = document.querySelector('.lp-group[data-group="view"]');
      if (!grp || document.querySelector(".transparency-hint")) return;
      grp.classList.add("onboard-pulse");
      setTimeout(() => grp.classList.remove("onboard-pulse"), 5500);
      const tip = document.createElement("div");
      tip.className = "onboard-tip transparency-hint";
      tip.setAttribute("role", "complementary");
      tip.setAttribute("aria-label", "透明度功能提示");
      tip.innerHTML = `
        <div class="onb-head">
          <span class="onb-icon"><svg class="icon"><use href="#icon-sparkles"/></svg></span>
          <span class="onb-title">看得见的 AI</span>
          <button class="onb-close" type="button" aria-label="关闭提示">✕</button>
        </div>
        <ul class="onb-list">
          <li>左栏 <b>整理 · 折叠</b> 里 <b>≈ 近重复折叠</b> + 相似度滑块:拖一拖,看 AI 怎么把近似画面归组(可调,不是黑箱)</li>
          <li><b>🎬 时序场景</b>:按拍摄时间把这次拍摄切成叙事段落</li>
          <li>点开任意照片,顶部 <b>🔍 为什么</b> 一行讲清这张为何 keep / maybe / cull</li>
        </ul>
        <button class="onb-dismiss" type="button">知道了</button>`;
      document.body.appendChild(tip);
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
    }, 1600);   // let render() + buildViewToggles() populate the group first
  })();
