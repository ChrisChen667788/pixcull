(function _initSessionHealth() {
  // v3.21 — the run's own health, where the photographer can find it.
  //
  // `fallback_ledger` has recorded, per pass, how many frames were
  // candidates, how many were attempted, what was withheld and why. The
  // server puts all of it in /api/run/<id>. `results.html` has never read
  // a byte of it. So a run that quietly fell back to template advice on
  // 40% of frames looked, in the report, exactly like one that did not —
  // and the photographer's only route to the truth was /admin, which
  // they have no reason to open on a good day and no idea to open on a
  // bad one.
  //
  // WHERE IT GOES, AND WHY NOT NEXT TO THE PHOTOS. Health telemetry in
  // the main view reads as self-flagellation and gets ignored within a
  // week. This is one chip in the toolbar that appears ONLY when there
  // is something to say, and opens a panel when clicked. On a clean run
  // the photographer never sees it, which is the correct amount of
  // attention for "nothing went wrong".
  //
  // A structural fault is different from a rate and is styled as such:
  // "this pass had work to do and did none of it" is not a percentage,
  // it is a thing that is broken.

  const RUN_ID = (window.PIXCULL_RUN_ID
                  || (window.run_id !== undefined ? window.run_id : ""));

  function pct(x) { return Math.round((x || 0) * 100); }

  function summarise(fb, faults) {
    // Returns {level, headline, lines} or null when there is nothing to
    // report. Null is the common case and it must stay cheap.
    const passes = (fb && fb.passes) || {};
    const lines = [];
    let degraded = 0, withheld = 0;
    Object.keys(passes).sort().forEach(function (name) {
      const p = passes[name] || {};
      const fellBack = p.fell_back | 0;
      const held = p.withheld | 0;
      if (!fellBack && !held) return;
      if (fellBack) degraded += fellBack;
      if (held) withheld += held;
      const why = Object.keys(p.by_reason || {})
        .map(function (r) { return r + "×" + p.by_reason[r]; }).join(" · ");
      const heldWhy = Object.keys(p.withheld_reasons || {})
        .map(function (r) { return r + "×" + p.withheld_reasons[r]; }).join(" · ");
      lines.push({
        pass: name,
        attempted: p.attempted | 0,
        succeeded: p.succeeded | 0,
        fell_back: fellBack,
        rate: pct(p.fallback_rate),
        withheld: held,
        why: why,
        heldWhy: heldWhy,
      });
    });
    const hasFaults = !!(faults && faults.length);
    if (!lines.length && !hasFaults) return null;
    return {
      level: hasFaults ? "fault" : "degraded",
      headline: hasFaults
        ? _t("health.fault", "有一个环节该做的事一件没做")
        : _t("health.degraded", "本次有降级")
            + "(" + degraded + " 退回 / " + withheld + " 未做)",
      lines: lines,
      faults: (faults || []).slice(),
    };
  }

  function _t(key, fallback) {
    try {
      const v = (window.I18N || {})[key];
      return (typeof v === "string" && v.length) ? v : fallback;
    } catch (_e) { return fallback; }
  }

  function render(sum) {
    if (!sum) return;                 // clean run: no chip, no chrome
    const bar = document.querySelector(".toolbar") || document.body;
    if (document.getElementById("sessionHealthChip")) return;
    const chip = document.createElement("button");
    chip.id = "sessionHealthChip";
    chip.type = "button";
    chip.className = "pill session-health " + sum.level;
    chip.textContent = (sum.level === "fault" ? "⚠ " : "◐ ") + sum.headline;
    chip.title = _t("health.open", "点开看这次运行哪些环节降级了");
    chip.addEventListener("click", function () { openPanel(sum); });
    bar.appendChild(chip);
  }

  function openPanel(sum) {
    let el = document.getElementById("sessionHealthPanel");
    if (el) { el.hidden = !el.hidden; return; }
    el = document.createElement("div");
    el.id = "sessionHealthPanel";
    el.className = "session-health-panel";
    const rows = sum.lines.map(function (l) {
      return "<tr><td>" + l.pass + "</td><td>" + l.succeeded + "/"
        + l.attempted + "</td><td>" + l.rate + "%</td><td>"
        + (l.why || "—") + "</td><td>" + (l.withheld || 0)
        + (l.heldWhy ? " (" + l.heldWhy + ")" : "") + "</td></tr>";
    }).join("");
    const faults = sum.faults.length
      ? "<ul class=\"health-faults\"><li>"
        + sum.faults.join("</li><li>") + "</li></ul>"
      : "";
    el.innerHTML =
      "<h3>" + _t("health.title", "本次运行的健康度") + "</h3>"
      + faults
      + "<table><thead><tr><th>" + _t("health.pass", "环节")
      + "</th><th>" + _t("health.ok", "成功/尝试")
      + "</th><th>" + _t("health.rate", "退回率")
      + "</th><th>" + _t("health.why", "原因")
      + "</th><th>" + _t("health.withheld", "未做") + "</th></tr></thead>"
      + "<tbody>" + rows + "</tbody></table>"
      + "<p class=\"health-note\">"
      + _t("health.note",
           "「退回」= 该环节试过但用了兜底结果;「未做」= 该环节按配置根本没试。"
           + "两者不是一回事,分开记。")
      + "</p>";
    (document.querySelector("main") || document.body).appendChild(el);
  }

  function load() {
    if (!RUN_ID) return;
    fetch("/api/run/" + encodeURIComponent(RUN_ID))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (view) {
        if (!view) return;
        render(summarise(view.fallbacks, view.fallback_faults));
      })
      .catch(function () { /* health telemetry must never break the report */ });
  }

  window.PixCullSessionHealth = { summarise: summarise };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();
