  (function setupAnnotationExplainer() {
    const KEY = "pixcull_seen_rubric_intro_v1";
    const am = document.getElementById("annModal");
    if (!am) return;
    let injected = false;
    function _seen() {
      try { return localStorage.getItem(KEY) === "1"; }
      catch (_e) { return true; }   // privacy mode → treat as seen
    }
    function _markSeen() {
      try { localStorage.setItem(KEY, "1"); } catch (_e) {}
    }
    function _inject() {
      if (injected) return;
      injected = true;
      const layer = document.createElement("div");
      layer.id = "rubricIntroLayer";
      layer.style.cssText = (
        "position:fixed;inset:0;z-index:120;display:flex;" +
        "align-items:center;justify-content:center;" +
        "background:rgba(0,0,0,0.75);backdrop-filter:blur(4px);" +
        "opacity:0;transition:opacity 320ms cubic-bezier(0.2,0.8,0.2,1);"
      );
      const card = document.createElement("div");
      card.style.cssText = (
        "width:min(520px,92vw);background:linear-gradient(135deg,#2a2c36,#1d1f29);" +
        "border:1px solid rgba(255,255,255,0.10);border-radius:14px;" +
        "padding:28px;color:#fff;text-align:center;" +
        "transform:perspective(700px) rotateY(70deg);" +
        "transition:transform 540ms cubic-bezier(0.34,1.56,0.64,1);" +
        "box-shadow:0 30px 70px rgba(0,0,0,0.45);"
      );
      card.innerHTML = (
        "<div style='font-size:30px;margin-bottom:8px'>⌬</div>" +
        "<h2 style='margin:0 0 6px;font-size:20px;letter-spacing:-0.01em'>每张照片 6 个轴 · 1-5★</h2>" +
        "<div style='color:#a0a4b0;font-size:13px;line-height:1.65;margin-bottom:18px'>" +
        "技术 · 主体 · 构图 · 光线 · 时刻 · 美感<br>" +
        "Tab 在轴间跳 · 1-5 直接给当前轴打星 · 一张全维度评分通常 &lt; 5 秒。" +
        "</div>" +
        "<button id='rubricIntroDismiss' type='button' " +
        "style='background:linear-gradient(135deg,#d5b584,#93743f);color:#fff;" +
        "border:0;padding:9px 22px;border-radius:999px;font-weight:600;" +
        "font-size:13px;cursor:pointer'>开始 →</button>"
      );
      layer.appendChild(card);
      document.body.appendChild(layer);
      // Trigger the flip + fade after one frame
      requestAnimationFrame(() => {
        layer.style.opacity = "1";
        card.style.transform = "perspective(700px) rotateY(0deg)";
      });
      function _dismiss() {
        _markSeen();
        document.removeEventListener("keydown", _onKey, true);
        layer.style.opacity = "0";
        card.style.transform = "perspective(700px) rotateY(-70deg)";
        setTimeout(() => layer.remove(), 360);
      }
      // Persistent CAPTURE-phase key handling. The old `{ once:true }`
      // Escape listener was consumed by the FIRST keypress of ANY key —
      // a keyboard-flow user (1/2/3/Tab mid-cull) burned it instantly,
      // Escape went dead and the veil read as a frozen UI. While the
      // veil is up we also swallow every other shortcut, so keys can't
      // silently annotate/navigate the photos behind it.
      function _onKey(ev) {
        if (!document.body.contains(layer)) {
          document.removeEventListener("keydown", _onKey, true);
          return;
        }
        if (ev.key === "Escape" || ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault(); ev.stopPropagation();
          _dismiss();
          return;
        }
        if (ev.key === "Tab") return;       // keep the dismiss button reachable
        ev.stopPropagation();               // veil up → no shortcuts behind it
      }
      document.getElementById("rubricIntroDismiss")
              .addEventListener("click", _dismiss);
      layer.addEventListener("click", ev => {
        if (ev.target === layer) _dismiss();
      });
      document.addEventListener("keydown", _onKey, true);
    }
    // Hook: watch for .ann-modal getting .show — that's the "first open"
    // trigger.  Mutation observer keeps us decoupled from the existing
    // openAnnotationModal callsites.
    const mo = new MutationObserver(() => {
      if (am.classList.contains("show") && !_seen()) {
        _inject();
      }
    });
    mo.observe(am, { attributes: true, attributeFilter: ["class"] });
  })();
