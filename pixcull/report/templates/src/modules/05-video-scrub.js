  (function initVideoScrub() {
    const V = PAYLOAD.video;
    if (!V || !Array.isArray(V.frames) || !V.frames.length) return;
    const frames = V.frames, reel = V.reel || [];
    const audio = V.audio || [];   // v2.19-P2 — bottom-lane events
    const fnIdx = new Map(frames.map((f, i) => [f.filename, i]));
    const t0 = frames[0].t, tEnd = frames[frames.length - 1].t || (t0 + 1);
    let playing = 0, speed = 1, timer = null;
    const st = document.createElement("style");
    st.textContent =
      "#lbVideoBar{position:absolute;left:50%;transform:translateX(-50%);"
      + "bottom:104px;width:min(72%,900px);z-index:42;background:rgba(10,11,13,.86);"
      + "backdrop-filter:blur(8px);border:1px solid #23262e;border-radius:12px;"
      + "padding:8px 12px 10px;display:none}"
      + ".lightbox.show #lbVideoBar{display:block}"
      + "#lbVideoBar .vbc{display:flex;gap:8px;align-items:center;margin-bottom:5px}"
      + "#lbVideoBar button{background:#1b1e26;border:1px solid #23262e;color:#e8e8ea;"
      + "border-radius:7px;padding:4px 11px;font-size:13px;cursor:pointer}"
      + "#lbVideoBar button.on{background:#c4b9a9;border-color:#c4b9a9;color:#fff}"
      + "#lbVideoBar .vbr{margin-left:auto;color:#9aa0aa;font:11px ui-monospace,monospace}"
      + "#vbTl{width:100%;height:54px;display:block;cursor:pointer;touch-action:none}";
    document.head.appendChild(st);
    const bar = document.createElement("div");
    bar.id = "lbVideoBar";
    bar.innerHTML =
      '<div class="vbc"><button data-vb="back" title="后退播放">◀◀</button>'
      + '<button data-vb="pause" title="暂停" class="on">❚❚</button>'
      + '<button data-vb="fwd" title="前进播放">▶▶</button>'
      + '<span class="vbr" id="vbReadout">视频时间线</span></div>'
      + '<svg id="vbTl" viewBox="0 0 1000 60" preserveAspectRatio="none"></svg>';
    (document.getElementById("lightbox") || document.body).appendChild(bar);
    const tl = bar.querySelector("#vbTl");
    const readout = bar.querySelector("#vbReadout");
    const tx = (t) => (tEnd > t0) ? (t - t0) / (tEnd - t0) * 1000 : 0;
    function draw() {
      let s = "";
      reel.forEach((c) => {
        const x1 = tx(+c.start_s), x2 = tx(+c.end_s);
        s += '<rect x="' + x1.toFixed(1) + '" y="0" width="'
          + Math.max(2, x2 - x1).toFixed(1) + '" height="60" fill="#c4b9a9" '
          + 'opacity="' + (0.12 + 0.22 * Math.min(1, +c.score || 0)).toFixed(2) + '"/>';
        s += '<text x="' + (x1 + 2).toFixed(1) + '" y="11" fill="#d8cebf" '
          + 'font-size="9">#' + c.rank + '</text>';
      });
      // v2.19-P2 — audio-event lane (mirrors the /video review page).
      const AUD_FILL = { laughter: "var(--keep)", applause: "var(--accent-hi)",
                         music: "var(--muted)" };
      audio.forEach((e) => {
        const f = AUD_FILL[e.kind]; if (!f) return;
        const x1 = tx(+e.start_s), x2 = tx(+e.end_s);
        s += '<rect x="' + x1.toFixed(1) + '" y="55" width="'
          + Math.max(2, x2 - x1).toFixed(1) + '" height="4" rx="1.5" fill="' + f
          + '" opacity="0.9"><title>' + e.kind + " "
          + (+e.start_s).toFixed(1) + "–" + (+e.end_s).toFixed(1) + "s</title></rect>";
      });
      let area = "0,60", line = "";
      frames.forEach((f, i) => {
        const x = tx(f.t).toFixed(1), y = (60 - (f.score_temporal || 0) * 60).toFixed(1);
        area += " " + x + "," + y; line += (i ? " L" : "M") + x + " " + y;
      });
      area += " 1000,60";
      s += '<polygon points="' + area + '" fill="rgba(196,185,169,0.22)"/>';
      s += '<path d="' + line + '" fill="none" stroke="#c4b9a9" stroke-width="1.4"/>';
      s += '<line id="vbPh" x1="0" y1="0" x2="0" y2="60" stroke="#6a6052" stroke-width="2"/>';
      tl.innerHTML = s;
    }
    const curIdx = () => fnIdx.has(_lbCurrentFn) ? fnIdx.get(_lbCurrentFn) : 0;
    function go(i) {
      i = Math.max(0, Math.min(frames.length - 1, i));
      openLightbox(frames[i].filename);
    }
    function setBtns() {
      bar.querySelector('[data-vb=back]').classList.toggle("on", playing < 0);
      bar.querySelector('[data-vb=pause]').classList.toggle("on", playing === 0);
      bar.querySelector('[data-vb=fwd]').classList.toggle("on", playing > 0);
    }
    function pause() { playing = 0; speed = 1; if (timer) clearInterval(timer); timer = null; setBtns(); }
    function play(dir) {
      if (playing === dir) { speed = Math.min(8, speed * 2); }
      else { playing = dir; speed = 1; }
      if (timer) clearInterval(timer);
      timer = setInterval(() => {
        const nx = curIdx() + playing;
        if (nx < 0 || nx >= frames.length) { pause(); return; }
        go(nx);
      }, Math.max(60, 240 / speed));
      setBtns();
    }
    window._videoScrubSync = function () {
      if (!lb.classList.contains("show")) return;
      const f = frames[curIdx()];
      const p = tl.querySelector("#vbPh");
      if (p) { const x = tx(f.t); p.setAttribute("x1", x); p.setAttribute("x2", x); }
      readout.textContent = f.t.toFixed(2) + "s · score " +
        (f.score_temporal || 0).toFixed(2) + " · " + (curIdx() + 1) + "/" + frames.length;
    };
    let dragging = false;
    function seek(ev) {
      const r = tl.getBoundingClientRect();
      const x = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
      const t = t0 + x * (tEnd - t0);
      let best = 0, bd = 1e9;
      frames.forEach((f, i) => { const d = Math.abs(f.t - t); if (d < bd) { bd = d; best = i; } });
      pause(); go(best);
    }
    tl.addEventListener("pointerdown", (e) => { dragging = true; seek(e); });
    tl.addEventListener("pointermove", (e) => { if (dragging) seek(e); });
    window.addEventListener("pointerup", () => { dragging = false; });
    bar.querySelector('[data-vb=back]').onclick = () => play(-1);
    bar.querySelector('[data-vb=pause]').onclick = pause;
    bar.querySelector('[data-vb=fwd]').onclick = () => play(1);
    // Pausing on close keeps a stray interval from running in the bg.
    const _lbCloseEl = document.getElementById("lbClose");
    if (_lbCloseEl) _lbCloseEl.addEventListener("click", pause);
    draw();
  })();
