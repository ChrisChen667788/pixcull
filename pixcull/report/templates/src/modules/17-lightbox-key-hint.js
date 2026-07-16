  (function setupLightboxKeyHint() {
    const KEY = "pixcull_seen_lightbox_keys_v0_13";
    let seen = false;
    try { seen = localStorage.getItem(KEY) === "1"; } catch (_e) { seen = true; }
    if (seen) return;
    const lb = document.getElementById("lightbox");
    if (!lb) return;
    function _markSeen() {
      try { localStorage.setItem(KEY, "1"); } catch (_e) {}
      seen = true;
    }
    function _show() {
      if (seen) return;
      _markSeen();
      const toast = document.createElement("div");
      toast.style.cssText = (
        "position:absolute;bottom:120px;left:50%;transform:translateX(-50%);" +
        "background:rgba(20,18,14,0.96);color:#fff;" +
        "padding:14px 22px;border-radius:12px;z-index:8;" +
        "font:13px/1.6 system-ui;text-align:center;" +
        "box-shadow:0 12px 32px rgba(0,0,0,0.45);" +
        "border:1px solid rgba(196,185,169,0.30);" +
        "max-width:min(560px,90vw);" +
        "opacity:0;transition:opacity 320ms cubic-bezier(0.2,0.8,0.2,1)," +
        "transform 320ms cubic-bezier(0.34,1.56,0.64,1);"
      );
      toast.innerHTML = (
        "<div style='font-weight:600;color:#c4b9a9;margin-bottom:6px;" +
        "font-size:11px;letter-spacing:0.04em;text-transform:uppercase'>" +
        "✨ 这是你第一次打开 lightbox</div>" +
        "<div>三个 PixCull 专属键位:</div>" +
        "<div style='margin-top:8px;display:flex;justify-content:center;gap:18px;flex-wrap:wrap'>" +
        "<span><kbd style='background:rgba(196,185,169,0.20);padding:3px 8px;" +
        "border-radius:4px;font-family:ui-monospace,Menlo;color:#fff;" +
        "border:1px solid rgba(196,185,169,0.40);font-size:11px'>A</kbd> " +
        "<span style='color:#aaa;font-size:11.5px'>AI heatmap</span></span>" +
        "<span><kbd style='background:rgba(196,185,169,0.20);padding:3px 8px;" +
        "border-radius:4px;font-family:ui-monospace,Menlo;color:#fff;" +
        "border:1px solid rgba(196,185,169,0.40);font-size:11px'>H</kbd> " +
        "<span style='color:#aaa;font-size:11.5px'>EXIF + 直方图</span></span>" +
        "<span><kbd style='background:rgba(196,185,169,0.20);padding:3px 8px;" +
        "border-radius:4px;font-family:ui-monospace,Menlo;color:#fff;" +
        "border:1px solid rgba(196,185,169,0.40);font-size:11px'>\\</kbd> " +
        "<span style='color:#aaa;font-size:11.5px'>burst 比较</span></span>" +
        "</div>" +
        "<div style='margin-top:8px;color:#888;font-size:10.5px'>" +
        "按任意键 / 6 秒后自动消失</div>"
      );
      lb.appendChild(toast);
      requestAnimationFrame(() => {
        toast.style.opacity = "1";
      });
      const fade = () => {
        toast.style.opacity = "0";
        setTimeout(() => { try { toast.remove(); } catch (_e) {} }, 320);
      };
      setTimeout(fade, 6000);
      document.addEventListener("keydown", fade, { once: true });
    }
    // Watch lightbox for first .show via MutationObserver
    const mo = new MutationObserver(() => {
      if (lb.classList.contains("show") && !seen) {
        // Defer 800ms so the user's eye lands on the image first
        setTimeout(_show, 800);
      }
    });
    mo.observe(lb, { attributes: true, attributeFilter: ["class"] });
  })();
