  (function setupLightboxTouch() {
    // ==================================================================
    // v0.9-P1-5 — iPad / touch gestures for the lightbox.
    //
    // Three gestures, all vanilla TouchEvent — no third-party library:
    //
    //   * 1-finger swipe (when fit) — horizontal Δ > 60 px → prev/next.
    //     Vertical Δ > 100 px → close lightbox (Apple Photos pattern).
    //     Always wins over a tap; sub-threshold motion falls through
    //     to the tap-to-zoom branch on touchend.
    //
    //   * 1-finger drag (when zoomed) — pan, identical to the existing
    //     mouse-drag path but adapted for TouchEvent coords. Clamps via
    //     the same _lbClampPan() so the photo can't drift off-screen.
    //
    //   * 2-finger pinch — zoom around the midpoint of the two fingers,
    //     calling _lbZoomToPoint with scale = current * (now / start).
    //
    //   * tap (Δ < 8 px, < 200 ms, 1 finger) — _lbZoomToggleAt at the
    //     touch point. Apple Photos: first tap fit → 1:1, second tap 1:1
    //     → fit. Stays out of the way of two-finger pinches and swipes.
    //
    // Wired directly on lbImg + the lightbox shell so the user can grab
    // either; native scroll/zoom is suppressed via touch-action CSS plus
    // preventDefault on the start event (one-time, so iOS Safari's
    // default tap-to-magnify never fires).
    // ==================================================================
    const _LB_TOUCH = {
      active:        false,
      startTime:     0,
      // 1-finger
      startX:        0,
      startY:        0,
      startPanX:     0,
      startPanY:     0,
      lastDX:        0,
      lastDY:        0,
      didSwipe:      false,
      // 2-finger pinch
      pinching:      false,
      startDist:     0,
      startMidX:     0,
      startMidY:     0,
      startScale:    1,
      // gesture classification thresholds
      tapDist:       8,
      tapMs:         220,
      swipeNavPx:    60,
      swipeClosePx:  100,
    };

    function _lbTouchDist(t0, t1) {
      return Math.hypot(t1.clientX - t0.clientX, t1.clientY - t0.clientY);
    }
    function _lbTouchMid(t0, t1) {
      return [(t0.clientX + t1.clientX) / 2,
              (t0.clientY + t1.clientY) / 2];
    }

    lbImg.addEventListener("touchstart", e => {
      if (!lb.classList.contains("show")) return;
      // Suppress iOS Safari's native pinch/scroll/tap-magnify so we
      // own the gesture entirely.  touch-action: none on .lb-img
      // (CSS below) handles it for browsers that honour it, but we
      // still preventDefault for the older WebKit fallback.
      if (e.touches.length >= 1) e.preventDefault();
      _LB_TOUCH.active    = true;
      _LB_TOUCH.startTime = Date.now();
      _LB_TOUCH.didSwipe  = false;
      if (e.touches.length === 1) {
        _LB_TOUCH.pinching  = false;
        _LB_TOUCH.startX    = e.touches[0].clientX;
        _LB_TOUCH.startY    = e.touches[0].clientY;
        _LB_TOUCH.startPanX = _lbZoom.panX;
        _LB_TOUCH.startPanY = _lbZoom.panY;
        _LB_TOUCH.lastDX    = 0;
        _LB_TOUCH.lastDY    = 0;
        if (_lbZoom.mode === "1to1") lbImg.classList.add("dragging");
      } else if (e.touches.length === 2) {
        _LB_TOUCH.pinching   = true;
        _LB_TOUCH.startDist  = _lbTouchDist(e.touches[0], e.touches[1]);
        const [mx, my]       = _lbTouchMid(e.touches[0], e.touches[1]);
        _LB_TOUCH.startMidX  = mx;
        _LB_TOUCH.startMidY  = my;
        _LB_TOUCH.startScale = _lbZoom.scale || 1;
        lbImg.classList.remove("dragging");
      }
    }, { passive: false });

    lbImg.addEventListener("touchmove", e => {
      if (!_LB_TOUCH.active) return;
      e.preventDefault();
      if (_LB_TOUCH.pinching && e.touches.length === 2) {
        const dist = _lbTouchDist(e.touches[0], e.touches[1]);
        const ratio = dist / (_LB_TOUCH.startDist || dist || 1);
        const target = _LB_TOUCH.startScale * ratio;
        const [mx, my] = _lbTouchMid(e.touches[0], e.touches[1]);
        // Anchor the zoom around the midpoint of the two fingers so
        // the pixel the user pinched stays under their fingers.
        _lbZoomToPoint(target, mx, my);
        return;
      }
      if (e.touches.length === 1) {
        const dx = e.touches[0].clientX - _LB_TOUCH.startX;
        const dy = e.touches[0].clientY - _LB_TOUCH.startY;
        _LB_TOUCH.lastDX = dx;
        _LB_TOUCH.lastDY = dy;
        if (_lbZoom.mode === "1to1") {
          // Drag-pan when zoomed.
          _lbZoom.panX = _LB_TOUCH.startPanX + dx;
          _lbZoom.panY = _LB_TOUCH.startPanY + dy;
          _lbClampPan();
          _applyLbTransform();
        } else {
          // Fit-mode: preview the swipe with a small follow-the-finger
          // translate so the user feels the gesture being recognised.
          // Only horizontal — vertical close-gesture also nudges DOWN
          // for visual feedback.
          const absX = Math.abs(dx), absY = Math.abs(dy);
          if (absX > _LB_TOUCH.tapDist || absY > _LB_TOUCH.tapDist) {
            _LB_TOUCH.didSwipe = true;
            // Damped follow (60% of finger movement) gives a rubber-
            // band feel without committing to a full transform.
            if (absX > absY) {
              lbImg.style.transform = `translateX(${dx * 0.6}px)`;
            } else if (dy > 0) {
              lbImg.style.transform = `translate(0, ${dy * 0.6}px) scale(${1 - dy / 1200})`;
            }
          }
        }
      }
    }, { passive: false });

    function _lbEndTouch() {
      _LB_TOUCH.active = false;
      _LB_TOUCH.pinching = false;
      lbImg.classList.remove("dragging");
    }

    lbImg.addEventListener("touchend", e => {
      if (!_LB_TOUCH.active) return;
      const dt = Date.now() - _LB_TOUCH.startTime;
      const dx = _LB_TOUCH.lastDX;
      const dy = _LB_TOUCH.lastDY;
      const wasPinching = _LB_TOUCH.pinching;
      _lbEndTouch();
      if (wasPinching) return;
      // Tap-to-zoom: short, tight, not a swipe
      if (!_LB_TOUCH.didSwipe
          && Math.hypot(dx, dy) < _LB_TOUCH.tapDist
          && dt < _LB_TOUCH.tapMs
          && e.changedTouches.length === 1) {
        const t = e.changedTouches[0];
        _lbZoomToggleAt(t.clientX, t.clientY);
        return;
      }
      // Reset any drag preview translate before deciding nav-vs-snap-back
      if (_lbZoom.mode !== "1to1") lbImg.style.transform = "";
      if (_lbZoom.mode === "1to1") return;  // pan completed — nothing else to do
      const absX = Math.abs(dx), absY = Math.abs(dy);
      if (absX > _LB_TOUCH.swipeNavPx && absX > absY) {
        // Horizontal swipe: prev / next
        lightboxStep(dx < 0 ? +1 : -1);
      } else if (dy > _LB_TOUCH.swipeClosePx && absY > absX) {
        // Vertical drag-down: close (Apple Photos)
        lb.classList.remove("show");
      }
      // sub-threshold → snap back (the transform reset above already did it)
    }, { passive: false });

    lbImg.addEventListener("touchcancel", () => {
      _lbEndTouch();
      // Snap back from any partial swipe preview
      if (_lbZoom.mode !== "1to1") lbImg.style.transform = "";
    });

    // ============================================================
    // v0.7-P1-1 — Loupe RGB readout (lightbox).  Mirrors the
    // cmpModal RGB readout shipped in v0.7-P0-1: visible only when
    // lbImg is in `.zoomed` (1:1) state AND the cursor is inside
    // the image rect.  Reuses _ensureRgbCanvas / _samplePixel
    // helpers defined for the cmpModal so we don't duplicate
    // canvas-sampling logic.
    // ============================================================
    const lbRgbReadout = document.getElementById("lbRgbReadout");
    function _hideLbRgbReadout() {
      if (lbRgbReadout) lbRgbReadout.classList.remove("show");
    }
    function _updateLbRgbReadout(e) {
      if (!lbRgbReadout || !lbImg) return;
      if (!lb.classList.contains("show")) { _hideLbRgbReadout(); return; }
      if (!lbImg.classList.contains("zoomed")) { _hideLbRgbReadout(); return; }
      const rect = lbImg.getBoundingClientRect();
      if (e.clientX < rect.left || e.clientX > rect.right ||
          e.clientY < rect.top  || e.clientY > rect.bottom) {
        _hideLbRgbReadout();
        return;
      }
      const nx = ((e.clientX - rect.left) / rect.width)  * lbImg.naturalWidth;
      const ny = ((e.clientY - rect.top)  / rect.height) * lbImg.naturalHeight;
      const px = _samplePixel(lbImg, nx, ny);
      if (!px) { _hideLbRgbReadout(); return; }
      const y = Math.round(0.299*px.r + 0.587*px.g + 0.114*px.b);
      const hex = "#" + [px.r, px.g, px.b]
        .map(v => v.toString(16).padStart(2, "0").toUpperCase()).join("");
      lbRgbReadout.innerHTML = `
        <div class="rgb-line">
          <span class="swatch" style="background:rgb(${px.r},${px.g},${px.b})"></span>
          <span class="rgb-vals">R ${px.r}&nbsp;&nbsp;G ${px.g}&nbsp;&nbsp;B ${px.b}</span>
        </div>
        <div class="rgb-hex">${hex}</div>
        <div class="rgb-y">Y ${y} · ${Math.round((y/255)*100)}%</div>
      `;
      const READ_W = 160, READ_H = 64;
      let left = e.clientX + 14;
      let top  = e.clientY + 14;
      if (left + READ_W > window.innerWidth)  left = e.clientX - READ_W - 12;
      if (top  + READ_H > window.innerHeight) top  = e.clientY - READ_H - 12;
      lbRgbReadout.style.left = left + "px";
      lbRgbReadout.style.top  = top  + "px";
      lbRgbReadout.classList.add("show");
    }
    // Bind on the img-pane so the readout still fires inside the
    // padding around lbImg when zoomed (and hides cleanly when the
    // cursor wanders outside the actual image rect).
    lbImg.parentElement.addEventListener("mousemove", _updateLbRgbReadout);
    lbImg.parentElement.addEventListener("mouseleave", _hideLbRgbReadout);
    // Lightbox close → hide readout (avoid a phantom panel hanging
    // on screen after the lightbox transitions out).
    lb.addEventListener("transitionend", _hideLbRgbReadout);

    // ============================================================
    // v0.7-P1-2 — Inspector mobile bottom-sheet.
    // On ≤640px the .info-pane is a 140px peek drawer; tap the
    // drag-handle area (top ~22px) to expand to 80vh. Tap again
    // (or tap the image area) to collapse. Swiping the drawer
    // up/down is handled by browser scroll once it's expanded
    // (overflow-y: auto), so no custom touch math required.
    // ============================================================
    const _LB_BOTTOMSHEET_MQ = window.matchMedia("(max-width: 640px)");
    function _lbToggleInfoExpanded() {
      if (!_LB_BOTTOMSHEET_MQ.matches) return;
      lb.classList.toggle("info-expanded");
    }
    if (lbInfo) {
      lbInfo.addEventListener("click", e => {
        if (!_LB_BOTTOMSHEET_MQ.matches) return;
        // Only the top 22px (the drag-handle band) triggers toggle.
        // Clicks inside expanded content keep working (links, pills,
        // section toggles, etc.).
        if (!lb.classList.contains("info-expanded")) {
          // Collapsed: any tap on the peek area expands.
          _lbToggleInfoExpanded();
          e.preventDefault();
          return;
        }
        // Expanded: tap on the top handle band collapses.
        const rect = lbInfo.getBoundingClientRect();
        if (e.clientY - rect.top < 22) {
          _lbToggleInfoExpanded();
          e.preventDefault();
        }
      });
    }
    // Tapping the dimmed image area while expanded → collapse.
    // Capture: true so this fires before the lightbox close handler
    // (which would otherwise dismiss the lightbox on mobile when
    // the user just meant to dismiss the drawer).
    lbImg.parentElement.addEventListener("click", e => {
      if (!_LB_BOTTOMSHEET_MQ.matches) return;
      if (!lb.classList.contains("info-expanded")) return;
      // Only the scrim (NOT the image itself) collapses.
      if (e.target === lbImg) return;
      lb.classList.remove("info-expanded");
      e.stopPropagation();
    }, true);
    // Reset drawer state every time the lightbox opens so a
    // previously-expanded session doesn't leak into the next photo.
    // v2.68.3 — the `info-expanded` check is not redundant; it is the
    // whole fix.
    //
    // `DOMTokenList.remove()` re-serialises and SETS the class attribute
    // unconditionally — the spec's "update steps" run whether or not the
    // token was present — and setting an attribute queues a mutation
    // record even when the value is identical. So this callback, which
    // observes `class` on `lb` and then writes `class` on `lb`, fed
    // itself: close the lightbox, `show` goes away, the callback removes
    // a token that was already absent, that write queues another record,
    // the callback runs again. Forever, at 100% CPU, until reload.
    //
    // It could only ever fire on CLOSE — with `show` present the branch
    // is skipped — which is exactly the shape of the report: opening a
    // photo was fine, exiting killed the page.
    const _lbOpenObserver = new MutationObserver(() => {
      if (!lb.classList.contains("show")
          && lb.classList.contains("info-expanded")) {
        lb.classList.remove("info-expanded");
      }
    });
    _lbOpenObserver.observe(lb, { attributes: true, attributeFilter: ["class"] });

    lb.addEventListener("click", e => {
      // Only close on backdrop or img-pane padding click — not on info-
      // pane, close button, nav buttons, rotate buttons, zoom buttons,
      // or the image itself (the image has its own click → toggle zoom).
      if (e.target.closest(".info-pane")) return;
      if (e.target === lbClose) return;
      if (e.target.closest(".nav-btn")) return;
      if (e.target.closest(".rotate-grp")) return;
      if (e.target.closest(".zoom-grp")) return;
      if (e.target === lbImg) return;
      lb.classList.remove("show");
    });

    // P-UX-6 — sticky decision toolbar inside the lightbox info pane.
  })();
