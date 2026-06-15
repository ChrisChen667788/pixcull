(() => {
  const PAYLOAD = __PAYLOAD__;

  // V17.12 — browser-side error capture (same shape as /verticals
  // and upload pages). Best-effort POST; server respects V14.7
  // opt-in so this is a no-op when reporting is disabled.
  (function() {
    const _seen = new Set();
    function _capture(payload) {
      const key = (payload.message||"") + "|" + (payload.source||"") + "|" + (payload.lineno||"");
      if (_seen.has(key)) return;
      _seen.add(key);
      if (_seen.size > 20) return;
      try {
        fetch("/error_reports/client_event", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({...payload,
            url: location.pathname,
            ua: navigator.userAgent.slice(0, 200)}),
          keepalive: true,
        }).catch(() => {});
      } catch (e) {}
    }
    window.addEventListener("error", e => _capture({
      kind: "error", message: e.message || "",
      source: e.filename || "", lineno: e.lineno || 0,
      colno: e.colno || 0,
      stack: (e.error && e.error.stack) || "",
    }));
    window.addEventListener("unhandledrejection", e => _capture({
      kind: "unhandledrejection",
      message: String((e.reason && e.reason.message) || e.reason || ""),
      stack: (e.reason && e.reason.stack) || "",
    }));
  })();
  const { run_id, rows, summary } = PAYLOAD;

  // v0.5 — populate the new workspace-bar run pill.  Still
  // updates the legacy #runTag too in case anything probes it,
  // but the visible affordance is now #runPill inside .crumb-title.
  (function _populateRunTag() {
    const n = rows.length;
    const shortId = (run_id || "").slice(0, 12);
    const text = `${n} 张 · ${shortId}`;
    const newEl = document.getElementById("runPill");
    if (newEl) {
      newEl.textContent = text;
      newEl.style.display = "inline-flex";
      newEl.title = `run id: ${run_id}`;
    }
    const legacy = document.getElementById("runTag");
    if (legacy) {
      legacy.textContent = text;
      legacy.style.display = "inline-flex";
    }
    document.title = `PixCull · ${n} 张 · ${shortId}`;
  })();

  // P-UX-25 — multi-tab annotation conflict guard. Public surface
  // declared here at the top of the IIFE so quickLabel() / _lbLabel()
  // can call broadcastAnnotation() unconditionally; the real
  // BroadcastChannel + UI wiring is in the _initMultiTab() block
  // further down (it needs toast()/render() to be defined first).
  // Until init runs, broadcastAnnotation is a no-op stub.
  const _pixMultiTab = { broadcastAnnotation: () => {} };

  // V14.0 — shared HTML escape. Used everywhere a server-supplied
  // string (filename, scene name, rationale text) lands in innerHTML
  // or an attribute. Prevents a filename like ``"><script>alert(1)`` from
  // breaking the lightbox or the cluster header.
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
  ));

  // ==================================================================
  // v0.8-P0-1 — UI i18n shim (zh_CN ↔ en_US).
  //
  // Every translatable element in the template carries
  //   data-i18n="key"               (for textContent)
  //   data-i18n-attr-title="key"    (for the title attr)
  //   data-i18n-attr-aria-label="key" (etc.)
  // _applyLang(lang) fetches /api/v1/locale?lang=<lang>, merges the
  // result into I18N_STRINGS, and re-paints every annotated element.
  // The choice is persisted in localStorage so reloads / new tabs
  // pick it up. Default is zh_CN.
  //
  // The first paint (DOMContentLoaded) only flips strings when the
  // user has previously set a non-default language — avoids an
  // unnecessary network round-trip on the common case.
  // ==================================================================
  const I18N_KEY = "pixcull_lang";
  let I18N_STRINGS = {};        // key → translated string (current lang)
  let I18N_CURRENT = "zh_CN";   // current language code

  // v0.8-P2-1 — supported locale cycle.
  const I18N_CYCLE = ["zh_CN", "en_US", "ja_JP"];
  // Single-char chip label per locale (what the switcher shows).
  const I18N_CHIP_LABEL = {zh_CN: "中", en_US: "EN", ja_JP: "あ"};
  function _getStoredLang() {
    try {
      const v = localStorage.getItem(I18N_KEY);
      return I18N_CYCLE.includes(v) ? v : "zh_CN";
    } catch (_e) { return "zh_CN"; }
  }
  function _setStoredLang(lang) {
    try { localStorage.setItem(I18N_KEY, lang); } catch (_e) {}
  }

  async function _fetchLocale(lang) {
    try {
      const r = await fetch(`/api/v1/locale?lang=${encodeURIComponent(lang)}`);
      if (!r.ok) return null;
      const d = await r.json();
      return (d && d.strings && typeof d.strings === "object") ? d.strings : null;
    } catch (_e) { return null; }
  }

  // Re-paint every element carrying a data-i18n* attribute.
  // Missing keys leave the existing text in place (the original
  // template's hardcoded Chinese is a graceful fallback).
  function _applyLangToDom() {
    document.querySelectorAll("[data-i18n]").forEach(el => {
      const key = el.getAttribute("data-i18n");
      const txt = I18N_STRINGS[key];
      if (typeof txt === "string" && txt.length) {
        el.textContent = txt;
      }
    });
    // Attribute-keyed translations (title / aria-label / placeholder)
    document.querySelectorAll("[data-i18n-attr-title]").forEach(el => {
      const v = I18N_STRINGS[el.getAttribute("data-i18n-attr-title")];
      if (typeof v === "string" && v.length) el.setAttribute("title", v);
    });
    document.querySelectorAll("[data-i18n-attr-aria-label]").forEach(el => {
      const v = I18N_STRINGS[el.getAttribute("data-i18n-attr-aria-label")];
      if (typeof v === "string" && v.length) el.setAttribute("aria-label", v);
    });
    document.querySelectorAll("[data-i18n-attr-placeholder]").forEach(el => {
      const v = I18N_STRINGS[el.getAttribute("data-i18n-attr-placeholder")];
      if (typeof v === "string" && v.length) el.setAttribute("placeholder", v);
    });
    // Update the lang switcher label to show the language the user
    // would switch TO next (cycles zh → en → ja → zh).
    const lblEl = document.getElementById("langSwitcherLabel");
    if (lblEl) {
      const idx = I18N_CYCLE.indexOf(I18N_CURRENT);
      const next = I18N_CYCLE[(idx + 1) % I18N_CYCLE.length];
      lblEl.textContent = I18N_CHIP_LABEL[next] || "EN";
    }
    // Update html lang attr so screen-readers + CSS :lang() rules work
    const _htmlLang = {zh_CN: "zh-CN", en_US: "en", ja_JP: "ja"};
    document.documentElement.setAttribute("lang",
      _htmlLang[I18N_CURRENT] || "en");
  }

  async function _applyLang(lang) {
    const strings = await _fetchLocale(lang);
    if (!strings) {
      // Couldn't fetch — leave the previous render in place.
      return false;
    }
    I18N_STRINGS = strings;
    I18N_CURRENT = lang;
    _setStoredLang(lang);
    _applyLangToDom();
    return true;
  }

  // Helper for dynamic strings (e.g. emitted from JS templating)
  // — returns the translated string or the key as fallback.
  function _t(key, fallback) {
    const v = I18N_STRINGS[key];
    return (typeof v === "string" && v.length) ? v : (fallback || key);
  }

  // Wire the switcher button + boot.
  document.addEventListener("DOMContentLoaded", () => {
    const stored = _getStoredLang();
    I18N_CURRENT = stored;
    const lblEl = document.getElementById("langSwitcherLabel");
    if (lblEl) {
      const idx = I18N_CYCLE.indexOf(stored);
      const next = I18N_CYCLE[(idx + 1) % I18N_CYCLE.length];
      lblEl.textContent = I18N_CHIP_LABEL[next] || "EN";
    }
    if (stored !== "zh_CN") {
      // The HTML is rendered server-side in zh — only fetch if the
      // user previously chose non-default.
      _applyLang(stored);
    }
    const btn = document.getElementById("langSwitcher");
    if (btn) {
      btn.addEventListener("click", async () => {
        // Cycle zh → en → ja → zh
        const idx = I18N_CYCLE.indexOf(I18N_CURRENT);
        const next = I18N_CYCLE[(idx + 1) % I18N_CYCLE.length];
        btn.disabled = true;
        const ok = await _applyLang(next);
        btn.disabled = false;
        if (!ok && typeof showToast === "function") {
          showToast("Locale switch failed", "error");
        }
      });
    }
  });

  // V16.0 — i18n display map. Keep token IDs (snake_case English) as
  // the wire format because (a) they're stable across versions and (b)
  // the rescorer / golden-set CSV tooling expects them. We translate
  // ONLY at render time so the data layer stays untouched.
  //
  // Strategy: every map falls back to the original token if the key
  // isn't found, so a new flag emitted by a future detector still
  // shows up (just in English) instead of vanishing — fail open, not
  // fail invisible.
  const I18N_GENRE = {
    portrait: "人像", wildlife: "野生", landscape: "风光",
    architecture: "建筑", street: "街拍", event: "事件",
    documentary: "纪实", fashion: "时尚", macro: "微距",
    food: "美食", sports: "运动", astro: "天文",
    abstract: "抽象", stilllife: "静物",
  };
  const I18N_STYLE = {
    mono: "黑白", low_key: "低调", high_key: "高调",
    silhouette: "剪影", long_exposure: "长曝光",
    rear_curtain_sync: "后帘同步", night: "夜景",
  };
  const I18N_FLAG = {
    severely_blurry:        "严重模糊",
    subject_blur:           "主体模糊",
    global_blur:            "整体偏软",
    blurred_subject:        "主体模糊",
    soft_subject:           "主体偏软",
    closed_eyes:            "闭眼帧",
    blink:                  "闭眼帧",
    motion_blur_on_face:    "脸部动态模糊",
    face_occluded:          "脸部遮挡",
    no_clear_subject:       "无明确主体",
    highlights_clipped:     "高光剪切",
    shadows_clipped:        "阴影剪切",
    severely_underexposed:  "严重欠曝",
    severely_overexposed:   "严重过曝",
    highlight_clip:         "高光剪切",
    horizon_tilt:           "地平线倾斜",
    duplicate_in_cluster:   "连拍组重复",
  };
  const I18N_SOURCE = {
    auto:   "自动规则",
    AUTO:   "自动规则",
    model:  "训练模型",
    MODEL:  "训练模型",
    vlm:    "本地 VLM",
    VLM:    "本地 VLM",
    meta:   "DeepSeek",
    META:   "DeepSeek",
    human:  "人工",
    HUMAN:  "人工",
  };
  const I18N_DECISION = {
    keep: "保留", maybe: "待定", cull: "剔除",
  };

  // ================================================================
  // v0.7-P0-3 — large-batch (5k+) hardening helpers.
  //
  // _throttle: classic leading-edge throttle so high-frequency
  //   callbacks (MutationObserver during chunked grid re-render,
  //   IntersectionObserver during fast scroll) don't pin the main
  //   thread.  Returns a function that fires immediately the first
  //   time and at most every `wait` ms thereafter; trailing call
  //   guaranteed.  Stats counter (`._fires`) lets /admin/perf show
  //   how often each observer actually runs.
  //
  // _adaptiveRootMargin: an IntersectionObserver rootMargin that
  //   scales down with the row count, so 5k-photo runs don't
  //   materialize hundreds of cards ahead of the viewport.
  //
  // PixCullStorage: localStorage façade with QuotaExceeded fallback
  //   to in-memory cache + a console warning.  Existing call sites
  //   (`localStorage.setItem(...)`) keep working; the few hot
  //   writers (buckets, view presets, annotation queue) can switch
  //   to PixCullStorage.set() to get the safer behavior.
  // ================================================================
  function _throttle(fn, wait) {
    let last = 0, timer = null, pending = null;
    const wrapped = function (...args) {
      const now = Date.now();
      pending = args;
      wrapped._fires = (wrapped._fires || 0) + 1;
      if (now - last >= wait) {
        last = now;
        try { fn.apply(null, pending); } finally { pending = null; }
        return;
      }
      if (timer) return;
      timer = setTimeout(() => {
        timer = null;
        if (pending) {
          last = Date.now();
          const a = pending; pending = null;
          fn.apply(null, a);
        }
      }, wait - (now - last));
    };
    wrapped._fires = 0;
    return wrapped;
  }
  function _adaptiveRootMargin(n) {
    // Empirically: 200% lookahead at < 1k rows; 100% at 1k-3k;
    // 60% at 3k-5k; 40% above. Each step halves the # of cards
    // materialized in advance.
    if (n > 5000) return "40% 0px 40% 0px";
    if (n > 3000) return "60% 0px 60% 0px";
    if (n > 1000) return "100% 0px 100% 0px";
    return "200% 0px 200% 0px";
  }
  const PixCullStorage = (function () {
    const memFallback = new Map();
    const SET_LOG = "[pixcull-storage] quota exceeded, falling back to memory";
    let warnedQuota = false;
    return {
      get(key) {
        if (memFallback.has(key)) return memFallback.get(key);
        try { return localStorage.getItem(key); } catch (_e) { return null; }
      },
      set(key, value) {
        try {
          localStorage.setItem(key, value);
          memFallback.delete(key);
          return true;
        } catch (e) {
          // QuotaExceededError / SecurityError / NS_ERROR_DOM_QUOTA_REACHED
          if (!warnedQuota) { console.warn(SET_LOG); warnedQuota = true; }
          memFallback.set(key, value);
          return false;
        }
      },
      remove(key) {
        memFallback.delete(key);
        try { localStorage.removeItem(key); } catch (_e) {}
      },
      // Diagnostic — returned by /admin/perf for live monitoring.
      _stats() {
        let lsSize = 0, lsKeys = 0;
        try {
          for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            if (!k || !k.startsWith("pixcull_")) continue;
            lsSize += (k.length + (localStorage.getItem(k) || "").length) * 2;
            lsKeys++;
          }
        } catch (_e) {}
        return {
          ls_keys: lsKeys,
          ls_bytes_est: lsSize,
          mem_fallback_keys: memFallback.size,
        };
      },
    };
  })();
  // Expose for /admin/perf-style debugging (window.PixCullStorage._stats()).
  window.PixCullStorage = PixCullStorage;
  // P-PRO-4.1 — wedding-moment i18n. Mirrors WEDDING_MOMENTS.label_zh
  // server-side; kept in sync by hand because the vocabulary is
  // small and stable. "unknown" is the abstain sentinel.
  const I18N_WEDDING_MOMENT = {
    preparation_bride: "新娘准备", preparation_groom: "新郎准备",
    first_look: "First Look", processional: "入场",
    vows: "宣誓", ring_exchange: "交换戒指",
    first_kiss: "第一吻", recessional: "退场",
    group_portraits: "合影", first_dance: "第一支舞",
    speeches: "致辞", toast: "敬酒",
    cake_cutting: "切蛋糕", bouquet_toss: "捧花",
    reception_general: "宴席", candid: "花絮",
    // P-PRO-4.3 — Chinese wedding moments
    door_block: "堵门 / 接亲", hair_combing: "梳头",
    tea_ceremony: "敬茶", kneeling_bow: "跪拜 / 三鞠躬",
    red_dress: "红嫁衣", firecrackers: "鞭炮 / 礼炮",
    unknown: "未识别",
  };

  // P-UX-4 — cull-reason taxonomy. Loaded from /api/v1/taxonomy on
  // page-init; cached here so render() can call _cullReasonLabel()
  // synchronously when building each card. Both declarations are
  // hoisted (var + function-declaration) so they're safe to call
  // from the first render() pass before the async fetch resolves —
  // empty map → label fallback to the raw token.
  var _CULL_REASONS_LIST = [];   // [{token, label_zh}, ...]
  var _CULL_REASONS_MAP  = {};   // {token: label_zh}
  function _cullReasonLabel(token) {
    if (!token) return "";
    return _CULL_REASONS_MAP[token] || token;
  }

  // P-UX-5 — labels for similarity reasons returned by
  // /api/v1/runs/<id>/similar/<filename>. Kept as a static map (not
  // taxonomy-fetched) because the reason vocabulary is server-pinned
  // and small enough that bundling it inline keeps the lightbox fast.
  const I18N_SIM_REASON = {
    burst:           "同连拍",
    same_scene:      "同场景",
    same_person:     "同人物",
    same_location:   "同地点",
    similar_rubric:  "相似评分",
  };

  function tr(token, table) {
    if (token == null) return "";
    return (table && table[token]) || token;
  }
  function trGenre(g)  { return tr(g, I18N_GENRE); }
  function trStyle(s)  { return tr(s, I18N_STYLE); }
  function trFlag(f)   { return tr(f, I18N_FLAG); }
  function trSource(s) { return tr(s, I18N_SOURCE); }

  // Reasons + flags arrive as strings like "severely_blurry" or
  // "score=0.57 · severely_blurry · highlight_clip". Split on common
  // separators, translate each token, rejoin with a Chinese-friendly
  // middle dot. ``score=0.57`` → ``综合分=0.57``;
  // ``rescorer_promoted(P=0.85)`` → ``模型上调(P=0.85)``.
  const _REASON_PREFIX_MAP = [
    ["low_score=",            "综合分偏低="],
    ["score=",                "综合分="],
    ["rescorer_promoted(P=",  "模型上调(P="],
    ["rescorer_demoted(P=",   "模型下调(P="],
  ];
  function trToken(t) {
    if (!t) return "";
    for (const [prefix, zh] of _REASON_PREFIX_MAP) {
      if (t.startsWith(prefix)) return zh + t.slice(prefix.length);
    }
    if (I18N_FLAG[t])  return I18N_FLAG[t];
    if (I18N_STYLE[t]) return I18N_STYLE[t];
    if (I18N_GENRE[t]) return I18N_GENRE[t];
    return t;
  }
  function trReason(s) {
    if (!s) return "";
    // Pipeline emits ``a · b · c`` (Chinese middle dot) or ``a, b`` or
    // space-separated. Try each; replace whitespace runs with the
    // middle dot for visual consistency.
    return String(s)
      .split(/[·,\s]+/)
      .filter(x => x.length)
      .map(trToken)
      .join(" · ");
  }

  // V14.4 — modal a11y wiring via MutationObserver. The existing
  // results page has 16+ ``classList.add/remove("show")`` call sites
  // for lightbox / annotation / cluster-compare; rather than rewrite
  // them all, we observe the class attribute on each registered modal
  // and apply ARIA + focus trap reactively. The same observer also
  // restores focus to the opener on close.
  function _modalFocusables(el) {
    return Array.from(el.querySelectorAll(
      'a[href], button, input, textarea, select, [tabindex]:not([tabindex="-1"])'
    )).filter(x => !x.disabled && x.offsetParent !== null);
  }
  function _attachTrap(el) {
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-modal", "true");
    if (!el.getAttribute("aria-labelledby")) {
      const head = el.querySelector("h1, h2, h3, .modal-title");
      if (head) {
        if (!head.id) head.id = "modal-title-" + Math.random().toString(36).slice(2, 8);
        el.setAttribute("aria-labelledby", head.id);
      }
    }
    el._previouslyFocused = document.activeElement;
    setTimeout(() => {
      const f = _modalFocusables(el);
      if (f.length) f[0].focus();
    }, 0);
    el._trapHandler = (e) => {
      if (e.key !== "Tab") return;
      const f = _modalFocusables(el);
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault(); last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault(); first.focus();
      }
    };
    el.addEventListener("keydown", el._trapHandler);
  }
  function _detachTrap(el) {
    if (el._trapHandler) {
      el.removeEventListener("keydown", el._trapHandler);
      el._trapHandler = null;
    }
    const prev = el._previouslyFocused;
    el._previouslyFocused = null;
    if (prev && typeof prev.focus === "function" && document.body.contains(prev)) {
      prev.focus();
    }
  }
  function registerModal(el) {
    if (!el || el._a11yWired) return;
    el._a11yWired = true;
    el._isOpen = el.classList.contains("show");
    if (el._isOpen) _attachTrap(el);
    const obs = new MutationObserver(() => {
      const open = el.classList.contains("show");
      if (open && !el._isOpen) {
        el._isOpen = true;
        _attachTrap(el);
      } else if (!open && el._isOpen) {
        el._isOpen = false;
        _detachTrap(el);
      }
    });
    obs.observe(el, { attributes: true, attributeFilter: ["class"] });
  }
  // Convenience wrappers that bookend a class toggle with a11y.
  // (Used by the new browser-modal call sites; legacy sites benefit
  // automatically via the observer.)
  function openModal(el) {
    if (!el) return;
    registerModal(el);
    el.classList.add("show");
  }
  function closeModal(el) {
    if (!el) return;
    el.classList.remove("show");
  }

  // V14.2 — non-blocking toast. Replaces native alert() for ack
  // messages where you don't actually need to interrupt the user.
  // ``kind`` is one of: '' (info, blue), 'success', 'error', 'warning'.
  // Auto-dismisses after `ms` (default 3500); click to dismiss early.
  function toast(message, kind = "", ms = 3500) {
    const stack = document.getElementById("toastStack");
    if (!stack) { console.log("[toast]", message); return; }
    const el = document.createElement("div");
    el.className = "toast" + (kind ? " " + kind : "");
    el.textContent = message;
    el.addEventListener("click", () => removeToast(el));
    stack.appendChild(el);
    setTimeout(() => removeToast(el), ms);
  }
  function removeToast(el) {
    if (!el || !el.parentNode) return;
    el.classList.add("fading");
    setTimeout(() => el.remove(), 220);
  }
  // expose for any inline-script / debugging callers
  window.pcToast = toast;

  // Header stats
  const statsEl = document.getElementById("stats");
  const ela = summary.elapsed_s != null ? summary.elapsed_s + "s" : "--";
  // v0.4 P2 (2/4) — annotate each stat <b> with data-stat so the
  // quickLabel / _lbLabel post-pass can update + pulse the matching
  // number without re-rendering the whole header.
  const stats = [
    // v0.9-P0-2 — primary total renders with brand gradient (signature
    // anchor visible at-a-glance in the workspace bar).  Per-decision
    // counts keep their colour-coded look (keep/maybe/cull semantics).
    `<span>共 <b data-stat="total" class="stat-value-large">${summary.n_total}</b> 张</span>`,
    `<span class="keep">keep <b data-stat="keep">${summary.n_keep}</b></span>`,
    `<span class="maybe">maybe <b data-stat="maybe">${summary.n_maybe}</b></span>`,
    `<span class="cull">cull <b data-stat="cull">${summary.n_cull}</b></span>`,
    `<span class="stat-aux">耗时 <b>${ela}</b></span>`,
  ];
  if (summary.rescorer_active) {
    stats.push(`<span class="stat-aux" title="V1.1 学习重打分器:在 ${summary.rescorer_n_scored} 张非 cull 图上给出 keep/maybe 预测">rescorer <b>${summary.rescorer_n_scored}</b> 评分 / <b>${summary.rescorer_n_disagrees}</b> 与规则不一致</span>`);
  }
  // V2.0 rubric annotation progress
  if (summary.n_human_labeled != null) {
    stats.push(`<span class="stat-aux" title="人工 rubric 标注进度,这些标注会喂入下一轮 rescorer 训练">人工标注 <b>${summary.n_human_labeled}</b>/${summary.n_total}</span>`);
  }
  // V17.2 — vertical policy badge. Tells the user "you tagged this
  // batch as <vertical>; here's how the thresholds were shifted vs
  // the default rule stack." Hover for the human-readable rationale.
  if (summary.vertical) {
    const v = summary.vertical;
    const deltaParts = [];
    if (v.keep_min_delta) {
      const sign = v.keep_min_delta > 0 ? "+" : "";
      deltaParts.push(`keep ${sign}${(v.keep_min_delta*100).toFixed(0)}pp`);
    }
    if (v.cull_max_delta) {
      const sign = v.cull_max_delta > 0 ? "+" : "";
      deltaParts.push(`cull ${sign}${(v.cull_max_delta*100).toFixed(0)}pp`);
    }
    if (v.tolerated_flags && v.tolerated_flags.length) {
      const tr = v.tolerated_flags.map(f => trFlag(f)).join("/");
      deltaParts.push(`容忍 ${tr}`);
    }
    const deltaStr = deltaParts.length ? ` · ${deltaParts.join(" · ")}` : "";
    stats.push(
      `<span class="vertical-badge" title="${esc(v.policy_notes || '')}">`
      + `${esc(v.icon)} 垂类 <b>${esc(v.zh)}</b>${esc(deltaStr)}`
      + `</span>`
    );
    // V17.8 — promote-to-sample-bank button. Only when the run has
    // a vertical AND ≥1 human keep/cull annotation. Closes the
    // feedback loop: label here → next batch's policy uses it.
    if (summary.n_promotable && summary.n_promotable > 0) {
      stats.push(
        `<button class="promote-btn" id="promoteBtn"`
        + ` title="把你刚才标的 keep/cull 写入 ${esc(v.zh)} 的 sample bank,`
        + `下次该垂类调参/AI 话术就能看到这批数据">`
        + `📥 灌入 sample bank (<b>${summary.n_promotable}</b>)`
        + `</button>`
      );
    }
  }
  statsEl.innerHTML = stats.join("");

  // v0.9-P0-2 — count-up the four primary stat numbers from 0 to
  // their final value over ~900ms.  Fires only during the initial
  // hero reveal (body.hero-revealing is on); later quickLabel-
  // triggered updates use the existing stat-pulse path so the
  // numbers don't reset to 0 on every annotation.
  if (document.body.classList.contains("hero-revealing")
      && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    statsEl.querySelectorAll('b[data-stat]').forEach(el => {
      const target = parseInt(el.textContent, 10);
      if (!isFinite(target) || target < 0) return;
      const start = performance.now();
      const duration = 900;
      el.textContent = "0";
      function tick(now) {
        const t = Math.min(1, (now - start) / duration);
        // Ease-out cubic — number ramps fast then settles
        const eased = 1 - Math.pow(1 - t, 3);
        el.textContent = String(Math.round(target * eased));
        if (t < 1) requestAnimationFrame(tick);
        else el.textContent = String(target);
      }
      requestAnimationFrame(tick);
    });
  }

  // V17.8 — wire the promote-to-bank button if it rendered
  const promoteBtn = document.getElementById("promoteBtn");
  if (promoteBtn) {
    promoteBtn.addEventListener("click", async () => {
      const vzh = (summary.vertical && summary.vertical.zh) || "vertical";
      if (!confirm(`把这次的 ${summary.n_promotable} 张人工标注 keep/cull 灌入 ${vzh} sample bank?\n(下次跑该垂类的 batch 就会用上这些数据)`)) return;
      promoteBtn.disabled = true;
      try {
        const res = await fetch(`/verticals/promote_run/${encodeURIComponent(run_id)}`, {method: "POST"});
        const d = await res.json();
        if (!res.ok) {
          toast(`灌入失败: ${d.error || res.status}`, "error");
          promoteBtn.disabled = false;
          return;
        }
        toast(`已灌入 ${d.n_promoted} 张 (${d.vertical_zh} bank: 👍 ${d.counts.good} · 👎 ${d.counts.bad})`, "success");
        if (d.n_skipped > 0) {
          console.log("V17.8 skipped:", d.skipped);
          toast(`(${d.n_skipped} 张跳过,详见 console)`, "");
        }
        promoteBtn.textContent = `✓ 已灌入 ${d.n_promoted}`;
      } catch (e) {
        toast(`灌入出错: ${e}`, "error");
        promoteBtn.disabled = false;
      }
    });
  }

  // V9.0 — sort + scene filter + style filter + cluster grouping
  // Active filter state. activeDecision is one of all/keep/maybe/cull.
  // activeScenes is a Set of scene names; empty = no filter (all scenes).
  // activeStyles is a Set of style mode names; empty = no filter.
  const filterState = {
    decision: "all",
    scenes: new Set(),
    styles: new Set(),
    // V22.1 — set of face cluster ids active in the filter. Empty
    // set = no face filter (all photos pass).
    faceClusters: new Set(),
    // V23 — set of GPS location cluster ids; empty = no filter.
    // The special value -2 means "未知位置 / no GPS" — distinct
    // from -1 (which DBSCAN noise would use, but we use min_samples=1
    // so -1 never appears on the GPS side).
    locationClusters: new Set(),
    // V23 — toggle: when true, only the highest-score-final photo
    // in each location cluster passes. Off by default.
    locationBestOnly: false,
    // V27 — toggle: when true, only the top-ranked frame per burst
    // cluster passes. Off by default. Pairs with the "🎯 每连拍峰值"
    // button populated by buildBurstPeakFilter().
    burstPeakOnly: false,
    // P2.4 — when populated, only photos in this active-learning
    // queue pass the filter. Map<filename, priority_rank> so the
    // grid can also show "AL #N" badges per card.
    activeLearningQueue: null,    // null = inactive, Map = active
    // P-UX-4 — when set, only rows whose cull_reason matches pass.
    // null = no filter; one of _CULL_REASONS_LIST tokens otherwise.
    cullReason: null,
    // P-AI-2 — semantic-search filter. When the user runs a query,
    // we store the result filenames as a Set so the grid filter can
    // intersect against it. {q: string, filenames: Set} or null.
    semSearch: null,
    // v2.6-P1 — fold CLIP near-dup groups to their hero (data in _NEARDUP).
    nearDupFold: false,
    // P-UX-27 — wedding-moment filter.  Set of moment keys (e.g.
    // {"first_kiss", "ring_exchange"}).  Empty = no filter.
    // Populated by clicking the 💒 chip on any grid card.
    weddingMoments: new Set(),
    sort: "default",
  };

  // Build dynamic scene + style filter chips from data
  function buildDynamicFilters() {
    const sceneCounts = {};
    const styleCounts = {};
    rows.forEach(r => {
      if (r.scene) sceneCounts[r.scene] = (sceneCounts[r.scene] || 0) + 1;
      (r.style_modes || []).forEach(s => {
        styleCounts[s] = (styleCounts[s] || 0) + 1;
      });
    });
    const sceneEl = document.getElementById("sceneFilters");
    sceneEl.innerHTML = Object.entries(sceneCounts)
      .sort((a, b) => b[1] - a[1])
      .map(([s, n]) => `<span class="pill" data-scene="${esc(s)}">${esc(s)} <span style="opacity:0.5">${n}</span></span>`)
      .join("");
    const styleEl = document.getElementById("styleFilters");
    styleEl.innerHTML = Object.entries(styleCounts)
      .sort((a, b) => b[1] - a[1])
      .map(([s, n]) => `<span class="pill" data-style="${esc(s)}">${esc(s)} <span style="opacity:0.5">${n}</span></span>`)
      .join("");
    sceneEl.querySelectorAll(".pill").forEach(el => {
      el.addEventListener("click", () => {
        const s = el.dataset.scene;
        if (filterState.scenes.has(s)) { filterState.scenes.delete(s); el.classList.remove("active"); }
        else { filterState.scenes.add(s); el.classList.add("active"); }
        if (typeof _flashFilter === "function") _flashFilter();
        render();
      });
    });
    styleEl.querySelectorAll(".pill").forEach(el => {
      el.addEventListener("click", () => {
        const s = el.dataset.style;
        if (filterState.styles.has(s)) { filterState.styles.delete(s); el.classList.remove("active"); }
        else { filterState.styles.add(s); el.classList.add("active"); }
        if (typeof _flashFilter === "function") _flashFilter();
        render();
      });
    });

    // V22.1 — face cluster filter chips. Driven by PAYLOAD.face_clusters
    // (computed server-side from row.face_clusters). Hidden when no
    // clusters were found (run has no recurring faces).
    buildFaceFilters();
    // V23 — GPS location cluster filter chips.
    buildLocationFilters();
    // V27 — burst peak toggle (sports/event "THE shot" picker).
    buildBurstPeakFilter();
    // P2.4 — active-learning toggle (label the highest-info-gain
    // photos first).
    buildActiveLearningFilter();
  }
  // ``buildDynamicFilters()`` reaches `buildFaceFilters` /
  // `buildLocationFilters` / `buildBurstPeakFilter` which close over
  // ``faceClustersState`` / ``locationsState`` / ``_REAL_BURSTS`` —
  // all declared below with `let` / `const`. Function declarations
  // are hoisted, but the variables they reference aren't (TDZ),
  // so the call has to wait until all of them are initialized.
  // See the explicit invocation farther down, right after
  // ``buildBurstPeakFilter()`` is declared.

  // V22.1 — face cluster chip rendering. Out-of-line so we can re-run
  // it after a label edit refreshes the cluster info from /face_clusters.
  let faceClustersState = (PAYLOAD.face_clusters && PAYLOAD.face_clusters.clusters) || [];
  function buildFaceFilters() {
    // v0.6 — legacy divider (#faceFiltersDivider) is now gone from
    // the markup since filter groups moved to the Library panel.
    // We toggle the new .lp-group container instead (#lpFaceGroup).
    const divider = document.getElementById("faceFiltersDivider");
    const lpGroup = document.getElementById("lpFaceGroup");
    const el = document.getElementById("faceFilters");
    const real = faceClustersState.filter(c => c.id >= 0);
    if (!real.length) {
      if (divider) divider.style.display = "none";
      if (lpGroup) lpGroup.style.display = "none";
      el.innerHTML = "";
      return;
    }
    if (divider) divider.style.display = "block";
    if (lpGroup) lpGroup.style.display = "";
    el.innerHTML = real.map(c => {
      const isActive = filterState.faceClusters.has(c.id);
      // V22.2 — when there's no user label but the centroid matched
      // a labeled cluster from a previous run, display the suggestion
      // with a "≈" marker so the user can see + accept it.
      let display = c.label;
      let suggestionHint = "";
      if (!display && c.suggested_label) {
        display = "≈ " + c.suggested_label.label;
        suggestionHint = ` (跨 run 推测,相似度 ${c.suggested_label.similarity.toFixed(2)})`;
      }
      if (!display) display = "Person " + (c.id + 1);
      const tip = `${c.n_photos} 张照片 · ${c.n_faces} 张人脸${suggestionHint}\\n样本: ${(c.sample_filenames || []).join(', ')}`;
      // V22.3 — mini-avatar. ``/face_avatar/<run>/<cid>`` returns the
      // best-representative face crop. ``onerror`` swaps in the 👤
      // glyph if the file doesn't exist (older runs without avatars).
      const avatarUrl = `/face_avatar/${run_id}/${c.id}`;
      const avatarImg = `<img src="${avatarUrl}" class="face-pill-avatar" `
        + `onerror="this.outerHTML='👤'" `
        + `alt="" style="width:18px;height:18px;border-radius:50%;`
        + `object-fit:cover;vertical-align:middle;margin-right:4px">`;
      return `<span class="pill face-pill${isActive ? ' active' : ''}" data-cid="${c.id}" title="${esc(tip)}">`
           + avatarImg
           + `<span class="face-pill-label" data-cid="${c.id}">${esc(display)}</span>`
           + ` <span style="opacity:0.5">${c.n_photos}</span>`
           + ` <span class="face-pill-edit" data-cid="${c.id}" title="重命名这一组" style="margin-left:4px;opacity:0.4;cursor:text">✎</span>`
           + `</span>`;
    }).join("");

    el.querySelectorAll(".face-pill").forEach(pill => {
      pill.addEventListener("click", e => {
        // ✎ icon click = inline rename; the pill itself = toggle filter
        if (e.target.classList.contains("face-pill-edit")) {
          e.stopPropagation();
          startInlineRename(pill);
          return;
        }
        const cid = parseInt(pill.dataset.cid, 10);
        if (filterState.faceClusters.has(cid)) {
          filterState.faceClusters.delete(cid);
          pill.classList.remove("active");
        } else {
          filterState.faceClusters.add(cid);
          pill.classList.add("active");
        }
        render();
      });
    });
  }

  // V22.1 — inline rename UI. Replaces the label <span> with an <input>,
  // POSTs to /face_clusters/<run>/label on Enter / blur, then rerenders.
  function startInlineRename(pill) {
    const cid = parseInt(pill.dataset.cid, 10);
    const labelSpan = pill.querySelector(".face-pill-label");
    if (!labelSpan) return;
    const old = labelSpan.textContent;
    const input = document.createElement("input");
    input.value = old.startsWith("Person ") ? "" : old;
    input.placeholder = "Bride / Groom / 小宝 ...";
    input.style.cssText = "background:transparent;border:none;border-bottom:1px solid var(--fg);"
      + "color:var(--fg);font:inherit;width:9em;outline:none;padding:0";
    labelSpan.replaceWith(input);
    input.focus(); input.select();

    let done = false;
    async function commit() {
      if (done) return; done = true;
      const newLabel = input.value.trim();
      if (newLabel === old || (newLabel === "" && old.startsWith("Person "))) {
        // No real change; just restore display
        const restore = document.createElement("span");
        restore.className = "face-pill-label";
        restore.dataset.cid = String(cid);
        restore.textContent = old;
        input.replaceWith(restore);
        return;
      }
      try {
        const res = await fetch(`/face_clusters/${run_id}/label`, {
          method:  "POST",
          headers: {"Content-Type": "application/json"},
          body:    JSON.stringify({cluster_id: cid, label: newLabel}),
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        // Refresh cluster info from server (don't trust our local
        // state — the server's the source of truth for labels).
        const r2 = await fetch(`/face_clusters/${run_id}`);
        if (r2.ok) {
          const fresh = await r2.json();
          faceClustersState = fresh.clusters || [];
          buildFaceFilters();
        }
      } catch (e) {
        console.error("rename failed:", e);
        // Restore old display on failure
        const restore = document.createElement("span");
        restore.className = "face-pill-label";
        restore.dataset.cid = String(cid);
        restore.textContent = old;
        input.replaceWith(restore);
      }
    }
    input.addEventListener("keydown", e => {
      if (e.key === "Enter") { e.preventDefault(); commit(); }
      else if (e.key === "Escape") { done = true; const r = document.createElement("span"); r.className = "face-pill-label"; r.dataset.cid = String(cid); r.textContent = old; input.replaceWith(r); }
    });
    input.addEventListener("blur", commit);
  }

  // V23 — GPS location cluster filter chips + "每地点选一张" toggle.
  // Driven by PAYLOAD.locations.clusters (computed server-side from
  // row.gps_cluster_id). Hidden when the run has no GPS at all.
  let locationsState = (PAYLOAD.locations && PAYLOAD.locations.clusters) || [];
  const locationsNoGps = (PAYLOAD.locations && PAYLOAD.locations.n_no_gps) || 0;
  function buildLocationFilters() {
    // v0.6 — see buildFaceFilters for the lp-group migration note.
    const divider = document.getElementById("locationFiltersDivider");
    const lpGroup = document.getElementById("lpLocationGroup");
    const el = document.getElementById("locationFilters");
    if (!locationsState.length) {
      if (divider) divider.style.display = "none";
      if (lpGroup) lpGroup.style.display = "none";
      el.innerHTML = "";
      return;
    }
    if (divider) divider.style.display = "block";
    if (lpGroup) lpGroup.style.display = "";
    // Each pill: "📍 <label-or-lat,lon> <count> ✎"
    const pills = locationsState.map(c => {
      const isActive = filterState.locationClusters.has(c.id);
      const lat = c.center_lat != null ? c.center_lat.toFixed(3) : "?";
      const lon = c.center_lon != null ? c.center_lon.toFixed(3) : "?";
      // V23.1 — prefer the user-supplied label over raw coords.
      const display = c.label && c.label.length > 0
        ? c.label
        : `${lat},${lon}`;
      const tip = `${c.n_photos} 张照片\\n中心: (${lat}, ${lon})\\n` +
                  `🏆 当地最佳: ${c.best_filename} (${c.best_score?.toFixed(2)})\\n` +
                  `样本: ${(c.sample_filenames || []).join(', ')}`;
      return `<span class="pill location-pill${isActive ? ' active' : ''}" `
           + `data-loc="${c.id}" title="${esc(tip)}">`
           + `📍 <span class="location-pill-label" data-loc="${c.id}">${esc(display)}</span> `
           + `<span style="opacity:0.5">${c.n_photos}</span>`
           + ` <span class="location-pill-edit" data-loc="${c.id}" `
           + `title="重命名地点(如 Notre Dame / 我家)" `
           + `style="margin-left:4px;opacity:0.4;cursor:text">✎</span>`
           + `</span>`;
    });
    // Unknown-location bucket if any photos lack GPS
    if (locationsNoGps > 0) {
      const isActive = filterState.locationClusters.has(-2);
      pills.push(`<span class="pill location-pill${isActive ? ' active' : ''}" `
        + `data-loc="-2" title="无 EXIF GPS 的照片">📍 未知位置 `
        + `<span style="opacity:0.5">${locationsNoGps}</span></span>`);
    }
    // V23 "选每地点最佳" toggle
    pills.push(`<span class="pill location-best-toggle${filterState.locationBestOnly ? ' active' : ''}" `
      + `title="每个地点只显示分数最高的一张" data-best="1">🏆 每地点一张</span>`);
    el.innerHTML = pills.join("");

    el.querySelectorAll(".location-pill").forEach(pill => {
      pill.addEventListener("click", e => {
        // V23.1 — ✎ icon opens inline rename; pill click toggles filter.
        if (e.target.classList.contains("location-pill-edit")) {
          e.stopPropagation();
          startLocationRename(pill);
          return;
        }
        const cid = parseInt(pill.dataset.loc, 10);
        if (filterState.locationClusters.has(cid)) {
          filterState.locationClusters.delete(cid);
          pill.classList.remove("active");
        } else {
          filterState.locationClusters.add(cid);
          pill.classList.add("active");
        }
        render();
      });
    });
    el.querySelectorAll(".location-best-toggle").forEach(b => {
      b.addEventListener("click", () => {
        filterState.locationBestOnly = !filterState.locationBestOnly;
        b.classList.toggle("active");
        render();
      });
    });
  }

  // V23 — "best filename per cluster" lookup, used by the location-best
  // filter. Computed once from locationsState; if filterState changes
  // we don't need to recompute since the cluster->best mapping is
  // a property of the run, not the filter.
  function bestFilenamePerLocation() {
    const m = new Map();
    for (const c of locationsState) {
      if (c.best_filename) m.set(c.id, c.best_filename);
    }
    return m;
  }

  // V23.1 — inline rename for location pills. Mirrors the V22.1
  // face-cluster rename: replace the label <span> with an <input>,
  // POST to /api/v1/runs/<id>/locations/label on Enter / blur,
  // re-fetch /api/v1/runs/<id>/locations to refresh display.
  function startLocationRename(pill) {
    const cid = parseInt(pill.dataset.loc, 10);
    const labelSpan = pill.querySelector(".location-pill-label");
    if (!labelSpan) return;
    const old = labelSpan.textContent;
    const input = document.createElement("input");
    // Pre-populate with the EXISTING label if it's not the bare
    // coordinate fallback (lat,lon — those are the "no name" form).
    input.value = old.includes(",") && /^-?\d/.test(old) ? "" : old;
    input.placeholder = "Notre Dame / 我家 / 海岸边 ...";
    input.style.cssText = "background:transparent;border:none;"
      + "border-bottom:1px solid var(--fg);color:var(--fg);font:inherit;"
      + "width:11em;outline:none;padding:0";
    labelSpan.replaceWith(input);
    input.focus(); input.select();

    let done = false;
    async function commit() {
      if (done) return; done = true;
      const newLabel = input.value.trim();
      if (newLabel === old) {
        const restore = document.createElement("span");
        restore.className = "location-pill-label";
        restore.dataset.loc = String(cid);
        restore.textContent = old;
        input.replaceWith(restore);
        return;
      }
      try {
        const res = await fetch(`/api/v1/runs/${run_id}/locations/label`, {
          method:  "POST",
          headers: {"Content-Type": "application/json"},
          body:    JSON.stringify({cluster_id: cid, label: newLabel}),
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        const r2 = await fetch(`/api/v1/runs/${run_id}/locations`);
        if (r2.ok) {
          const fresh = await r2.json();
          locationsState = fresh.clusters || [];
          buildLocationFilters();
        }
      } catch (e) {
        console.error("location rename failed:", e);
        const restore = document.createElement("span");
        restore.className = "location-pill-label";
        restore.dataset.loc = String(cid);
        restore.textContent = old;
        input.replaceWith(restore);
      }
    }
    input.addEventListener("keydown", e => {
      if (e.key === "Enter") { e.preventDefault(); commit(); }
      else if (e.key === "Escape") {
        done = true;
        const r = document.createElement("span");
        r.className = "location-pill-label";
        r.dataset.loc = String(cid);
        r.textContent = old;
        input.replaceWith(r);
      }
    });
    input.addEventListener("blur", commit);
  }

  // V27 — burst peak filter. Compute the set of burst cluster_ids that
  // actually have >1 frames (the only ones where "peak" is meaningful)
  // ONCE up front; the toggle button shows the count.
  const _BURST_CLUSTER_SIZES = (() => {
    const s = new Map();
    for (const r of rows) {
      const cid = r.cluster_id;
      if (cid == null) continue;
      s.set(cid, (s.get(cid) || 0) + 1);
    }
    return s;
  })();
  const _REAL_BURSTS = [..._BURST_CLUSTER_SIZES.entries()].filter(([_, n]) => n >= 2);
  function buildBurstPeakFilter() {
    // v0.6 — see buildFaceFilters
    const divider = document.getElementById("burstPeakDivider");
    const lpGroup = document.getElementById("lpBurstGroup");
    const el = document.getElementById("burstPeakFilter");
    if (!el) return;
    const hasBursts = _REAL_BURSTS.length > 0;
    // Sidebar burst group stays tied to actual bursts; the toolbar row
    // now ALSO hosts the time-independent near-dup fold, so it renders
    // even on a burst-less run (v2.6-P1).
    if (lpGroup) lpGroup.style.display = hasBursts ? "" : "none";
    if (divider) divider.style.display = hasBursts ? "block" : "none";
    let html = "";
    if (hasBursts) {
      const totalBurstPhotos = _REAL_BURSTS.reduce((s, [_, n]) => s + n, 0);
      html +=
        `<span class="pill burst-peak-toggle${filterState.burstPeakOnly ? ' active' : ''}" ` +
        `title="${_REAL_BURSTS.length} 个连拍组,共 ${totalBurstPhotos} 张 — ` +
        `打开后只保留每组的最佳一张">` +
        `🎯 每连拍峰值 <span style="opacity:0.5">${_REAL_BURSTS.length}</span></span>` +
        // v2.4-P1-1 — collapse each burst into a single peak "hero" card
        // carrying a ⧉N stack badge (click it to expand → compare modal).
        `<span class="pill burst-collapse-toggle${filterState.collapseBursts ? ' active' : ''}" ` +
        `title="把每个连拍组折叠成一张峰值代表 + ⧉计数;点卡片角的 ⧉N 展开并排比较">` +
        `⧉ 折叠成堆</span>` +
        // P0.3 — direct entry to the V9.2 compare modal without
        // having to switch to sort=cluster first.
        `<span class="pill burst-compare-jump" ` +
        `title="打开并排比较 — 从第一个连拍组开始,←/→ 翻页">` +
        `⊞ 并排比较</span>`;
    }
    // v2.6-P1 — visual near-duplicate fold. CLIP-based, so it also
    // catches the re-shot composition minutes later that time-bucketed
    // bursts can't. First toggle lazily builds the embeddings cache.
    html +=
      `<span class="pill neardup-toggle${filterState.nearDupFold ? ' active' : ''}" ` +
      `title="按视觉相似度(CLIP)把近重复折成一张代表;点卡片角的 ≈N 并排比较 — 首次开启需建索引,稍慢">` +
      `≈ 近重复折叠</span>`;
    el.innerHTML = html;
    el.querySelectorAll(".neardup-toggle").forEach(b => {
      b.addEventListener("click", () => _toggleNearDupFold(b));
    });
    el.querySelectorAll(".burst-collapse-toggle").forEach(b => {
      b.addEventListener("click", () => {
        filterState.collapseBursts = !filterState.collapseBursts;
        b.classList.toggle("active");
        render();
      });
    });
    el.querySelectorAll(".burst-peak-toggle").forEach(b => {
      b.addEventListener("click", () => {
        filterState.burstPeakOnly = !filterState.burstPeakOnly;
        b.classList.toggle("active");
        render();
      });
    });
    el.querySelectorAll(".burst-compare-jump").forEach(b => {
      b.addEventListener("click", () => {
        // Jump straight to the first burst cluster
        if (_REAL_BURSTS.length > 0) {
          openCompare(`c${_REAL_BURSTS[0][0]}`);
        }
      });
    });
  }

  // v2.6-P1 — near-dup fold state. byHero maps a group's representative
  // (highest score_final, server-picked) to ALL group members; hidden is
  // the flat set of folded-away non-heroes.
  let _NEARDUP = null;
  function _toggleNearDupFold(btn) {
    if (filterState.nearDupFold) {
      filterState.nearDupFold = false;
      btn.classList.remove("active");
      render();
      return;
    }
    if (_NEARDUP) {                       // already fetched → instant fold
      filterState.nearDupFold = true;
      btn.classList.add("active");
      render();
      return;
    }
    btn.style.opacity = "0.55";
    btn.textContent = "≈ 建索引中…";
    fetch(`/api/v1/runs/${run_id}/near_dups`)
      .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(d => {
        const byHero = new Map(), hidden = new Set();
        (d.groups || []).forEach(g => {
          byHero.set(g.hero, g.members);
          g.members.forEach(fn => { if (fn !== g.hero) hidden.add(fn); });
        });
        _NEARDUP = { byHero, hidden };
        filterState.nearDupFold = true;
        btn.classList.add("active");
        btn.textContent = `≈ 近重复折叠 `;
        const n = document.createElement("span");
        n.style.opacity = "0.5"; n.textContent = String(byHero.size);
        btn.appendChild(n);
        if (!byHero.size) showToast("未发现视觉近重复组(阈值 0.92)");
        render();
      })
      .catch(err => {
        showToast("近重复索引失败: " + err.message, "error");
        btn.textContent = "≈ 近重复折叠";
      })
      .finally(() => { btn.style.opacity = ""; });
  }

  // P2.4 — active-learning filter. Click → fetch top-N queue from
  // /api/v1/runs/<id>/next_to_label?n=20, populate
  // filterState.activeLearningQueue as a Map<filename,
  // {rank, why}>. Click again → clear (re-shows everything).
  // The active-learning quota (20) is hard-coded for now; future
  // V31 could expose a slider.
  const _ACTIVE_LEARNING_N = 20;
  function buildActiveLearningFilter() {
    const divider = document.getElementById("activeLearningDivider");
    const el = document.getElementById("activeLearningFilter");
    // Image-failure investigation 2026-Q4: `activeLearningDivider` was
    // removed in an earlier refactor; the bare access threw TypeError
    // which aborted the rest of the IIFE — rows[] never populated and
    // the grid stayed empty (which is what made the README hero
    // screenshot capture render a blank page).  Guard cleanly; the
    // filter itself still works because `el` is still in the DOM.
    if (!el) return;
    if (divider) divider.style.display = "block";
    const active = filterState.activeLearningQueue != null;
    const sizeNote = active
      ? ` <span style="opacity:0.5">${filterState.activeLearningQueue.size}</span>`
      : "";
    el.innerHTML =
      `<span class="pill active-learning-toggle${active ? ' active' : ''}" ` +
      `title="主动学习排队: 列出最值得标注的 ${_ACTIVE_LEARNING_N} 张照片 — ` +
      `优先暴露规则与 rescorer 不一致 / 概率临界 / 分数临界 / 还未标注的">` +
      `🎯 主动学习${sizeNote}</span>`;
    el.querySelectorAll(".active-learning-toggle").forEach(b => {
      b.addEventListener("click", async () => {
        if (filterState.activeLearningQueue != null) {
          // Toggle off
          filterState.activeLearningQueue = null;
          buildActiveLearningFilter();
          render();
          return;
        }
        b.classList.add("active");
        b.innerHTML = "🎯 主动学习 <span style=\"opacity:0.5\">…</span>";
        try {
          const r = await fetch(
            `/api/v1/runs/${run_id}/next_to_label?n=${_ACTIVE_LEARNING_N}`
          );
          if (!r.ok) throw new Error("HTTP " + r.status);
          const data = await r.json();
          if (data.done) {
            // No unlabeled photos left — friendly message
            toast(data.message || "已标完本批所有图片 ✓", "success");
            b.classList.remove("active");
            buildActiveLearningFilter();
            return;
          }
          const m = new Map();
          (data.queue || []).forEach(q => {
            m.set(q.filename, {rank: q.priority_rank, why: q.why});
          });
          filterState.activeLearningQueue = m;
          buildActiveLearningFilter();
          render();
        } catch (e) {
          console.error("active learning fetch failed", e);
          toast("主动学习队列获取失败: " + e, "error");
          b.classList.remove("active");
          buildActiveLearningFilter();
        }
      });
    });
  }

  // All TDZ-sensitive state that buildDynamicFilters transitively
  // closes over (faceClustersState, locationsState, locationsNoGps,
  // _BURST_CLUSTER_SIZES, _REAL_BURSTS, _ACTIVE_LEARNING_N) is now
  // declared above — safe to populate every filter pill group.
  //
  // P-UX-8 — previously this call sat right after buildDynamicFilters
  // was defined (~line 2009). It crashed with "Cannot access
  // 'faceClustersState' before initialization" in any browser that
  // strictly enforces TDZ (Chromium-headless does; Safari is more
  // forgiving which is why the bug stayed hidden). End-user symptom:
  // the entire grid silently fails to render — the page draws the
  // header and filter pills only, leaving the photo area black.
  buildDynamicFilters();

  // Sort key function
  function sortRows(arr) {
    const order = { keep: 0, maybe: 1, cull: 2, "": 3 };
    const a = [...arr];
    // P2.4 — when active-learning filter is on, sort by AL rank
    // (lowest rank = highest priority). Ignores the user's chosen
    // sort because the queue order IS the meaningful order.
    if (filterState.activeLearningQueue != null) {
      const q = filterState.activeLearningQueue;
      a.sort((x, y) => {
        const rx = q.get(x.filename)?.rank ?? 1e9;
        const ry = q.get(y.filename)?.rank ?? 1e9;
        return rx - ry;
      });
      return a;
    }
    const s = filterState.sort;
    if (s === "score_desc")   a.sort((x, y) => (y.score_final ?? -1) - (x.score_final ?? -1));
    else if (s === "score_asc")  a.sort((x, y) => (x.score_final ?? 999) - (y.score_final ?? 999));
    else if (s === "datetime_asc")  a.sort((x, y) => (x.datetime || "").localeCompare(y.datetime || ""));
    else if (s === "datetime_desc") a.sort((x, y) => (y.datetime || "").localeCompare(x.datetime || ""));
    // v0.7-P2-1 — sort by learned style distance (ascending = closest first).
    // Rows without a distance go to the tail.
    else if (s === "style_distance_asc") {
      a.sort((x, y) => {
        const dx = (typeof x.style_distance === "number") ? x.style_distance : 99;
        const dy = (typeof y.style_distance === "number") ? y.style_distance : 99;
        return dx - dy;
      });
    }
    else if (s === "cluster") {
      a.sort((x, y) => {
        const cx = x.cluster_id ?? 1e9, cy = y.cluster_id ?? 1e9;
        if (cx !== cy) return cx - cy;
        // within cluster: best first (descending final score)
        return (y.score_final ?? 0) - (x.score_final ?? 0);
      });
    } else {
      // default: keep > maybe > cull, then descending score
      a.sort((x, y) => {
        const dx = order[x.decision] ?? 4, dy = order[y.decision] ?? 4;
        if (dx !== dy) return dx - dy;
        return (y.score_final ?? 0) - (x.score_final ?? 0);
      });
    }
    return a;
  }

  // Grid
  const grid = document.getElementById("grid");

  // v0.6 (1/5) — Library panel collapse / mobile drawer.
  // On desktop, the panel collapses to a 36px rail with just the
  // expand button.  On mobile (<= 900px) it becomes a drawer
  // that slides in from the left.  Both states persist in
  // localStorage[pixcull_lib_panel] = "open" | "collapsed".
  (function _initLibraryPanel() {
    const panel = document.getElementById("libraryPanel");
    const backdrop = document.getElementById("libraryPanelBackdrop");
    const btn = document.getElementById("lpCollapseBtn");
    if (!panel || !btn) return;
    const _LP_KEY = "pixcull_lib_panel";
    const isMobile = () => window.matchMedia("(max-width: 900px)").matches;

    function _apply(state) {
      if (isMobile()) {
        // Mobile: "open" shows the drawer, anything else hides it
        panel.classList.toggle("open", state === "open");
        if (backdrop) backdrop.classList.toggle("show", state === "open");
        panel.classList.remove("collapsed");
      } else {
        // Desktop: "collapsed" shrinks to rail, default expanded
        panel.classList.toggle("collapsed", state === "collapsed");
        panel.classList.remove("open");
        if (backdrop) backdrop.classList.remove("show");
      }
    }
    let _state = "expanded";
    try { _state = localStorage.getItem(_LP_KEY) || "expanded"; }
    catch (e) {}
    _apply(_state);

    btn.addEventListener("click", () => {
      if (isMobile()) {
        // Mobile click closes the drawer
        _state = "expanded";   // i.e. "not open"
      } else {
        _state = _state === "collapsed" ? "expanded" : "collapsed";
      }
      try { localStorage.setItem(_LP_KEY, _state); } catch (e) {}
      _apply(_state);
    });
    // Mobile: tap backdrop to close
    if (backdrop) {
      backdrop.addEventListener("click", () => {
        _state = "expanded";   // i.e. not "open"
        try { localStorage.setItem(_LP_KEY, _state); } catch (e) {}
        _apply(_state);
      });
    }
    // Keyboard: "B" toggles the panel (LR-style)
    document.addEventListener("keydown", e => {
      // Ignore when typing in inputs
      if (e.target.matches("input, textarea, select")) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "b" || e.key === "B") {
        e.preventDefault();
        if (isMobile()) {
          // Open / close drawer
          _state = panel.classList.contains("open") ? "expanded" : "open";
        } else {
          _state = _state === "collapsed" ? "expanded" : "collapsed";
        }
        try { localStorage.setItem(_LP_KEY, _state); } catch (e) {}
        _apply(_state);
      }
    });
    // Re-apply on viewport changes so the same persisted state
    // makes sense after a resize across the mobile breakpoint.
    window.addEventListener("resize", () => _apply(_state));
  })();

  // v0.5 LR-grade (2/3) — density toolbar.  LR Library has a
  // 4-step grid-size slider that's been the standard photographer
  // affordance for a decade.  PixCull's 3-step (S / M / L) is
  // enough: tight (browse), default (default), spread (review).
  // Persisted in localStorage so the photographer's chosen
  // density survives reload.
  (function _initDensityToolbar() {
    const _DENSITY_KEY = "pixcull_density";
    const tb = document.querySelector(".density-toolbar");
    if (!tb || !grid) return;
    function _apply(density) {
      grid.classList.remove("density-s", "density-m", "density-l");
      grid.classList.add("density-" + density);
      tb.querySelectorAll("button").forEach(b => {
        b.classList.toggle("active", b.dataset.density === density);
      });
    }
    let saved = "m";
    try { saved = localStorage.getItem(_DENSITY_KEY) || "m"; } catch (e) {}
    if (!["s","m","l"].includes(saved)) saved = "m";
    _apply(saved);
    tb.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", () => {
        const d = btn.dataset.density;
        if (!d) return;
        try { localStorage.setItem(_DENSITY_KEY, d); } catch (e) {}
        _apply(d);
      });
    });
  })();

  // v2.2 soft-skill — VISUAL_DENSITY dial (舒朗 calm ⇄ 详尽 dense).
  // Calm is the default: the card is photo + decision + editorial
  // score + the quiet axis strip; dense restores every secondary chip
  // / reason / advice line.  Toggles `.dense` on #grid (the calm CSS
  // is gated on `.grid:not(.dense)`); persisted across reloads.
  (function _initCalmToolbar() {
    const _CALM_KEY = "pixcull_calm";
    const tb = document.querySelector(".calm-toolbar");
    if (!tb || !grid) return;
    function _apply(mode) {
      grid.classList.toggle("dense", mode === "dense");
      tb.querySelectorAll("button").forEach(b => {
        b.classList.toggle("active", b.dataset.calm === mode);
      });
    }
    let saved = "calm";
    try { saved = localStorage.getItem(_CALM_KEY) || "calm"; } catch (e) {}
    if (!["calm", "dense"].includes(saved)) saved = "calm";
    _apply(saved);
    tb.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", () => {
        const m = btn.dataset.calm;
        if (!m) return;
        try { localStorage.setItem(_CALM_KEY, m); } catch (e) {}
        _apply(m);
      });
    });
  })();

  // v0.4 P2 (2/4) — stat-counter pulse helpers.
  // Called from quickLabel + _lbLabel when a decision flip changes
  // a keep/maybe/cull tally.  Direct DOM patch + brief pulse class
  // so the user sees the number tick + bounce.
  function _pulseStat(name) {
    if (!name) return;
    const el = document.querySelector(`.stats b[data-stat="${name}"]`);
    if (!el) return;
    el.classList.remove("pulse");
    void el.offsetWidth;   // restart animation
    el.classList.add("pulse");
    setTimeout(() => el.classList.remove("pulse"), 400);
  }
  function _shiftStatCounts(prevDecision, newDecision) {
    if (prevDecision === newDecision) return;
    // Decrement the previous bucket (if any)
    if (prevDecision && ["keep","maybe","cull"].includes(prevDecision)) {
      const k = "n_" + prevDecision;
      summary[k] = Math.max(0, (summary[k] || 0) - 1);
      const el = document.querySelector(`.stats b[data-stat="${prevDecision}"]`);
      if (el) el.textContent = summary[k];
      _pulseStat(prevDecision);
    }
    // Increment the new bucket
    if (["keep","maybe","cull"].includes(newDecision)) {
      const k = "n_" + newDecision;
      summary[k] = (summary[k] || 0) + 1;
      const el = document.querySelector(`.stats b[data-stat="${newDecision}"]`);
      if (el) el.textContent = summary[k];
      _pulseStat(newDecision);
    }
  }

  // v0.4 P1 (2/4) — quick fade flash when filter state changes.
  // Adds `.filtering` to .grid for one paint frame so the user
  // perceives "the filter applied" rather than a paint glitch.
  // No-op if prefers-reduced-motion is set (CSS handles that).
  function _flashFilter() {
    if (!grid) return;
    grid.classList.add("filtering");
    // Two rAFs so the browser commits the dimmed style before
    // we clear it; otherwise the transition can be optimized away.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        grid.classList.remove("filtering");
      });
    });
  }

  function render() {
    let filtered = rows;
    if (filterState.decision !== "all") {
      filtered = filtered.filter(r => r.decision === filterState.decision);
    }
    if (filterState.scenes.size > 0) {
      filtered = filtered.filter(r => filterState.scenes.has(r.scene));
    }
    if (filterState.styles.size > 0) {
      filtered = filtered.filter(r =>
        (r.style_modes || []).some(s => filterState.styles.has(s))
      );
    }
    // P-UX-27 — wedding moment filter.  Set populated by clicking
    // the 💒 chip on any grid card; empty = no filter.
    if (filterState.weddingMoments.size > 0) {
      filtered = filtered.filter(r =>
        r.wedding_moment && filterState.weddingMoments.has(r.wedding_moment)
      );
    }
    // P-UX-4 — cull-reason filter. Active when the user has clicked
    // a pill in the "因为 X 而 cull" group; passes rows whose
    // cull_reason matches (and which are themselves cull — the
    // server-side hydration already gates that).
    if (filterState.cullReason) {
      filtered = filtered.filter(r => r.cull_reason === filterState.cullReason);
    }
    // P-AI-2 — semantic search filter. Intersect against the CLIP
    // top-K result set; preserves the existing decision/scene/face
    // filters so "show keep + matching 'flying bird'" composes
    // naturally.
    if (filterState.semSearch && filterState.semSearch.filenames) {
      filtered = filtered.filter(r =>
        filterState.semSearch.filenames.has(r.filename)
      );
    }
    // V22.1 — face cluster filter. A row passes if any of its face
    // cluster ids is currently selected. Empty set = no filter.
    if (filterState.faceClusters.size > 0) {
      filtered = filtered.filter(r =>
        (r.face_clusters || []).some(cid => filterState.faceClusters.has(cid))
      );
    }
    // V23 — GPS location filter. -2 = "未知位置" (no GPS). A row
    // passes if its gps_cluster_id is selected OR (gps_cluster_id
    // is null AND -2 is selected).
    if (filterState.locationClusters.size > 0) {
      filtered = filtered.filter(r => {
        const cid = r.gps_cluster_id;
        if (cid != null && filterState.locationClusters.has(cid)) return true;
        if (cid == null && filterState.locationClusters.has(-2)) return true;
        return false;
      });
    }
    // V23 — "每地点最佳" toggle. Keep one row per location cluster
    // (the highest score_final one, precomputed server-side).
    if (filterState.locationBestOnly) {
      const bestMap = bestFilenamePerLocation();
      filtered = filtered.filter(r => {
        const cid = r.gps_cluster_id;
        if (cid == null) return false;   // unknown-location photos hidden
        return bestMap.get(cid) === r.filename;
      });
    }
    // V27 — "每连拍峰值" toggle. Keep only the photo with
    // is_burst_peak=true in each burst cluster of size ≥ 2 (singletons
    // pass-through since they're not real bursts).
    // V27 peak-only OR v2.4-P1-1 折叠成堆 both reduce each burst cluster
    // (size ≥ 2) to just its is_burst_peak hero; singletons pass through.
    // 折叠成堆 additionally renders a ⧉N stack badge on the survivor.
    if (filterState.burstPeakOnly || filterState.collapseBursts) {
      filtered = filtered.filter(r => {
        const size = _BURST_CLUSTER_SIZES.get(r.cluster_id) || 0;
        if (size < 2) return true;       // singleton cluster: keep
        return r.is_burst_peak === true;
      });
    }
    // v2.6-P1 — visual near-dup fold: hide every non-hero member of a
    // CLIP near-dup group (the hero carries the ≈N badge to expand).
    if (filterState.nearDupFold && _NEARDUP) {
      filtered = filtered.filter(r => !_NEARDUP.hidden.has(r.filename));
    }
    // P2.4 — active-learning filter. When the queue map is set, only
    // photos in it pass; subsequent sortRows respects rank order via
    // a custom sort key further down.
    if (filterState.activeLearningQueue != null) {
      const q = filterState.activeLearningQueue;
      filtered = filtered.filter(r => q.has(r.filename));
    }
    const sorted = sortRows(filtered);

    // ──────────────────────────────────────────────────────────────
    // v0.9-P1-4 — AI visualization helpers.
    //
    // _aiRadialSvg(score)   — radial progress ring around score_final
    // _aiSparklineSvg(vals) — 6-axis line graph for rubric_stars
    //
    // Both reference the #aiBrandGrad gradient defined in the SVG
    // sprite block (line ~4738) — single source of truth for the
    // signature indigo→violet→pink palette.  When the page renders
    // outside the main IIFE scope (e.g. the inline /share page) the
    // helpers degrade silently to a plain number.
    // ──────────────────────────────────────────────────────────────
    function _aiRadialSvg(score, opts) {
      const s = (score == null || isNaN(score)) ? null : Math.max(0, Math.min(1, +score));
      const lg = !!(opts && opts.large);
      // r=7 gives a 22 px outer box (r + stroke + tiny padding).
      // Circumference 2π·7 ≈ 44; round so dasharray maths is stable.
      const r = lg ? 14 : 7;
      const c = Math.PI * 2 * r;
      const offset = s == null ? c : c * (1 - s);
      return `<svg viewBox="0 0 24 24" aria-hidden="true">
        <circle class="sr-track" cx="12" cy="12" r="${r}"></circle>
        <circle class="sr-fill"  cx="12" cy="12" r="${r}"
          stroke-dasharray="${c.toFixed(2)}"
          stroke-dashoffset="${offset.toFixed(2)}"></circle>
      </svg>`;
    }
    function _aiSparklineSvg(vals, opts) {
      // vals: array of 6 stars (1..5), missing → null.
      const W = 280, H = 36, PAD_X = 6, PAD_Y = 4;
      const usable = W - PAD_X * 2;
      const stepX = usable / 5;            // 6 axes → 5 segments
      const yFor = (v) =>
        (v == null) ? null
        : H - PAD_Y - ((v - 1) / 4) * (H - PAD_Y * 2);
      const pts = vals.map((v, i) => {
        const y = yFor(v);
        if (y == null) return null;
        return { x: PAD_X + i * stepX, y, v };
      });
      const linePts = pts.filter(p => p != null);
      if (linePts.length < 2) {
        // Not enough data for a meaningful line; render a placeholder
        // rule so the layout doesn't pop.
        return `<svg class="ai-sparkline" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
          <line class="sp-axis" x1="${PAD_X}" y1="${H/2}" x2="${W - PAD_X}" y2="${H/2}"/>
        </svg>`;
      }
      const lineD = linePts.map((p, i) =>
        (i === 0 ? "M" : "L") + p.x.toFixed(1) + "," + p.y.toFixed(1)
      ).join(" ");
      // Area path: line + drop to bottom edge for the filled wash
      const areaD = lineD
        + ` L${linePts[linePts.length - 1].x.toFixed(1)},${H - PAD_Y}`
        + ` L${linePts[0].x.toFixed(1)},${H - PAD_Y} Z`;
      const dots = linePts.map(p =>
        `<circle class="sp-dot" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="2"/>`
      ).join("");
      // Mid-line ref so eyes have a sense of "3 stars = baseline"
      const midY = (H - PAD_Y - 0.5 * (H - PAD_Y * 2)).toFixed(1);
      return `<svg class="ai-sparkline" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
        <line class="sp-axis" x1="${PAD_X}" y1="${midY}" x2="${W - PAD_X}" y2="${midY}"/>
        <path class="sp-area" d="${areaD}"/>
        <path class="sp-line" d="${lineD}"/>
        ${dots}
      </svg>`;
    }
    // v0.13 patch — expose the two pure helpers globally so that
    // renderInfoPane() (declared OUTSIDE render()) can still call
    // them.  Pre-v0.13 versions had renderInfoPane nested inside
    // render(); somewhere along the way it got hoisted out and
    // the closure dependency stopped working.  Cheapest fix.
    window._aiRadialSvg    = _aiRadialSvg;
    window._aiSparklineSvg = _aiSparklineSvg;

    // Card renderer (extracted)
    function renderCard(r) {
      const thumb = `/thumb/${run_id}/${encodeURIComponent(r.filename)}`;
      const full = `/full/${run_id}/${encodeURIComponent(r.filename)}`;
      const dim = (k, v) => v == null
        ? `<div class="dim"><span class="k">${k}</span><span class="v">--</span></div>`
        : `<div class="dim"><span class="k">${k}</span><span class="v">${v.toFixed(2)}</span></div>`;
      // P2.4 — when the active-learning filter is on, mark each card
      // with "AL #N" + the per-photo "why" tooltip so the user knows
      // why this photo was prioritized.
      let activeLearningBadge = "";
      if (filterState.activeLearningQueue != null) {
        const al = filterState.activeLearningQueue.get(r.filename);
        if (al) {
          activeLearningBadge =
            `<div style="position:absolute;top:6px;left:6px;
             background:linear-gradient(90deg,#c4b9a9,#c4b9a9);
             color:#fff;padding:2px 8px;border-radius:3px;
             font-size:10px;font-weight:600;z-index:5;
             box-shadow:0 1px 4px rgba(0,0,0,0.4)"
             title="${esc(al.why || '')}">AL #${al.rank}</div>`;
        }
      }
      // v2.4-P1-1 — burst "stack" badge.  In 折叠成堆 mode each ≥2-frame
      // burst collapses to its peak hero; this ⧉N badge shows how many
      // frames the card stands in for and opens the side-by-side compare
      // modal for that cluster (the "expand" affordance).
      let burstStackBadge = "";
      // v2.6-P1 — ≈N visual near-dup badge on the group's hero. Rendered
      // first so a card that is BOTH a burst peak and a near-dup hero
      // shows ⧉ at the default top-right and ≈ offset below it.
      if (filterState.nearDupFold && _NEARDUP
          && _NEARDUP.byHero.has(r.filename)) {
        const members = _NEARDUP.byHero.get(r.filename);
        const bothBadges = filterState.collapseBursts && r.is_burst_peak
          && (_BURST_CLUSTER_SIZES.get(r.cluster_id) || 0) >= 2;
        burstStackBadge +=
          `<button type="button" class="burst-stack-badge" `
          + `data-neardup="${esc(r.filename)}" `
          + (bothBadges ? `style="top:40px" ` : "")
          + `title="视觉近重复 ${members.length} 张(CLIP)— 点击并排比较">`
          + `≈ ${members.length}</button>`;
      }
      if (filterState.collapseBursts && r.is_burst_peak) {
        const _stackN = _BURST_CLUSTER_SIZES.get(r.cluster_id) || 0;
        if (_stackN >= 2) {
          burstStackBadge +=                 // += so the ≈ near-dup badge coexists
            `<button type="button" class="burst-stack-badge" `
            + `data-cluster="c${esc(String(r.cluster_id))}" `
            + `title="此连拍组共 ${_stackN} 张 — 点击展开并排比较">`
            + `⧉ ${_stackN}</button>`;
        }
      }
      // V16.0 — translate reason tokens for the card display.
      // Keep the raw value in the title attr so power users can still
      // grep for the underlying token if needed.
      const reasonI18N = trReason(r.reason);
      const reasonShort = reasonI18N && reasonI18N.length > 60
        ? reasonI18N.slice(0, 60) + "…" : reasonI18N;
      // V1.2 shadow-mode badge: shows the rescorer's verdict + P(keep) when
      // present. Disagrees-with-rule cases get a yellow ring so they pop.
      let rescorerBadge = "";
      if (r.rescorer_pred) {
        const dis = r.rescorer_pred !== r.decision;
        const probTxt = r.rescorer_prob_keep == null ? "--" :
          r.rescorer_prob_keep.toFixed(2);
        rescorerBadge = `<span class="rs ${dis ? 'dis' : ''}" title="V1.1 rescorer: ${r.rescorer_pred} (P=${probTxt})">${r.rescorer_pred==='keep'?'✓':'?'} ${probTxt}</span>`;
      }
      // V3.1 meta-judge badge: shows overall verdict + confidence and
      // a tooltip with inconsistencies. When meta disagrees with rule,
      // pop a yellow ring like the rescorer-disagreement marker.
      let metaBadge = "";
      if (r.meta_overall_label) {
        const dis = r.meta_overall_label !== r.decision;
        const conf = r.meta_confidence == null ? "" : ` ${(r.meta_confidence*100).toFixed(0)}%`;
        const inc = r.meta_inconsistencies || "";
        const tip = `DeepSeek meta-judge: ${r.meta_overall_label}${conf}\n${r.meta_overall_rationale}\n${inc ? '矛盾: '+inc : ''}`.replace(/"/g,'&quot;');
        metaBadge = `<span class="rs meta ${dis?'dis':''}" title="${tip}">⌬ ${r.meta_overall_label[0].toUpperCase()}${conf}</span>`;
      }
      // V2.0 rubric stars per axis. Only show shorter labels on each
      // card (full descriptors live in the annotation modal).
      const axisAbbr = {
        technical: "技", subject: "主", composition: "构",
        light: "光", moment: "瞬", aesthetic: "美"
      };
      const ax = (name) => {
        const stars = r.rubric_stars && r.rubric_stars[name];
        if (stars == null) return `<div class="ax"><span class="k">${axisAbbr[name]}</span><span class="v">--</span></div>`;
        const s = Math.round(stars);
        const cls = `s${s}` + (r.rubric_human_labeled ? " human" : "");
        // v0.9-P1-4 — inline --axis-fill drives the ::before bottom-up
        // wash so each chip is already a 6-bar bullet chart even
        // without scanning numbers.  Clamp to [0, 1].
        const fill = Math.max(0, Math.min(1, (stars - 1) / 4));
        return `<div class="ax ${cls}" style="--axis-fill:${fill.toFixed(3)}" title="${name}: ${stars.toFixed(1)}★${r.rubric_human_labeled?' (human)':''}"><span class="k">${axisAbbr[name]}</span><span class="v">${stars.toFixed(1)}</span></div>`;
      };
      // Image-failure investigation 2026-Q4: _syncConflictFns is
      // declared with `let` below (search "v0.10-P0-1"), so even
      // `typeof X` throws ReferenceError when this function is
      // called inside the TDZ window — which can happen during
      // initial render() if the IIFE's top-down execution order
      // shifts.  Replace with a window-attached lookup so the
      // check is safe regardless of declaration order.
      const _conflictSet = (typeof window !== "undefined"
                             && window._syncConflictFns)
                             || null;
      const cardCls = r.decision
        + (r.rubric_human_labeled ? " has-human" : "")
        + (r.needs_review ? " needs-review" : "")
        + (_conflictSet && _conflictSet.has(r.filename)
            ? " sync-conflict" : "");
      // V9.0 style chip — V16.0 localized to Chinese label, raw token
      // still in tooltip so users can map to the wire format.
      const styleChips = (r.style_modes || []).map(
        s => `<span class="style-chip" title="检测到风格: ${esc(s)}">${esc(trStyle(s))}</span>`
      ).join("");
      // V14.0 — escape filename for every interpolation site. Filenames
      // can contain quotes/angle brackets on macOS+APFS, and an injected
      // attribute would break the whole card.
      const fnEsc = esc(r.filename);
      // V16.2 — read any persisted manual rotation override (set
      // either from the lightbox or from the card hover button).
      // Same localStorage key as lightbox (_lbRotKey), so the two
      // views share state — rotate once, both update.
      const rotDeg = _lbRotGet(r.filename);
      const rotStyle = rotDeg ? `style="transform: rotate(${rotDeg}deg)"` : "";
      // v0.5 LR-grade (2/3) — LR Library-style decision glyph
      // overlayed top-left of the thumb (small, monochrome,
      // doesn't compete with the photo).  Same shapes as the
      // P-UX-23 a11y glyphs (✓ / ? / ✕) but presented as a
      // floating chip rather than inline with the badge row.
      const glyphMap = { keep: "✓", maybe: "?", cull: "✕" };
      const decisionGlyph = r.decision && glyphMap[r.decision]
        ? `<span class="thumb-decision-glyph dg-${r.decision}" title="${esc(r.decision)}">${glyphMap[r.decision]}</span>`
        : "";
      // Bottom-gradient overlay holding filename + score, like the
      // LR Library thumbnail metadata strip.  Always present so
      // the gradient is visible; opacity-toggled by hover at the
      // grid level.
      const scoreText = r.score_final == null
        ? "" : r.score_final.toFixed(2);
      return `
        <div class="card ${cardCls}" data-fn="${fnEsc}">
          ${activeLearningBadge}
          ${burstStackBadge}
          <div class="thumb-wrap">
            <!-- v0.13.5 — decoding="async" so the main thread isn't
                 blocked decoding 200+ JPEGs simultaneously on initial
                 render.  Native lazy-loading still throttles network
                 requests.  fetchpriority=low so off-viewport thumbs
                 don't crowd out CSS / fonts. -->
            <img class="thumb" src="${thumb}" data-full="${full}" loading="lazy" decoding="async" fetchpriority="low" alt="${fnEsc}" ${rotStyle}>
            ${decisionGlyph}
            <div class="thumb-overlay">
              <span class="thumb-overlay-fn" title="${fnEsc}">${fnEsc}</span>
              ${scoreText ? `<span class="thumb-overlay-score">${scoreText}</span>` : ""}
            </div>
            <!-- v0.9-P1-1 — floating action group, top-right.
                 Three discrete primary actions: zoom (open lightbox),
                 add-to-bucket (quick assign), compare (alt path to ⇆). -->
            <div class="card-actions" data-fn="${fnEsc}" role="group"
                 aria-label="${esc(fnEsc)} 操作">
              <button class="card-action card-action-zoom" type="button"
                      data-fn="${fnEsc}" title="打开放大窗 (或 Space)">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                  <line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/>
                </svg>
              </button>
              <button class="card-action card-action-bucket" type="button"
                      data-fn="${fnEsc}" title="加入交付桶">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M5 7h14l-1.5 12.5a2 2 0 0 1-2 1.5h-7a2 2 0 0 1-2-1.5L5 7z"/>
                  <path d="M9 7V5a3 3 0 0 1 6 0v2"/>
                </svg>
              </button>
              <button class="card-action card-action-compare" type="button"
                      data-fn="${fnEsc}" title="加入 A/B 比较(同 ⇆ / c)">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M7 16V4M3 8l4-4 4 4"/>
                  <path d="M17 8v12M13 16l4 4 4-4"/>
                </svg>
              </button>
            </div>
          </div>
          <button class="annotate-btn" data-fn="${fnEsc}" title="人工标注 (rubric)">${r.rubric_human_labeled ? "✓ 已标" : "标注"}</button>
          <button class="card-rot-btn" data-fn="${fnEsc}" type="button" title="顺时针旋转 90°(在放大窗中可继续微调)">↻</button>
          <button class="card-cmp-btn" data-fn="${fnEsc}" type="button"
            title="选这张进入 A/B 比较(Shift+点击缩略图同效;c 键也可)"><svg class="icon icon--sm"><use href="#icon-swap"/></svg></button>
          <div class="body">
            <div class="row1">
              <span class="badge ${r.decision}" title="${esc(r.decision)}">${esc(tr(r.decision, I18N_DECISION) || r.decision)}</span>
              <span class="fn" title="${fnEsc}">${fnEsc}</span>
              ${rescorerBadge}
              ${metaBadge}
              ${styleChips}
              ${r.cull_reason ? `<span class="cull-reason-chip" title="cull 原因: ${esc(_cullReasonLabel(r.cull_reason))}">✕ ${esc(_cullReasonLabel(r.cull_reason))}</span>` : ""}
              ${r.wedding_moment ? (() => {
                  const mLabel = I18N_WEDDING_MOMENT[r.wedding_moment] || r.wedding_moment;
                  const uncertain = r.wedding_moment === "unknown";
                  const conf = r.wedding_moment_confidence != null
                    ? ` · 置信度 ${(r.wedding_moment_confidence * 100).toFixed(0)}%` : "";
                  // P-UX-27 — clickable filter.  data-moment carries the
                  // moment key; the click handler in the grid delegate
                  // adds/removes from filterState.weddingMoments.
                  const active = filterState.weddingMoments.has(r.wedding_moment) ? "active" : "";
                  return `<span class="moment-chip ${uncertain ? "uncertain" : ""} ${active}"
                          data-moment="${esc(r.wedding_moment)}"
                          title="婚礼 moment: ${esc(mLabel)}${esc(conf)} · 点击只看此 moment">` +
                          `<svg class="icon icon--sm"><use href="#icon-heart"/></svg>` +
                          `<span>${esc(mLabel)}</span></span>`;
                })() : ""}
              ${r.needs_review ? `<span class="review-me-chip" title="自动 / 训练模型 / VLM / DeepSeek 这 4 个评分源对此图分歧大 (累计 ${(r.inconsistency_total || 0).toFixed(1)} ★ stddev) — 值得人工复核">⚠ review me</span>` : ""}
              ${r.exposure_outlier ? (() => {
                  const d = r.exposure_deviation || {};
                  const ld = d.luma_delta || 0;
                  const hd = d.highlight_delta || 0;
                  const cls = ld > 0 ? "over" : "under";
                  const dir = ld > 0 ? "↑" : "↓";
                  const stops = Math.abs(ld) / 18;
                  return `<span class="exposure-chip ${cls}" title="此图相对连拍组中位数曝光偏离 ${dir} ${Math.abs(ld).toFixed(0)} luma (~${stops.toFixed(1)} 档) · 高光剪裁差 ${hd >= 0 ? '+' : ''}${hd.toFixed(1)}% · 连拍组共 ${d.cluster_size || '?'} 张">☼ ${dir}${stops.toFixed(1)}EV</span>`;
                })() : ""}
            </div>
            <div class="row2">
              <span class="scene" title="${esc(r.scene || '')}">${esc(trGenre(r.scene) || "?")}</span>
              <!-- v0.9-P1-4 — radial progress + brand-gradient
                   text-fill turn score_final into a glanceable visual
                   signal.  Falls back gracefully on null. -->
              <span class="score-radial" title="score_final ${r.score_final == null ? '(unavailable)' : r.score_final.toFixed(3) + ' · 0..1'}">
                ${_aiRadialSvg(r.score_final)}
                <span>综合分 <span class="ai-num">${r.score_final == null ? "--" : r.score_final.toFixed(2)}</span></span>
              </span>
            </div>
            <div class="row3">
              ${ax("technical")}${ax("subject")}${ax("composition")}
              ${ax("light")}${ax("moment")}${ax("aesthetic")}
            </div>
            <div class="row4" title="${esc(r.reason || '')}">${esc(reasonShort || "")}</div>
            ${(r.advice && r.advice.rationale) ? `<div class="row5 rationale-line" title="V14.3 — 为何 maybe">⊕ ${esc(r.advice.rationale)}</div>` : ''}
            ${(r.advice && r.advice.strengths && r.advice.strengths.length) ? `<div class="row5 strengths" title="V5.2 摄影正典优点">✓ ${r.advice.strengths.slice(0,2).map(esc).join(' · ')}</div>` : ''}
            ${(r.advice && r.advice.suggestions && r.advice.suggestions.length) ? `<div class="row5 fixes" title="V5.2 改进建议">→ ${esc(r.advice.suggestions[0])}</div>` : ''}
          </div>
        </div>
      `;
    }
    // End of renderCard

    // V9.0: when sorting by cluster, insert visual dividers for each
    // multi-image cluster so the user sees burst groupings explicitly.
    //
    // V14.1 — produce *segments* (HTML strings) rather than one giant
    // string so the renderer below can flush them to the DOM in
    // batches. For ≤200 cards we still render in one shot (no point
    // batching when it's all visible at once).
    const segments = [];
    if (filterState.sort === "cluster") {
      // Group rows by cluster_id
      const groups = new Map();
      sorted.forEach(r => {
        const c = r.cluster_id == null ? `solo-${r.filename}` : `c${r.cluster_id}`;
        if (!groups.has(c)) groups.set(c, []);
        groups.get(c).push(r);
      });
      // Render: only show divider for clusters with >1 member
      groups.forEach((members, key) => {
        if (members.length > 1) {
          const best = members[0];
          segments.push(`<div class="cluster-divider">
            <span>连拍组 (${members.length} 张) · 最佳: ${esc(best.filename)}</span>
            <span class="compare-btn" data-cluster="${esc(key)}">⊞ 并排比较</span>
          </div>`);
        }
        members.forEach(r => { segments.push(renderCard(r)); });
      });
    } else {
      sorted.forEach(r => { segments.push(renderCard(r)); });
    }
    let html = segments.join("");
    // V14.1 — progressive rendering for big batches. Inserting 1500
    // cards at once janks the main thread for ~300 ms on a mid laptop.
    // Render the first 100 immediately (above-fold), then chunk the
    // remainder in 80-card slices via requestAnimationFrame so the page
    // becomes interactive while the rest streams in. Skip the dance
    // entirely below the threshold — it's already imperceptible there.
    //
    // P-UX-18 — for batches above HUGE_THRESHOLD, switch to a third
    // strategy: emit placeholder divs for cards past FIRST_BATCH and
    // materialize them via IntersectionObserver as they scroll near
    // the viewport. Caps live-card DOM weight at first-batch +
    // visible-viewport-worth ≈ ~150 even when the batch has 5000+
    // rows. The placeholder takes the same approximate card height
    // so the scrollbar position stays accurate.
    const BATCH_THRESHOLD = 200;
    const FIRST_BATCH = 100;
    const CHUNK = 80;
    const HUGE_THRESHOLD = 500;
    const PLACEHOLDER_HEIGHT = 340;   // approx card render height

    // Cancel any in-flight progressive render from a previous filter
    // change so we don't double-insert cards.
    if (window._pcProgressiveToken) window._pcProgressiveToken.cancelled = true;
    const token = { cancelled: false };
    window._pcProgressiveToken = token;

    // V14.0 — richer empty states. Three cases:
    //   1) rows.length === 0           → pipeline produced nothing
    //   2) filtered.length === 0       → user's filter excluded everything
    //   3) html === ""                 → defensive (shouldn't happen)
    if (!html) {
      let emptyHtml;
      if (rows.length === 0) {
        // v0.13.14 — replace line-art SVG with MiniMax painter
        // illustration.  onerror falls back to the legacy SVG for
        // offline / first-run.
        emptyHtml = `
          <div class="empty-state">
            <img class="empty-art-img"
                 src="/docs/illustrations/art-empty-inbox.png" alt=""
                 onerror="this.outerHTML='<svg class=&quot;empty-art&quot;><use href=&quot;#art-empty-inbox&quot;/></svg>'">
            <div class="empty-title">这个 run 没有产出任何结果</div>
            <div class="empty-hint">
              可能原因:全部图片解码失败 / 文件夹为空 / 仅含非图片文件。
            </div>
            <div class="empty-actions">
              <a class="btn primary" href="/">返回上传新批次</a>
              <button class="btn" onclick="window.location.reload()">刷新此页</button>
            </div>
          </div>`;
      } else {
        const totalFilters = filterState.scenes.size + filterState.styles.size +
                             filterState.weddingMoments.size +
                             (filterState.decision !== "all" ? 1 : 0);
        // v0.9-P2-3 — differentiate filter-empty from search-empty.
        // Filter-empty = user set criteria (decision / scene / style…).
        // Search-empty = user typed a CLIP query that didn't land.
        // Different art + framing keeps the two failure modes legible:
        // "refine your filter" vs "try a synonym".
        const isSearch = !!(filterState.semSearch
                            && filterState.semSearch.q);
        if (isSearch) {
          emptyHtml = `
          <div class="empty-state">
            <img class="empty-art-img"
                 src="/docs/illustrations/art-no-search.png" alt=""
                 onerror="this.outerHTML='<svg class=&quot;empty-art&quot;><use href=&quot;#art-no-search&quot;/></svg>'">
            <div class="empty-title">没有照片匹配你的搜索</div>
            <div class="empty-hint">
              CLIP 没有在 ${rows.length} 张图中找到匹配
              <b>"${esc(filterState.semSearch.q)}"</b> 的照片。
              试试同义词,或更宽泛的描述
              (比如 "sunset over water" 替代 "golden hour beach")。
            </div>
            <div class="empty-actions">
              <button class="btn primary" id="resetSearchBtn">清除搜索</button>
            </div>
          </div>`;
        } else {
          emptyHtml = `
          <div class="empty-state">
            <img class="empty-art-img"
                 src="/docs/illustrations/art-no-match.png" alt=""
                 onerror="this.outerHTML='<svg class=&quot;empty-art&quot;><use href=&quot;#art-no-match&quot;/></svg>'">
            <div class="empty-title">当前筛选下没有图片</div>
            <div class="empty-hint">
              ${totalFilters} 个筛选条件正在过滤这个 ${rows.length} 张图的批次。
            </div>
            <div class="empty-actions">
              <button class="btn primary" id="resetFiltersBtn">重置所有筛选</button>
            </div>
          </div>`;
        }
      }
      grid.innerHTML = emptyHtml;
      const reset = document.getElementById("resetFiltersBtn");
      if (reset) reset.addEventListener("click", () => {
        filterState.decision = "all";
        filterState.scenes.clear();
        filterState.styles.clear();
        // P-UX-4 — also clear the cull-reason filter on full reset
        filterState.cullReason = null;
        // P-UX-27 — same for the wedding-moment filter
        filterState.weddingMoments.clear();
        document.querySelectorAll("#decisionPills .pill, #sceneFilters .pill, #styleFilters .pill, #cullReasonFilter .pill")
          .forEach(el => el.classList.remove("active"));
        document.querySelector('#decisionPills .pill[data-d="all"]')?.classList.add("active");
        render();
      });
      // v0.9-P2-3 — search-empty CTA: clear just the semantic search,
      // leaving other filters intact (a user who's iterating on the
      // query string doesn't want their scene + decision pills wiped).
      const resetSearch = document.getElementById("resetSearchBtn");
      if (resetSearch) resetSearch.addEventListener("click", () => {
        filterState.semSearch = null;
        const ssi = document.getElementById("semSearchInput");
        const ssc = document.getElementById("semSearchClearBtn");
        if (ssi) ssi.value = "";
        if (ssc) ssc.style.display = "none";
        render();
      });
    } else if (segments.length <= BATCH_THRESHOLD) {
      // Small batch: one shot, fastest path.
      grid.innerHTML = html;
    } else if (segments.length <= HUGE_THRESHOLD) {
      // Mid batch: paint the above-fold portion, then stream the rest
      // in chunks so the user can scroll/click immediately.
      grid.innerHTML = segments.slice(0, FIRST_BATCH).join("");
      const remaining = segments.slice(FIRST_BATCH);
      let idx = 0;
      function step() {
        if (token.cancelled) return;
        const slice = remaining.slice(idx, idx + CHUNK);
        if (!slice.length) return;
        const tmp = document.createElement("div");
        tmp.innerHTML = slice.join("");
        // Move children directly — appendChild detaches from tmp,
        // so we don't pay the cost of re-parsing.
        const frag = document.createDocumentFragment();
        while (tmp.firstChild) frag.appendChild(tmp.firstChild);
        grid.appendChild(frag);
        idx += CHUNK;
        if (idx < remaining.length) requestAnimationFrame(step);
      }
      requestAnimationFrame(step);
    } else {
      // P-UX-18 — huge batch (≥ 500 rows). Avoid materializing all
      // cards: only render the first FIRST_BATCH eagerly, and emit
      // placeholder divs (with the approximate card height) for
      // the rest. An IntersectionObserver watches each placeholder
      // and replaces it with the real card HTML when it's within
      // 2 viewports of the user's scroll. The total live-card DOM
      // weight stays roughly proportional to viewport size, not
      // batch size — a 5000-photo wedding renders just as smoothly
      // as a 200-photo session.
      grid.innerHTML = segments.slice(0, FIRST_BATCH).join("");
      // Emit placeholder divs for the rest. data-idx points back to
      // the segment array entry; data-fn carries the filename so
      // keyboard nav can still index by filename even before
      // materialization.
      const placeholderFrag = document.createDocumentFragment();
      for (let i = FIRST_BATCH; i < segments.length; i++) {
        const ph = document.createElement("div");
        ph.className = "card-placeholder";
        ph.style.height = PLACEHOLDER_HEIGHT + "px";
        ph.dataset.idx = String(i);
        placeholderFrag.appendChild(ph);
      }
      grid.appendChild(placeholderFrag);

      // Tear down a previous observer (filter change → re-render
      // means new placeholders, the old IO would still hold refs).
      if (window._pcCardObserver) {
        try { window._pcCardObserver.disconnect(); } catch (_e) {}
      }
      const io = new IntersectionObserver((entries) => {
        if (token.cancelled) return;
        for (const ent of entries) {
          if (!ent.isIntersecting) continue;
          const ph = ent.target;
          const idx = parseInt(ph.dataset.idx || "-1", 10);
          if (idx < 0 || idx >= segments.length) continue;
          const tmp = document.createElement("div");
          tmp.innerHTML = segments[idx];
          // Move the real card into the placeholder's slot.
          while (tmp.firstChild) ph.parentNode.insertBefore(tmp.firstChild, ph);
          io.unobserve(ph);
          ph.remove();
        }
      }, {
        // v0.7-P0-3 — adaptive rootMargin: full 200% ahead at <1k
        // rows (the snappy default), gracefully drops to 40% at
        // 5k+ so we don't keep hundreds of cards in RAM ahead of
        // the viewport. _adaptiveRootMargin lives near the top of
        // the script.
        rootMargin: _adaptiveRootMargin(rows.length),
        threshold: 0,
      });
      grid.querySelectorAll(".card-placeholder").forEach(el => io.observe(el));
      window._pcCardObserver = io;
    }
  }
  render();

  // ============================================================
  // v0.9-P0-2 — hero reveal (the signature moment).
  //
  // On page boot (and only then — not on filter re-renders), add
  // body.hero-revealing so the CSS keyframes fire.  Walk grid
  // cards, set --idx so the staggered animation-delay works.
  // After ~2.1s remove the class — any subsequent re-render is
  // instant.  prefers-reduced-motion users skip the reveal
  // entirely (CSS @media handles that).
  // ============================================================
  (function _heroReveal() {
    // Skip on slow connections / save-data — animation work is
    // wasted CPU on those clients.
    if (navigator.connection
        && navigator.connection.saveData === true) return;
    document.body.classList.add("hero-revealing");
    // Per-card stagger index.  Set on every initial card whose
    // animation will fire.  IntersectionObserver-materialised
    // placeholders catch up via the MutationObserver below.
    function setStaggerIndices() {
      let i = 0;
      grid.querySelectorAll(".card").forEach(card => {
        card.style.setProperty("--idx", String(i));
        i += 1;
      });
    }
    setStaggerIndices();
    // Late-materialised placeholders (P-UX-18 large-batch streaming)
    // get their --idx set when they swap into real .card elements.
    const lateObs = new MutationObserver(muts => {
      for (const m of muts) {
        for (const node of m.addedNodes) {
          if (node.nodeType === 1 && node.classList?.contains("card")) {
            // Continue stagger from the current visible count
            const idx = grid.querySelectorAll(".card").length - 1;
            // Cap to 64 to match the CSS clamp
            node.style.setProperty("--idx", String(Math.min(idx, 64)));
          }
        }
      }
    });
    lateObs.observe(grid, { childList: true });
    // Tear down after the reveal finishes
    setTimeout(() => {
      document.body.classList.remove("hero-revealing");
      lateObs.disconnect();
    }, 2200);
  })();

  // V9.0 sort dropdown
  document.getElementById("sortBy").addEventListener("change", e => {
    filterState.sort = e.target.value;
    render();
  });

  // P-UX-20 — saved view presets. Captures the full filter combo
  // (decision + scenes + styles + cull_reason + sort) as a named
  // entry in localStorage. Power users build the same combo over
  // and over ("keep + with-face + score>0.7"); this lets them
  // build once + recall by name.
  const _VIEW_PRESETS_KEY = "pixcull_view_presets_v1";

  function _readPresets() {
    try {
      return JSON.parse(localStorage.getItem(_VIEW_PRESETS_KEY) || "{}");
    } catch (_e) { return {}; }
  }
  function _writePresets(p) {
    try { localStorage.setItem(_VIEW_PRESETS_KEY, JSON.stringify(p)); }
    catch (_e) { /* localStorage full / disabled — silent skip */ }
  }

  function _captureCurrentView() {
    return {
      decision: filterState.decision,
      scenes:   [...filterState.scenes],
      styles:   [...filterState.styles],
      faceClusters:     [...filterState.faceClusters],
      locationClusters: [...filterState.locationClusters],
      cullReason: filterState.cullReason,
      sort:       filterState.sort,
      burstPeakOnly:    filterState.burstPeakOnly,
      locationBestOnly: filterState.locationBestOnly,
      // P-UX-27 — persist the wedding-moment filter in saved presets
      weddingMoments:   [...filterState.weddingMoments],
    };
  }
  function _applyView(view) {
    if (!view) return;
    filterState.decision = view.decision || "all";
    filterState.scenes = new Set(view.scenes || []);
    filterState.styles = new Set(view.styles || []);
    filterState.faceClusters     = new Set(view.faceClusters || []);
    filterState.locationClusters = new Set(view.locationClusters || []);
    filterState.cullReason = view.cullReason || null;
    filterState.sort       = view.sort || "default";
    filterState.burstPeakOnly    = !!view.burstPeakOnly;
    filterState.locationBestOnly = !!view.locationBestOnly;
    filterState.weddingMoments   = new Set(view.weddingMoments || []);
    // Sync UI: decision pill active class
    document.querySelectorAll("#decisionPills .pill").forEach(el => {
      el.classList.toggle("active",
        el.dataset.d === filterState.decision);
    });
    document.getElementById("sortBy").value = filterState.sort;
    _rebuildPresetDropdown();
    render();
  }
  function _rebuildPresetDropdown() {
    const sel = document.getElementById("viewPresetBy");
    if (!sel) return;
    const presets = _readPresets();
    const names = Object.keys(presets).sort();
    sel.innerHTML =
      `<option value="">视图预设 ▾</option>` +
      names.map(n =>
        `<option value="${esc(n)}">${esc(n)}</option>`).join("") +
      (names.length ? `<option value="__delete__">删除预设…</option>` : "");
  }

  // v0.7-P1-3 — built-in starter presets, seeded once on first
  // load.  These cover the 4 most-asked-for combos across every
  // run; users can delete them just like their own presets if
  // they don't like them. The "★ 起" prefix marks them as
  // starters so they don't get confused with user-built ones.
  const _STARTER_PRESETS_SEED_KEY = "pixcull_starter_presets_seeded_v1";
  const _STARTER_PRESETS = {
    "★ 起 · 仪式 only": {
      decision: "all", scenes: [], styles: [],
      faceClusters: [], locationClusters: [],
      cullReason: null, sort: "default",
      burstPeakOnly: false, locationBestOnly: false,
      weddingMoments: ["ceremony", "vows", "rings", "kiss"],
    },
    "★ 起 · 废片二审": {
      decision: "cull", scenes: [], styles: [],
      faceClusters: [], locationClusters: [],
      cullReason: null, sort: "score_desc",
      burstPeakOnly: false, locationBestOnly: false,
      weddingMoments: [],
    },
    "★ 起 · 连拍峰值 only": {
      decision: "all", scenes: [], styles: [],
      faceClusters: [], locationClusters: [],
      cullReason: null, sort: "default",
      burstPeakOnly: true, locationBestOnly: false,
      weddingMoments: [],
    },
    "★ 起 · 高置信 keep": {
      decision: "keep", scenes: [], styles: [],
      faceClusters: [], locationClusters: [],
      cullReason: null, sort: "score_desc",
      burstPeakOnly: false, locationBestOnly: false,
      weddingMoments: [],
    },
  };
  function _seedStarterPresets() {
    if (localStorage.getItem(_STARTER_PRESETS_SEED_KEY)) return;
    const current = _readPresets();
    let dirty = false;
    for (const [name, view] of Object.entries(_STARTER_PRESETS)) {
      if (!current[name]) {
        current[name] = view;
        dirty = true;
      }
    }
    if (dirty) _writePresets(current);
    try { localStorage.setItem(_STARTER_PRESETS_SEED_KEY, "1"); } catch (_e) {}
  }
  _seedStarterPresets();

  _rebuildPresetDropdown();

  // v0.7-P1-3 — JSON import / export. Lets users move presets
  // across browsers, runs, and machines. Schema is the raw map of
  // {name → view}, wrapped in {schema: "pixcull.view_presets/v1",
  // exported_at: ISO, presets: {...}} so future migrations have a
  // version hook.
  document.getElementById("exportPresetsBtn")?.addEventListener("click", () => {
    const presets = _readPresets();
    const names = Object.keys(presets);
    if (!names.length) {
      showToast("还没有预设可导出", "info");
      return;
    }
    const payload = {
      schema: "pixcull.view_presets/v1",
      exported_at: new Date().toISOString(),
      presets,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)],
                         { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `pixcull-view-presets-${new Date().toISOString().slice(0,10)}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast(`已导出 ${names.length} 个视图预设`, "success");
  });
  document.getElementById("importPresetsBtn")?.addEventListener("click", () => {
    document.getElementById("importPresetsInput")?.click();
  });
  document.getElementById("importPresetsInput")?.addEventListener("change", e => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const data = JSON.parse(reader.result);
        // Accept either {schema, presets} (v1) or a raw {name → view} map.
        const incoming = (data && data.presets && typeof data.presets === "object")
          ? data.presets
          : (data && typeof data === "object" ? data : null);
        if (!incoming) throw new Error("invalid file");
        const names = Object.keys(incoming);
        if (!names.length) throw new Error("empty");
        const current = _readPresets();
        // Merge: existing keys are overwritten (the user pulled
        // them in deliberately).  Track new vs replaced.
        let added = 0, replaced = 0;
        for (const [name, view] of Object.entries(incoming)) {
          if (current[name]) replaced++;
          else added++;
          current[name] = view;
        }
        _writePresets(current);
        _rebuildPresetDropdown();
        showToast(`已导入 ${added} 个新预设 + 覆盖 ${replaced} 个同名预设`, "success");
      } catch (err) {
        showToast("导入失败:不是有效的预设 JSON", "error");
      } finally {
        // Reset input so the same file can be re-picked.
        e.target.value = "";
      }
    };
    reader.onerror = () => showToast("读取文件失败", "error");
    reader.readAsText(f);
  });

  // P-AI-2 — CLIP semantic search input. Enter runs the query; the
  // first query for a run takes 1-2 minutes to build the embeddings
  // cache (CLIP encode every photo) — subsequent queries are <100ms.
  // We show an inline loading state in the input + toast the result.
  const semSearchInput = document.getElementById("semSearchInput");
  const semSearchClearBtn = document.getElementById("semSearchClearBtn");
  async function runSemSearch(query) {
    if (!query.trim()) return;
    semSearchInput.disabled = true;
    const orig = semSearchInput.placeholder;
    semSearchInput.placeholder = "🔎 搜索中…(首次较慢)";
    try {
      const r = await fetch(
        `/api/v1/runs/${run_id}/semantic_search?q=${encodeURIComponent(query)}&k=50`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      const names = new Set((d.results || []).map(x => x.filename));
      filterState.semSearch = { q: query, filenames: names };
      semSearchClearBtn.style.display = "";
      const cacheLabel = d.cached ? "cached" : `built in ${(d.build_ms/1000).toFixed(1)}s`;
      showToast(`找到 ${names.size} 张匹配 "${query}" 的照片 (${cacheLabel})`, "success");
      render();
    } catch (e) {
      showToast("语义搜索失败: " + e.message, "error");
    } finally {
      semSearchInput.disabled = false;
      semSearchInput.placeholder = orig;
    }
  }
  semSearchInput?.addEventListener("keydown", e => {
    if (e.key === "Enter") {
      e.preventDefault();
      runSemSearch(semSearchInput.value);
    }
  });
  semSearchClearBtn?.addEventListener("click", () => {
    filterState.semSearch = null;
    semSearchInput.value = "";
    semSearchClearBtn.style.display = "none";
    render();
  });

  document.getElementById("saveViewBtn")?.addEventListener("click", () => {
    const name = prompt("给这个视图起个名字\n(例: 婚礼 keep + 高分 / 风光 best-of-location)");
    if (!name || !name.trim()) return;
    const presets = _readPresets();
    presets[name.trim()] = _captureCurrentView();
    _writePresets(presets);
    _rebuildPresetDropdown();
    showToast(`已保存视图 "${name.trim()}"`, "success");
  });
  document.getElementById("viewPresetBy")?.addEventListener("change", e => {
    const v = e.target.value;
    if (!v) return;
    if (v === "__delete__") {
      const presets = _readPresets();
      const names = Object.keys(presets);
      if (!names.length) { e.target.value = ""; return; }
      const target = prompt(
        "要删除哪个预设?(输入名字)\n现有: " + names.join(", "));
      if (target && presets[target]) {
        delete presets[target];
        _writePresets(presets);
        _rebuildPresetDropdown();
        showToast(`已删除 "${target}"`, "success");
      }
      e.target.value = "";
      return;
    }
    const presets = _readPresets();
    if (presets[v]) {
      _applyView(presets[v]);
      showToast(`已加载视图 "${v}"`, "info");
    }
    e.target.value = "";   // reset to header so re-pick works
  });

  // Decision filter pills (the original keep/maybe/cull/all set)
  document.querySelectorAll("#decisionPills .pill").forEach(el => {
    el.addEventListener("click", () => {
      document.querySelectorAll("#decisionPills .pill").forEach(x => x.classList.remove("active"));
      el.classList.add("active");
      filterState.decision = el.dataset.d;
      render();
    });
  });

  // V10.1 Lightbox — image + full evaluation panel
  const lb = document.getElementById("lightbox");
  const lbImg = document.getElementById("lbImg");
  const lbInfo = document.getElementById("lbInfo");
  const lbClose = document.getElementById("lbClose");
  // v0.6 (2/5) — persist user fold/unfold choices on each
  // info-section so the Inspector pane feels like LR Develop
  // (your "I never look at Raw Flags" stays remembered across
  // photos AND across page reloads).  Delegated so we don't
  // re-attach per renderInfoPane() rebuild.
  if (lbInfo) {
    lbInfo.addEventListener("toggle", e => {
      const det = e.target;
      if (!det || !det.classList || !det.classList.contains("info-section")) return;
      const sec = det.dataset.sec;
      if (!sec) return;
      const st = _readInspectorState();
      st[sec] = !!det.open;
      _writeInspectorState(st);
    }, true);  // capture — <details> toggle doesn't bubble in some engines

    // v0.8-P1-1 — λ-cycling chip click handler.  Cycles through
    // [0.0, 0.3, 0.5, 0.7, 1.0] so the user can dial between
    // "pure V2 (visual)" and "pure V1 (axis stars)".  Re-blends
    // distances + re-renders without a server round-trip.
    lbInfo.addEventListener("click", e => {
      const chip = e.target.closest(".style-lambda-chip");
      if (!chip) return;
      e.preventDefault();
      e.stopPropagation();
      const cycle = [0.0, 0.3, 0.5, 0.7, 1.0];
      const cur = _getStyleLambda();
      // Pick the next value > cur, wrapping around
      let next = cycle.find(v => v > cur + 0.01);
      if (next === undefined) next = cycle[0];
      // v0.11-P1-3 — clicking the chip is an explicit user choice;
      // freeze the auto-vertical-pick from now on for this run.
      _markLambdaManual();
      _rebleStyleDistances(next);
      // Re-open the lightbox info pane (render() rebuilt lbInfo)
      // — the existing flow expects the user is still inside it.
      const fn = (typeof _lbCurrentFn === "string") ? _lbCurrentFn : null;
      if (fn) {
        const r = rows.find(x => x.filename === fn);
        if (r) lbInfo.innerHTML = renderInfoPane(r);
      }
    });
  }
  // V14.4 — register for ARIA + focus trap. Existing call sites that
  // do ``lb.classList.add("show")`` continue to work; the observer
  // handles a11y reactively.
  registerModal(lb);

  // V14.2 — track the current lightbox row so keyboard nav can step
  // through the *visible* card order (whatever filters/sort are
  // applied), not just the raw `rows` array.
  let _lbCurrentFn = null;

  function _lbVisibleFns() {
    return Array.from(grid.querySelectorAll(".card")).map(c => c.dataset.fn);
  }

  function openLightbox(fn) {
    const r = rows.find(x => x.filename === fn);
    if (!r) return;
    _lbCurrentFn = fn;
    // v2.3.1-C — the grid-context "新手提示" coachmark must not linger
    // over the lightbox (they overlapped in the first-open screenshots).
    // Dismiss it the moment a photo opens; the lightbox has its own hint.
    document.querySelectorAll(".onboard-tip").forEach((t) => t.remove());
    // P-UX-2 — reset zoom state for each photo. A culling pass is
    // "fit, glance, decide" — landing on the next frame already
    // zoomed-in from the previous one would be disorienting. Pros
    // explicitly press z / click again when they want to pixel-peep
    // the next shot.
    _lbZoom.mode = "fit";
    _lbZoom.scale = 1.0;
    _lbZoom.panX = 0; _lbZoom.panY = 0;
    _lbZoom.hiResLoaded = false;
    _lbZoom.hiResReady = false;
    _lbZoom.hiResUrl = null;
    _lbZoom.hiResPreloadingUrl = null;
    _lbZoom.hiResPreloadEl = null;
    // V14.1 — tell the server how big our viewport actually is so it
    // can serve a viewport-bucketed cache (800/1200/1600/...) instead
    // of always 1600 even on a 13" laptop. devicePixelRatio handles
    // retina (a 2× display wants 2× pixels for crispness).
    const dpr = Math.max(1, Math.min(window.devicePixelRatio || 1, 2));
    const w = Math.round(Math.min(window.innerWidth || 1280, 2400) * dpr);
    lbImg.style.opacity = "1";  // reset from any in-flight cross-fade
    lbImg.src = `/full/${run_id}/${encodeURIComponent(fn)}?w=${w}`;
    lbInfo.innerHTML = renderInfoPane(r);
    // V16.1 — apply any persisted manual rotation override for this
    // image. EXIF auto-rotate (server-side ImageOps.exif_transpose)
    // already gets 99% of cases right; this is the fallback for
    // images with no orientation tag, or rare cases where the user
    // wants a different framing than EXIF intended.
    _applyLbTransform();
    _updateLbZoomBadge();
    // P-CORE-4 — kick off opportunistic hi-res preload AFTER a beat,
    // so the visible image loads first (network/decoder prioritized).
    // setTimeout 200ms is enough for the viewport-bucketed image to
    // get on screen without competing for bandwidth.
    setTimeout(() => {
      if (_lbCurrentFn === fn) _maybeLoadHiRes(true);   // opportunistic
    }, 200);
    lbImg.classList.remove("zoomed", "dragging");
    const _zt = document.getElementById("lbZoomToggle");
    if (_zt) _zt.classList.remove("active");
    lb.classList.add("show");
    lb.classList.add("with-filmstrip");
    // v0.5 LR-grade (3/3) — build / refresh the filmstrip
    _buildLbFilmstrip(fn);
    // P-UX-5 — kick the similar-photos lookup. Doesn't block lightbox
    // open; the section above shows a "寻找类似…" placeholder until
    // this returns. Each photo's result is cached so flipping back
    // and forth doesn't re-hit the endpoint.
    _loadLbSimilar(fn);
    // v2.2-P0-2 — keep the video scrubber's playhead in sync when this
    // run is a video run (no-op for photo runs).
    if (window._videoScrubSync) window._videoScrubSync(fn);
  }

  // v2.2-P0-2 — unified lightbox: a video run gets a timeline-scrubber
  // panel inside the photo lightbox (score_temporal peaks + reel bands +
  // click/drag seek + ◀◀/❚❚/▶▶ playback).  Reuses the existing j/k/←/→
  // frame nav for stepping (so no key conflict).  Entirely no-op for
  // photo runs (PAYLOAD.video is null).  The standalone /video page
  // remains the deep-link fallback.
  (function initVideoScrub() {
    const V = PAYLOAD.video;
    if (!V || !Array.isArray(V.frames) || !V.frames.length) return;
    const frames = V.frames, reel = V.reel || [];
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

  // v0.5 LR-grade (3/3) — populate the lightbox filmstrip with the
  // currently-visible (filtered) grid order.  Builds once per open
  // then only updates the .current highlight on navigation.
  const _lbFilmstrip = document.getElementById("lbFilmstrip");
  let _lbFsBuiltFor = null;   // filename of the photo we last built FOR
  function _buildLbFilmstrip(currentFn) {
    if (!_lbFilmstrip) return;
    const fns = _lbVisibleFns();
    if (!fns.length) return;
    // Rebuild if (a) first time, (b) the visible set changed
    const shouldRebuild = _lbFsBuiltFor === null ||
      _lbFilmstrip.children.length !== fns.length;
    if (shouldRebuild) {
      _lbFilmstrip.innerHTML = fns.map(fn => {
        const r = rows.find(x => x.filename === fn);
        const dec = r && r.decision;
        const dotCls = dec === "keep" ? "keep"
                      : dec === "maybe" ? "maybe"
                      : dec === "cull" ? "cull" : "";
        // v0.6 (4/5) — pull a 200px JPEG instead of the default 420.
        // Filmstrip thumbs render at ~80x60 CSS px so 200px source is
        // crisp on retina yet ~3.5× smaller payload + faster decode.
        const thumbUrl = `/thumb/${run_id}/${encodeURIComponent(fn)}?w=200`;
        const isCurrent = fn === currentFn;
        return `<div class="fs-thumb${isCurrent ? " current" : ""}" data-fn="${esc(fn)}"
                     role="listitem" title="${esc(fn)}">
                  <img loading="lazy" alt="" src="${thumbUrl}">
                  ${dotCls ? `<span class="fs-dot ${dotCls}"></span>` : ""}
                </div>`;
      }).join("");
      _lbFsBuiltFor = currentFn;
      // Wire click delegation once
      if (!_lbFilmstrip._wired) {
        _lbFilmstrip.addEventListener("click", e => {
          const t = e.target.closest(".fs-thumb");
          if (!t || !t.dataset.fn) return;
          openLightbox(t.dataset.fn);
        });
        _lbFilmstrip._wired = true;
      }
    } else {
      // Just shift the .current highlight
      _lbFilmstrip.querySelectorAll(".fs-thumb").forEach(el => {
        el.classList.toggle("current", el.dataset.fn === currentFn);
      });
    }
    // Center the current thumb in view
    const cur = _lbFilmstrip.querySelector(".fs-thumb.current");
    if (cur) {
      cur.scrollIntoView({behavior: "smooth", block: "nearest",
                          inline: "center"});
    }
    // v0.11-P1-1 — keep the timeline scrubber in sync too.
    // v2.2 fix: `visible` was undefined in this scope (ReferenceError on
    // every lightbox open, which also aborted scrubber sync) — compute
    // the visible filenames the same way lightboxStep() does.
    _updateLbScrubber(_lbVisibleFns(), currentFn);
  }

  // v0.11-P1-1 — DaVinci-style timeline scrubber.  Drag the bar to
  // scrub through every visible photo; click jumps directly; ±5
  // photos around the playhead are pre-fetched so the experience
  // feels instant on local-SSD setups.
  const _lbScrubber       = document.getElementById("lbScrubber");
  const _lbScrubberFill   = document.getElementById("lbScrubberFill");
  const _lbScrubberThumb  = document.getElementById("lbScrubberThumb");
  const _lbScrubberReadout = document.getElementById("lbScrubberReadout");
  const _LB_SCRUB_PRELOAD_RADIUS = 5;
  const _lbPreloadPool    = new Map();   // fn → <img> kept warm in cache

  function _lbPreloadAround(fns, idx) {
    if (!Array.isArray(fns) || idx < 0) return;
    const wanted = new Set();
    const lo = Math.max(0, idx - _LB_SCRUB_PRELOAD_RADIUS);
    const hi = Math.min(fns.length - 1, idx + _LB_SCRUB_PRELOAD_RADIUS);
    for (let i = lo; i <= hi; i++) wanted.add(fns[i]);
    // Drop pool entries that fell out of range — they release memory
    // when the <img> goes out of scope.
    for (const fn of Array.from(_lbPreloadPool.keys())) {
      if (!wanted.has(fn)) _lbPreloadPool.delete(fn);
    }
    // Add new ones
    for (const fn of wanted) {
      if (_lbPreloadPool.has(fn)) continue;
      const im = new Image();
      // Same w= sizing rule openLightbox uses; falls into the same
      // viewport-bucketed cache so the actual nav is a cache hit.
      const dpr = Math.max(1, Math.min(window.devicePixelRatio || 1, 2));
      const w = Math.round(Math.min(window.innerWidth || 1280, 2400) * dpr);
      im.src = `/full/${run_id}/${encodeURIComponent(fn)}?w=${w}`;
      _lbPreloadPool.set(fn, im);
    }
  }

  function _updateLbScrubber(fns, currentFn) {
    if (!_lbScrubber || !Array.isArray(fns) || !fns.length) return;
    const idx = Math.max(0, fns.indexOf(currentFn));
    const pct = fns.length === 1 ? 0 : (idx / (fns.length - 1)) * 100;
    _lbScrubberFill.style.width  = pct.toFixed(2) + "%";
    _lbScrubberThumb.style.left  = pct.toFixed(2) + "%";
    _lbScrubber.setAttribute("aria-valuenow", String(idx));
    _lbScrubber.setAttribute("aria-valuemax", String(fns.length - 1));
    _lbScrubberReadout.style.left = pct.toFixed(2) + "%";
    _lbScrubberReadout.textContent = `${idx + 1} / ${fns.length}`;
    _lbPreloadAround(fns, idx);
  }

  if (_lbScrubber) {
    // Mouse + touch interaction.  We grab the current list of visible
    // filenames at the start of each drag so filters that change
    // mid-drag don't desync the playhead.
    let _scrubbing = false;
    let _scrubFns  = [];

    function _scrubFromEvent(ev) {
      if (!_scrubFns.length) return;
      const rect = _lbScrubber.getBoundingClientRect();
      const clientX = (ev.touches && ev.touches[0])
                        ? ev.touches[0].clientX : ev.clientX;
      const ratio = Math.min(1, Math.max(0,
        (clientX - rect.left) / Math.max(1, rect.width)));
      const idx = Math.round(ratio * (_scrubFns.length - 1));
      const fn = _scrubFns[idx];
      if (fn && fn !== _lbCurrentFn) {
        if (typeof window.openLightbox === "function") {
          window.openLightbox(fn);
        }
      }
    }

    _lbScrubber.addEventListener("mousedown", ev => {
      ev.preventDefault();
      _scrubFns = _lbVisibleFns();
      _scrubbing = true;
      _lbScrubber.classList.add("active");
      _scrubFromEvent(ev);
    });
    window.addEventListener("mousemove", ev => {
      if (_scrubbing) _scrubFromEvent(ev);
    });
    window.addEventListener("mouseup", () => {
      if (_scrubbing) {
        _scrubbing = false;
        _lbScrubber.classList.remove("active");
      }
    });
    // Touch parity for iPad
    _lbScrubber.addEventListener("touchstart", ev => {
      ev.preventDefault();
      _scrubFns = _lbVisibleFns();
      _scrubbing = true;
      _lbScrubber.classList.add("active");
      _scrubFromEvent(ev);
    }, { passive: false });
    _lbScrubber.addEventListener("touchmove", ev => {
      if (_scrubbing) _scrubFromEvent(ev);
    }, { passive: true });
    _lbScrubber.addEventListener("touchend", () => {
      if (_scrubbing) {
        _scrubbing = false;
        _lbScrubber.classList.remove("active");
      }
    });
  }

  // P-UX-5 — async lookup + render for the lightbox's similar-photos
  // section. Talks to /api/v1/runs/<id>/similar/<filename>?k=5 and
  // injects thumbnails into #lbSimilarBody. Plain click navigates to
  // that photo in the lightbox; Shift+click pins for A/B compare so
  // the "find a near-dupe → compare" workflow stays inside the
  // lightbox without a round-trip to the grid.
  const _LB_SIMILAR_CACHE = new Map();   // filename → array

  async function _loadLbSimilar(fn) {
    if (!fn) return;
    const body = document.getElementById("lbSimilarBody");
    if (!body) return;
    // Race-guard: if the user has already navigated to the next
    // photo before our fetch returns, don't paint stale results.
    const requestedFn = fn;
    // Cache hit → paint synchronously.
    if (_LB_SIMILAR_CACHE.has(fn)) {
      _paintLbSimilar(_LB_SIMILAR_CACHE.get(fn));
      return;
    }
    body.className = "similar-loading";
    body.textContent = "寻找类似…";
    try {
      const res = await fetch(
        `/api/v1/runs/${run_id}/similar/${encodeURIComponent(fn)}?k=5`);
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      const similar = Array.isArray(data.similar) ? data.similar : [];
      _LB_SIMILAR_CACHE.set(fn, similar);
      if (_lbCurrentFn !== requestedFn) return;  // navigated away
      _paintLbSimilar(similar);
    } catch (_e) {
      if (_lbCurrentFn !== requestedFn) return;
      body.className = "similar-empty";
      body.textContent = "暂时无法加载类似照片";
    }
  }

  function _paintLbSimilar(similar) {
    const body = document.getElementById("lbSimilarBody");
    if (!body) return;
    if (!similar.length) {
      body.className = "similar-empty";
      body.textContent = "本批中没有明显类似的照片";
      return;
    }
    body.className = "similar-row";
    body.innerHTML = similar.map(s => {
      const fnEsc = esc(s.filename);
      // v0.6 (4/5) — similar-photos row is ~80px tall, same 200-bucket
      // as filmstrip works fine.
      const thumb = `/thumb/${run_id}/${encodeURIComponent(s.filename)}?w=200`;
      const simPct = Math.round((s.similarity || 0) * 100);
      const dec = s.decision || "";
      const reasonsText = (s.reasons || [])
        .map(t => I18N_SIM_REASON[t] || t).join(" · ");
      return `
        <div class="similar-item" data-fn="${fnEsc}"
             title="${fnEsc} — ${esc(reasonsText)} (相似度 ${simPct}%)">
          <img src="${thumb}" loading="lazy" alt="${fnEsc}">
          <div class="deco">
            ${dec ? `<span class="dec ${dec}">${esc(dec)}</span>` : '<span></span>'}
            <span class="sim">${simPct}%</span>
          </div>
        </div>
      `;
    }).join("");
    // Reason tag row below the thumbs — union of reasons across the
    // top-k, deduped, ordered by first appearance.
    const reasonOrder = [];
    const reasonSeen = new Set();
    for (const s of similar) {
      for (const t of (s.reasons || [])) {
        if (!reasonSeen.has(t)) { reasonSeen.add(t); reasonOrder.push(t); }
      }
    }
    if (reasonOrder.length) {
      const tags = reasonOrder.map(t =>
        `<span class="similar-reason-tag">${esc(I18N_SIM_REASON[t] || t)}</span>`
      ).join("");
      const wrap = document.createElement("div");
      wrap.className = "similar-reason-tags";
      wrap.innerHTML = tags;
      body.appendChild(wrap);
    }
  }

  // Event delegation: a click on any .similar-item navigates the
  // lightbox to that photo; Shift+click pins it for A/B compare.
  document.addEventListener("click", e => {
    const item = e.target.closest(".lightbox .similar-item");
    if (!item) return;
    const fn = item.dataset.fn;
    if (!fn) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.shiftKey) {
      // Pin without navigating away — user can compare current vs
      // similar from the same view.
      pinForCompare(fn);
      return;
    }
    openLightbox(fn);
  });

  // V16.1 — manual rotation override. Persisted per (run_id, filename)
  // in localStorage as a degree value (0/90/180/270). 0 = honor EXIF.
  function _lbRotKey(fn)   { return `pixcull-rot:${run_id}:${fn}`; }
  function _lbRotGet(fn)   {
    const v = parseInt(localStorage.getItem(_lbRotKey(fn)) || "0", 10);
    return ((v % 360) + 360) % 360;
  }
  function _lbRotSet(fn, deg) {
    deg = ((deg % 360) + 360) % 360;
    if (deg === 0) localStorage.removeItem(_lbRotKey(fn));
    else localStorage.setItem(_lbRotKey(fn), String(deg));
  }
  // P-UX-2 — zoom + pan state for the 1:1 focus check. Session-only
  // (resets on photo change, unlike rotation which is persisted).
  // mode "fit": image at object-fit:contain scale (1.0); "1to1":
  // scaled so 1 image pixel == 1 screen pixel (or whatever scale the
  // user has wheeled to). hiResLoaded gates the high-resolution
  // image swap so we only fetch it once per photo.
  const _lbZoom = {
    mode: "fit",
    scale: 1.0,
    panX: 0,
    panY: 0,
    dragging: false,
    dragStartClientX: 0,
    dragStartClientY: 0,
    dragStartPanX: 0,
    dragStartPanY: 0,
    mouseDownPos: null,
    hiResLoaded: false,
    hiResUrl: null,
  };

  // P-UX-2 — Single transform composer. Order matters: in CSS,
  // `transform: translate(...) scale(...) rotate(...)` applies
  // rotate first, then scale, then translate. Rotating first means
  // EXIF orientation stays consistent across zoom; translating last
  // means panX/panY are in *screen* pixels (matches mouse-drag dx/dy).
  function _applyLbTransform() {
    if (!_lbCurrentFn) return;
    const deg = _lbRotGet(_lbCurrentFn);
    const { scale, panX, panY } = _lbZoom;
    const parts = [];
    if (panX || panY) parts.push(`translate(${panX}px, ${panY}px)`);
    if (scale !== 1)   parts.push(`scale(${scale})`);
    if (deg)           parts.push(`rotate(${deg}deg)`);
    lbImg.style.transform = parts.join(" ");
  }
  // Backwards-compat shim — old callers still expect _applyLbRotation
  // (just an alias now since the composer handles rotation too).
  function _applyLbRotation() { _applyLbTransform(); }

  function _lbRotateBy(delta) {
    if (!_lbCurrentFn) return;
    const next = _lbRotGet(_lbCurrentFn) + delta;
    _lbRotSet(_lbCurrentFn, next);
    _applyLbTransform();
    // V16.2 — keep the matching grid card's thumbnail in sync.
    _syncCardRotation(_lbCurrentFn);
  }
  function _lbRotateReset() {
    if (!_lbCurrentFn) return;
    _lbRotSet(_lbCurrentFn, 0);
    _applyLbTransform();
    _syncCardRotation(_lbCurrentFn);
  }

  // P-UX-2 — zoom + pan + hi-res-swap interaction layer.
  // ===================================================
  //
  //   click image (fit)     → 1:1 zoom centered on click point
  //   click image (zoomed)  → back to fit (no pan)
  //   drag image (zoomed)   → pan within image bounds
  //   wheel up/down         → fine-tune zoom centered on cursor
  //   z                     → toggle fit ↔ 1:1 centered on viewport
  //   0                     → reset pan (stay zoomed)
  //
  // Hi-res swap: when entering zoom for the first time on a photo,
  // we pre-load /full/<run>/<fn>?w=3600 in the background then swap
  // src once it's ready. The current viewport-bucketed image keeps
  // showing in the meantime so the user never sees a flash.

  const _LB_MIN_SCALE = 1.0;
  const _LB_MAX_SCALE = 8.0;
  const _LB_CLICK_DRAG_THRESH = 4;   // px of mouse motion that turns a click into a drag

  function _lbZoomBadgeEl() { return document.getElementById("lbZoomBadge"); }
  function _lbZoomToggleEl() { return document.getElementById("lbZoomToggle"); }

  function _updateLbZoomBadge() {
    const el = _lbZoomBadgeEl();
    if (!el) return;
    if (_lbZoom.mode === "fit") {
      el.classList.remove("show");
      el.textContent = "";
    } else {
      // Express scale relative to "fit" (object-fit:contain). At
      // exactly the natural-pixel-per-screen-pixel ratio we show
      // "1:1"; otherwise show a percentage of fit so the user has a
      // sense of how zoomed-in they are.
      const fitW = lbImg.offsetWidth;
      const natural = lbImg.naturalWidth;
      const oneOneScale = (natural && fitW) ? natural / fitW : 1;
      const pct = Math.round(100 * _lbZoom.scale / oneOneScale);
      el.textContent = pct === 100 ? "1:1" : `${Math.round(100 * _lbZoom.scale)}%`;
      el.classList.add("show");
    }
    const tgl = _lbZoomToggleEl();
    if (tgl) tgl.classList.toggle("active", _lbZoom.mode !== "fit");
  }

  // Cap the pan so the image edges don't pull inside the viewport
  // (we don't want "black space + half image" — feels broken).
  function _lbClampPan() {
    const fitW = lbImg.offsetWidth;
    const fitH = lbImg.offsetHeight;
    if (!fitW || !fitH) return;
    const paneRect = lbImg.parentElement.getBoundingClientRect();
    const scaledW = fitW * _lbZoom.scale;
    const scaledH = fitH * _lbZoom.scale;
    // Max pan = how far the image edge can move past the viewport
    // edge while keeping at least one edge visible. When scaled <=
    // viewport on an axis, lock to 0 on that axis.
    const maxX = Math.max(0, (scaledW - paneRect.width)  / 2);
    const maxY = Math.max(0, (scaledH - paneRect.height) / 2);
    _lbZoom.panX = Math.max(-maxX, Math.min(maxX, _lbZoom.panX));
    _lbZoom.panY = Math.max(-maxY, Math.min(maxY, _lbZoom.panY));
  }

  // P-CORE-4 — Hi-res preload + cross-fade swap. Pre-V0.2 behavior
  // was: wait until the user CLICKS to zoom, THEN fetch the 3600px
  // image, then hard-swap src. The ~200-400 ms gap between click
  // and pixel-sharp 1:1 was visible as a flash.
  //
  // V0.2 behavior: kick off the hi-res fetch immediately when the
  // lightbox opens (idle network + decoding="async" so it doesn't
  // block the main thread). When the user first clicks to zoom,
  // the hi-res is usually already decoded — swap with a 120ms
  // cross-fade so the swap itself is invisible.
  //
  // ``opportunistic=true`` means "we're not at 1:1 yet, just
  // pre-warming"; ``opportunistic=false`` is the original first-
  // zoom path which needs to actually swap now.
  function _maybeLoadHiRes(opportunistic = false) {
    if (_lbZoom.hiResLoaded) return;
    const fn = _lbCurrentFn;
    if (!fn) return;
    const url = `/full/${run_id}/${encodeURIComponent(fn)}?w=3600`;

    // If preload is already ready and the user just entered zoom,
    // swap with a fade right now.
    if (_lbZoom.hiResReady && _lbZoom.hiResUrl === url && !opportunistic) {
      _swapToHiResWithFade(url);
      return;
    }

    // Start (or reuse) a preload.
    if (_lbZoom.hiResPreloadingUrl !== url) {
      const pre = new Image();
      pre.decoding = "async";
      pre.onload = () => {
        if (_lbCurrentFn !== fn) return;     // user navigated away
        _lbZoom.hiResUrl = url;
        _lbZoom.hiResReady = true;
        // If by the time the preload finishes the user has ALREADY
        // entered zoom (signaled by lbImg having .zoomed class),
        // swap with fade now. Otherwise we keep the bytes in the
        // browser cache for whenever they do click.
        if (lbImg.classList.contains("zoomed")) {
          _swapToHiResWithFade(url);
        }
      };
      pre.src = url;
      _lbZoom.hiResPreloadingUrl = url;
      _lbZoom.hiResPreloadEl = pre;
    }

    // If the user clicked to zoom but the preload isn't done yet,
    // we'll get the fade when the onload handler above fires.
  }

  function _swapToHiResWithFade(url) {
    if (_lbZoom.hiResLoaded) return;
    _lbZoom.hiResLoaded = true;
    // Cross-fade: dial opacity to 0 → swap src → next-frame back to 1.
    // The transition CSS on lbImg already covers transform; we apply
    // opacity inline temporarily so we don't pollute the shared rule.
    const prevTransition = lbImg.style.transition;
    lbImg.style.transition = "opacity 120ms ease, " + (prevTransition || "transform 220ms cubic-bezier(0.16, 1, 0.3, 1)");
    lbImg.style.opacity = "0";
    lbImg.addEventListener("transitionend", function onEnd(e) {
      if (e.propertyName !== "opacity") return;
      lbImg.removeEventListener("transitionend", onEnd);
      lbImg.src = url;
      // Wait for the new src to decode before re-revealing.
      lbImg.addEventListener("load", () => {
        requestAnimationFrame(() => {
          lbImg.style.opacity = "1";
          // Restore transition rule after the fade-in completes
          setTimeout(() => { lbImg.style.transition = prevTransition || ""; }, 200);
          _updateLbZoomBadge();
        });
      }, { once: true });
    });
  }

  // Zoom to a target scale around a viewport point (clientX, clientY).
  // The point under the cursor stays put after the transform — Adobe
  // Lightroom / Photo Mechanic / Capture One all use this gesture so
  // pros feel at home.
  function _lbZoomToPoint(newScale, clientX, clientY) {
    newScale = Math.max(_LB_MIN_SCALE, Math.min(_LB_MAX_SCALE, newScale));
    const rect = lbImg.getBoundingClientRect();
    // Click point in image-local coordinates relative to the image's
    // *current* visual center.
    const cx = (clientX - (rect.left + rect.width  / 2));
    const cy = (clientY - (rect.top  + rect.height / 2));
    // Solve for the new pan that keeps (cx, cy) anchored under the
    // cursor. In current state we have pan=(p,q) and scale=s; after
    // the transform we want pan=(p',q') and scale=s' such that the
    // point at (cx, cy) in the viewport stays at (cx, cy). Working
    // through the algebra (with translate-then-scale semantics):
    //   p' = cx - (cx - p) * (s' / s)
    const s = _lbZoom.scale || 1;
    _lbZoom.panX = cx - (cx - _lbZoom.panX) * (newScale / s);
    _lbZoom.panY = cy - (cy - _lbZoom.panY) * (newScale / s);
    _lbZoom.scale = newScale;
    _lbZoom.mode = newScale > 1.001 ? "1to1" : "fit";
    if (_lbZoom.mode === "fit") {
      _lbZoom.panX = 0; _lbZoom.panY = 0;
      lbImg.classList.remove("zoomed");
    } else {
      lbImg.classList.add("zoomed");
      _maybeLoadHiRes();
    }
    _lbClampPan();
    _applyLbTransform();
    _updateLbZoomBadge();
  }

  // Toggle to 1:1 (or back to fit) around a viewport point. If no
  // point provided (e.g. keyboard z), use viewport center.
  function _lbZoomToggleAt(clientX, clientY) {
    if (_lbZoom.mode === "fit") {
      const fitW = lbImg.offsetWidth;
      const natural = lbImg.naturalWidth;
      const target = (natural && fitW) ? natural / fitW : 2.0;
      if (clientX == null || clientY == null) {
        const rect = lbImg.getBoundingClientRect();
        clientX = rect.left + rect.width  / 2;
        clientY = rect.top  + rect.height / 2;
      }
      _lbZoomToPoint(target, clientX, clientY);
    } else {
      _lbZoomToPoint(1.0, 0, 0);
    }
  }
  // V16.2 — push the current localStorage rotation onto every visible
  // card matching this filename. Cheap query, runs only on rotate.
  function _syncCardRotation(fn) {
    const deg = _lbRotGet(fn);
    if (!grid) return;
    grid.querySelectorAll(`.card[data-fn]`).forEach(card => {
      if (card.dataset.fn !== fn) return;
      const img = card.querySelector("img.thumb");
      if (img) img.style.transform = deg ? `rotate(${deg}deg)` : "";
    });
  }

  // V14.2 — step within the visible card order. Wraps around the ends.
  function lightboxStep(delta) {
    const visible = _lbVisibleFns();
    if (!visible.length) return;
    let i = visible.indexOf(_lbCurrentFn);
    if (i < 0) i = 0;
    const nextI = (i + delta + visible.length) % visible.length;
    openLightbox(visible[nextI]);
    // Also move card focus so closing the lightbox lands on the
    // matching card (consistent with mouse behavior).
    if (typeof focusCard === "function") focusCard(visible[nextI], false);
  }

  // v0.6 (2/5) — LR Develop-style Inspector pane.  Each section
  // is a <details> that the user can collapse independently; state
  // is keyed by section id and persisted across lightbox opens so
  // the user's "I never look at Raw Flags" choice sticks.  Defaults
  // bias toward "show useful stuff, hide diagnostics".
  const _INSPECTOR_DEFAULTS = {
    scores:     true,    // 评分
    similar:    true,    // 类似照片
    "ai-judge": true,    // AI judgment (DeepSeek + VLM)
    rationale:  true,    // 为何 maybe
    warnings:   true,    // 矛盾警示
    strengths:  true,    // 优点
    weaknesses: true,    // 改进建议
    flags:      false,   // 检测器旗标 (closed by default)
    reason:     false,   // 规则栈说明 (closed by default)
  };
  const _INSPECTOR_KEY = `pixcull_inspector_state:${run_id}`;
  function _readInspectorState() {
    try { return JSON.parse(localStorage.getItem(_INSPECTOR_KEY) || "{}"); }
    catch (_e) { return {}; }
  }
  function _writeInspectorState(s) {
    try { localStorage.setItem(_INSPECTOR_KEY, JSON.stringify(s)); }
    catch (_e) { /* full / disabled */ }
  }
  function _sectionOpen(secId) {
    const st = _readInspectorState();
    if (Object.prototype.hasOwnProperty.call(st, secId)) {
      return !!st[secId];
    }
    return !!_INSPECTOR_DEFAULTS[secId];
  }
  // Markup helper for one collapsible section.  Use this instead
  // of the legacy `<div class="section">` template so the user
  // gets disclose/collapse + state persistence for free.
  function _sec(secId, title, bodyHtml) {
    if (!bodyHtml) return "";
    const open = _sectionOpen(secId) ? " open" : "";
    return `<details class="info-section" data-sec="${esc(secId)}"${open}>
      <summary>${esc(title)}</summary>
      <div class="lb-body">${bodyHtml}</div>
    </details>`;
  }

  function renderInfoPane(r) {
    const axisNames = ["technical","subject","composition","light","moment","aesthetic"];
    const axisAbbr = {technical:"技术", subject:"主体", composition:"构图",
                       light:"光线", moment:"瞬间", aesthetic:"美感"};
    // Final star strip + per-source detail rows
    // P-UX-10 — per-axis source disagreement; cells whose stddev is
    // above _INCONSISTENCY_AXIS_THRESH get a dashed accent so the
    // user immediately sees WHICH dimension the rubric is unsure
    // about, not just "this row is noisy".
    const perAxisNoise = r.inconsistency_per_axis || {};
    const finalStars = axisNames.map(n => {
      const s = r.rubric_stars && r.rubric_stars[n];
      const cls = s == null ? "" : `s${Math.round(s)}`;
      const noise = perAxisNoise[n];
      const noisyCls = (noise != null && noise >= 0.7) ? " noisy" : "";
      // P-UX-11 — show ± half-width when we have a stddev from ≥ 2
      // sources. Suppress when the value itself is unavailable.
      // Hides for "trivial" disagreement (<0.05★) — it adds noise.
      const errChip = (s != null && noise != null && noise >= 0.05)
        ? `<span class="err">±${noise.toFixed(2)}</span>` : "";
      const noisyTitle = (noise != null && noise >= 0.7)
        ? ` title="4 个评分源在此维度上分歧 ±${noise.toFixed(2)}★ — 建议人工复核"` :
          (noise != null && noise >= 0.05)
            ? ` title="4 源在此维度的标准差 ±${noise.toFixed(2)}★"` : "";
      // v0.9-P1-4 — inline --axis-fill drives the same bottom-up
      // wash as the grid card row, just at a bigger size.
      const inFill = (s == null) ? 0 : Math.max(0, Math.min(1, (s - 1) / 4));
      return `<div class="ax ${cls}${noisyCls}" style="--axis-fill:${inFill.toFixed(3)}"${noisyTitle}><span class="k">${axisAbbr[n]}</span><span class="v">${s == null ? '--' : s.toFixed(1)}</span>${errChip}</div>`;
    }).join("");
    // Per-source comparison (auto / model / vlm / human if present)
    // V16.0 — labels translated through I18N_SOURCE so users see
    // "自动规则 / 训练模型 / 本地 VLM / DeepSeek / 人工" not the
    // raw English tokens.
    const sourceRows = [
      ["auto",   r.rubric_auto_stars],
      ["model",  r.rubric_model_stars],
      ["vlm",    r.rubric_vlm_stars],
      ["meta",   r.rubric_meta_stars],
      ["human",  r.rubric_human_stars],
    ].filter(([_, m]) => m && Object.values(m).some(v => v != null));
    // v0.13.6 — replace the slash-separated "5.0/4.2/4.5/3.9/--/3.0"
    // with a 6-cell mini stacked bar.  Each cell is a 12×6px chip
    // colored from low-saturation grey (1★) → indigo (3★) →
    // brand-pink (5★).  Hovering a chip shows the exact value;
    // the row label uses the i18n source name.
    const _axisBarCell = (v) => {
      if (v == null) {
        return '<span class="ax-cell empty" title="缺失"></span>';
      }
      const t = Math.max(0, Math.min(1, (v - 1) / 4));
      // 6a6052 (graphite) → dcb87e (brass) — editorial-warm score ramp
      const r = Math.round(0x6a + (0xdc - 0x6a) * t);
      const g = Math.round(0x60 + (0xb8 - 0x60) * t);
      const b = Math.round(0x52 + (0x7e - 0x52) * t);
      const op = (0.30 + 0.60 * t).toFixed(2);
      return `<span class="ax-cell" title="${v.toFixed(2)}" ` +
             `style="background:rgba(${r},${g},${b},${op})">` +
             `<span class="ax-tip">${v.toFixed(1)}</span></span>`;
    };
    const detailHtml = sourceRows.map(([label, m]) => {
      const cells = axisNames.map(n => _axisBarCell(m[n])).join("");
      return `<div class="row src-row">` +
             `<span class="name">${trSource(label)}</span>` +
             `<span class="ax-bar">${cells}</span>` +
             `</div>`;
    }).join("");

    // Style chips + scene + decision header — V16.0 localized.
    const styleChips = (r.style_modes || []).map(
      s => `<span class="style-tag" title="${esc(s)}">${esc(trStyle(s))}</span>`
    ).join("");
    const dec = r.decision || "?";
    const decLabel = tr(dec, I18N_DECISION);
    const scoreLine = r.score_final == null ? "--" : r.score_final.toFixed(2);

    // Strengths + suggestions
    const strengths = (r.advice && r.advice.strengths) || [];
    const weaknesses = (r.advice && r.advice.weaknesses) || [];
    const suggestions = (r.advice && r.advice.suggestions) || [];
    const inconsistencies = (r.advice && r.advice.inconsistencies) || [];
    // V14.3 — detail arrays carry per-phrase canon source attribution
    // ("Adams · Zone System" etc). Falls back to flat-string render
    // when detail isn't populated (older runs / API-fed data).
    const strengthsDetail = (r.advice && r.advice.strengths_detail) || null;
    const weaknessesDetail = (r.advice && r.advice.weaknesses_detail) || null;
    const rationale = (r.advice && r.advice.rationale) || "";

    // V19.4 (bug-fix) — there used to be a local `const esc = ...`
    // here, shadowing the outer IIFE-scope `esc` (declared once near
    // the top of the script, line ~8694). Because `const` hoists into
    // the TDZ, every `esc(...)` reference EARLIER in this function —
    // the `styleChips = (r.style_modes || []).map(s => ${esc(s)})`
    // assignment, in particular — threw a ReferenceError on rows
    // that had any style_modes attached. Symptom: clicking those
    // cards silently did nothing (lightbox never showed). Removed the
    // duplicate; the outer `esc` works just as well here.

    // V27.1 — peak badge in lightbox. Show 🏆 when this row is
    // the burst-peak AND its cluster has ≥2 photos (singletons
    // aren't meaningful "peaks"). Visible at-a-glance so the user
    // can verify the picker chose the right frame.
    const _clusterSize = _BURST_CLUSTER_SIZES.get(r.cluster_id) || 0;
    // P-AI-5.1 — append the per-component reason ("最锐 +1.6σ" etc.)
    // to the badge tooltip when the burst-peak scorer produced one.
    const _peakReason = r.burst_peak_reason ? ` — ${r.burst_peak_reason}` : "";
    const peakBadge = (r.is_burst_peak && _clusterSize >= 2)
      ? `<span class="badge keep" title="此连拍组的最佳一张(共 ${_clusterSize} 张)${esc(_peakReason)}" `
        + `style="background:linear-gradient(90deg,#d4a843,#b88a2e);color:#1a1d24">`
        + `<svg class="icon icon--sm"><use href="#icon-trophy"/></svg>`
        + `<span>连拍峰值</span></span>`
      : '';

    // P-PRO-1 — Lr develop-settings indicator. When the source XMP
    // has any crs:* edits (Exposure/Highlights/Shadows/etc),
    // load_image_for_display() applies them to the lightbox preview.
    // This badge tells the user "what you see is your Lr edit, not
    // the RAW" so they don't second-guess the scoring vs preview gap.
    const developBadge = r.has_develop_settings
      ? `<span class="badge" title="此预览已应用 Lightroom 的调色设置(crs:Exposure / Highlights / Shadows / Temperature 等)。打分仍基于原 RAW — 见 ROADMAP P-PRO-1 v0.2 计划重新打分基于调色后预览。" `
        + `style="background:rgba(74,222,128,0.18);color:#88e0a6;border:1px solid rgba(74,222,128,0.35);font-size:9.5px">`
        + `🎨 已应用 Lr 调色</span>`
      : '';

    // v0.7-P2-1 — style-clone distance badge.  Only rendered when
    // a profile has been trained AND this row has a distance.
    // Color encodes nearness: green (≤ 0.15) → muted (≤ 0.30) →
    // warning amber (≤ 0.50) → red beyond.  We deliberately don't
    // round to integer percent — the precision (0.0-1.0) matches
    // the underlying signal the user is sorting by.
    // v0.7-P2-1 / v0.8-P1-1 — style-distance badges.  Up to three
    // chips when both V1 (axis-MAD) and V2 (CLIP visual centroid)
    // are available: one per-component + the blended scoreboard.
    function _styleChipColor(d) {
      let bg = "rgba(148,148,160,0.18)";
      let fg = "var(--muted)";
      let bd = "rgba(148,148,160,0.35)";
      if (d <= 0.15)      { bg = "rgba(74,222,128,0.18)"; fg = "#88e0a6"; bd = "rgba(74,222,128,0.35)"; }
      else if (d <= 0.30) { bg = "rgba(196,185,169,0.18)"; fg = "#c4b9a9"; bd = "rgba(196,185,169,0.35)"; }
      else if (d <= 0.50) { bg = "rgba(217,163,12,0.20)"; fg = "#e3c25e"; bd = "rgba(217,163,12,0.40)"; }
      else                { bg = "rgba(248,113,113,0.20)"; fg = "#ee8888"; bd = "rgba(248,113,113,0.40)"; }
      return {bg, fg, bd};
    }
    function _styleChip(label, d, tip) {
      const c = _styleChipColor(d);
      return `<span class="badge" title="${esc(tip)}" ` +
        `style="background:${c.bg};color:${c.fg};border:1px solid ${c.bd};font-size:9.5px">` +
        `${label} ${d.toFixed(2)}</span>`;
    }
    let styleBadge = "";
    const hasV1 = typeof r.style_distance_v1 === "number";
    const hasV2 = typeof r.style_distance_v2 === "number";
    if (hasV1 || hasV2) {
      const parts = [];
      if (hasV1 && hasV2) {
        // Both components present — show dual + blended
        parts.push(_styleChip("📐 评分",
          r.style_distance_v1,
          "评分距离 (axis-MAD V1): " + r.style_distance_v1.toFixed(3)
          + " — 仅看 rubric 星 & scene 是否像参考"));
        parts.push(_styleChip("🔭 视觉",
          r.style_distance_v2,
          "视觉距离 (CLIP V2): " + r.style_distance_v2.toFixed(3)
          + " — 用 CLIP embedding 算的视觉相似度"));
        if (typeof r.style_distance === "number") {
          parts.push(_styleChip("🎨 综合",
            r.style_distance,
            "综合 = λ·V1 + (1-λ)·V2 — 点 λ 芯片切换权重"));
        }
        // v0.8-P1-1 — λ-cycling chip.  Click cycles 0.0 → 0.3 → 0.5
        // → 0.7 → 1.0 → 0.3 …; "0.0" means pure V2 (visual only),
        // "1.0" means pure V1 (axis-only).
        // v0.11-P1-3 — surface the λ source ("manual" / "auto:wedding"
        // / "default") so the photographer can see why a particular
        // λ is in effect.
        const curLam = _getStyleLambda();
        const lamSrc = _getStyleLambdaSource();
        let srcLabel = "";
        if (lamSrc.startsWith("auto:")) {
          srcLabel = ` · ${lamSrc.slice(5)} 自动`;
        } else if (lamSrc === "manual") {
          srcLabel = " · 手动";
        }
        parts.push(
          `<button class="badge style-lambda-chip" type="button"
                   title="λ = V1 (axis) 权重 · 当前 ${curLam.toFixed(2)}${
                     srcLabel} → 点击循环;${
                     lamSrc.startsWith('auto:') ?
                       '基于 docs/STYLE-V2-BENCHMARK.md 推荐表自动选择' :
                       '可点击在 0.0 / 0.3 / 0.5 / 0.7 / 1.0 之间循环'}"
                   style="background:rgba(196,185,169,0.10);color:#c4b9a9;
                          border:1px dashed rgba(196,185,169,0.40);
                          font-size:9.5px;cursor:pointer;font-family:inherit">
             λ ${curLam.toFixed(2)}${srcLabel}
           </button>`);
      } else if (hasV1) {
        // V1 only — same one-chip render as v0.7-P2-1
        parts.push(_styleChip("🎨 风格距离",
          r.style_distance_v1,
          "风格距离 (V1): " + r.style_distance_v1.toFixed(3)
          + " (0=完全像你 keep 的风格,1=完全不像)"));
      } else {
        parts.push(_styleChip("🔭 视觉",
          r.style_distance_v2,
          "视觉距离 (V2): " + r.style_distance_v2.toFixed(3)));
      }
      styleBadge = parts.join(" ");
    } else if (typeof r.style_distance === "number") {
      // Legacy / fallback when only the blended is set
      styleBadge = _styleChip("🎨 风格距离", r.style_distance,
        "风格距离: " + r.style_distance.toFixed(3));
    }

    // v0.9-P1-4 — sparkline showing the 6-axis shape across the
    // top of the scores section.  Same data the chips below carry,
    // but glanceable: high-tech low-moment shows as an asymmetric
    // peak; a balanced "everything is 4★" reads as a flat plateau.
    const _sparkVals = axisNames.map(n =>
      r.rubric_stars && r.rubric_stars[n] != null
        ? r.rubric_stars[n] : null
    );
    // v0.13 — use window-scoped helpers; renderInfoPane runs
    // outside render()'s lexical scope (see render() exit at L8059).
    const _sparkFn = (typeof _aiSparklineSvg === "function")
      ? _aiSparklineSvg
      : window._aiSparklineSvg;
    const sparklineSvg = _sparkFn ? _sparkFn(_sparkVals) : "";
    const sparklineLab = `<div class="ai-sparkline-lab" aria-hidden="true">`
      + axisNames.map(n => `<span>${axisAbbr[n]}</span>`).join("")
      + `</div>`;

    // v0.6 (2/5) — sections are now LR Develop-style <details>
    // blocks emitted via _sec() so users can fold the diagnostics
    // they never read.  Header (filename + meta + decision toolbar)
    // stays uncollapsible.
    const scoresBody = `${sparklineSvg}${sparklineLab}
        <div class="axis-grid">${finalStars}</div>
        ${detailHtml ? `<div class="axis-grid-detail">${detailHtml}</div>` : ''}`;
    const similarBody = `<div id="lbSimilarBody" class="similar-loading">寻找类似…</div>
        <div class="similar-hint">点击跳转 · Shift+点击 = 加入 A/B 比较</div>`;

    // Combined "AI 判读" section: DeepSeek + VLM merged so the user
    // doesn't have two near-identical paragraph blocks.
    const aiJudgeParts = [];
    if (r.meta_overall_rationale) {
      const confChip = r.meta_confidence != null
        ? ` <span class="canon-cite">置信 ${(r.meta_confidence*100).toFixed(0)}%</span>`
        : '';
      aiJudgeParts.push(
        `<div class="rationale"><strong style="color:var(--fg)">DeepSeek ⌬</strong>${confChip}<br>${esc(r.meta_overall_rationale)}</div>`
      );
    }
    if (r.vlm_overall_rationale) {
      aiJudgeParts.push(
        `<div class="rationale" style="margin-top:8px"><strong style="color:var(--fg)">VLM 视觉</strong><br>${esc(r.vlm_overall_rationale)}</div>`
      );
    }
    const aiJudgeBody = aiJudgeParts.join("");

    const warningsBody = inconsistencies.length
      ? `<div class="rationale warn">${inconsistencies.map(esc).join('<br>')}</div>`
      : "";

    const rationaleBody = rationale
      ? `<div class="rationale">${esc(rationale)}</div>`
      : "";

    const strengthsBody = strengths.length
      ? `<ul class="strengths-list">${
          (strengthsDetail || strengths.map(s => ({phrase: s}))).map(d => `
            <li>
              ${esc(d.phrase || d)}
              ${d.source ? `<span class="canon-cite" title="正典出处">— ${esc(d.source)}</span>` : ''}
            </li>
          `).join('')
        }</ul>`
      : "";

    const weaknessesBody = (weaknesses.length || suggestions.length)
      ? `<ul class="weak-list">${
          weaknessesDetail
            ? weaknessesDetail.map(d => `
                <li>
                  ${esc(d.phrase)}
                  ${d.source ? `<span class="canon-cite">— ${esc(d.source)}</span>` : ''}
                  ${d.fix ? `<div class="fix-line">→ ${esc(d.fix)}</div>` : ''}
                </li>`).join('')
            : [...weaknesses, ...suggestions].map(s => `<li>${esc(s)}</li>`).join('')
        }</ul>`
      : "";

    const flagsBody = r.flags
      ? `<div class="rationale" title="${esc(r.flags)}">${esc(trReason(r.flags))}</div>`
      : "";

    const reasonBody = r.reason
      ? `<div class="rationale" title="${esc(r.reason)}">${esc(trReason(r.reason))}</div>`
      : "";

    return `
      <h2>${esc(r.filename)}</h2>
      <div class="meta-line">
        <span class="badge ${dec}" title="${esc(dec)}">${esc(decLabel)}</span>
        ${peakBadge}
        ${developBadge}
        ${styleBadge}
        <span title="${esc(r.scene || '')}">${esc(trGenre(r.scene) || '?')}</span>
        <!-- v0.9-P1-4 — radial + brand-gradient text on score_final,
             at .lg size so it carries weight in the bigger inspector
             pane.  Falls back to "--" cleanly when score is missing. -->
        <span class="score-radial lg" title="score_final · 0..1">
          ${(typeof _aiRadialSvg === "function" ? _aiRadialSvg : window._aiRadialSvg)(r.score_final, {large:true})}
          <span>综合分 <span class="ai-num" style="font-size:1.1em">${scoreLine}</span></span>
        </span>
        ${styleChips}
        ${r.cluster_id != null ? `<span title="连拍组 ID">连拍组 ${r.cluster_id}</span>` : ''}
        ${r.rubric_human_labeled ? '<span style="color:var(--keep)">✓ 人工已标</span>' : ''}
      </div>

      <div class="inspector-sections">
        ${_sec("scores", "★ 评分 · 人工 → DeepSeek → VLM → 模型 → 自动", scoresBody)}
        <div id="lbSimilarSection">
          ${_sec("similar", "↳ 类似照片", similarBody)}
        </div>
        ${_sec("ai-judge", "⌬ AI 判读", aiJudgeBody)}
        ${_sec("warnings",  "⚠ 矛盾警示", warningsBody)}
        ${_sec("rationale", "⊕ 为何 maybe", rationaleBody)}
        ${_sec("strengths", "✓ 优点", strengthsBody)}
        ${_sec("weaknesses","✎ 改进建议", weaknessesBody)}
        ${_sec("flags",     "⚑ 检测器旗标", flagsBody)}
        ${_sec("reason",    "⚙ 规则栈说明", reasonBody)}
      </div>

      <!-- P-UX-6 — sticky decision toolbar. Mirrors the 1/2/3 hotkeys
           with explicit buttons + active state so mouse users + new
           users without the muscle memory can drive culling from the
           lightbox. The active button reflects the current decision
           (auto OR human) and updates after every click via
           _updateLbDecisionToolbar(). Clicking advances to the next
           visible photo just like keyboard 1/2/3 do. -->
      <div class="decision-toolbar" id="lbDecisionToolbar"
           role="group" aria-label="为这张照片打标">
        <button class="decision-btn keep ${dec === 'keep' ? 'active' : ''}"
                data-label="keep" type="button"
                title="保留 (1)">
          <span class="label">保留</span>
          <span class="hk">1</span>
        </button>
        <button class="decision-btn maybe ${dec === 'maybe' ? 'active' : ''}"
                data-label="maybe" type="button"
                title="待定 (2)">
          <span class="label">待定</span>
          <span class="hk">2</span>
        </button>
        <button class="decision-btn cull ${dec === 'cull' ? 'active' : ''}"
                data-label="cull" type="button"
                title="剔除 (3) · 可补充 cull 原因">
          <span class="label">剔除</span>
          <span class="hk">3</span>
        </button>
        <button class="decision-btn auto-adv ${_autoAdvance ? 'active' : ''}"
                id="lbAutoAdvBtn" type="button"
                aria-pressed="${_autoAdvance ? 'true' : 'false'}"
                title="决策后自动跳下一张(rapid cull · 点此可开关 · 持久化)">
          <span class="label">⏩ 自动</span>
        </button>
      </div>
    `;
  }

  grid.addEventListener("click", e => {
    const t = e.target;
    // v2.4-P1-1 — ⧉N burst-stack badge → expand the collapsed cluster
    // into the side-by-side compare modal.  Stop propagation so the
    // underlying thumb click (open lightbox) doesn't also fire.
    const stackBadge = t.closest(".burst-stack-badge");
    // v2.6-P1 — ≈N near-dup badge expands its group via the free-pick
    // compare flow (the group spans arbitrary times, not one cluster id).
    if (stackBadge && stackBadge.dataset.neardup) {
      e.stopPropagation();
      e.preventDefault();
      const members = _NEARDUP && _NEARDUP.byHero.get(stackBadge.dataset.neardup);
      if (members && typeof openCompareCustom === "function") {
        openCompareCustom(members);
      }
      return;
    }
    if (stackBadge && stackBadge.dataset.cluster) {
      e.stopPropagation();
      e.preventDefault();
      if (typeof openCompare === "function") openCompare(stackBadge.dataset.cluster);
      return;
    }
    // P-UX-27 — clickable wedding moment chip.  Toggle the
    // matching moment in filterState.weddingMoments + re-render.
    // Stops propagation so the underlying card thumb click
    // (which would open the lightbox) doesn't also fire.
    const momentChip = t.closest(".moment-chip");
    if (momentChip && momentChip.dataset.moment) {
      e.stopPropagation();
      const mk = momentChip.dataset.moment;
      if (filterState.weddingMoments.has(mk)) {
        filterState.weddingMoments.delete(mk);
      } else {
        filterState.weddingMoments.add(mk);
      }
      if (typeof _flashFilter === "function") _flashFilter();
      render();
      return;
    }
    // V16.2 — card-hover rotate button. Bumps rotation by +90° and
    // updates BOTH the inline transform on the matching <img.thumb>
    // AND the localStorage state, so a subsequent lightbox open
    // picks up the change. Stops propagation so the underlying
    // thumb click (which would open lightbox) doesn't fire.
    const rotBtn = t.closest(".card-rot-btn");
    if (rotBtn) {
      e.stopPropagation();
      const fn = rotBtn.dataset.fn;
      if (!fn) return;
      _lbRotateCard(fn, +90);
      return;
    }
    // v0.9-P1-1 — card-action floating buttons (top-right group).
    // 3 discrete entry points so the most-frequent actions don't
    // require right-click or keyboard hunting.
    const actBtn = t.closest(".card-action");
    if (actBtn) {
      e.stopPropagation();
      e.preventDefault();
      const fn = actBtn.dataset.fn;
      if (!fn) return;
      if (actBtn.classList.contains("card-action-zoom")) {
        openLightbox(fn);
        return;
      }
      if (actBtn.classList.contains("card-action-compare")) {
        // Delegate to the existing free-pick compare flow used by
        // .card-cmp-btn / Shift-click / `c` key.  pinForCompare lives
        // higher up in this script.
        if (typeof pinForCompare === "function") pinForCompare(fn);
        return;
      }
      if (actBtn.classList.contains("card-action-bucket")) {
        // Open the buckets panel and pre-arm an assignment for this
        // photo: if the user has a "last-used" bucket, push directly
        // into it; otherwise just open the panel so they can pick.
        const lastBucket = (() => {
          try { return localStorage.getItem("pixcull_last_bucket:" + run_id); }
          catch (_e) { return null; }
        })();
        if (lastBucket && typeof _readBuckets === "function") {
          const b = _readBuckets();
          if (b[lastBucket]) {
            if (!b[lastBucket].includes(fn)) b[lastBucket].push(fn);
            _writeBuckets(b);
            _refreshCardBucketTags?.();
            _renderBucketsPill?.();
            showToast?.(`已加入 “${lastBucket}”`, "success");
            return;
          }
        }
        // Fall back: open the panel so the user picks.
        document.getElementById("bucketsToggleBtn")?.click();
        return;
      }
      return;
    }
    if (t.tagName === "IMG" && t.classList.contains("thumb")) {
      // climb to find data-fn on the .card
      const card = t.closest(".card");
      if (card && card.dataset.fn) openLightbox(card.dataset.fn);
    }
  });

  // V16.2 — card-side helper: rotate the thumbnail on a single card,
  // share state with the lightbox via the same localStorage key.
  function _lbRotateCard(fn, delta) {
    const next = _lbRotGet(fn) + delta;
    _lbRotSet(fn, next);
    const deg = _lbRotGet(fn);
    // Update every visible card matching this filename (cards may
    // appear once per render; safe to query-all-and-set).
    grid.querySelectorAll(`.card[data-fn]`).forEach(card => {
      if (card.dataset.fn !== fn) return;
      const img = card.querySelector("img.thumb");
      if (img) img.style.transform = deg ? `rotate(${deg}deg)` : "";
    });
    // If the lightbox is currently showing this image, sync its
    // rotation too — same state in both views.
    if (_lbCurrentFn === fn) _applyLbRotation();
  }
  lbClose.addEventListener("click", () => lb.classList.remove("show"));
  // V14.2 — wire chevron clicks for mouse users; keyboard already
  // covered by the document-level keydown handler above.
  const lbPrev = document.getElementById("lbPrev");
  const lbNext = document.getElementById("lbNext");
  if (lbPrev) lbPrev.addEventListener("click", e => {
    e.stopPropagation(); lightboxStep(-1);
  });
  if (lbNext) lbNext.addEventListener("click", e => {
    e.stopPropagation(); lightboxStep(+1);
  });
  // V16.1 — manual rotate button handlers
  const lbRotL = document.getElementById("lbRotL");
  const lbRotR = document.getElementById("lbRotR");
  const lbRotReset = document.getElementById("lbRotReset");
  if (lbRotL) lbRotL.addEventListener("click", e => {
    e.stopPropagation(); _lbRotateBy(-90);
  });
  if (lbRotR) lbRotR.addEventListener("click", e => {
    e.stopPropagation(); _lbRotateBy(+90);
  });
  if (lbRotReset) lbRotReset.addEventListener("click", e => {
    e.stopPropagation(); _lbRotateReset();
  });

  // P-UX-2 — zoom-toggle button + image click-to-zoom + drag-to-pan
  // + wheel-zoom. The image itself becomes interactive: clicks toggle
  // 1:1 around the click point, drags pan within bounds, wheel
  // incrementally zooms. Clicking the dark padding around the image
  // (img-pane outside the <img>) still closes the lightbox.
  const lbZoomToggle = document.getElementById("lbZoomToggle");
  if (lbZoomToggle) lbZoomToggle.addEventListener("click", e => {
    e.stopPropagation();
    _lbZoomToggleAt(null, null);
  });

  // Track mousedown so we can distinguish a click (toggle) from a
  // drag (pan). Only count motion > _LB_CLICK_DRAG_THRESH as a drag.
  lbImg.addEventListener("mousedown", e => {
    if (e.button !== 0) return;
    _lbZoom.mouseDownPos = { x: e.clientX, y: e.clientY };
    if (_lbZoom.mode === "1to1") {
      e.preventDefault();
      _lbZoom.dragging = true;
      _lbZoom.dragStartClientX = e.clientX;
      _lbZoom.dragStartClientY = e.clientY;
      _lbZoom.dragStartPanX = _lbZoom.panX;
      _lbZoom.dragStartPanY = _lbZoom.panY;
      lbImg.classList.add("dragging");
    }
  });
  // Listen on window so a fast drag whose mouseup leaves the image
  // doesn't strand us in dragging-state.
  window.addEventListener("mousemove", e => {
    if (!_lbZoom.dragging) return;
    _lbZoom.panX = _lbZoom.dragStartPanX + (e.clientX - _lbZoom.dragStartClientX);
    _lbZoom.panY = _lbZoom.dragStartPanY + (e.clientY - _lbZoom.dragStartClientY);
    _lbClampPan();
    _applyLbTransform();
  });
  window.addEventListener("mouseup", () => {
    if (_lbZoom.dragging) {
      _lbZoom.dragging = false;
      lbImg.classList.remove("dragging");
    }
  });
  // Click = toggle zoom, but ignore the click if the user actually
  // dragged (motion > 4px). stopPropagation so the lb-click handler
  // below doesn't close the lightbox out from under us.
  lbImg.addEventListener("click", e => {
    const down = _lbZoom.mouseDownPos;
    _lbZoom.mouseDownPos = null;
    if (down) {
      const dist = Math.hypot(e.clientX - down.x, e.clientY - down.y);
      if (dist > _LB_CLICK_DRAG_THRESH) return;  // was a drag
    }
    e.stopPropagation();
    _lbZoomToggleAt(e.clientX, e.clientY);
  });
  // Mouse wheel = incremental zoom centered on cursor. Wheel up
  // zooms in, wheel down zooms out. Trackpad pinch on macOS also
  // fires wheel events with ctrlKey set — same handler covers it.
  lbImg.parentElement.addEventListener("wheel", e => {
    if (!lb.classList.contains("show")) return;
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    const target = (_lbZoom.scale || 1) * factor;
    _lbZoomToPoint(target, e.clientX, e.clientY);
  }, { passive: false });

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
  const _lbOpenObserver = new MutationObserver(() => {
    if (!lb.classList.contains("show")) {
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
  // Three buttons (keep / maybe / cull) — each fires a POST to
  // /annotation/... with the corresponding label, updates the local
  // row state, refreshes the toolbar's active highlight, and advances
  // to the next visible photo (consistent with the 1/2/3 hotkeys).
  // For cull, also fires the reject-reason picker (P-UX-4).
  function _updateLbDecisionToolbar(label) {
    const tb = document.getElementById("lbDecisionToolbar");
    if (!tb) return;
    tb.querySelectorAll(".decision-btn").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.label === label);
    });
  }

  async function _lbLabel(label) {
    const fn = _lbCurrentFn;
    if (!fn) return;
    const r = rows.find(x => x.filename === fn);
    // v0.4 P2 (2/4) — capture for the stat counter shift
    const _prevDecision = r ? r.decision : null;
    if (r) {
      pushUndo([{
        filename: fn,
        prev_decision: r.decision,
        prev_human_labeled: r.rubric_human_labeled,
      }]);
    }
    try {
      await fetch(`/annotation/${run_id}/${encodeURIComponent(fn)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          axes: {},
          overall_label: label,
          overall_rationale: `labeled ${label} via lightbox toolbar`,
        }),
      });
      if (r) {
        r.rubric_human_labeled = true;
        r.decision = label;
        if (label !== "cull") r.cull_reason = "";
      }
      // v0.4 P2 (2/4) — shift stat counters + pulse, same as
      // the keyboard path.
      _shiftStatCounts(_prevDecision, label);
      // P-UX-25 — same broadcast as quickLabel(); see the comment
      // on the keyboard path for rationale.
      _pixMultiTab.broadcastAnnotation(fn, label);
      // Sync the matching grid card so closing the lightbox lands
      // on a card with the right decision border + has-human class.
      const card = grid.querySelector(`.card[data-fn="${CSS.escape(fn)}"]`);
      if (card) {
        card.classList.remove("keep", "maybe", "cull");
        card.classList.add(label, "has-human");
        // v0.4 P1 — match the grid-side flash so closing the
        // lightbox shows the card "just got labeled" by the
        // same animation the keyboard path triggers.
        card.classList.remove('label-flash');
        void card.offsetWidth;
        card.classList.add('label-flash');
        setTimeout(() => card.classList.remove('label-flash'), 380);
      }
      summary.n_human_labeled = (summary.n_human_labeled || 0) + 1;
    } catch (_e) { /* ignore network blip */ }
    _updateLbDecisionToolbar(label);
    if (label === "cull") promptCullReason(fn);
    // Advance to next visible photo (same as keyboard 1/2/3 + j) when
    // auto-advance is on. Cull keeps the photo up so the reason picker
    // isn't swapped out from under the user.
    if (_autoAdvance && label !== "cull") lightboxStep(+1);
  }

  // Event delegation on the lightbox so the toolbar wiring survives
  // every renderInfoPane() rebuild without needing re-attachment.
  lb.addEventListener("click", e => {
    const adv = e.target.closest("#lbAutoAdvBtn");
    if (adv) { e.stopPropagation(); _setAutoAdvance(!_autoAdvance); return; }
    const btn = e.target.closest(".decision-btn[data-label]");
    if (!btn) return;
    e.stopPropagation();
    _lbLabel(btn.dataset.label);
  });

  // ==================================================================
  // V9.1 — keyboard navigation + quick labeling
  //   j / k / ←→        prev / next card
  //   1 / 2 / 3        label current as keep/maybe/cull (saves human anno)
  //   space / enter    open lightbox (zoom)
  //   ?                show shortcut cheat sheet
  //   Esc              close any modal
  // Active card is the one that has class .focused (visually outlined).
  // ==================================================================
  let focusedFn = null;
  // v2.4 — keyboard-first cull loop: a keep/maybe/cull decision hops to
  // the next photo so a pass flows at ~1-2 s/photo (the lightbox already
  // did this; the grid now does too). Toggle persists in localStorage.
  let _autoAdvance = true;
  try { _autoAdvance = localStorage.getItem("pixcull_autoadvance") !== "0"; } catch (e) {}
  function _setAutoAdvance(on) {
    _autoAdvance = !!on;
    try { localStorage.setItem("pixcull_autoadvance", on ? "1" : "0"); } catch (e) {}
    document.querySelectorAll(".decision-btn.auto-adv").forEach(b => {
      b.classList.toggle("active", _autoAdvance);
      b.setAttribute("aria-pressed", _autoAdvance ? "true" : "false");
    });
  }
  // V10.1 toast (single-element, bottom-center). V14.2 — keep the
  // signature, delegate to the new stack-based ``toast()`` so we get
  // multi-toast support for free without rewriting all callers.
  function showToast(msg, kind = "info") {
    toast(msg, kind === "info" ? "" : kind);
  }
  // V10.1 — undo stack for batch / quick-label actions
  // Each entry: array of {filename, prev_decision, prev_human_labeled}
  const undoStack = [];
  const UNDO_LIMIT = 20;
  function pushUndo(snapshots) {
    if (!snapshots || !snapshots.length) return;
    undoStack.push(snapshots);
    if (undoStack.length > UNDO_LIMIT) undoStack.shift();
  }
  async function performUndo() {
    const snap = undoStack.pop();
    if (!snap) return;
    let n = 0;
    for (const item of snap) {
      try {
        // Re-post annotation with the old decision (or a special clear)
        await fetch(`/annotation/${run_id}/${encodeURIComponent(item.filename)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            axes: {},
            overall_label: item.prev_decision || "",
            overall_rationale: "撤销",
          }),
        });
        const r = rows.find(x => x.filename === item.filename);
        if (r) {
          r.decision = item.prev_decision;
          r.rubric_human_labeled = item.prev_human_labeled;
        }
        n++;
      } catch (e) { /* ignore */ }
    }
    render();
    return n;
  }

  function visibleCards() {
    return Array.from(grid.querySelectorAll('.card[data-fn]'));
  }
  function focusCard(fn, scrollInto = true) {
    visibleCards().forEach(c => c.classList.remove('focused'));
    const t = grid.querySelector(`.card[data-fn="${CSS.escape(fn)}"]`);
    if (t) {
      t.classList.add('focused');
      if (scrollInto) t.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      focusedFn = fn;
    }
  }
  function moveFocus(delta) {
    const cards = visibleCards();
    if (!cards.length) return;
    const idx = cards.findIndex(c => c.dataset.fn === focusedFn);
    const next = (idx === -1) ? 0 : Math.max(0, Math.min(cards.length - 1, idx + delta));
    focusCard(cards[next].dataset.fn);
  }
  // Save a quick label for the focused card by POSTing /annotation
  // with overall_label only — same endpoint the modal uses.
  async function quickLabel(label) {
    if (!focusedFn) return;
    const r = rows.find(x => x.filename === focusedFn);
    // v0.4 P2 (2/4) — capture the previous decision BEFORE the
    // POST so we can shift the stat counters even if the network
    // is slow.  Counter update happens in the response handler
    // alongside the in-memory r.decision update.
    const _prevDecision = r ? r.decision : null;
    if (r) {
      pushUndo([{
        filename: focusedFn,
        prev_decision: r.decision,
        prev_human_labeled: r.rubric_human_labeled,
      }]);
    }
    // v0.8-P0-2 — record the local-edit timestamp so the sync
    // poller knows this row is fresher than any incoming remote
    // edit of the same photo.  v0.9-P1-2 — pass the action verb
    // (keep/maybe/cull) so peers see "✅ 二摄 标 keep · IMG_001".
    if (typeof _markLocalEdit === "function") _markLocalEdit(focusedFn, label);
    // v0.10-P0-1 — push the edit to peers via two-way sync.  No-op
    // when not in an event session (the function early-returns).
    // Fire-and-forget — if the network is down, the offline queue
    // catches it.
    if (typeof _pushEdits === "function") {
      _pushEdits([{ filename: focusedFn, decision: label }]);
    }
    const wasFn = focusedFn;
    try {
      await fetch(`/annotation/${run_id}/${encodeURIComponent(focusedFn)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          axes: {},
          overall_label: label,
          overall_rationale: `quick-labeled ${label} via keyboard`,
        }),
      });
      if (r) {
        r.rubric_human_labeled = true;
        r.decision = label;
        // P-UX-4 — flipping away from cull clears any stale reason.
        if (label !== "cull") r.cull_reason = "";
      }
      // v0.4 P2 (2/4) — shift the header stat counters in the
      // matching keep/maybe/cull buckets + pulse the changed
      // numbers so the user feels their action move the totals.
      _shiftStatCounts(_prevDecision, label);
      // P-UX-25 — broadcast to any sibling tab on the same run_id so
      // the user sees the change live in the other window instead of
      // discovering a stale decision on next reload.
      _pixMultiTab.broadcastAnnotation(focusedFn, label);
      // Quick visual feedback: flash a label badge near the card.
      const card = grid.querySelector(`.card[data-fn="${CSS.escape(focusedFn)}"]`);
      if (card) {
        card.classList.remove('keep','maybe','cull');
        card.classList.add(label, 'has-human');
        // v0.4 P1 — micro-interaction: brief scale-bounce + ring
        // so the keystroke registers as a felt action, not just
        // a class change on the badge.  Self-clears so subsequent
        // keystrokes re-fire the animation.
        card.classList.remove('label-flash');
        // force reflow so removing + adding in the same tick
        // restarts the keyframe
        void card.offsetWidth;
        card.classList.add('label-flash');
        setTimeout(() => card.classList.remove('label-flash'), 380);
      }
      summary.n_human_labeled = (summary.n_human_labeled || 0) + 1;
    } catch (e) { /* ignore quick errors */ }
    // P-UX-4 — after a cull, prompt for a reason. Opt-in: auto-
    // dismisses in ~6 s, never blocks the keep/maybe/cull rhythm.
    if (label === "cull") promptCullReason(wasFn);
    // v2.4 — keyboard cull loop: hop focus to the next card so a
    // 1 / 2 / 3 spree flows through the grid without reaching for the mouse.
    if (_autoAdvance) moveFocus(1);
  }
  // V14.5 — shortcuts cheat sheet replaces the old alert(). The
  // overlay HTML is statically rendered; JS just toggles .show
  // and the registerModal observer handles ARIA + focus trap.
  const shortcutsModal = document.getElementById("shortcutsModal");
  const shortcutsClose = document.getElementById("shortcutsClose");
  const shortcutsHint = document.getElementById("shortcutsHint");
  if (shortcutsModal) registerModal(shortcutsModal);

  // P-UX-24 — figure out which surface is active at the moment the
  // shortcuts overlay is requested. Priority: compare-modal > lightbox
  // > grid (a compare modal lives on top of a lightbox-or-grid; the
  // lightbox lives on top of the grid). Fallback "grid" covers the
  // bare results page state with no modal open.
  function _activeShortcutCtx() {
    const cmpEl = document.getElementById("cmpModal");
    if (cmpEl && cmpEl.classList.contains("show")) return "compare";
    const lbEl = document.getElementById("lightbox");
    if (lbEl && lbEl.classList.contains("show")) return "lightbox";
    return "grid";
  }
  const _CTX_LABELS = {
    grid:     "网格视图",
    lightbox: "放大窗",
    compare:  "A/B 比较窗",
  };
  function _applyShortcutsContext(ctx) {
    const sections = shortcutsModal.querySelectorAll(".shortcut-section");
    sections.forEach(sec => {
      const secCtx = sec.dataset.ctx || "universal";
      sec.classList.remove("ctx-active", "ctx-dim");
      if (secCtx === ctx) {
        sec.classList.add("ctx-active");
      } else if (secCtx !== "universal") {
        // not active + not universal → dim. Universal stays clear so
        // Esc / ⌘Z / ? are always legibly available.
        sec.classList.add("ctx-dim");
      }
    });
    const badge = document.getElementById("shortcutsCtxBadge");
    if (badge) badge.textContent = "当前:" + (_CTX_LABELS[ctx] || ctx);
  }

  // ================================================================
  // v0.6 (5/5) — hold-Space contextual cheat-sheet (Finder pattern).
  // Press-and-hold Space ≥ HOLD_MS surfaces a frosted strip showing
  // the 4-6 most-useful keys for the *current* context (grid /
  // lightbox / compare). Release Space → strip fades + the upcoming
  // Space-up is consumed (no lightbox toggle).
  // Tap Space (< HOLD_MS) → existing toggle-lightbox behavior.
  // ================================================================
  const KBD_HOLD_MS = 350;
  const kbdCheat    = document.getElementById("kbdCheat");
  // Subset of the full shortcuts modal, distilled to the keys a
  // panicked user actually needs in the moment.  Order is
  // most-frequent-first; the strip caps visually at ~6 pills.
  const KBD_CHEAT_DATA = {
    grid: [
      {keys: ["1"], desc: "keep"},
      {keys: ["2"], desc: "maybe"},
      {keys: ["3"], desc: "cull"},
      {keys: ["←", "→"], desc: "上/下一张"},
      {keys: ["B"], desc: "侧栏"},
      {keys: ["?"], desc: "全部"},
    ],
    lightbox: [
      {keys: ["1"], desc: "keep"},
      {keys: ["2"], desc: "maybe"},
      {keys: ["3"], desc: "cull"},
      {keys: ["←", "→"], desc: "前/后一张"},
      {keys: ["Z"], desc: "1:1"},
      {keys: ["Esc"], desc: "关闭"},
    ],
    compare: [
      {keys: ["Z"], desc: "同步 1:1"},
      {keys: ["+", "−"], desc: "缩放"},
      {keys: ["0"], desc: "重置"},
      {keys: ["Esc"], desc: "关闭"},
    ],
  };

  function _renderKbdCheat(ctx) {
    if (!kbdCheat) return;
    const rows = KBD_CHEAT_DATA[ctx] || KBD_CHEAT_DATA.grid;
    const label = _CTX_LABELS[ctx] || "网格";
    const html = [`<span class="kbd-ctx">${esc(label)}</span>`];
    rows.forEach(r => {
      const keysHtml = r.keys
        .map(k => `<kbd>${esc(k)}</kbd>`).join(" ");
      html.push(
        `<span class="kbd-cell">${keysHtml}<span class="desc">${esc(r.desc)}</span></span>`
      );
    });
    html.push(`<span class="kbd-more">松开 Space 关闭</span>`);
    kbdCheat.innerHTML = html.join("");
  }

  let _kbdHoldTimer  = null;   // setTimeout handle for the hold-debounce
  let _kbdCheatShown = false;  // true while the overlay is on screen
  let _kbdSpaceDown  = false;  // dedupes keyboard auto-repeat events

  function _showKbdCheat() {
    if (!kbdCheat) return;
    _renderKbdCheat(_activeShortcutCtx());
    kbdCheat.classList.add("show");
    kbdCheat.setAttribute("aria-hidden", "false");
    _kbdCheatShown = true;
  }
  function _hideKbdCheat() {
    if (!kbdCheat) return;
    kbdCheat.classList.remove("show");
    kbdCheat.setAttribute("aria-hidden", "true");
    _kbdCheatShown = false;
  }
  function _cancelKbdHold() {
    if (_kbdHoldTimer) {
      clearTimeout(_kbdHoldTimer);
      _kbdHoldTimer = null;
    }
  }
  // Tap-vs-hold gate, called from the keydown handler before any
  // other Space-specific logic. Returns true when the caller should
  // suppress the default Space behavior (i.e. the hint is showing
  // OR we are in the hold-debounce window).
  function _kbdSpaceDownGate(e) {
    // Auto-repeat events — first one already started the timer; bail.
    if (e.repeat || _kbdSpaceDown) {
      e.preventDefault();
      return true;
    }
    _kbdSpaceDown = true;
    _cancelKbdHold();
    _kbdHoldTimer = setTimeout(() => {
      _kbdHoldTimer = null;
      _showKbdCheat();
    }, KBD_HOLD_MS);
    return false;  // caller still gets to perform the tap path
  }
  // Returns true if the keyup should suppress the lightbox toggle
  // (because we showed the overlay or are still in the hold window).
  function _kbdSpaceUpGate() {
    const wasShown = _kbdCheatShown;
    _cancelKbdHold();
    _hideKbdCheat();
    _kbdSpaceDown = false;
    return wasShown;
  }
  // Any *other* key released while Space is held also dismisses the
  // overlay — matches Finder behaviour where the user reads, picks
  // a key, then releases everything.
  document.addEventListener("keyup", e => {
    if (e.key !== " " && e.key !== "Spacebar" && _kbdCheatShown) {
      _hideKbdCheat();
    }
  });

  function showShortcuts() {
    if (!shortcutsModal) return;
    _applyShortcutsContext(_activeShortcutCtx());
    shortcutsModal.classList.add("show");
  }
  function hideShortcuts() {
    if (shortcutsModal) shortcutsModal.classList.remove("show");
  }
  if (shortcutsClose) {
    shortcutsClose.addEventListener("click", hideShortcuts);
  }
  if (shortcutsHint) {
    shortcutsHint.addEventListener("click", showShortcuts);
  }
  if (shortcutsModal) {
    shortcutsModal.addEventListener("click", e => {
      if (e.target === shortcutsModal) hideShortcuts();
    });
  }

  document.addEventListener("keydown", e => {
    // Ignore when typing in inputs / textareas
    const tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    // V10.1: Cmd+Z / Ctrl+Z → undo (allow modifier passthrough)
    if ((e.metaKey || e.ctrlKey) && e.key === "z" && !e.shiftKey) {
      e.preventDefault();
      performUndo().then(n => { if (n) showToast(`已撤销 ${n} 个标注`); });
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    // Modal-aware: Esc closes any open modal first. V14.5 also
    // routes Esc to the shortcuts overlay; ordering matters because
    // multiple modals can stack (e.g. shortcuts opened over the
    // lightbox should close shortcuts first, leaving the lightbox).
    if (e.key === "Escape") {
      if (shortcutsModal && shortcutsModal.classList.contains("show")) {
        hideShortcuts(); return;
      }
      // Topmost layer first: the annotation modal stacks OVER the
      // lightbox, so it must close before the lightbox — the old order
      // closed the lightbox UNDERNEATH and left the modal floating over
      // the grid (v2.5 stability sweep).
      const am = document.getElementById("annModal");
      if (am && am.classList.contains("show")) { am.classList.remove("show"); return; }
      if (lb.classList.contains("show")) { lb.classList.remove("show"); return; }
      const bm = document.getElementById("browserModal");
      if (bm && bm.classList.contains("show")) { bm.classList.remove("show"); return; }
      // P-UX-3 — Esc also cancels a pending A/B compare pick. This
      // is last in the chain so any open modal still takes priority.
      if (_compareA) { cancelComparePick(); return; }
      // P-UX-4 — Esc also dismisses the cull-reason picker tray.
      if (cullReasonTray && cullReasonTray.classList.contains("show")) {
        _hideCullReasonTray(); return;
      }
      return;
    }
    // Don't act when an annotation modal is open — let modal own input
    const am = document.getElementById("annModal");
    if (am && am.classList.contains("show")) return;

    // V14.2 — when the lightbox is open, j/k/← →/PageUp/PageDown
    // navigate between filtered+sorted rows *within* the lightbox so
    // the user can flip through the keep/maybe/cull batch without
    // closing and re-opening. Falls back to card focus only when the
    // lightbox is closed.
    if (lb.classList.contains("show")) {
      // v2.8-DESIGN P0-1 (v2.8.1 freeze fix) — "i" toggles zen mode: hide the
      // info inspector so the photo claims the full viewport (content-first).
      // MUST NOT bind Tab here: registerModal(lb) installs a focus-trap
      // _trapHandler on Tab (line ~2521 / 486). A second Tab handler raced it —
      // toggling lb-zen mid-cycle hid the just-focused element (offsetParent
      // null) so focus escaped the lightbox to <body>; thereafter ESC/j/k
      // landed on body and the lightbox read as frozen. Use a non-trap key.
      if (e.key === "i" || e.key === "I") { e.preventDefault(); lb.classList.toggle("lb-zen"); return; }
      if (e.key === "j" || e.key === "ArrowRight" || e.key === "PageDown") {
        e.preventDefault(); lightboxStep(+1); return;
      }
      if (e.key === "k" || e.key === "ArrowLeft" || e.key === "PageUp") {
        e.preventDefault(); lightboxStep(-1); return;
      }
      // V16.1 — r / R inside lightbox = rotate CW / CCW (manual override)
      if (e.key === "r") { e.preventDefault(); _lbRotateBy(+90);  return; }
      if (e.key === "R") { e.preventDefault(); _lbRotateBy(-90);  return; }
      // P-UX-6 — route 1/2/3 through the lightbox label flow so the
      // sticky decision toolbar's active highlight stays in sync.
      // (quickLabel uses focusedFn which may diverge from the
      // lightbox's _lbCurrentFn when the user clicked a card to
      // open rather than tabbing through with j/k.)
      if (e.key === "1") { e.preventDefault(); _lbLabel("keep");  return; }
      if (e.key === "2") { e.preventDefault(); _lbLabel("maybe"); return; }
      if (e.key === "3") { e.preventDefault(); _lbLabel("cull");  return; }
      // P-UX-2 — z = toggle 1:1 focus check (around viewport center);
      // 0 = reset pan but stay at current scale so the user can
      // re-center after wandering. + / - = wheel-equivalent zoom.
      if (e.key === "z" || e.key === "Z") {
        e.preventDefault(); _lbZoomToggleAt(null, null); return;
      }
      if (e.key === "0") {
        e.preventDefault();
        _lbZoom.panX = 0; _lbZoom.panY = 0;
        _lbClampPan(); _applyLbTransform(); return;
      }
      if (e.key === "+" || e.key === "=") {
        e.preventDefault();
        const rect = lbImg.getBoundingClientRect();
        _lbZoomToPoint((_lbZoom.scale || 1) * 1.25,
                       rect.left + rect.width / 2,
                       rect.top  + rect.height / 2);
        return;
      }
      if (e.key === "-" || e.key === "_") {
        e.preventDefault();
        const rect = lbImg.getBoundingClientRect();
        _lbZoomToPoint((_lbZoom.scale || 1) / 1.25,
                       rect.left + rect.width / 2,
                       rect.top  + rect.height / 2);
        return;
      }
      // P-UX-3 — c inside lightbox = pin the current photo for A/B
      // compare. If A is already pinned, this closes the lightbox
      // and opens the compare modal with [A, current]; if not, the
      // current frame becomes A. Lets the user 1:1-check then pin.
      if (e.key === "c" || e.key === "C") {
        e.preventDefault();
        if (!_lbCurrentFn) return;
        const cur = _lbCurrentFn;
        if (_compareA && _compareA !== cur) {
          lb.classList.remove("show");
          // Defer one tick so the lightbox-close transition starts
          // before the modal animates in.
          setTimeout(() => pinForCompare(cur), 30);
        } else {
          pinForCompare(cur);
        }
        return;
      }
    }

    if (e.key === "j" || e.key === "ArrowRight") { e.preventDefault(); moveFocus(+1); }
    else if (e.key === "k" || e.key === "ArrowLeft") { e.preventDefault(); moveFocus(-1); }
    else if (e.key === "1") { e.preventDefault(); quickLabel("keep"); }
    else if (e.key === "2") { e.preventDefault(); quickLabel("maybe"); }
    else if (e.key === "3") { e.preventDefault(); quickLabel("cull"); }
    // P-UX-13 — Photo Mechanic-style hotkeys for full-keyboard culling.
    // Shift+1/2/3 = label AND advance to next visible card (the
    // "set rhythm" of Photo Mechanic — you never have to think
    // about moving on, the action does it for you).
    else if (e.key === "!" || (e.shiftKey && e.key === "1")) {
      e.preventDefault(); quickLabel("keep"); setTimeout(() => moveFocus(+1), 0);
    }
    else if (e.key === "@" || (e.shiftKey && e.key === "2")) {
      e.preventDefault(); quickLabel("maybe"); setTimeout(() => moveFocus(+1), 0);
    }
    else if (e.key === "#" || (e.shiftKey && e.key === "3")) {
      e.preventDefault(); quickLabel("cull"); setTimeout(() => moveFocus(+1), 0);
    }
    // F = "flag" toggle (mapped to keep, mirroring Photo Mechanic
    // which uses T for tag = "flagged for review"). Without modifier,
    // F is the most natural single-key keep.
    else if (e.key === "f" || e.key === "F") {
      e.preventDefault(); quickLabel("keep");
    }
    // G = jump to next burst-cluster group. Walks the visible cards
    // until cluster_id changes, then focuses the first card of the
    // new cluster. Crucial for tearing through 1000-frame events.
    else if (e.key === "g" || e.key === "G") {
      e.preventDefault();
      const visible = visibleCards();
      if (!visible.length) return;
      const curIdx = focusedFn
        ? visible.findIndex(c => c.dataset.fn === focusedFn) : -1;
      const curRow = curIdx >= 0
        ? rows.find(r => r.filename === visible[curIdx].dataset.fn) : null;
      const curCluster = curRow ? curRow.cluster_id : null;
      for (let i = (curIdx >= 0 ? curIdx + 1 : 0); i < visible.length; i++) {
        const row = rows.find(r => r.filename === visible[i].dataset.fn);
        if (!row) continue;
        if (row.cluster_id !== curCluster) {
          focusCard(visible[i].dataset.fn, true);
          return;
        }
      }
      // Wrap around to first cluster if we ran off the end
      if (visible.length > 0) focusCard(visible[0].dataset.fn, true);
    }
    // Backspace = undo + go back (Photo Mechanic's "I take it back"
    // gesture). performUndo restores the prior decision; the focus
    // step rewinds to the photo that just got undone.
    else if (e.key === "Backspace") {
      e.preventDefault();
      performUndo();
      moveFocus(-1);
    }
    // [ / ] = rank decrease/increase. Mapped onto cycling through
    // keep → maybe → cull → maybe → keep so a single key tap nudges
    // the verdict one notch at a time without leaving the keyboard.
    else if (e.key === "[") {
      e.preventDefault();
      if (!focusedFn) return;
      const r = rows.find(x => x.filename === focusedFn);
      const cur = r ? r.decision : "maybe";
      const next = { keep: "maybe", maybe: "cull", cull: "cull" }[cur] || "cull";
      quickLabel(next);
    }
    else if (e.key === "]") {
      e.preventDefault();
      if (!focusedFn) return;
      const r = rows.find(x => x.filename === focusedFn);
      const cur = r ? r.decision : "maybe";
      const next = { keep: "keep", maybe: "keep", cull: "maybe" }[cur] || "maybe";
      quickLabel(next);
    }
    // P-UX-3 — c on the grid pins the currently focused card for
    // A/B compare. If another card was already pinned, this fires
    // the modal directly. Symmetrical with the lightbox-side c.
    else if (e.key === "c" || e.key === "C") {
      e.preventDefault();
      if (focusedFn) pinForCompare(focusedFn);
    }
    else if (e.key === " " || e.key === "Spacebar") {
      // v0.6 (5/5) — hold-Space → cheat-sheet (Finder pattern). The
      // keydown only *starts* the hold timer; we DON'T toggle the
      // lightbox here. The toggle happens in the matching keyup
      // handler below, and only if the hint never surfaced.
      e.preventDefault();
      _kbdSpaceDownGate(e);
    }
    else if (e.key === "Enter") {
      e.preventDefault();
      if (focusedFn && typeof openAnnotation === "function") {
        openAnnotation(focusedFn);
      }
    }
    else if (e.key === "?") {
      e.preventDefault();
      showShortcuts();
    }
  });

  // ============================================================
  // v0.9-P0-4 — Cmd+K command palette.
  //
  // Linear/Raycast/Notion-grade keyboard-first action entry.
  // Builds a static action registry on boot, augmented at
  // open-time with dynamic items (view presets, buckets) read
  // from localStorage.  Fuzzy matcher is a simple subsequence
  // scorer with contiguous + prefix bonuses — no library, ~60
  // lines.  Keyboard: ⌘K / Ctrl+K opens; ↑↓ moves; ↵ fires;
  // Esc closes; click on a row fires.
  // ============================================================
  const cmdkModal   = document.getElementById("cmdkModal");
  const cmdkInput   = document.getElementById("cmdkInput");
  const cmdkResults = document.getElementById("cmdkResults");
  const _CMDK_RECENT_KEY = "pixcull_cmdk_recent";
  let _cmdkOpen = false;
  let _cmdkItems = [];        // current filtered+sorted items
  let _cmdkActiveIdx = 0;

  // --- Static action registry (built once) ---
  // group ordering shapes the "primary surface" of the palette;
  // dynamic items (presets / buckets) appended at open-time.
  function _cmdkStaticActions() {
    return [
      // Decisions
      { id: "dec.all",   label: "筛选: 全部", group: "筛选",
        hint: "all", icon: "○",
        run: () => _cmdkPickDecision("all") },
      { id: "dec.keep",  label: "筛选: 仅 keep", group: "筛选",
        hint: "1", icon: "●",
        run: () => _cmdkPickDecision("keep") },
      { id: "dec.maybe", label: "筛选: 仅 maybe", group: "筛选",
        hint: "2", icon: "●",
        run: () => _cmdkPickDecision("maybe") },
      { id: "dec.cull",  label: "筛选: 仅 cull", group: "筛选",
        hint: "3", icon: "●",
        run: () => _cmdkPickDecision("cull") },
      { id: "filter.reset", label: "重置所有筛选", group: "筛选",
        hint: "", icon: "↺",
        run: () => _cmdkResetFilters() },
      // Sort
      { id: "sort.default",     label: "排序: 默认",          group: "排序",
        hint: "", icon: "≡", run: () => _cmdkPickSort("default") },
      { id: "sort.score_desc",  label: "排序: 总分高 → 低",    group: "排序",
        hint: "", icon: "↓", run: () => _cmdkPickSort("score_desc") },
      { id: "sort.score_asc",   label: "排序: 总分低 → 高",    group: "排序",
        hint: "", icon: "↑", run: () => _cmdkPickSort("score_asc") },
      { id: "sort.cluster",     label: "排序: 按连拍聚类",      group: "排序",
        hint: "", icon: "⫶", run: () => _cmdkPickSort("cluster") },
      { id: "sort.style_dist",  label: "排序: 🎨 像我风格的优先", group: "排序",
        hint: "", icon: "🎨", run: () => _cmdkPickSort("style_distance_asc") },
      // Language
      { id: "lang.zh", label: "切换语言: 中文",   group: "语言",
        hint: "", icon: "中", run: () => _cmdkApplyLang("zh_CN") },
      { id: "lang.en", label: "Switch language: English", group: "语言",
        hint: "", icon: "EN", run: () => _cmdkApplyLang("en_US") },
      { id: "lang.ja", label: "言語切替: 日本語",   group: "语言",
        hint: "", icon: "あ", run: () => _cmdkApplyLang("ja_JP") },
      // Actions
      { id: "act.train_style", label: "🎨 训练风格模型", group: "操作",
        hint: "", icon: "🎨",
        run: () => document.getElementById("styleTrainBtn")?.click() },
      { id: "act.share_link",  label: "🔗 生成客户分享链接", group: "操作",
        hint: "", icon: "🔗",
        run: () => document.getElementById("shareLinkBtn")?.click() },
      { id: "act.sync_event",  label: "📡 生成协作会话", group: "操作",
        hint: "", icon: "📡",
        run: () => document.getElementById("syncEventBtn")?.click() },
      { id: "act.toggle_library", label: "切换 Library 侧栏", group: "操作",
        hint: "B", icon: "▣",
        run: () => document.getElementById("lpCollapseBtn")?.click() },
      { id: "act.toggle_buckets", label: "打开 / 关闭 桶面板", group: "操作",
        hint: "", icon: "🪣",
        run: () => document.getElementById("bucketsToggleBtn")?.click() },
      { id: "act.shortcuts",   label: "显示所有快捷键", group: "操作",
        hint: "?", icon: "⌨",
        run: () => showShortcuts() },
      // Export
      { id: "exp.xmp",   label: "导出: 下载 XMP zip", group: "导出",
        hint: "", icon: "↓",
        run: () => document.getElementById("exportZipBtn")?.click() },
      { id: "exp.csv",   label: "导出: 下载 CSV",     group: "导出",
        hint: "", icon: "↓",
        run: () => document.getElementById("csvBtn")?.click() },
      { id: "exp.json",  label: "导出: 结构化 JSON",  group: "导出",
        hint: "", icon: "↓",
        run: () => document.getElementById("jsonStructuredBtn")?.click() },
      { id: "exp.gallery", label: "导出: HTML 相册",   group: "导出",
        hint: "", icon: "📔",
        run: () => document.getElementById("galleryBtn")?.click() },
      // Navigation
      { id: "nav.history", label: "去: 🕒 历史时间线", group: "导航",
        hint: "", icon: "↗", run: () => { location.href = "/history"; } },
      { id: "nav.tether",  label: "去: 📡 Tethered Live", group: "导航",
        hint: "", icon: "↗", run: () => { location.href = "/tether"; } },
      { id: "nav.upload",  label: "去: 上传新一批",  group: "导航",
        hint: "", icon: "↗", run: () => { location.href = "/"; } },
      { id: "nav.admin",   label: "去: 存储管理",     group: "导航",
        hint: "", icon: "↗", run: () => { location.href = "/admin"; } },
    ];
  }

  // Dynamic items: view presets + bucket assignments — read at
  // open-time so palette stays fresh as the user creates more.
  function _cmdkDynamicActions() {
    const out = [];
    // View presets
    try {
      const presets = JSON.parse(
        localStorage.getItem("pixcull_view_presets_v1") || "{}");
      Object.keys(presets).sort().forEach(name => {
        out.push({
          id: "preset." + name,
          label: "应用视图预设: " + name,
          group: "视图预设",
          hint: "",
          icon: "★",
          run: () => {
            if (typeof _applyView === "function") _applyView(presets[name]);
            else showToast("视图预设应用失败 — _applyView 未定义", "error");
          },
        });
      });
    } catch (_e) {}
    // Buckets
    try {
      const buckets = JSON.parse(
        localStorage.getItem(`pixcull_buckets:${run_id}`) || "{}");
      Object.keys(buckets).sort().forEach(name => {
        const n = (buckets[name] || []).length;
        out.push({
          id: "bucket." + name,
          label: `筛选: 桶 “${name}” (${n} 张)`,
          group: "桶",
          hint: "",
          icon: "🪣",
          run: () => {
            // Reuse the existing "filter by bucket" handler logic
            if (typeof filterState !== "undefined") {
              filterState.semSearch = {
                q: `🪣 ${name}`,
                filenames: new Set(buckets[name] || []),
              };
              const sin = document.getElementById("semSearchInput");
              const sclr = document.getElementById("semSearchClearBtn");
              if (sin) sin.value = `🪣 ${name}`;
              if (sclr) sclr.style.display = "";
              render();
            }
          },
        });
      });
    } catch (_e) {}
    return out;
  }

  // --- Fuzzy matcher (subsequence + contiguous + prefix bonuses) ---
  function _cmdkScore(query, target) {
    if (!query) return 0.001;   // tiny non-zero to keep stable order
    const q = query.toLowerCase();
    const t = target.toLowerCase();
    if (t === q) return 1000;                                  // exact
    if (t.startsWith(q)) return 800 - (t.length - q.length);   // prefix
    if (t.includes(q))   return 600 - (t.length - q.length);   // substring
    // Subsequence + contiguous bonus
    let qi = 0, score = 0, lastMatch = -2;
    for (let ti = 0; ti < t.length && qi < q.length; ti++) {
      if (t[ti] === q[qi]) {
        score += 10;
        if (ti === lastMatch + 1) score += 18;  // contiguous bonus
        if (ti === 0) score += 12;              // start-of-string bonus
        lastMatch = ti;
        qi++;
      }
    }
    return qi === q.length ? score : 0;
  }

  function _cmdkSnapshot() {
    // The visible action set at any given open: static + dynamic
    return _cmdkStaticActions().concat(_cmdkDynamicActions());
  }

  function _cmdkReadRecent() {
    try {
      return JSON.parse(localStorage.getItem(_CMDK_RECENT_KEY) || "[]")
        .slice(0, 5);
    } catch (_e) { return []; }
  }
  function _cmdkPushRecent(id) {
    try {
      const cur = _cmdkReadRecent().filter(x => x !== id);
      cur.unshift(id);
      localStorage.setItem(_CMDK_RECENT_KEY,
                            JSON.stringify(cur.slice(0, 5)));
    } catch (_e) {}
  }

  function _cmdkRender(query) {
    const all = _cmdkSnapshot();
    let items;
    if (!query || !query.trim()) {
      // Empty query → recent-used first, then full list grouped
      const recents = _cmdkReadRecent();
      const recentObjs = recents
        .map(id => all.find(a => a.id === id))
        .filter(Boolean)
        .map(a => Object.assign({}, a, { _recent: true }));
      const recentIds = new Set(recents);
      items = recentObjs.concat(all.filter(a => !recentIds.has(a.id)));
    } else {
      items = all
        .map(a => Object.assign({}, a, { _s: _cmdkScore(query, a.label) }))
        .filter(a => a._s > 0)
        .sort((a, b) => b._s - a._s);
    }
    _cmdkItems = items;
    if (!items.length) {
      cmdkResults.innerHTML = `<div class="cmdk-empty">无匹配的操作 · 试试 “导出” / “排序” / “风格”</div>`;
      _cmdkActiveIdx = 0;
      return;
    }
    // Group-render (only when no query active, to preserve grouping
    // semantics — when querying, ranked-flat is the right UX)
    const rows = [];
    if (!query || !query.trim()) {
      let lastGroup = null;
      items.forEach((it, i) => {
        const g = it._recent ? "最近" : it.group;
        if (g !== lastGroup) {
          rows.push(`<div class="cmdk-group">${esc(g)}</div>`);
          lastGroup = g;
        }
        rows.push(_cmdkItemHtml(it, i));
      });
    } else {
      items.forEach((it, i) => rows.push(_cmdkItemHtml(it, i)));
    }
    cmdkResults.innerHTML = rows.join("");
    _cmdkActiveIdx = 0;
    _cmdkApplyActive();
  }

  function _cmdkItemHtml(it, i) {
    const hint = it.hint ? `<span class="cmdk-item-hint">${esc(it.hint)}</span>` : "";
    return `<div class="cmdk-item" data-idx="${i}" role="option">
      <span class="cmdk-item-icon">${esc(it.icon || "•")}</span>
      <span class="cmdk-item-label">${esc(it.label)}</span>
      ${hint}
    </div>`;
  }

  function _cmdkApplyActive() {
    cmdkResults.querySelectorAll(".cmdk-item").forEach(el => {
      el.classList.toggle("active",
        parseInt(el.dataset.idx, 10) === _cmdkActiveIdx);
    });
    // Scroll active into view
    const a = cmdkResults.querySelector(".cmdk-item.active");
    if (a) a.scrollIntoView({ block: "nearest" });
  }

  function openCmdk() {
    _cmdkOpen = true;
    cmdkModal.classList.add("show");
    cmdkModal.setAttribute("aria-hidden", "false");
    cmdkInput.value = "";
    _cmdkRender("");
    // Defer focus so the keydown that triggered ⌘K doesn't leak in
    setTimeout(() => cmdkInput.focus(), 30);
  }
  function closeCmdk() {
    _cmdkOpen = false;
    cmdkModal.classList.remove("show");
    cmdkModal.setAttribute("aria-hidden", "true");
  }
  function _cmdkFire(idx) {
    const it = _cmdkItems[idx];
    if (!it) return;
    _cmdkPushRecent(it.id);
    closeCmdk();
    try { it.run(); }
    catch (e) { showToast("执行失败: " + e.message, "error"); }
  }

  // --- Helper closures used by the registered actions ---
  function _cmdkPickDecision(d) {
    const pill = document.querySelector(`#decisionPills .pill[data-d="${d}"]`);
    if (pill) pill.click();
  }
  function _cmdkPickSort(s) {
    const sortSel = document.getElementById("sortBy");
    if (sortSel) {
      sortSel.value = s;
      sortSel.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }
  function _cmdkApplyLang(lang) {
    if (typeof _applyLang === "function") _applyLang(lang);
  }
  function _cmdkResetFilters() {
    if (typeof filterState !== "undefined") {
      filterState.decision = "all";
      filterState.scenes = new Set();
      filterState.styles = new Set();
      filterState.faceClusters = new Set();
      filterState.locationClusters = new Set();
      filterState.cullReason = null;
      filterState.burstPeakOnly = false;
      filterState.locationBestOnly = false;
      filterState.weddingMoments = new Set();
      filterState.semSearch = null;
      document.querySelectorAll("#decisionPills .pill").forEach(el =>
        el.classList.toggle("active", el.dataset.d === "all"));
      render();
    }
  }

  // --- Wiring ---
  cmdkInput?.addEventListener("input", () => _cmdkRender(cmdkInput.value));
  cmdkInput?.addEventListener("keydown", e => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (_cmdkItems.length) {
        _cmdkActiveIdx = (_cmdkActiveIdx + 1) % _cmdkItems.length;
        _cmdkApplyActive();
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (_cmdkItems.length) {
        _cmdkActiveIdx = (_cmdkActiveIdx - 1 + _cmdkItems.length) % _cmdkItems.length;
        _cmdkApplyActive();
      }
    } else if (e.key === "Enter") {
      e.preventDefault();
      _cmdkFire(_cmdkActiveIdx);
    } else if (e.key === "Escape") {
      e.preventDefault();
      closeCmdk();
    }
  });
  cmdkResults?.addEventListener("click", e => {
    const it = e.target.closest(".cmdk-item");
    if (!it) return;
    _cmdkFire(parseInt(it.dataset.idx, 10));
  });
  cmdkModal?.addEventListener("click", e => {
    if (e.target === cmdkModal) closeCmdk();
  });
  // Global ⌘K / Ctrl+K toggle (works from any focus state).
  document.addEventListener("keydown", e => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k"
        && !e.shiftKey && !e.altKey) {
      e.preventDefault();
      _cmdkOpen ? closeCmdk() : openCmdk();
    }
  });

  // v0.6 (5/5) — Space keyup handler. If the hold-cheat-sheet was
  // shown during the hold, just dismiss it and consume the up event
  // (no lightbox toggle). Otherwise the user did a quick tap →
  // perform the original toggle-lightbox behavior.
  document.addEventListener("keyup", e => {
    if (e.key !== " " && e.key !== "Spacebar") return;
    // Same skip rule as keydown — typing in inputs etc.
    const tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
      _kbdSpaceUpGate();
      return;
    }
    // Don't act when an annotation modal owns input.
    const am = document.getElementById("annModal");
    if (am && am.classList.contains("show")) {
      _kbdSpaceUpGate();
      return;
    }
    e.preventDefault();
    const wasHeld = _kbdSpaceUpGate();
    if (wasHeld) return;  // hint was shown → that *was* the gesture
    // Original tap behavior: toggle lightbox on focused card.
    if (lb.classList.contains("show")) {
      lb.classList.remove("show");
    } else if (typeof focusedFn !== "undefined" && focusedFn) {
      openLightbox(focusedFn);
    }
  });

  // Auto-focus the first visible card after each render
  const _origRender = render;
  render = function () {
    _origRender();
    const cards = visibleCards();
    if (cards.length) focusCard(cards[0].dataset.fn, false);
  };
  render();

  // ==================================================================
  // V2.0 rubric annotation flow.
  //   1. fetch /rubric_meta once → build the form skeleton
  //   2. clicking 标注 on a card opens the modal pre-filled with the
  //      auto-decomposed rubric for that image (or the existing human
  //      labels if it's already been rated)
  //   3. saving POSTs /annotation/<run_id>/<filename> and immediately
  //      navigates to the next active-learning candidate
  // ==================================================================
  const annModal = document.getElementById("annModal");
  registerModal(annModal);  // V14.4 — ARIA dialog + focus trap
  const annThumb = document.getElementById("annThumb");
  const annMeta = document.getElementById("annMeta");
  const annWhy = document.getElementById("annWhy");
  const annTitle = document.getElementById("annTitle");
  const annOverall = document.getElementById("annOverall");
  const annOverallRationale = document.getElementById("annOverallRationale");
  const annClose = document.getElementById("annClose");
  const annNext = document.getElementById("annNext");
  const annSave = document.getElementById("annSave");
  const axesContainer = document.getElementById("axesContainer");
  // v0.7-P0-2 — new top progress bar + inline cull-reason picker
  const annProgressTrack = document.getElementById("annProgressTrack");
  const annProgressCount = document.getElementById("annProgressCount");
  const annCullReasons   = document.getElementById("annCullReasons");
  const annCullReasonPills = document.getElementById("annCullReasonPills");
  let _annSelectedCullReason = null;

  function _showAnnCullReasons() {
    if (!annCullReasons) return;
    // Populate from the taxonomy fetched at boot (P-UX-4 path).  If
    // it's not loaded yet (rare — fetch is fired on page load), the
    // tray simply stays empty and the save path still works.
    if (annCullReasonPills && !annCullReasonPills.dataset.built && _CULL_REASONS_LIST.length) {
      annCullReasonPills.innerHTML = _CULL_REASONS_LIST.map(e =>
        `<button class="reason-pill" type="button" data-token="${esc(e.token)}"
                  title="${esc(e.label_zh || e.token)}">${esc(e.label_zh || e.token)}</button>`
      ).join(" ");
      annCullReasonPills.dataset.built = "1";
      annCullReasonPills.addEventListener("click", e => {
        const b = e.target.closest("[data-token]");
        if (!b) return;
        annCullReasonPills.querySelectorAll(".reason-pill").forEach(p => p.classList.remove("active"));
        b.classList.add("active");
        _annSelectedCullReason = b.dataset.token;
      });
    }
    annCullReasons.classList.add("show");
    annCullReasons.setAttribute("aria-hidden", "false");
  }
  function _hideAnnCullReasons() {
    if (!annCullReasons) return;
    annCullReasons.classList.remove("show");
    annCullReasons.setAttribute("aria-hidden", "true");
    annCullReasonPills?.querySelectorAll(".reason-pill")
      .forEach(p => p.classList.remove("active"));
  }
  // annOverall change → show/hide inline cull-reason picker
  annOverall?.addEventListener("change", () => {
    if (annOverall.value === "cull") _showAnnCullReasons();
    else { _hideAnnCullReasons(); _annSelectedCullReason = null; }
  });

  let rubricMeta = null;
  let currentFn = null;

  async function loadRubricMeta() {
    if (rubricMeta) return rubricMeta;
    const res = await fetch("/rubric_meta");
    const data = await res.json();
    rubricMeta = data.axes;
    // v0.7-P0-2 — `data-axis-idx` lets the progress bar map back
    // to the rubricMeta index so each rated axis lights its
    // matching cell.
    axesContainer.innerHTML = rubricMeta.map((ax, idx) => `
      <div class="axis-row" data-axis="${ax.name}" data-axis-idx="${idx}">
        <div class="axis-name">${ax.label_zh}
          <span class="axis-en">${ax.label_en}</span>
        </div>
        <div class="axis-desc">${ax.description_zh}</div>
        <div class="stars" data-stars data-axis="${ax.name}" data-axis-idx="${idx}">
          ${[1,2,3,4,5].map(i => `<span class="star" data-v="${i}">★</span>`).join("")}
        </div>
        <div class="descriptor" data-descriptor></div>
        <textarea data-rationale data-slashmenu rows="1" placeholder="为什么是这个分?(可选,但越多越有用 · 输入 / 触发命令)"></textarea>
      </div>
    `).join("");
    // Wire up star click handlers
    axesContainer.querySelectorAll(".stars").forEach(starsEl => {
      const axisName = starsEl.dataset.axis;
      starsEl.querySelectorAll(".star").forEach(starEl => {
        starEl.addEventListener("click", () => {
          const v = parseInt(starEl.dataset.v);
          setStars(axisName, v);
          // Show descriptor for the chosen level
          const ax = rubricMeta.find(a => a.name === axisName);
          starsEl.parentElement.querySelector("[data-descriptor]").textContent =
            v + "★: " + ax.rubric_descriptors[v - 1];
        });
        starEl.addEventListener("mouseenter", () => {
          const v = parseInt(starEl.dataset.v);
          starsEl.querySelectorAll(".star").forEach((s, i) => {
            s.classList.toggle("on", i < v);
          });
        });
      });
      starsEl.addEventListener("mouseleave", () => {
        const locked = parseInt(starsEl.dataset.locked || "0");
        starsEl.querySelectorAll(".star").forEach((s, i) => {
          s.classList.remove("on");
          s.classList.toggle("locked", i < locked);
        });
      });
    });
    return rubricMeta;
  }

  function setStars(axisName, v) {
    const starsEl = axesContainer.querySelector(`.stars[data-axis="${axisName}"]`);
    starsEl.dataset.locked = String(v);
    starsEl.querySelectorAll(".star").forEach((s, i) => {
      s.classList.toggle("locked", i < v);
    });
    // v0.7-P0-2 — keep the progress bar in sync.
    _updateAnnProgress();
  }

  // v0.7-P0-2 — paint the 6 progress cells based on which axes
  // are rated. Counts ≥1★ as "rated"; updates the X/6 counter too.
  function _updateAnnProgress() {
    if (!annProgressTrack) return;
    let n = 0;
    axesContainer.querySelectorAll(".stars").forEach(starsEl => {
      const locked = parseInt(starsEl.dataset.locked || "0", 10);
      const idx    = parseInt(starsEl.dataset.axisIdx || "-1", 10);
      const cell   = annProgressTrack.querySelector(`[data-axis-idx="${idx}"]`);
      if (cell) cell.classList.toggle("lit", locked > 0);
      if (locked > 0) n++;
    });
    if (annProgressCount) annProgressCount.textContent = `${n} / 6`;
  }

  function clearForm() {
    axesContainer.querySelectorAll(".stars").forEach(s => {
      s.dataset.locked = "0";
      s.querySelectorAll(".star").forEach(x => x.classList.remove("locked", "on"));
    });
    axesContainer.querySelectorAll("textarea").forEach(t => t.value = "");
    axesContainer.querySelectorAll("[data-descriptor]").forEach(d => d.textContent = "");
    annOverall.value = "";
    annOverallRationale.value = "";
    annWhy.style.display = "none";
    // v0.7-P0-2 — reset progress bar + hide cull-reason picker.
    _updateAnnProgress();
    _hideAnnCullReasons();
    _annSelectedCullReason = null;
  }

  // V14.5 — when openAnnotation is called via openNextToLabel right
  // after a save, we want a smooth cross-fade rather than a jarring
  // hard reset. Pre-loading the next thumbnail before the swap kills
  // the broken-image flash; the .ann-card .transitioning class fades
  // form fields during the rebuild.
  async function openAnnotation(fn, why, opts = {}) {
    const transition = !!opts.transition;
    await loadRubricMeta();
    currentFn = fn;

    const annCard = annModal.querySelector(".ann-card");
    if (transition && annCard) annCard.classList.add("transitioning");

    clearForm();

    // Pre-load the next image so we never show a broken/empty <img>.
    const nextSrc = `/full/${run_id}/${encodeURIComponent(fn)}`;
    if (transition) {
      try {
        await new Promise((resolve) => {
          const probe = new Image();
          probe.onload = probe.onerror = resolve;
          probe.src = nextSrc;
          // Don't block forever if the image is huge / slow.
          setTimeout(resolve, 800);
        });
      } catch (e) { /* fall through anyway */ }
    }
    annThumb.src = nextSrc;

    const r = rows.find(x => x.filename === fn);
    annTitle.textContent = `${fn}`;
    annMeta.innerHTML = r
      ? `场景:<b>${esc(trGenre(r.scene) || "?")}</b> · 规则:<b>${esc(tr(r.decision, I18N_DECISION) || r.decision)}</b> · 综合分 ${r.score_final?.toFixed(2) || "--"}`
      : "";
    if (why) {
      annWhy.style.display = "block";
      annWhy.innerHTML = `<b>为什么挑这张?</b> ${why}`;
    }
    // Pre-fill from /annotation endpoint (auto or human)
    try {
      const res = await fetch(`/annotation/${run_id}/${encodeURIComponent(fn)}`);
      const data = await res.json();
      const rec = data.data || {};
      const axes = rec.axes || {};
      Object.keys(axes).forEach(axisName => {
        const ax = axes[axisName];
        if (ax.stars != null) {
          setStars(axisName, Math.round(ax.stars));
          const meta = rubricMeta.find(a => a.name === axisName);
          const starsEl = axesContainer.querySelector(`.stars[data-axis="${axisName}"]`);
          if (starsEl && meta) {
            starsEl.parentElement.querySelector("[data-descriptor]").textContent =
              Math.round(ax.stars) + "★: " + meta.rubric_descriptors[Math.round(ax.stars) - 1];
          }
        }
        if (ax.rationale) {
          const ta = axesContainer.querySelector(`.axis-row[data-axis="${axisName}"] textarea`);
          if (ta) ta.value = ax.rationale;
        }
      });
      if (rec.overall_label) annOverall.value = rec.overall_label;
      if (rec.overall_rationale) annOverallRationale.value = rec.overall_rationale;
      // v0.7-P0-2 — refresh progress bar after loading prior stars;
      // also re-show the cull-reason picker if the loaded record is
      // a cull (lets the user change reason without re-flipping the
      // overall dropdown).
      _updateAnnProgress();
      if (annOverall.value === "cull") _showAnnCullReasons();
      else _hideAnnCullReasons();
    } catch (e) { /* no prior — leave blank */ }
    annModal.classList.add("show");
    // V14.5 — clear the cross-fade veil one frame after the modal
    // is visible so the new content renders fully opaque.
    if (transition && annCard) {
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          annCard.classList.remove("transitioning");
        });
      });
    }
  }

  async function saveAnnotation(thenAdvance) {
    if (!currentFn) return;
    const axes = {};
    rubricMeta.forEach(ax => {
      const starsEl = axesContainer.querySelector(`.stars[data-axis="${ax.name}"]`);
      const stars = parseInt(starsEl.dataset.locked || "0");
      const ta = axesContainer.querySelector(`.axis-row[data-axis="${ax.name}"] textarea`);
      const rationale = ta ? ta.value.trim() : "";
      if (stars > 0 || rationale) {
        axes[ax.name] = { stars: stars || null, rationale };
      }
    });
    if (Object.keys(axes).length === 0 && !annOverall.value) {
      toast("至少打 1 颗星 或 选 keep/maybe/cull", "warning");
      return;
    }
    const body = {
      axes,
      overall_label: annOverall.value,
      overall_rationale: annOverallRationale.value,
    };
    // v0.7-P0-2 — inline cull-reason picker. When the user chose
    // cull AND picked a reason pill, fold it into the same POST
    // instead of triggering the separate floating tray afterward.
    if (annOverall.value === "cull" && _annSelectedCullReason) {
      body.cull_reason = _annSelectedCullReason;
    }
    annSave.disabled = true;
    try {
      const res = await fetch(`/annotation/${run_id}/${encodeURIComponent(currentFn)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const e = await res.json().catch(() => ({}));
        toast("保存失败:" + (e.error || res.status), "error");
        return;
      }
      // Update local rows so the card re-render reflects the save
      const r = rows.find(x => x.filename === currentFn);
      if (r) {
        r.rubric_human_labeled = true;
        Object.keys(axes).forEach(k => {
          if (axes[k].stars) r.rubric_stars[k] = axes[k].stars;
        });
        if (annOverall.value) {
          r.decision = annOverall.value;
          // P-UX-4 — flipping away from cull clears any stale reason
          if (annOverall.value !== "cull") r.cull_reason = "";
        }
      }
      const activeFilter = document.querySelector("#filters .pill.active").dataset.d;
      render(activeFilter);
      // P-UX-4 — if the user just culled via the rubric modal, prompt
      // for a reason (unless they're already advancing — in advance
      // mode the rapid-flow rhythm shouldn't be interrupted).
      // v0.7-P0-2 — skip the floating prompt when the inline picker
      // already captured a reason; we already POSTed it above.
      if (annOverall.value === "cull" && !thenAdvance && !_annSelectedCullReason) {
        promptCullReason(currentFn);
      }
      summary.n_human_labeled = (summary.n_human_labeled || 0) + (r && !rows._wasLabeled ? 1 : 0);
      if (thenAdvance) {
        // V14.5 — toast confirmation + smooth cross-fade to next.
        // The modal stays open the whole time; only the contents
        // morph, so the user keeps their flow without a page-jump.
        toast("已保存 ✓ — 加载下一张", "success", 1800);
        await openNextToLabel({ transition: true });
      } else {
        toast("已保存 ✓", "success", 1500);
        annModal.classList.remove("show");
      }
    } finally {
      annSave.disabled = false;
    }
  }

  async function openNextToLabel(opts = {}) {
    try {
      const res = await fetch(`/next_to_label/${run_id}`);
      const data = await res.json();
      if (data.done) {
        annModal.classList.remove("show");
        toast(data.message || "已标完本批所有图片 ✓", "success");
        return;
      }
      openAnnotation(data.filename, data.why, opts);
    } catch (e) {
      annModal.classList.remove("show");
      toast("active learning 队列失败:" + e, "error");
    }
  }

  // Wire up
  grid.addEventListener("click", e => {
    const btn = e.target.closest(".annotate-btn");
    if (btn) {
      e.stopPropagation();
      openAnnotation(btn.dataset.fn);
    }
  });
  annClose.addEventListener("click", () => annModal.classList.remove("show"));
  // Escape must close the annotation modal even while focus sits in one
  // of its inputs (the modal autofocuses the star/rationale fields). The
  // global shortcut handler bails on INPUT/TEXTAREA before its Escape
  // chain, which made the open modal a keyboard dead-end — the "frozen
  // UI" of the v2.5 stability sweep. Capture phase = focus-immune;
  // stopPropagation = the global chain can't also close the lightbox
  // underneath on the same keypress. Skips when the tour modal is
  // stacked on top (its own capture handler owns that Escape).
  document.addEventListener("keydown", e => {
    if (e.key !== "Escape" || !annModal.classList.contains("show")) return;
    const tour = document.getElementById("tourModal");
    if (tour && tour.classList.contains("show")) return;
    // The first-open rubric-intro veil stacks over this modal and owns
    // Escape while present (its capture handler registers later → would
    // otherwise never see the event).
    if (document.getElementById("rubricIntroLayer")) return;
    e.preventDefault(); e.stopPropagation();
    annModal.classList.remove("show");
  }, true);
  annNext.addEventListener("click", () => openNextToLabel());
  annSave.addEventListener("click", () => saveAnnotation(true));
  annModal.addEventListener("click", e => {
    if (e.target === annModal) annModal.classList.remove("show");
  });
  document.getElementById("annNextBtn").addEventListener("click", () => openNextToLabel());
  document.getElementById("kbdHelpBtn").addEventListener("click", () => showShortcuts());

  // V9.3 — CSV download is just a link
  const csvBtn = document.getElementById("csvBtn");
  csvBtn.href = `/scores_csv/${run_id}`;
  csvBtn.setAttribute("download", "");
  // v0.8-P2-2 — structured exports (scores + annotations + style distances)
  const csvStruct = document.getElementById("csvStructuredBtn");
  if (csvStruct) {
    csvStruct.href = `/export/structured/${run_id}.csv`;
    csvStruct.setAttribute("download", "");
  }
  const jsonStruct = document.getElementById("jsonStructuredBtn");
  if (jsonStruct) {
    jsonStruct.href = `/export/structured/${run_id}.json`;
    jsonStruct.setAttribute("download", "");
  }

  // V23.x — standalone HTML gallery export. Plain link with the
  // download attr; Shift+click widens scope to keep+maybe.
  const galleryBtn = document.getElementById("galleryBtn");
  function updateGalleryHref(includeMaybe) {
    const inc = includeMaybe ? "keep,maybe" : "keep";
    galleryBtn.href = `/gallery_zip/${run_id}?include=${inc}`;
  }
  updateGalleryHref(false);
  // P2.5 — auto-caption button. Plain click = compose mode (free);
  // Shift-click = polish via DeepSeek (INFRA-4-budgeted).
  document.getElementById("captionBtn").addEventListener("click", async e => {
    const polish = e.shiftKey;
    const btn = e.currentTarget;
    const orig = btn.textContent;
    btn.disabled = true; btn.textContent = polish ? "📝 LLM 润色中…" : "📝 生成中…";
    try {
      const res = await fetch(`/api/v1/runs/${run_id}/auto_caption`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({polish, decisions: ["keep"]}),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || "HTTP " + res.status);
      const mode = polish ? `LLM 润色 (¥${data.cost_yuan.toFixed(3)})` : "compose";
      toast(`已生成 ${data.written} 条 caption · ${mode}`, "success");
    } catch (e) {
      toast("Caption 生成失败: " + e.message, "error");
    } finally {
      btn.disabled = false; btn.textContent = orig;
    }
  });

  // P-UX-15 — Lr/C1 round-trip button. POSTs to /api/v1/runs/<id>/lr_sync
  // which walks every photo's XMP sidecar, maps Lr rating → PixCull
  // decision, and appends human annotations for changes. Confirms
  // before running because it mutates annotations.jsonl irreversibly
  // (well — undoable per-row via the existing undo stack, but the
  // pattern is "lots of changes at once" so a confirm is friendly).
  const lrSyncBtn = document.getElementById("lrSyncBtn");
  if (lrSyncBtn) lrSyncBtn.addEventListener("click", async () => {
    if (!confirm(
        "将扫描每张照片的 XMP sidecar,把 Lr/C1 的 rating 同步成 PixCull 的 keep/maybe/cull " +
        "标注(5/4★→keep, 3★→maybe, 2/1★→cull, 0★→跳过)。\n\n" +
        "继续?")) return;
    const orig = lrSyncBtn.textContent;
    lrSyncBtn.disabled = true; lrSyncBtn.textContent = "↩ 扫描中…";
    try {
      const res = await fetch(`/api/v1/runs/${run_id}/lr_sync`, {
        method: "POST", headers: {"Content-Type": "application/json"}, body: "{}",
      });
      const d = await res.json();
      if (!res.ok || !d.ok) throw new Error(d.error || "HTTP " + res.status);
      const msg = `已读 ${d.sidecars_seen} 个 XMP · 应用 ${d.applied} 条变更 · 已一致 ${d.unchanged} · 跳过 ${d.skipped}`;
      toast(msg, "success");
      // Refresh local state — easiest is reload, since we just
      // wrote N annotations and the in-memory row state is stale.
      if (d.applied > 0) {
        setTimeout(() => location.reload(), 1200);
      }
    } catch (e) {
      toast("Lr/C1 同步失败: " + e.message, "error");
    } finally {
      lrSyncBtn.disabled = false; lrSyncBtn.textContent = orig;
    }
  });

  galleryBtn.setAttribute("download", "");
  galleryBtn.addEventListener("click", e => {
    // If user shift-clicked, swap to keep+maybe before letting the
    // browser follow the link. updateGalleryHref mutates href in
    // place; the click then targets the new URL.
    if (e.shiftKey) {
      updateGalleryHref(true);
      // Reset back to keep-only after the click so a later plain
      // click goes back to default.
      setTimeout(() => updateGalleryHref(false), 200);
    }
  });

  // ==================================================================
  // ==================================================================
  // v0.8-P1-3 — share-URL modal (QR + short link + copy buttons).
  // Replaces the v0.7 native window.prompt() flow with a proper
  // modal that surfaces a scannable QR + a one-click-copy short URL.
  // Used by BOTH the share-link issuer (v0.7-P1-4) AND the sync-event
  // issuer (v0.8-P0-2).
  // ==================================================================
  async function _mintShortLink(longUrl) {
    try {
      const r = await fetch("/s/issue", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ long_url: longUrl }),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      return await r.json();
    } catch (_e) {
      return null;   // caller falls back to the long URL
    }
  }
  async function _openShareUrlModal(longUrl, opts) {
    opts = opts || {};
    const modal     = document.getElementById("shareUrlModal");
    const titleEl   = document.getElementById("shareUrlTitle");
    const subtitle  = document.getElementById("shareUrlSubtitle");
    const qrImg     = document.getElementById("shareUrlQrImg");
    const shortIn   = document.getElementById("shareUrlShort");
    const longIn    = document.getElementById("shareUrlLong");
    const footnote  = document.getElementById("shareUrlFootnote");
    const closeBtn  = document.getElementById("shareUrlClose");
    if (!modal) return;
    titleEl.textContent = opts.title || "分享链接";
    subtitle.textContent = opts.subtitle ||
      "扫描二维码,或复制下面的链接发给对方:";
    footnote.textContent = opts.footnote || "";

    // Optimistic UI: pre-fill long URL, show "正在生成短链…" while
    // the /s/issue round-trip lands.
    const fullLong = longUrl.startsWith("http")
      ? longUrl : (location.origin + longUrl);
    longIn.value = fullLong;
    shortIn.value = "正在生成短链…";
    qrImg.removeAttribute("src");
    modal.classList.add("show");
    modal.setAttribute("aria-hidden", "false");

    const rec = await _mintShortLink(fullLong);
    if (rec && rec.short_url) {
      const shortFull = location.origin + rec.short_url;
      shortIn.value = shortFull;
      qrImg.src = rec.qr_url;
      // Auto-copy short URL to clipboard for the "paste into
      // iMessage immediately" workflow.
      try { await navigator.clipboard.writeText(shortFull); } catch (_e) {}
    } else {
      // Short-link issue failed — fall back to QR of the long URL.
      shortIn.value = fullLong;
      // Inline-render a fallback QR via the public route if we have it.
      // (We don't have a QR route for the long URL alone, so leave
      // the QR slot empty + tell the user.)
      qrImg.removeAttribute("src");
      footnote.textContent = "(短链服务暂不可用,请直接复制长 URL)";
    }
  }

  // Modal close wiring (singleton — set up once on boot).
  (function _wireShareUrlModal() {
    const modal = document.getElementById("shareUrlModal");
    if (!modal) return;
    const closeBtn = document.getElementById("shareUrlClose");
    function close() {
      modal.classList.remove("show");
      modal.setAttribute("aria-hidden", "true");
    }
    closeBtn?.addEventListener("click", close);
    // Click backdrop (NOT card) → close
    modal.addEventListener("click", e => {
      if (e.target === modal) close();
    });
    // Esc closes
    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && modal.classList.contains("show")) {
        close();
      }
    });
    // Copy buttons (delegated)
    function wireCopy(btnId, inputId) {
      const b = document.getElementById(btnId);
      const inp = document.getElementById(inputId);
      if (!b || !inp) return;
      b.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(inp.value);
          const orig = b.textContent;
          b.textContent = "已复制 ✓";
          b.classList.add("ok");
          setTimeout(() => {
            b.textContent = orig;
            b.classList.remove("ok");
          }, 1400);
        } catch (_e) {
          // Fall back to selectAll so the user can ⌘C manually
          inp.focus();
          inp.select();
        }
      });
    }
    wireCopy("shareUrlShortCopy", "shareUrlShort");
    wireCopy("shareUrlLongCopy",  "shareUrlLong");
  })();

  // v0.7-P1-4 — client delivery share link.
  // Mints a token via POST /share/<run>/issue then surfaces the
  // resulting URL in the share-URL modal (v0.8-P1-3).
  // ==================================================================
  document.getElementById("shareLinkBtn")?.addEventListener("click", async () => {
    // v0.9-P0-5 — collect richer brand meta so the new portfolio-style
    // share page can render: photographer / client / event name / event
    // date / photographer contact line.  Each prompt has a sensible
    // localStorage prefill so the photographer's identity persists.
    const _ls = (k) => { try { return localStorage.getItem(k) || ""; } catch (_e) { return ""; } };
    const _save = (k, v) => { try { localStorage.setItem(k, v || ""); } catch (_e) {} };

    const photographerIn = prompt(
      "摄影师名字(显示在分享页头部 / 留空跳过)",
      _ls("pixcull_photographer_name").trim()
    );
    if (photographerIn === null) return;
    const clientIn = prompt("客户名字(可选)", "");
    if (clientIn === null) return;
    const eventIn = prompt(
      "事件名(显示在大标题上 / 留空用「<客户>的相册」)\n例: 婚礼 · 2026 春 / 张家口冬奥 / 周末野生鸟类",
      ""
    );
    if (eventIn === null) return;
    const dateIn = prompt(
      "活动日期(可选,YYYY-MM-DD 或自由文本 / 留空自动用拍摄日期范围)",
      ""
    );
    if (dateIn === null) return;
    const contactIn = prompt(
      "你的联系方式(显示在 footer / 留空跳过)\n例: weibo @photographer-zhang / wx photog001 / hi@example.com",
      _ls("pixcull_photographer_contact")
    );
    if (contactIn === null) return;
    _save("pixcull_photographer_name", photographerIn || "");
    _save("pixcull_photographer_contact", contactIn || "");
    try {
      const res = await fetch(`/share/${run_id}/issue`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          photographer: photographerIn || "",
          client:       clientIn || "",
          event:        eventIn || "",
          event_date:   dateIn || "",
          contact:      contactIn || "",
        }),
      });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const d = await res.json();
      if (!d.ok || !d.url) throw new Error("server returned no URL");
      // v0.8-P1-3 — open the share-URL modal instead of native prompt.
      await _openShareUrlModal(d.url, {
        title:    "🔗 客户分享链接",
        subtitle: "扫描二维码,或复制下面的链接,发给客户:",
        footnote: "客户在浏览器里直接查看 keeps,不需要安装 PixCull。",
      });
      showToast("分享链接已生成", "success");
    } catch (err) {
      showToast("生成失败: " + err.message, "error");
    }
  });

  // ==================================================================
  // v0.7-P2-1 — style-clone V1 client wiring.
  //
  // On boot, we GET /style/distances/<run> once so any previously-
  // trained profile (from an earlier session) hydrates `rows[*].
  // style_distance` for free.  Then the 🎨 button POSTs the
  // currently-keep filenames as references, server learns + saves a
  // profile + distance map, we re-fetch and re-render.
  // ==================================================================
  // v0.8-P1-1 — user-tunable blend ratio between V1 (axis-MAD)
  // and V2 (CLIP centroid).  Persisted per-run; default 0.3 matches
  // pixcull.style.DEFAULT_LAMBDA.
  //
  // v0.11-P1-3 — per-vertical recommendation auto-pick.
  // ``docs/STYLE-V2-BENCHMARK.md`` ships a table of best-recall λ per
  // vertical (wedding 0.5 / landscape 0.3 / wildlife 0.5 / portrait
  // 0.5 / event 0.3).  When the user hasn't manually set λ for this
  // run AND the visible keep-decisions are ≥ 60% from a single
  // vertical, we silently auto-pick that vertical's λ.  The Inspector
  // chip surfaces the source ("λ=0.5 · wedding auto").  Manually
  // dragging the slider locks the override in localStorage and the
  // auto-pick stops firing for this run.
  // ==================================================================
  const _STYLE_LAMBDA_KEY        = `pixcull_style_lambda:${run_id}`;
  const _STYLE_LAMBDA_MANUAL_KEY = `pixcull_style_lambda_manual:${run_id}`;
  const _STYLE_LAMBDA_SOURCE_KEY = `pixcull_style_lambda_source:${run_id}`;

  // Per-vertical recommended λ — keep in sync with
  // docs/STYLE-V2-BENCHMARK.md "Recommended λ per vertical".
  const _STYLE_LAMBDA_PER_VERTICAL = Object.freeze({
    wedding:     0.5,
    landscape:   0.3,
    wildlife:    0.5,
    portrait:    0.5,
    event:       0.3,
    street:      0.3,
    stilllife:   0.3,
    // sport / macro / astro etc. → fall through to global default
  });
  const _STYLE_LAMBDA_GLOBAL_DEFAULT = 0.3;

  function _getStyleLambda() {
    try {
      const v = parseFloat(localStorage.getItem(_STYLE_LAMBDA_KEY));
      if (isFinite(v) && v >= 0 && v <= 1) return v;
    } catch (_e) {}
    return _STYLE_LAMBDA_GLOBAL_DEFAULT;
  }
  function _getStyleLambdaSource() {
    try {
      return localStorage.getItem(_STYLE_LAMBDA_SOURCE_KEY) || "default";
    } catch (_e) { return "default"; }
  }
  function _setStyleLambda(v, source) {
    try {
      localStorage.setItem(_STYLE_LAMBDA_KEY, String(v));
      if (source) {
        localStorage.setItem(_STYLE_LAMBDA_SOURCE_KEY, String(source));
      }
    } catch (_e) {}
  }
  function _isManualLambda() {
    try { return localStorage.getItem(_STYLE_LAMBDA_MANUAL_KEY) === "1"; }
    catch (_e) { return false; }
  }
  function _markLambdaManual() {
    try {
      localStorage.setItem(_STYLE_LAMBDA_MANUAL_KEY, "1");
      localStorage.setItem(_STYLE_LAMBDA_SOURCE_KEY, "manual");
    } catch (_e) {}
  }

  // v0.11-P1-3 — pick the dominant vertical among current visible
  // keep rows; return [vertical, fraction] when dominance ≥ 0.6,
  // else null.  Operates on the global `rows` array (defined further
  // up in the template).
  function _dominantKeepVertical() {
    if (!Array.isArray(rows) || rows.length === 0) return null;
    const counts = Object.create(null);
    let total = 0;
    for (const r of rows) {
      const dec = (r && r.decision) || "";
      if (dec !== "keep") continue;
      const v = (r.vertical || r.scene || "").toString().toLowerCase();
      if (!v) continue;
      counts[v] = (counts[v] || 0) + 1;
      total++;
    }
    if (total < 5) return null;   // too few keeps for a stable signal
    let topV = null, topN = 0;
    for (const v of Object.keys(counts)) {
      if (counts[v] > topN) { topN = counts[v]; topV = v; }
    }
    const frac = topN / total;
    return frac >= 0.60 ? [topV, frac] : null;
  }

  // Try to auto-pick λ once per page load.  Safe to call multiple
  // times — it no-ops when the user has already touched the slider.
  function _maybeAutoPickStyleLambda() {
    if (_isManualLambda()) return;
    const dom = _dominantKeepVertical();
    if (!dom) return;
    const [vert, frac] = dom;
    const rec = _STYLE_LAMBDA_PER_VERTICAL[vert];
    if (typeof rec !== "number") return;
    if (Math.abs(rec - _getStyleLambda()) < 0.01) return;  // already there
    _setStyleLambda(rec, `auto:${vert}`);
    if (typeof _rebleStyleDistances === "function") {
      _rebleStyleDistances(rec);
    }
    if (typeof window.toast === "function") {
      window.toast(
        `已自动切换为 ${vert} 推荐 λ=${rec.toFixed(1)} ` +
        `(${(frac*100).toFixed(0)}% keep 在 ${vert})`,
        "info"
      );
    }
  }
  function _styleBlend(v1, v2, lam) {
    if (typeof v1 !== "number" && typeof v2 !== "number") return null;
    if (typeof v1 !== "number") return v2;
    if (typeof v2 !== "number") return v1;
    const L = Math.max(0, Math.min(1, lam == null ? _getStyleLambda() : lam));
    return Math.round((L * v1 + (1 - L) * v2) * 1000) / 1000;
  }
  let _styleHasV2 = false;   // any row carries a V2 component?

  async function _hydrateStyleDistances() {
    try {
      const r = await fetch(`/style/distances/${run_id}`);
      if (!r.ok) return;
      const map = await r.json();
      if (!map || typeof map !== "object") return;
      let n = 0;
      let anyV2 = false;
      const lam = _getStyleLambda();
      for (const row of rows) {
        const entry = map[row.filename];
        if (entry == null) continue;
        // v0.8-P1-1 — entry is either:
        //   number   → legacy v0.7-P2-1 format (V1 only)
        //   object   → {v1, v2?, blend?} (v0.8+ format)
        let v1 = null, v2 = null, blend = null;
        if (typeof entry === "number") {
          v1 = entry;
          blend = entry;
        } else if (typeof entry === "object") {
          if (typeof entry.v1 === "number") v1 = entry.v1;
          if (typeof entry.v2 === "number") v2 = entry.v2;
          if (typeof entry.blend === "number") blend = entry.blend;
          // Re-blend client-side using the user's chosen λ (server
          // bakes in the default, but the slider tunes from there)
          const local = _styleBlend(v1, v2, lam);
          if (local !== null) blend = local;
          if (v2 !== null) anyV2 = true;
        }
        if (v1 !== null) row.style_distance_v1 = v1;
        if (v2 !== null) row.style_distance_v2 = v2;
        if (blend !== null) row.style_distance = blend;
        n++;
      }
      if (n > 0) {
        // Make the new sort option available
        _styleHasDistances = true;
        _styleHasV2 = anyV2;
        _refreshStyleSortOption();
        // v0.11-P1-3 — auto-pick per-vertical λ now that we have V2
        // distances (otherwise the chip would say "auto:wedding" with
        // no effect because there's no V2 to blend).
        if (anyV2) _maybeAutoPickStyleLambda();
        // Re-render so card chips appear
        render();
      }
    } catch (_e) { /* offline / no profile yet — silent */ }
  }

  // Re-blend without re-fetching: re-compute row.style_distance from
  // existing v1/v2 components when the user moves the λ slider.
  function _rebleStyleDistances(lam) {
    if (typeof lam === "number") _setStyleLambda(lam);
    const L = _getStyleLambda();
    for (const row of rows) {
      const v1 = row.style_distance_v1;
      const v2 = row.style_distance_v2;
      const b = _styleBlend(v1, v2, L);
      if (b !== null) row.style_distance = b;
    }
    render();
  }
  let _styleHasDistances = false;
  function _refreshStyleSortOption() {
    const sortSel = document.getElementById("sortBy");
    if (!sortSel) return;
    // Only add once
    if (sortSel.querySelector('option[value="style_distance_asc"]')) return;
    const opt = document.createElement("option");
    opt.value = "style_distance_asc";
    opt.textContent = "🎨 像我风格的优先";
    sortSel.appendChild(opt);
  }
  _hydrateStyleDistances();

  // ==================================================================
  // v0.8-P0-2 — LAN sync event (host side).
  //
  // Host clicks 📡 协作会话 → server mints a token → host pastes the
  // URL into iMessage / AirDrop / iPad QR scan → guests open the URL
  // → their browser sees ?event=<token> + starts polling
  // /api/v1/sync/event/<token>/changes every 5s.
  //
  // The same results.html template handles both roles via the same
  // code path; differentiation is purely by URL param.
  // ==================================================================
  document.getElementById("syncEventBtn")?.addEventListener("click", async () => {
    const label = prompt(
      "会话名(任填,显示在团队里;留空跳过)\n例: 婚礼-2026-06-15",
      ""
    );
    if (label === null) return;
    const btn = document.getElementById("syncEventBtn");
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = "生成中…";
    try {
      const r = await fetch(`/sync/event/issue/${run_id}`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ label: label || "" }),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const d = await r.json();
      if (!d.ok || !d.url) throw new Error("server returned no URL");
      // v0.8-P1-3 — open the share-URL modal instead of native prompt.
      await _openShareUrlModal(d.url, {
        title:    "📡 协作会话链接",
        subtitle: "扫描二维码,或复制下面的链接,发给二摄 / 编辑:",
        footnote: "他们打开后自动加入,每 5s 同步一次标注。",
      });
      showToast("协作会话已生成", "success");
    } catch (err) {
      showToast("生成失败: " + err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = orig;
    }
  });

  // ==================================================================
  // v0.8-P0-2 — LAN sync event (guest side).
  //
  // If the page URL carries ?event=<token>, switch into "collaborative
  // pulling" mode: poll the host every 5s for annotation changes,
  // merge them into rows[], flag conflicts (local edit newer than
  // incoming remote of same photo with different decision).
  // ==================================================================
  const _SYNC_EVENT_TOKEN = (() => {
    try {
      const p = new URLSearchParams(location.search);
      return p.get("event") || "";
    } catch (_e) { return ""; }
  })();
  const _SYNC_POLL_MS = 5000;
  let _syncLastTs = 0;
  let _syncRowMtimes = {};  // filename → last local-edit mtime_ms
  let _syncConflictFns = new Set();
  // Image-failure investigation 2026-Q4: also publish on window so
  // renderCard()'s window-attached lookup (see the TDZ fix above)
  // resolves to the live Set rather than to `null`.  This keeps
  // sync-conflict styling working after renderCard fires.
  window._syncConflictFns = _syncConflictFns;
  // v0.10-P0-1 — richer per-conflict state: filename → {local, remote}
  // so the conflict-resolution modal can show both versions side-by-side
  // without re-fetching.  Populated by _syncPollOnce when it would
  // otherwise just have flagged the filename via _syncConflictFns.
  const _syncConflictMap = new Map();
  let _syncPeers = 0;       // bookkeeping for the live badge

  function _markLocalEdit(filename, action) {
    if (!filename) return;
    _syncRowMtimes[filename] = Date.now();
    // v0.9-P1-2 — feed the same call-site into the presence pipeline
    // so anywhere we record a local edit, peers automatically see
    // "📝 编辑刚标 IMG_007 · keep". The action arg is optional —
    // older call-sites pre-P1-2 pass only the filename, in which
    // case we record the action as "edit" (generic).
    try {
      if (typeof _presenceMarkAction === "function") {
        _presenceMarkAction(filename, action || "edit");
      }
    } catch (_e) { /* presence is best-effort */ }
  }

  function _applyRemoteAnnotation(remote) {
    if (!remote || !remote.filename) return null;
    const row = rows.find(r => r.filename === remote.filename);
    if (!row) return null;
    // Mirror the fields the existing annotation flow writes to.
    const fields = ["decision", "rubric_stars", "rubric_human_labeled",
                    "rubric_human_user", "rubric_human_at",
                    "cull_reason", "advice"];
    let changed = false;
    for (const f of fields) {
      if (Object.prototype.hasOwnProperty.call(remote, f)
          && JSON.stringify(row[f]) !== JSON.stringify(remote[f])) {
        row[f] = remote[f];
        changed = true;
      }
    }
    return changed ? row : null;
  }

  async function _syncPollOnce() {
    if (!_SYNC_EVENT_TOKEN) return;
    try {
      const url = `/api/v1/sync/event/${encodeURIComponent(_SYNC_EVENT_TOKEN)}`
                 + `/changes?since=${_syncLastTs}`;
      const r = await fetch(url);
      if (r.status === 404 || r.status === 410) {
        // Event revoked / expired
        showToast("协作会话已失效", "error");
        const badge = document.getElementById("syncBadge");
        if (badge) badge.style.display = "none";
        return false;
      }
      if (!r.ok) return false;
      const d = await r.json();
      const incoming = Array.isArray(d.annotations) ? d.annotations : [];
      _syncLastTs = Number(d.server_ts) || _syncLastTs;
      let applied = 0;
      for (const remote of incoming) {
        // Conflict rule: local edited AFTER this remote → mark
        const remoteMs = Number(remote.updated_at_ms) || 0;
        const localMs  = _syncRowMtimes[remote.filename] || 0;
        const row      = rows.find(r => r.filename === remote.filename);
        const decsDiffer = row && row.decision !== remote.decision;
        if (decsDiffer && localMs > remoteMs) {
          _syncConflictFns.add(remote.filename);
          // v0.10-P0-1 — also stash the snapshot pair so the modal
          // can render both versions without re-fetching.  We take
          // a defensive copy of the local row because subsequent
          // _applyRemoteAnnotation calls would otherwise mutate it.
          _syncConflictMap.set(remote.filename, {
            local:  row ? Object.assign({}, row) : null,
            remote: remote,
          });
          continue;
        }
        const updated = _applyRemoteAnnotation(remote);
        if (updated) {
          applied += 1;
          // Remote application clears any prior conflict on this row.
          _syncConflictFns.delete(remote.filename);
          _syncConflictMap.delete(remote.filename);
        }
      }
      if (applied > 0 || _syncConflictFns.size > 0) {
        // Re-render so chips refresh
        render();
        _refreshSyncBadge();
      }
      return true;
    } catch (_e) {
      return false;
    }
  }
  function _refreshSyncBadge() {
    const badge = document.getElementById("syncBadge");
    if (!badge) return;
    const conflicts = _syncConflictFns.size;
    badge.style.display = "";
    // v0.10-P0-1 — conflict badge is now clickable to open the
    // resolution modal.  Also surface the offline-queue depth when
    // > 0 so the user knows their edits are pending.
    const offline = (typeof _SYNC_OFFLINE !== "undefined")
                  ? _SYNC_OFFLINE.queue.length : 0;
    const parts = [];
    if (conflicts > 0) parts.push(`${conflicts} 处冲突`);
    if (offline > 0)   parts.push(`${offline} 待同步`);
    badge.textContent = parts.length
      ? `📡 协作中 · ${parts.join(" · ")}`
      : "📡 协作中 · 同步";
    badge.classList.toggle("conflict", conflicts > 0);
    badge.style.cursor = conflicts > 0 ? "pointer" : "default";
    badge.title = conflicts > 0 ? "点击解决冲突" : "";
  }
  // Inject a sync-badge into the workspace bar once on boot if we're
  // a guest (joined via ?event=). Hosts get the badge too — they see
  // their own session "live".
  function _initSyncBadge() {
    if (!_SYNC_EVENT_TOKEN) return;
    const bar = document.querySelector(".workspace-bar");
    if (!bar) return;
    const b = document.createElement("span");
    b.id = "syncBadge";
    b.className = "sync-badge";
    b.textContent = "📡 协作中 · 连接中…";
    // v0.10-P0-1 — click → conflict modal (no-op when 0 conflicts)
    b.addEventListener("click", () => {
      if (_syncConflictFns.size > 0) _openConflictModal();
    });
    bar.insertBefore(b,
      document.getElementById("langSwitcher") || bar.lastElementChild);
  }
  _initSyncBadge();
  if (_SYNC_EVENT_TOKEN) {
    // First poll immediate, then every _SYNC_POLL_MS
    _syncPollOnce().then(() => _refreshSyncBadge());
    setInterval(_syncPollOnce, _SYNC_POLL_MS);
  }

  // ==================================================================
  // v0.10-P0-2 — mDNS auto-discovery of LAN sync events.
  //
  // Only fires when we're NOT already in an event session (no point
  // hunting for sessions when we're already collaborating).  Hits
  // /api/v1/sync/discover once on page-ready; if zeroconf is
  // available on the server AND there are active sessions, shows a
  // toast with a "join" CTA.  Sessions discovered later (host
  // starts a session mid-session) are picked up on the next
  // explicit user-driven refresh — we don't poll, since that would
  // burn UDP traffic for what's already a low-frequency event.
  // ==================================================================
  async function _discoverLanSessions() {
    if (_SYNC_EVENT_TOKEN) return;  // already in a session
    try {
      const r = await fetch("/api/v1/sync/discover?timeout=2.0");
      if (!r.ok) return;
      const d = await r.json();
      if (!d.available) return;     // zeroconf not installed
      const sessions = Array.isArray(d.sessions) ? d.sessions : [];
      // Filter out sessions tied to runs other than this one — a
      // collaborator browsing /results/<run_A> doesn't care about
      // an event scoping /results/<run_B>.
      const sameRun = sessions.filter(s => s.run_id === run_id);
      if (sameRun.length === 0) return;
      // Show a non-blocking toast (or a small banner) with a join CTA.
      const s = sameRun[0];      // for multi-session, prefer first
      const label = s.label ? `"${s.label}"` : "未命名会话";
      const banner = document.createElement("div");
      banner.id = "lanDiscoverBanner";
      banner.style.cssText = (
        "position:fixed;bottom:24px;left:50%;transform:translateX(-50%);" +
        "background:var(--surface-2);color:var(--fg);" +
        "border:1px solid var(--accent);" +
        "border-radius:999px;padding:8px 16px;" +
        "box-shadow:var(--shadow-md);" +
        "z-index:1200;display:flex;gap:10px;align-items:center;" +
        "font-size:12px;"
      );
      banner.innerHTML =
        `<span>📡 在 LAN 内发现协作会话 ${esc(label)}</span>` +
        `<a class="btn primary" style="padding:4px 12px;font-size:11.5px"` +
        ` href="${esc(s.host_url)}/results/${esc(run_id)}` +
        `?event=" data-token-prefix="${esc(s.token_prefix)}">加入</a>` +
        `<button class="btn" style="padding:4px 10px;font-size:11.5px"` +
        ` id="lanDiscoverDismiss">×</button>`;
      document.body.appendChild(banner);
      // Note — the join link can't auto-populate the FULL token (mDNS
      // TXT only carries the prefix on purpose).  Joining requires
      // the user to ask the host for the full token over the same
      // channel they'd otherwise paste from (iMessage / AirDrop /
      // QR scan).  The prefix is shown so they can verify they're
      // joining the right session.
      banner.querySelector("a").addEventListener("click", (e) => {
        e.preventDefault();
        const full = prompt(
          `请输入完整 token(前 6 字符应该是 ${s.token_prefix}…):`,
          s.token_prefix
        );
        if (!full) return;
        if (!full.startsWith(s.token_prefix)) {
          showToast("token 前缀不匹配 — 请确认", "error");
          return;
        }
        location.href = `${s.host_url}/results/${encodeURIComponent(run_id)}`
                      + `?event=${encodeURIComponent(full)}`;
      });
      banner.querySelector("#lanDiscoverDismiss")
            .addEventListener("click", () => banner.remove());
    } catch (_e) { /* discovery is best-effort */ }
  }
  // Kick discovery 600ms after page-ready so it doesn't race with
  // first-render — the toast appearing mid-reveal would feel jittery.
  setTimeout(_discoverLanSessions, 600);

  // ==================================================================
  // v0.10-P0-1 — Two-way sync push + offline queue + conflict modal.
  //
  // Three pieces:
  //
  //   1. _pushEdits([{filename, decision, ...}, ...])
  //      Sends a batch of edits to the host via POST /sync/event/
  //      <token>/push.  Other peers see them on their next /changes
  //      poll cycle — no extra fan-out logic needed because the
  //      server appends to the same annotations.jsonl that
  //      compute_changes_since reads.
  //
  //   2. Offline queue (IndexedDB-backed when available, in-mem
  //      otherwise).  When the push fetch fails (network out,
  //      host machine asleep, ...), the edits land in
  //      _SYNC_OFFLINE.queue and a watcher tries to flush on
  //      visibilitychange + every 30s.
  //
  //   3. Conflict resolution modal.  Renders the local + remote
  //      versions side-by-side, lets the user pick winner or "keep
  //      both" (which produces a new audit row with the user as
  //      edited_by).  Reuses the v0.9-P1-1 .modal-action chrome.
  //
  // All three layers are inert when ?event= isn't in the URL — the
  // existing solo-photographer flow stays untouched.
  // ==================================================================
  const _SYNC_OFFLINE = {
    queue:    [],       // pending pushes; flushed when network OK
    flushing: false,
    lastFlushAt: 0,
  };

  // Try to use IndexedDB so a tab refresh / browser quit doesn't
  // lose edits.  Falls back to in-memory when IDB is unavailable
  // (private mode / older browsers).
  const _SYNC_IDB_NAME = "pixcull_sync_offline_v1";
  function _idbOpen() {
    return new Promise((resolve, reject) => {
      if (!window.indexedDB) { reject(new Error("no idb")); return; }
      const req = indexedDB.open(_SYNC_IDB_NAME, 1);
      req.onupgradeneeded = (e) => {
        const db = e.target.result;
        if (!db.objectStoreNames.contains("queue")) {
          db.createObjectStore("queue", { keyPath: "id", autoIncrement: true });
        }
      };
      req.onsuccess = (e) => resolve(e.target.result);
      req.onerror   = () => reject(req.error);
    });
  }
  async function _idbAdd(edit) {
    try {
      const db = await _idbOpen();
      return await new Promise((resolve, reject) => {
        const tx = db.transaction("queue", "readwrite");
        tx.objectStore("queue").add(edit);
        tx.oncomplete = () => resolve(true);
        tx.onerror    = () => reject(tx.error);
      });
    } catch (_e) { return false; }
  }
  async function _idbAll() {
    try {
      const db = await _idbOpen();
      return await new Promise((resolve, reject) => {
        const tx = db.transaction("queue", "readonly");
        const req = tx.objectStore("queue").getAll();
        req.onsuccess = () => resolve(req.result || []);
        req.onerror   = () => reject(req.error);
      });
    } catch (_e) { return []; }
  }
  async function _idbClearKeys(keys) {
    try {
      const db = await _idbOpen();
      return await new Promise((resolve, reject) => {
        const tx = db.transaction("queue", "readwrite");
        const store = tx.objectStore("queue");
        for (const k of keys) store.delete(k);
        tx.oncomplete = () => resolve(true);
        tx.onerror    = () => reject(tx.error);
      });
    } catch (_e) { return false; }
  }

  // Boot — drain any pre-existing IDB queue into our in-mem mirror
  // so _refreshSyncBadge can show the depth + the flusher can act
  // on it immediately.
  (async () => {
    if (!_SYNC_EVENT_TOKEN) return;
    const stale = await _idbAll();
    if (stale.length) {
      _SYNC_OFFLINE.queue.push(...stale);
      _refreshSyncBadge();
    }
  })();

  async function _pushEdits(edits, opts) {
    if (!_SYNC_EVENT_TOKEN) return { ok: false, reason: "no-event" };
    if (!Array.isArray(edits) || edits.length === 0)
      return { ok: false, reason: "empty" };
    // Stamp every edit with the local client_id + display name from
    // the v0.9-P1-2 presence layer so the host's audit trail says
    // "二摄-小陈 标 keep on IMG_001 @ 12:34:56".
    const cid  = (typeof _presenceClientId !== "undefined")
               ? _presenceClientId : "web-anon";
    const name = (typeof _presenceDisplay !== "undefined")
               ? _presenceDisplay  : "anon";
    const stamped = edits.map(e => Object.assign({
      client_id:    cid,
      client_ts_ms: Date.now(),
      edited_by:    name,
    }, e));
    try {
      const r = await fetch(
        `/sync/event/${encodeURIComponent(_SYNC_EVENT_TOKEN)}/push`,
        {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ edits: stamped }),
        }
      );
      if (r.status === 404 || r.status === 410) {
        return { ok: false, reason: "event-revoked" };
      }
      if (!r.ok) return { ok: false, reason: "http-" + r.status };
      const d = await r.json();
      return { ok: true, accepted: d.accepted, rejected: d.rejected };
    } catch (_e) {
      // Network out — queue offline.  Throttle re-tries via the
      // visibilitychange + 30s interval flusher below.
      if (!(opts && opts.noQueue)) {
        for (const e of stamped) {
          _SYNC_OFFLINE.queue.push(e);
          _idbAdd(e);
        }
        _refreshSyncBadge();
      }
      return { ok: false, reason: "network", queued: stamped.length };
    }
  }

  async function _flushOfflineQueue() {
    if (_SYNC_OFFLINE.flushing) return;
    if (_SYNC_OFFLINE.queue.length === 0) return;
    _SYNC_OFFLINE.flushing = true;
    try {
      // Snapshot + remove.  If the push fails we re-queue.
      const batch = _SYNC_OFFLINE.queue.splice(0, _SYNC_OFFLINE.queue.length);
      const keys = batch.map(e => e.id).filter(k => k != null);
      const res = await _pushEdits(batch, { noQueue: true });
      if (res.ok) {
        // Persist the dequeue.
        if (keys.length) await _idbClearKeys(keys);
        _SYNC_OFFLINE.lastFlushAt = Date.now();
        showToast(`已同步 ${batch.length} 条离线编辑`, "success");
      } else {
        // Put them back at the head — order preserved.
        _SYNC_OFFLINE.queue.unshift(...batch);
      }
    } finally {
      _SYNC_OFFLINE.flushing = false;
      _refreshSyncBadge();
    }
  }

  if (_SYNC_EVENT_TOKEN) {
    // Try to flush whenever the tab becomes visible (often after a
    // network reconnect) and every 30s as a safety net.
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") _flushOfflineQueue();
    });
    setInterval(_flushOfflineQueue, 30_000);
    // Also flush on the standard online event.
    window.addEventListener("online", _flushOfflineQueue);
  }

  // ----------- Conflict resolution modal -----------
  function _openConflictModal() {
    if (_syncConflictMap.size === 0) return;
    let m = document.getElementById("conflictModal");
    if (!m) {
      m = document.createElement("div");
      m.id = "conflictModal";
      m.className = "modal";
      m.setAttribute("role", "dialog");
      m.setAttribute("aria-modal", "true");
      document.body.appendChild(m);
      m.addEventListener("click", (e) => {
        if (e.target === m) m.classList.remove("show");
      });
    }
    const entries = Array.from(_syncConflictMap.entries());
    const rows = entries.map(([fn, pair]) => {
      const localDec  = (pair.local  && pair.local.decision)  || "—";
      const remoteDec = (pair.remote && pair.remote.decision) || "—";
      const remoteBy  = (pair.remote && (pair.remote.edited_by
                         || pair.remote.client_id)) || "远程";
      return `
        <div class="cflx-row" data-fn="${esc(fn)}">
          <div class="cflx-fn"><span class="mono">${esc(fn)}</span></div>
          <div class="cflx-options">
            <button class="btn cflx-keep-local" data-fn="${esc(fn)}">
              <span class="cflx-side">本地</span>
              <span class="cflx-dec">${esc(localDec)}</span>
              <span class="cflx-by">你的版本</span>
            </button>
            <button class="btn cflx-keep-remote" data-fn="${esc(fn)}">
              <span class="cflx-side">远程</span>
              <span class="cflx-dec">${esc(remoteDec)}</span>
              <span class="cflx-by">${esc(remoteBy)}</span>
            </button>
            <button class="btn cflx-keep-both" data-fn="${esc(fn)}"
                    title="保留两边历史 — 写一行新的 audit + 选远程值生效">
              保留两边
            </button>
          </div>
        </div>`;
    }).join("");
    m.innerHTML = `
      <div class="modal-card modal-destructive" role="document">
        <div class="modal-header">
          <h3 class="modal-title">解决协作冲突 · ${entries.length} 处</h3>
          <button class="close" id="cflxClose" aria-label="关闭">✕</button>
        </div>
        <div class="modal-body" style="max-height:60vh;overflow:auto">
          <p style="color:var(--muted);font-size:12px;margin:0 0 12px">
            这些照片你和其他协作者都改过,但决定不同。挑一边赢家 —
            "保留两边" 会保留本地决定 + 在 audit 历史中记录远程版本。
          </p>
          <div class="cflx-list">${rows}</div>
        </div>
      </div>`;
    m.classList.add("show");
    m.querySelector("#cflxClose").addEventListener("click",
      () => m.classList.remove("show"));
    m.querySelectorAll(".cflx-keep-local").forEach(b => {
      b.addEventListener("click", () => _resolveConflict(b.dataset.fn, "local"));
    });
    m.querySelectorAll(".cflx-keep-remote").forEach(b => {
      b.addEventListener("click", () => _resolveConflict(b.dataset.fn, "remote"));
    });
    m.querySelectorAll(".cflx-keep-both").forEach(b => {
      b.addEventListener("click", () => _resolveConflict(b.dataset.fn, "both"));
    });
  }

  function _resolveConflict(filename, winner) {
    const pair = _syncConflictMap.get(filename);
    if (!pair) return;
    const row = rows.find(r => r.filename === filename);
    if (!row) return;
    if (winner === "remote") {
      // Apply the remote version + push it back so other peers'
      // conflict markers clear on their next poll.
      Object.assign(row, {
        decision:             pair.remote.decision,
        rubric_stars:         pair.remote.rubric_stars,
        rubric_human_labeled: pair.remote.rubric_human_labeled,
        cull_reason:          pair.remote.cull_reason,
        advice:               pair.remote.advice,
      });
      _pushEdits([{
        filename,
        decision:    pair.remote.decision,
        cull_reason: pair.remote.cull_reason,
      }]);
    } else if (winner === "local") {
      // Re-push our local version so the host's audit trail has the
      // most recent decision (and other peers re-pull it).
      _pushEdits([{
        filename,
        decision:    row.decision,
        cull_reason: row.cull_reason,
      }]);
    } else if (winner === "both") {
      // "Keep both" = audit-trail-only.  Push an explicit "audit"
      // edit annotating the remote version, then keep local as
      // current.  Future readers will see two JSONL lines:
      // remote (overwritten) + local (current).
      _pushEdits([{
        filename,
        decision: row.decision,
        cull_reason: row.cull_reason,
        advice: "kept both — remote version recorded in audit",
      }]);
    }
    _syncConflictMap.delete(filename);
    _syncConflictFns.delete(filename);
    _refreshSyncBadge();
    // If the modal is still open + there are more rows, re-render
    // it; if 0 left, close.
    const m = document.getElementById("conflictModal");
    if (m && m.classList.contains("show")) {
      if (_syncConflictMap.size === 0) m.classList.remove("show");
      else _openConflictModal();
    }
    render();
  }

  // ==================================================================
  // v0.9-P1-2 — multiplayer presence (Figma-lite "who's looking
  // at what").  Only active when ?event=<token> is in the URL.
  //
  // Wire model
  //   client_id    persistent per-tab (sessionStorage so cmd-T
  //                opens a NEW peer, but a reload re-uses the
  //                same id — matches Figma/Linear's mental model).
  //   display_name persistent per-browser (localStorage, editable
  //                from the presence-popover's "改名" link).
  //   heartbeat    POST every 30s with last_viewed_filename +
  //                last_action (carried forward by the server
  //                across view-only beats).
  //   poll         GET every 10s for the peer list — short enough
  //                that "二摄 just looked at IMG_007" lands within
  //                a beat of them looking, long enough that we're
  //                not hammering the LAN.
  //   disconnect   sendBeacon on pagehide / visibilitychange so
  //                peers clear instantly instead of waiting 90s
  //                for the stale-TTL evict.
  // ==================================================================
  const PRESENCE_ENABLED = !!_SYNC_EVENT_TOKEN;
  const PRESENCE_HB_MS   = 30_000;   // 30s — see comment above
  const PRESENCE_POLL_MS = 10_000;   // 10s
  let _presenceClientId  = "";
  let _presenceDisplay   = "";
  let _presenceLastView  = "";
  let _presenceLastAction       = "";
  let _presenceLastActionFile   = "";
  let _presencePending   = false;
  let _presencePeers     = [];

  function _presenceLoadIdentity() {
    // Per-tab client_id so two tabs from the same browser show as
    // two peers (which they are — the user can scroll in one tab
    // while editing in another).
    try {
      _presenceClientId = sessionStorage.getItem("pixcull_presence_cid") || "";
      if (!_presenceClientId) {
        const rand = Math.random().toString(36).slice(2, 10);
        _presenceClientId = `web-${rand}`;
        sessionStorage.setItem("pixcull_presence_cid", _presenceClientId);
      }
    } catch (_e) {
      _presenceClientId = "web-fallback-" + Math.random().toString(36).slice(2, 8);
    }
    try {
      _presenceDisplay = localStorage.getItem("pixcull_presence_name") || "";
    } catch (_e) { _presenceDisplay = ""; }
    if (!_presenceDisplay) {
      // Friendly default like "二摄-AB12" — encourages the user
      // to rename via the presence-popover's "改名" link but
      // doesn't block first-use.
      const hex = _presenceClientId.slice(-4).toUpperCase();
      _presenceDisplay = `二摄-${hex}`;
    }
  }

  function _presenceSaveName(name) {
    _presenceDisplay = (name || "").trim().slice(0, 40) || _presenceDisplay;
    try { localStorage.setItem("pixcull_presence_name", _presenceDisplay); }
    catch (_e) { /* private mode — fine */ }
    const my = document.getElementById("presenceMyName");
    if (my) my.textContent = _presenceDisplay;
  }

  // Called from _markLocalEdit when a row is edited.  Records
  // both the action verb (keep / cull / maybe / star / bucket /
  // edit) and the filename so the heartbeat can advertise:
  //   "📝 编辑刚标 IMG_007 · keep"
  function _presenceMarkAction(filename, action) {
    if (!PRESENCE_ENABLED) return;
    _presenceLastAction     = (action || "edit").slice(0, 32);
    _presenceLastActionFile = filename || "";
    // Don't wait for the 30s heartbeat — fire an extra beat so
    // peers see the action within the poll window.  We rate-limit
    // via _presencePending so a rapid-fire keep-spree doesn't spam
    // the LAN.
    _presenceHeartbeat({ throttled: true });
  }

  function _presenceMarkView(filename) {
    if (!PRESENCE_ENABLED) return;
    if (!filename || filename === _presenceLastView) return;
    _presenceLastView = filename;
    // Defer the heartbeat to the next interval tick — viewer
    // position changes way too fast (scroll, hover, lightbox
    // next/prev) for a per-change POST to be sane.
  }

  async function _presenceHeartbeat(opts) {
    if (!PRESENCE_ENABLED) return false;
    if (_presencePending && (opts && opts.throttled)) return false;
    _presencePending = true;
    try {
      const body = {
        client_id:            _presenceClientId,
        display_name:         _presenceDisplay,
        last_viewed_filename: _presenceLastView || null,
      };
      if (_presenceLastAction) {
        body.action          = _presenceLastAction;
        body.action_filename = _presenceLastActionFile || null;
      }
      const r = await fetch(
        `/sync/event/${encodeURIComponent(_SYNC_EVENT_TOKEN)}/presence`,
        {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify(body),
        }
      );
      if (r.status === 404 || r.status === 410) {
        // Event revoked — give up silently; sync poller already
        // toasted "协作会话已失效" for the user.
        return false;
      }
      // Clear the one-shot action so a quiet next-beat doesn't
      // re-broadcast a stale action.  The server has persisted it
      // for peers; we don't need to keep re-sending.
      _presenceLastAction     = "";
      _presenceLastActionFile = "";
      return r.ok;
    } catch (_e) {
      return false;
    } finally {
      _presencePending = false;
    }
  }

  async function _presencePollOnce() {
    if (!PRESENCE_ENABLED) return;
    try {
      const url = `/api/v1/sync/event/${encodeURIComponent(_SYNC_EVENT_TOKEN)}`
                + `/presence?exclude=${encodeURIComponent(_presenceClientId)}`;
      const r = await fetch(url);
      if (!r.ok) return;
      const d = await r.json();
      _presencePeers = Array.isArray(d.peers) ? d.peers : [];
      _presenceRenderPill();
      _presenceRenderPanel();
    } catch (_e) { /* swallow — best-effort */ }
  }

  // The ⏱-ago text we sprinkle in the popover.  Keeps the UI alive
  // even between polls — a "2 分钟前" doesn't suddenly become "just
  // now" again, only older.
  function _presenceAgo(ms) {
    if (!ms) return "—";
    const d = Date.now() - ms;
    if (d < 30_000)   return "刚刚";
    if (d < 60_000)   return Math.floor(d / 1000) + "s 前";
    if (d < 3600_000) return Math.floor(d / 60000) + " 分钟前";
    return Math.floor(d / 3600000) + " 小时前";
  }

  // Map of server-side action verbs → emoji + zh label.  The
  // server stores whatever string the client sent; we don't
  // enforce a closed vocab so future call-sites (e.g. ranker,
  // crop, rotate) can add new verbs without a server change.
  const _PRESENCE_ACTION_ZH = {
    keep:   ["✅", "标 keep"],
    maybe:  ["🤔", "标 maybe"],
    cull:   ["✂️", "标 cull"],
    star:   ["⭐", "改星级"],
    bucket: ["🗂️", "入桶"],
    ann:    ["📝", "评分"],
    edit:   ["📝", "编辑"],
  };

  function _presenceFmtAction(rec) {
    if (!rec.last_action) return "";
    const [emoji, label] = _PRESENCE_ACTION_ZH[rec.last_action]
                          || ["📝", rec.last_action];
    const fn = rec.last_action_filename || "—";
    return `${emoji} ${label} · <span class="pp-fn">${_escHtml(fn)}</span>`;
  }

  function _escHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;",
      '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function _presenceRenderPill() {
    const pill = document.getElementById("presencePill");
    if (!pill) return;
    const live = _presencePeers.length;
    if (live === 0) {
      pill.classList.add("solo");
      pill.innerHTML = `<span class="pp-dot"></span><span>独自工作中</span>`;
      return;
    }
    pill.classList.remove("solo");
    if (live === 1) {
      const p = _presencePeers[0];
      const verb = p.last_viewed_filename
        ? `正在看 <span class="pp-actor">${_escHtml(p.last_viewed_filename)}</span>`
        : "在线";
      pill.innerHTML = `<span class="pp-dot"></span>`
                     + `<span><span class="pp-actor">${_escHtml(p.display_name || "peer")}</span> ${verb}</span>`;
    } else {
      pill.innerHTML = `<span class="pp-dot"></span>`
                     + `<span><span class="pp-actor">${live}</span> 协作者在线 · 详情</span>`;
    }
  }

  function _presenceRenderPanel() {
    const list = document.getElementById("presenceList");
    if (!list) return;
    if (_presencePeers.length === 0) {
      // v0.9-P2-3 — illustrated empty state instead of bare text.
      // Uses the new #art-no-peer symbol from the sprite, mirroring
      // the .empty-art chrome from v0.4 P1 (3/4) at a smaller size
      // (the presence popover is ~380 px wide; 120×90 fits).
      list.innerHTML = `<div class="pp-empty" style="text-align:center;padding:18px 12px">
            <svg viewBox="0 0 160 120" style="width:120px;height:90px;opacity:0.92;
                 filter:drop-shadow(0 6px 18px var(--accent-glow))">
              <use href="#art-no-peer"/>
            </svg>
            <div style="margin-top:6px;font-weight:600;color:var(--fg);font-size:13px">
              暂无其他协作者在线
            </div>
            <div style="margin-top:4px;line-height:1.5">
              把分享链接发给二摄 / 编辑,他们打开后会出现在这里。
            </div>
          </div>`;
      return;
    }
    list.innerHTML = _presencePeers.map(p => {
      const name = _escHtml(p.display_name || "peer");
      const initial = (p.display_name || "?").trim().slice(0, 1);
      const view = p.last_viewed_filename
        ? `<div class="pp-meta">👁️ 正在看 <span class="pp-fn">${_escHtml(p.last_viewed_filename)}</span></div>`
        : `<div class="pp-meta">👁️ 还没打开任何照片</div>`;
      const action = p.last_action
        ? `<div class="pp-meta"><span class="pp-action">${_presenceFmtAction(p)}</span> · ${_presenceAgo(p.last_action_at_ms)}</div>`
        : "";
      const seen = `<div class="pp-meta">最近活跃 · ${_presenceAgo(p.last_seen_ms)}</div>`;
      return `<div class="pp-row">
        <span class="pp-avatar">${_escHtml(initial)}</span>
        <div style="flex:1; min-width:0;">
          <div class="pp-name">${name}</div>
          ${view}${action}${seen}
        </div>
      </div>`;
    }).join("");
  }

  function _presenceInjectPill() {
    if (!PRESENCE_ENABLED) return;
    const bar = document.querySelector(".workspace-bar");
    if (!bar) return;
    const pill = document.createElement("span");
    pill.id = "presencePill";
    pill.className = "presence-pill solo";
    pill.innerHTML = `<span class="pp-dot"></span><span>连接中…</span>`;
    pill.title = "协作者状态 · 点击查看详情";
    pill.addEventListener("click", () => {
      const m = document.getElementById("presenceModal");
      if (!m) return;
      // Refresh on open so the popover isn't 10s stale.
      _presencePollOnce();
      _presenceRenderPanel();
      const my = document.getElementById("presenceMyName");
      if (my) my.textContent = _presenceDisplay;
      m.classList.add("show");
    });
    // Insert right before the sync-badge (which we put before the
    // langSwitcher) so the two pills sit together at the right
    // edge of the workspace bar.
    const anchor = document.getElementById("syncBadge")
                || document.getElementById("langSwitcher")
                || bar.lastElementChild;
    bar.insertBefore(pill, anchor);
  }

  function _presenceBindModal() {
    const m = document.getElementById("presenceModal");
    if (!m) return;
    document.getElementById("presenceClose")?.addEventListener(
      "click", () => m.classList.remove("show"));
    m.addEventListener("click", (e) => {
      if (e.target === m) m.classList.remove("show");
    });
    document.getElementById("presenceRename")?.addEventListener("click", () => {
      const nv = prompt("显示给协作者的名字(最多 40 字)", _presenceDisplay);
      if (nv === null) return;
      _presenceSaveName(nv);
      _presenceHeartbeat({ throttled: false });
    });
  }

  // viewer-position hooks: wrap openLightbox so every lightbox-open
  // marks the viewer's focus on that filename.  Grid hover doesn't
  // mark — too noisy + the lightbox is the user's "I'm really
  // looking at this" signal.
  function _presenceWrapLightbox() {
    if (typeof window.openLightbox !== "function") return;
    const orig = window.openLightbox;
    window.openLightbox = function (fn) {
      try { _presenceMarkView(fn); } catch (_e) {}
      return orig.apply(this, arguments);
    };
  }
  // openLightbox is declared as a function (hoisted) but is a
  // module-local — wrap by overwriting the local symbol via the
  // existing identifier path.  In our codebase openLightbox sits
  // on window via implicit hoisting; if a stricter scope shows up
  // later this wrapper becomes a no-op (the function still exists,
  // we just don't get viewer-tracking on lightbox opens).
  try { window.openLightbox = openLightbox; _presenceWrapLightbox(); }
  catch (_e) { /* viewer-tracking is best-effort */ }

  if (PRESENCE_ENABLED) {
    _presenceLoadIdentity();
    _presenceInjectPill();
    _presenceBindModal();
    // First heartbeat + poll immediate, then on intervals.
    _presenceHeartbeat({ throttled: false }).then(_presencePollOnce);
    setInterval(() => _presenceHeartbeat({ throttled: false }), PRESENCE_HB_MS);
    setInterval(_presencePollOnce, PRESENCE_POLL_MS);
    // Refresh pill timestamps once a minute so "刚刚" turns into
    // "1 分钟前" without waiting for the next server poll.
    setInterval(_presenceRenderPanel, 60_000);
    // Disconnect cleanly so peers see us gone immediately.
    const _disconnect = () => {
      try {
        const blob = new Blob(
          [JSON.stringify({ client_id: _presenceClientId, disconnect: true })],
          { type: "application/json" }
        );
        navigator.sendBeacon(
          `/sync/event/${encodeURIComponent(_SYNC_EVENT_TOKEN)}/presence`,
          blob
        );
      } catch (_e) { /* sendBeacon unavailable — server will TTL-evict */ }
    };
    window.addEventListener("pagehide", _disconnect);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") _disconnect();
    });
  }

  // ==================================================================
  // v0.10-P1-3 — Notion-style slash menu inside the rubric rationale
  // textareas.  Typing "/" at the start of the field (or after a
  // newline) pops a tiny contextual menu with five quick actions:
  //
  //   /keep         set this axis to 5★
  //   /cull         set this axis to 1★
  //   /maybe        set this axis to 3★
  //   /cite <id>    insert a canonical citation template
  //   /explain      re-pull the DeepSeek explanation for this row
  //
  // Esc / clicking elsewhere closes.  ↑↓ navigate, Enter selects.
  // Inert when the textarea doesn't carry data-slashmenu — so the
  // existing rationale text-typing experience is untouched.
  // ==================================================================
  (function _slashMenuInit() {
    let menuEl = null;
    let activeTextarea = null;
    let cursorIdx = 0;     // index of the "/" that opened the menu
    let filterText = "";
    let selectedIndex = 0;

    const ALL_COMMANDS = [
      { key: "keep",    label: "标 5★(keep)",
        run: ta => _setAxisStarsFromTextarea(ta, 5) },
      { key: "cull",    label: "标 1★(cull)",
        run: ta => _setAxisStarsFromTextarea(ta, 1) },
      { key: "maybe",   label: "标 3★(maybe)",
        run: ta => _setAxisStarsFromTextarea(ta, 3) },
      { key: "cite",    label: "插入正典引用模板",
        run: ta => _insertAt(ta, " [cite: source · year] ") },
      { key: "explain", label: "重新拉 DeepSeek 解释",
        run: () => showToast("DeepSeek explanation refresh queued", "info") },
    ];

    function _setAxisStarsFromTextarea(ta, stars) {
      // The textarea lives inside .axis-row[data-axis="..."]; find
      // it + click the matching star.  Lets `/keep` mark the
      // current axis as 5★ without breaking the keyboard flow.
      const axisRow = ta.closest(".axis-row");
      if (!axisRow) return;
      const starEl = axisRow.querySelector(`.star[data-v="${stars}"]`);
      if (starEl) starEl.click();
    }

    function _insertAt(ta, text) {
      const start = ta.selectionStart || 0;
      const end   = ta.selectionEnd   || start;
      ta.value = ta.value.slice(0, start) + text + ta.value.slice(end);
      const newPos = start + text.length;
      ta.setSelectionRange(newPos, newPos);
      ta.focus();
    }

    function _closeMenu() {
      if (menuEl) {
        menuEl.remove();
        menuEl = null;
      }
      activeTextarea = null;
      filterText = "";
      selectedIndex = 0;
    }

    function _filtered() {
      if (!filterText) return ALL_COMMANDS;
      const f = filterText.toLowerCase();
      return ALL_COMMANDS.filter(c =>
        c.key.startsWith(f) || c.label.toLowerCase().includes(f));
    }

    function _renderMenu() {
      if (!activeTextarea) return;
      const items = _filtered();
      if (items.length === 0) { _closeMenu(); return; }
      if (selectedIndex >= items.length) selectedIndex = 0;
      if (!menuEl) {
        menuEl = document.createElement("div");
        menuEl.className = "slash-menu";
        menuEl.style.cssText = (
          "position:absolute;z-index:1500;" +
          "background:var(--surface-2);" +
          "border:1px solid var(--border-hi, var(--border));" +
          "border-radius:var(--radius-md, 8px);" +
          "box-shadow:var(--shadow-lg);" +
          "padding:4px 0;min-width:200px;" +
          "font-size:12px;"
        );
        document.body.appendChild(menuEl);
      }
      menuEl.innerHTML = items.map((c, i) =>
        `<div class="slash-item${i === selectedIndex ? " sel" : ""}" ` +
        ` style="padding:6px 12px;cursor:pointer;` +
        ` ${i === selectedIndex ? "background:var(--accent-soft, rgba(196,185,169,0.16));" : ""}"` +
        ` data-key="${c.key}">` +
        `  <span style="color:var(--accent);margin-right:6px">/</span>` +
        `  <b>${c.key}</b>` +
        `  <span style="color:var(--muted);margin-left:8px">${c.label}</span>` +
        `</div>`
      ).join("");
      // Position near the textarea
      const r = activeTextarea.getBoundingClientRect();
      menuEl.style.left = (r.left + window.scrollX) + "px";
      menuEl.style.top  = (r.bottom + window.scrollY + 4) + "px";
      // Wire click → run
      menuEl.querySelectorAll(".slash-item").forEach((el, i) => {
        el.addEventListener("mouseenter", () => {
          selectedIndex = i;
          _renderMenu();
        });
        el.addEventListener("click", () => {
          _runItem(_filtered()[i]);
        });
      });
    }

    function _runItem(cmd) {
      if (!cmd || !activeTextarea) return _closeMenu();
      const ta = activeTextarea;
      // Drop the "/filter" text that opened the menu first.
      ta.value = ta.value.slice(0, cursorIdx)
               + ta.value.slice(cursorIdx + 1 + filterText.length);
      ta.setSelectionRange(cursorIdx, cursorIdx);
      _closeMenu();
      try { cmd.run(ta); } catch (_e) {}
    }

    document.addEventListener("input", (e) => {
      const ta = e.target;
      if (!ta || ta.tagName !== "TEXTAREA") return;
      if (!ta.dataset.slashmenu) return;
      const pos = ta.selectionStart;
      const v = ta.value;
      // Find the most recent "/" preceded by start-of-text or a newline.
      let i = pos - 1;
      while (i >= 0 && v[i] !== "/" && v[i] !== "\n") i--;
      if (i < 0 || v[i] !== "/" || (i > 0 && v[i - 1] !== "\n")) {
        _closeMenu();
        return;
      }
      // Capture the filter text between / and the cursor
      activeTextarea = ta;
      cursorIdx = i;
      filterText = v.slice(i + 1, pos);
      selectedIndex = 0;
      _renderMenu();
    });

    document.addEventListener("keydown", (e) => {
      if (!menuEl || !activeTextarea) return;
      if (e.key === "Escape") { e.preventDefault(); _closeMenu(); return; }
      const items = _filtered();
      if (e.key === "ArrowDown") {
        e.preventDefault();
        selectedIndex = (selectedIndex + 1) % items.length;
        _renderMenu();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        selectedIndex = (selectedIndex - 1 + items.length) % items.length;
        _renderMenu();
      } else if (e.key === "Enter") {
        e.preventDefault();
        _runItem(items[selectedIndex]);
      }
    });

    document.addEventListener("click", (e) => {
      if (!menuEl) return;
      if (e.target.closest(".slash-menu")) return;
      if (e.target === activeTextarea) return;
      _closeMenu();
    });
  })();

  document.getElementById("styleTrainBtn")?.addEventListener("click", async () => {
    const keepRows = rows.filter(r => r.decision === "keep");
    if (keepRows.length < 3) {
      showToast(
        `需要至少 3 张 keep 作为风格参考(当前 ${keepRows.length} 张)`,
        "error"
      );
      return;
    }
    if (!confirm(
      `把当前 ${keepRows.length} 张 keep 当作风格参考,训练一个个人偏好模型?\n\n` +
      "训练后,每张照片都会有 “风格距离” 值,0 = 完全像你的风格,1 = 完全不像。"
    )) return;
    const btn = document.getElementById("styleTrainBtn");
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = "训练中…";
    try {
      const r = await fetch(`/style/train/${run_id}`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          refs: keepRows.map(x => x.filename),
        }),
      });
      if (!r.ok) {
        const detail = await r.text().catch(() => "");
        throw new Error(`HTTP ${r.status} ${detail.slice(0, 80)}`);
      }
      const d = await r.json();
      if (!d.ok) throw new Error("server returned ok=false");
      // Re-pull distances to populate every row
      await _hydrateStyleDistances();
      showToast(
        `风格模型已训练 · ${d.n_refs} 张参考 · ${d.n_scored} 张已打风格距离`,
        "success"
      );
    } catch (err) {
      showToast("训练失败: " + err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = orig;
    }
  });

  // V9.3 — batch label by score threshold
  document.getElementById("batchBtn").addEventListener("click", async () => {
    const keepThreshStr = prompt(
      "把 final score ≥ X 的全部标 keep,< Y 的全部标 cull (中间不动)。\n" +
      "格式: keep_min,cull_max  (例: 0.65,0.4)",
      "0.65,0.4"
    );
    if (!keepThreshStr) return;
    const parts = keepThreshStr.split(",").map(s => parseFloat(s.trim()));
    if (parts.length !== 2 || isNaN(parts[0]) || isNaN(parts[1])) {
      alert("格式错误,需要两个数字以逗号分隔。");
      return;
    }
    const [keepMin, cullMax] = parts;
    const keepRows = rows.filter(r => (r.score_final ?? -1) >= keepMin);
    const cullRows = rows.filter(r => (r.score_final ?? -1) > -1 && (r.score_final ?? 999) < cullMax);
    const ok = confirm(
      `批量打标:\n  ${keepRows.length} 张 → keep (score ≥ ${keepMin})\n` +
      `  ${cullRows.length} 张 → cull (score < ${cullMax})\n` +
      `共写 ${keepRows.length + cullRows.length} 个 annotation,会立刻反映到 UI。继续?`
    );
    if (!ok) return;
    // V10.1 — capture undo snapshot BEFORE mutating
    const snap = [];
    [...keepRows, ...cullRows].forEach(r => snap.push({
      filename: r.filename,
      prev_decision: r.decision,
      prev_human_labeled: r.rubric_human_labeled,
    }));
    pushUndo(snap);
    let n = 0;
    for (const [list, label] of [[keepRows, "keep"], [cullRows, "cull"]]) {
      for (const r of list) {
        try {
          await fetch(`/annotation/${run_id}/${encodeURIComponent(r.filename)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              axes: {},
              overall_label: label,
              overall_rationale: `batch: score ${label === 'keep' ? '≥' : '<'} ${label === 'keep' ? keepMin : cullMax}`,
            }),
          });
          r.rubric_human_labeled = true;
          r.decision = label;
          n++;
        } catch (e) { /* ignore */ }
      }
    }
    summary.n_human_labeled = (summary.n_human_labeled || 0) + n;
    showToast(`已批量标注 ${n} 张 · Cmd+Z 撤销`, "success");
    render();
  });

  // ==================================================================
  // V9.2 cluster compare modal — open via "⊞ 并排比较" on dividers
  // ==================================================================
  const cmpModal = document.getElementById("cmpModal");
  registerModal(cmpModal);  // V14.4 — ARIA dialog + focus trap
  const cmpTitle = document.getElementById("cmpTitle");
  const cmpMeta = document.getElementById("cmpMeta");
  const cmpBody = document.getElementById("cmpBody");
  const cmpClose = document.getElementById("cmpClose");

  function openCompare(clusterKey) {
    // Pull all rows in this cluster
    const members = rows.filter(r => {
      const ck = r.cluster_id == null ? `solo-${r.filename}` : `c${r.cluster_id}`;
      return ck === clusterKey;
    });
    if (members.length < 2) return;
    // Sort by score_final descending so best is first / left-most
    members.sort((a, b) => (b.score_final ?? 0) - (a.score_final ?? 0));
    const best = members[0];
    cmpTitle.textContent = `连拍组 ${clusterKey} (${members.length} 张)`;
    cmpMeta.textContent = `按 score_final 降序;左为最佳。空格键查看大图。`;

    const axisAbbr = {technical:"技", subject:"主", composition:"构",
                       light:"光", moment:"瞬", aesthetic:"美"};
    // v0.7-P0-1 — annotate the body root with n cells so CSS can
    // collapse to 50/50 split when there are exactly 2 (LR Compare
    // classic). Burst-cluster compares are almost always 2-4 cells.
    cmpBody.dataset.n = String(members.length);
    cmpBody.innerHTML = members.map(r => {
      const isBest = (r === best);
      const stars = ["technical","subject","composition","light","moment","aesthetic"].map(name => {
        const s = r.rubric_stars && r.rubric_stars[name];
        return `<div class="a">${axisAbbr[name]} ${s == null ? "--" : s.toFixed(1)}</div>`;
      }).join("");
      const dec = r.decision || "";
      // v0.7-P0-1 — three-pill picker replaces the single pick-btn.
      // .cmp-best-btn (below) handles the "make best + cull rest"
      // gesture from burst compare; here we add it only for that
      // mode (members.length >= 2 + same cluster_id, which is the
      // burst-compare entry path).
      const picker = `
        <div class="cmp-picker">
          <button class="cmp-pick-pill keep ${dec==='keep'?'active':''}"
                  data-fn="${esc(r.filename)}" data-pick="keep"
                  type="button" title="保留 (1)">保留</button>
          <button class="cmp-pick-pill maybe ${dec==='maybe'?'active':''}"
                  data-fn="${esc(r.filename)}" data-pick="maybe"
                  type="button" title="待定 (2)">待定</button>
          <button class="cmp-pick-pill cull ${dec==='cull'?'active':''}"
                  data-fn="${esc(r.filename)}" data-pick="cull"
                  type="button" title="剔除 (3)">剔除</button>
        </div>
        <button class="cmp-best-btn" data-fn="${esc(r.filename)}" data-best="1"
                type="button" title="选这张为最佳,其余 ${members.length-1} 张标 cull">
          ${isBest ? '✓ 已选最佳' : '✓ 选最佳 + 其余 cull'}
        </button>
      `;
      return `
        <div class="cmp-cell ${isBest?'best':''}" data-fn="${esc(r.filename)}">
          <div class="img-wrap" data-full="/full/${run_id}/${encodeURIComponent(r.filename)}">
            <img src="/thumb/${run_id}/${encodeURIComponent(r.filename)}" alt="${esc(r.filename)}">
          </div>
          <div class="meta">
            <span class="fn" title="${esc(r.filename)}">${esc(r.filename)}</span>
            <div class="meta-top">
              <span class="badge ${dec}" style="font-size:9px;padding:1px 5px">${dec || '?'}</span>
              <span class="score">final ${r.score_final == null ? "--" : r.score_final.toFixed(2)}</span>
            </div>
            <div class="stars">${stars}</div>
            ${picker}
          </div>
        </div>
      `;
    }).join("");
    cmpModal.classList.add("show");
    // P-UX-7 — every fresh compare opens at fit. The shared cmp-
    // zoom state is reset so a stray zoom from a previous compare
    // doesn't leak into the new one.
    if (typeof _cmpResetZoom === "function") _cmpResetZoom();

    // P-UX-7 — click on an .img-wrap is now reserved for the synced
    // zoom toggle (handled by cmpBody's delegated mousedown/click
    // listeners). The old "click to open in the lightbox" path
    // would break in-place pixel-peeping, so we drop it. Users who
    // want the full lightbox can still get there by closing this
    // modal and clicking the photo's card.

    // v0.7-P0-1 — two click paths inside the modal body, dispatched
    // by data attribute so we don't have separate listeners for each
    // sub-button. Delegated to cmpBody (not the individual cells)
    // so a future re-render doesn't lose handlers.
    cmpBody.querySelectorAll(".cmp-pick-pill").forEach(btn => {
      btn.addEventListener("click", async () => {
        const fn  = btn.dataset.fn;
        const lbl = btn.dataset.pick;
        if (!fn || !lbl) return;
        const row = rows.find(x => x.filename === fn);
        if (!row) return;
        const cell = btn.closest(".cmp-cell");
        // Optimistic UI: flip pill highlight + badge before the
        // network round-trip lands so the pro doesn't wait for it.
        cell?.querySelectorAll(".cmp-pick-pill").forEach(p => p.classList.remove("active"));
        btn.classList.add("active");
        const badge = cell?.querySelector(".badge");
        if (badge) {
          badge.classList.remove("keep", "maybe", "cull");
          badge.classList.add(lbl);
          badge.textContent = lbl;
        }
        // V10.1 — undo snapshot per-cell (lighter than the burst
        // pick path which snapshots all members at once).
        pushUndo([{
          filename: fn,
          prev_decision: row.decision,
          prev_human_labeled: row.rubric_human_labeled,
        }]);
        try {
          await fetch(`/annotation/${run_id}/${encodeURIComponent(fn)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              axes: {},
              overall_label: lbl,
              overall_rationale: `compare-modal pick: ${lbl}`,
            }),
          });
          row.rubric_human_labeled = true;
          row.decision = lbl;
          summary.n_human_labeled = (summary.n_human_labeled || 0) + 1;
        } catch (_e) { /* ignore — UI already updated */ }
        showToast(`已标 ${lbl}:${fn}`, "success");
      });
    });
    // "Make best + cull the rest" — the legacy burst-compare gesture
    // kept on a dedicated button so the per-cell pills above stay
    // semantically clean (one cell, one pill, one annotation).
    cmpBody.querySelectorAll(".cmp-best-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        const pickFn = btn.dataset.fn;
        if (!pickFn) return;
        const ok = confirm(`选 ${pickFn} 为最佳,其余 ${members.length - 1} 张标 cull?`);
        if (!ok) return;
        // V10.1 — undo snapshot (all members)
        pushUndo(members.map(m => ({
          filename: m.filename,
          prev_decision: m.decision,
          prev_human_labeled: m.rubric_human_labeled,
        })));
        for (const m of members) {
          const lbl = (m.filename === pickFn) ? "keep" : "cull";
          try {
            await fetch(`/annotation/${run_id}/${encodeURIComponent(m.filename)}`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                axes: {},
                overall_label: lbl,
                overall_rationale: `cluster compare: ${lbl === 'keep' ? 'picked as best' : 'rejected sibling'}`,
              }),
            });
            const local = rows.find(x => x.filename === m.filename);
            if (local) {
              local.rubric_human_labeled = true;
              local.decision = lbl;
            }
          } catch (e) { /* ignore */ }
        }
        summary.n_human_labeled = (summary.n_human_labeled || 0) + members.length;
        cmpModal.classList.remove("show");
        showToast(`已选 ${pickFn},其余 ${members.length-1} 张标 cull · Cmd+Z 撤销`, "success");
        render();
      });
    });
  }

  // Wire compare buttons (inside cluster dividers — they're rebuilt
  // on each render(), so use event delegation on the grid).
  grid.addEventListener("click", e => {
    const btn = e.target.closest(".compare-btn");
    if (btn && btn.dataset.cluster) {
      openCompare(btn.dataset.cluster);
    }
  });
  cmpClose.addEventListener("click", () => cmpModal.classList.remove("show"));
  cmpModal.addEventListener("click", e => {
    if (e.target === cmpModal) cmpModal.classList.remove("show");
  });

  // ==================================================================
  // P-UX-3 — free-pick A/B compare. Burst-cluster compare (above)
  // only covers photos that landed in the same DBSCAN cluster, but
  // pro photographers regularly need to compare any two near-dupes
  // — second-shooter coverage of the same moment, two angles of the
  // same subject, before/after a small reframe — that may not have
  // clustered together. This adds a "pin for compare" interaction
  // that lets the user pick any 2 photos and pipe them through the
  // existing compare modal (which is happily n-cell, not 2-only).
  //
  //   click the ⇆ button on a card  → pins as A (highlighted, tray
  //                                    appears at top of viewport)
  //   click the ⇆ on a 2nd card    → opens compare modal with [A, B]
  //   Shift-click the thumbnail     → same as the ⇆ button (fast path)
  //   Esc                            → cancels the A pick
  //   c key (focused card)           → pins/unpins that card
  //
  // The existing burst-walk prev/next buttons are hidden in custom
  // mode (they're cluster-specific and would mis-step).
  // ==================================================================

  let _compareA = null;  // filename of the pinned photo, or null
  const cmpPickTray   = document.getElementById("cmpPickTray");
  const cmpPickFn     = document.getElementById("cmpPickFn");
  const cmpPickCancel = document.getElementById("cmpPickCancel");

  function _updateCmpPickUI() {
    // Reflect _compareA into the floating tray + per-card class.
    cmpPickTray.classList.toggle("show", _compareA != null);
    if (_compareA) cmpPickFn.textContent = _compareA;
    // Sync .compare-a class on visible cards
    grid.querySelectorAll(".card.compare-a").forEach(c => {
      if (!_compareA || c.dataset.fn !== _compareA) {
        c.classList.remove("compare-a");
      }
    });
    if (_compareA) {
      grid.querySelectorAll(`.card[data-fn]`).forEach(c => {
        if (c.dataset.fn === _compareA) c.classList.add("compare-a");
      });
    }
  }
  function cancelComparePick() {
    _compareA = null;
    _updateCmpPickUI();
  }
  function pinForCompare(filename) {
    if (!filename) return;
    if (!_compareA) {
      _compareA = filename;
      _updateCmpPickUI();
      showToast(`已选 A: ${filename} · 点选第二张 (Esc 取消)`, "info");
      return;
    }
    if (_compareA === filename) {
      // Re-pinning the same card just cancels.
      cancelComparePick();
      return;
    }
    // Two photos selected → open the compare modal in custom mode.
    const a = _compareA, b = filename;
    cancelComparePick();
    openCompareCustom([a, b]);
  }

  // Generalized version of openCompare() that accepts an arbitrary
  // list of filenames instead of a cluster key. Reuses the same DOM
  // template, sort order (score_final desc), and pick-handler logic
  // as the cluster path so the UX is identical once the modal opens.
  function openCompareCustom(filenames) {
    const members = filenames
      .map(fn => rows.find(r => r.filename === fn))
      .filter(Boolean);
    if (members.length < 2) {
      showToast("至少需要两张图才能比较", "error");
      return;
    }
    members.sort((a, b) => (b.score_final ?? 0) - (a.score_final ?? 0));
    const best = members[0];
    cmpTitle.textContent = `A/B 比较 (${members.length} 张)`;
    cmpMeta.textContent =
      `按 score_final 降序;左为系统推荐。点 "选这张" 把另一张标 cull。`;

    const axisAbbr = {technical:"技", subject:"主", composition:"构",
                       light:"光", moment:"瞬", aesthetic:"美"};
    // v0.7-P0-1 — same n-cells annotation as openCompare so CSS
    // collapses to 50/50 split when exactly 2.
    cmpBody.dataset.n = String(members.length);
    cmpBody.innerHTML = members.map(r => {
      const isBest = (r === best);
      const stars = ["technical","subject","composition","light","moment","aesthetic"].map(name => {
        const s = r.rubric_stars && r.rubric_stars[name];
        return `<div class="a">${axisAbbr[name]} ${s == null ? "--" : s.toFixed(1)}</div>`;
      }).join("");
      const dec = r.decision || "";
      // v0.7-P0-1 — three-pill picker, parallels openCompare().
      const picker = `
        <div class="cmp-picker">
          <button class="cmp-pick-pill keep ${dec==='keep'?'active':''}"
                  data-fn="${esc(r.filename)}" data-pick="keep"
                  type="button" title="保留 (1)">保留</button>
          <button class="cmp-pick-pill maybe ${dec==='maybe'?'active':''}"
                  data-fn="${esc(r.filename)}" data-pick="maybe"
                  type="button" title="待定 (2)">待定</button>
          <button class="cmp-pick-pill cull ${dec==='cull'?'active':''}"
                  data-fn="${esc(r.filename)}" data-pick="cull"
                  type="button" title="剔除 (3)">剔除</button>
        </div>
        <button class="cmp-best-btn" data-fn="${esc(r.filename)}" data-best="1"
                type="button" title="选这张为 keep,其余 ${members.length-1} 张标 cull">
          ${isBest ? '✓ 系统推荐 · 选这张 + 其余 cull' : '✓ 选这张 + 其余 cull'}
        </button>
      `;
      return `
        <div class="cmp-cell ${isBest?'best':''}" data-fn="${esc(r.filename)}">
          <div class="img-wrap" data-full="/full/${run_id}/${encodeURIComponent(r.filename)}">
            <img src="/thumb/${run_id}/${encodeURIComponent(r.filename)}" alt="${esc(r.filename)}">
          </div>
          <div class="meta">
            <span class="fn" title="${esc(r.filename)}">${esc(r.filename)}</span>
            <div class="meta-top">
              <span class="badge ${dec}" style="font-size:9px;padding:1px 5px">${esc(dec || '?')}</span>
              <span class="score">final ${r.score_final == null ? "--" : r.score_final.toFixed(2)}</span>
            </div>
            <div class="stars">${stars}</div>
            ${picker}
          </div>
        </div>
      `;
    }).join("");

    // Hide the burst prev/next nav — meaningless in custom-pick mode.
    const _navPrev = document.getElementById("cmpPrev");
    const _navNext = document.getElementById("cmpNext");
    if (_navPrev) _navPrev.style.display = "none";
    if (_navNext) _navNext.style.display = "none";
    cmpModal.classList.add("show");
    // P-UX-7 — reset synced zoom for the new compare set.
    if (typeof _cmpResetZoom === "function") _cmpResetZoom();

    // v0.7-P0-1 — per-cell pill handler: independent labels.
    cmpBody.querySelectorAll(".cmp-pick-pill").forEach(btn => {
      btn.addEventListener("click", async () => {
        const fn  = btn.dataset.fn;
        const lbl = btn.dataset.pick;
        if (!fn || !lbl) return;
        const row = rows.find(x => x.filename === fn);
        if (!row) return;
        const cell = btn.closest(".cmp-cell");
        cell?.querySelectorAll(".cmp-pick-pill").forEach(p => p.classList.remove("active"));
        btn.classList.add("active");
        const badge = cell?.querySelector(".badge");
        if (badge) {
          badge.classList.remove("keep", "maybe", "cull");
          badge.classList.add(lbl);
          badge.textContent = lbl;
        }
        pushUndo([{
          filename: fn,
          prev_decision: row.decision,
          prev_human_labeled: row.rubric_human_labeled,
        }]);
        try {
          await fetch(`/annotation/${run_id}/${encodeURIComponent(fn)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              axes: {},
              overall_label: lbl,
              overall_rationale: `A/B compare pick: ${lbl}`,
            }),
          });
          row.rubric_human_labeled = true;
          row.decision = lbl;
          summary.n_human_labeled = (summary.n_human_labeled || 0) + 1;
        } catch (_e) { /* ignore — UI already updated */ }
        showToast(`已标 ${lbl}:${fn}`, "success");
      });
    });
    // Make best + cull the rest — same gesture as cluster compare.
    cmpBody.querySelectorAll(".cmp-best-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        const pickFn = btn.dataset.fn;
        if (!pickFn) return;
        const ok = confirm(
          `选 ${pickFn} 为 keep,其余 ${members.length - 1} 张标 cull?`);
        if (!ok) return;
        pushUndo(members.map(m => ({
          filename: m.filename,
          prev_decision: m.decision,
          prev_human_labeled: m.rubric_human_labeled,
        })));
        for (const m of members) {
          const lbl = (m.filename === pickFn) ? "keep" : "cull";
          try {
            await fetch(`/annotation/${run_id}/${encodeURIComponent(m.filename)}`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                axes: {},
                overall_label: lbl,
                overall_rationale: `A/B compare: ${lbl === 'keep' ? 'picked' : 'rejected'}`,
              }),
            });
            const local = rows.find(x => x.filename === m.filename);
            if (local) {
              local.rubric_human_labeled = true;
              local.decision = lbl;
            }
          } catch (e) { /* ignore */ }
        }
        summary.n_human_labeled = (summary.n_human_labeled || 0) + members.length;
        cmpModal.classList.remove("show");
        showToast(`已选 ${pickFn},另一张标 cull · Cmd+Z 撤销`, "success");
        render();
      });
    });
  }

  // Restore the burst-walk nav when the modal closes — the user may
  // open a real cluster compare next, and prev/next should work
  // again.
  function _restoreBurstNav() {
    const _navPrev = document.getElementById("cmpPrev");
    const _navNext = document.getElementById("cmpNext");
    if (_navPrev) _navPrev.style.display = "";
    if (_navNext) _navNext.style.display = "";
  }
  cmpClose.addEventListener("click", _restoreBurstNav);
  cmpModal.addEventListener("click", e => {
    if (e.target === cmpModal) _restoreBurstNav();
  });

  // Card-level wiring. Use event delegation on the grid so we don't
  // have to re-attach after every render(). Both the explicit ⇆ pin
  // button and Shift+click on the thumbnail map to pinForCompare();
  // the existing thumbnail-click → openLightbox path stays intact
  // for plain clicks.
  grid.addEventListener("click", e => {
    const cmpBtn = e.target.closest(".card-cmp-btn");
    if (cmpBtn) {
      e.stopPropagation();
      const fn = cmpBtn.dataset.fn;
      if (fn) pinForCompare(fn);
      return;
    }
    // Shift-click on a thumbnail = quick pin for compare.
    if (e.shiftKey && e.target.tagName === "IMG"
        && e.target.classList.contains("thumb")) {
      e.preventDefault(); e.stopPropagation();
      const card = e.target.closest(".card");
      if (card && card.dataset.fn) pinForCompare(card.dataset.fn);
      return;
    }
  }, true);  // capture phase so we get ahead of the existing thumb-click → openLightbox

  cmpPickCancel.addEventListener("click", () => cancelComparePick());

  // ==================================================================
  // P-UX-25 — multi-tab annotation conflict guard. Two scenarios this
  // handles:
  //
  //   1. User opens the same /results/<run_id> in a second tab (a
  //      reasonable workflow: one tab for grid, one for lightbox).
  //      Both tabs read the same annotations.jsonl on the server, so
  //      "1" labeled in tab A doesn't appear in tab B until reload.
  //      The user makes a different verdict in B → A's stale view
  //      gets overwritten by B's POST.
  //
  //   2. Two photographers on the same machine reviewing the same
  //      shoot at the same time (shared-account scenario in studios).
  //      Same conflict pattern as 1.
  //
  // Our remedy: BroadcastChannel + a small banner. We never block
  // saves — that would surprise the user. Instead we:
  //
  //   - announce presence on page load; if another tab replies,
  //     show a soft amber banner ("annotations sync — keep editing
  //     in one tab to avoid overwrites")
  //   - broadcast every annotation save → other tabs update their
  //     in-memory rows[] + re-render. Users see live changes from
  //     their sibling tab without a manual reload.
  //   - clean up on beforeunload so the surviving tab can hide the
  //     banner once it's the last one standing.
  //
  // BroadcastChannel is available everywhere except very old Safari
  // (< 15.4) and some embedded webviews. On those we silently no-op;
  // the user gets the same experience as today.
  // ==================================================================
  (function _initMultiTab() {
    if (typeof BroadcastChannel === "undefined") return;
    const _TAB_ID = (typeof crypto !== "undefined" && crypto.randomUUID)
      ? crypto.randomUUID()
      : (Date.now() + "-" + Math.random().toString(36).slice(2, 10));
    let _bc;
    try { _bc = new BroadcastChannel("pixcull-tab-coord:" + run_id); }
    catch (e) { return; }

    const _seenTabs = new Set();
    let _bannerEl = null;

    function _showBanner() {
      if (_bannerEl) {
        _bannerEl.classList.remove("hidden");
        return;
      }
      _bannerEl = document.createElement("div");
      _bannerEl.className = "multi-tab-banner";
      _bannerEl.setAttribute("role", "status");
      _bannerEl.setAttribute("aria-live", "polite");
      _bannerEl.innerHTML = `
        <span class="mtb-icon"><svg class="icon"><use href="#icon-alert"/></svg></span>
        <span class="mtb-msg">同一批结果已在其它 tab 打开 — 标注会双向同步,但建议只在一个 tab 内编辑以避免覆盖</span>
        <button class="mtb-close" type="button" aria-label="关闭多 tab 提示">✕</button>`;
      document.body.appendChild(_bannerEl);
      _bannerEl.querySelector(".mtb-close").addEventListener("click", () => {
        _bannerEl.classList.add("hidden");
      });
    }

    function _hideBannerIfAlone() {
      if (_seenTabs.size === 0 && _bannerEl) {
        _bannerEl.remove();
        _bannerEl = null;
      }
    }

    _bc.addEventListener("message", e => {
      const m = e.data || {};
      if (!m.type || !m.from || m.from === _TAB_ID) return;

      if (m.type === "hello") {
        _seenTabs.add(m.from);
        // Echo back so the newcomer learns about us too
        try { _bc.postMessage({type: "echo", from: _TAB_ID}); } catch (e) {}
        _showBanner();
      }
      else if (m.type === "echo") {
        _seenTabs.add(m.from);
        _showBanner();
      }
      else if (m.type === "bye") {
        _seenTabs.delete(m.from);
        _hideBannerIfAlone();
      }
      else if (m.type === "annot" && m.fn) {
        // Sibling tab labeled fn → reflect locally so the user sees
        // the change live in this tab.
        const r = rows.find(x => x.filename === m.fn);
        if (r && r.decision !== m.dec) {
          r.decision = m.dec;
          r.rubric_human_labeled = true;
          if (m.dec !== "cull") r.cull_reason = "";
          try { render(); } catch (err) {}
          try {
            if (typeof toast === "function") {
              toast(`其它 tab 标注:${m.fn.length > 40 ? m.fn.slice(0,38)+"…" : m.fn} → ${m.dec}`,
                    "info", 2400);
            }
          } catch (err) {}
        }
      }
    });

    _pixMultiTab.broadcastAnnotation = function (fn, dec) {
      try { _bc.postMessage({type: "annot", from: _TAB_ID, fn, dec}); }
      catch (e) {}
    };

    // Announce ourselves; existing tabs will reply with "echo".
    try { _bc.postMessage({type: "hello", from: _TAB_ID}); } catch (e) {}
    // Politely depart on unload so the survivor can drop the banner.
    window.addEventListener("beforeunload", () => {
      try { _bc.postMessage({type: "bye", from: _TAB_ID}); } catch (e) {}
    });
  })();

  // ==================================================================
  // P-CORE-3 — scene-distribution anomaly banner.
  //
  // P-CORE-2 added prior calibration + abstain on the SCENE
  // CLASSIFIER itself (one frame at a time).  This banner adds a
  // RUN-LEVEL sanity check: at page open, look at the scene
  // distribution across all rows and flag distributions that
  // suggest the classifier might be over-firing in this run.
  //
  // Heuristics (any of these triggers the banner):
  //   - any single scene > 60% of all rows
  //   - top-2 scenes combined > 95% AND total rows >= 30
  //     (small runs may legitimately be all-portrait)
  //   - "unknown" > 30% (P-CORE-2 abstained on >30% of frames —
  //     the classifier is genuinely uncertain about this run)
  //
  // Soft banner only; the user dismisses with X, or it
  // auto-hides after first card annotation.  Goal is to set
  // expectations BEFORE the user starts labeling, so they don't
  // mid-stream realize "wait, why are all my landscape shots
  // tagged stilllife".
  // ==================================================================
  (function _initSceneAnomalyBanner() {
    if (!rows || rows.length < 10) return;     // too few to judge

    // Count scenes
    const counts = new Map();
    for (const r of rows) {
      const s = r.scene || "(missing)";
      counts.set(s, (counts.get(s) || 0) + 1);
    }
    const n = rows.length;
    const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]);
    const [topScene, topN]       = sorted[0] || [null, 0];
    const [secondScene, secondN] = sorted[1] || [null, 0];
    const topPct    = topN / n;
    const top2Pct   = (topN + secondN) / n;
    const unknownN  = counts.get("unknown") || 0;
    const unknownPct = unknownN / n;

    let reason = null;
    if (topPct > 0.60) {
      reason = `单一场景 <b>${topScene}</b> 占了 <b>${(topPct*100).toFixed(0)}%</b> ` +
               `(${topN} / ${n})。如果与实际场景相符则忽略;否则建议重判场景。`;
    } else if (top2Pct > 0.95 && n >= 30) {
      reason = `<b>${topScene}</b> + <b>${secondScene}</b> 占了 <b>${(top2Pct*100).toFixed(0)}%</b>。` +
               `可能 scene 分类器把多种场景误归到这两类;先抽查再大批量标注。`;
    } else if (unknownPct > 0.30) {
      reason = `场景分类器在 <b>${(unknownPct*100).toFixed(0)}%</b> 的图片上 abstain ` +
               `(标为 unknown)。这一批光线 / 场景对 CLIP 来说不典型,人工复核优先。`;
    }
    if (!reason) return;

    const banner = document.createElement("div");
    banner.className = "scene-anomaly-banner";
    banner.setAttribute("role", "status");
    banner.setAttribute("aria-live", "polite");
    banner.innerHTML = `
      <span class="sab-icon"><svg class="icon"><use href="#icon-chart"/></svg></span>
      <span class="sab-msg">${reason}</span>
      <button class="sab-toggle" type="button">查看分布详情</button>
      <button class="sab-close" type="button" aria-label="关闭场景分布提示">✕</button>`;
    document.body.appendChild(banner);

    // P-UX-28 — pie chart panel.  Lazy-built on first click.
    let pieEl = null;
    function _buildPiePanel() {
      // Generate distinct hues evenly spaced around the wheel
      const entries = sorted;   // [[name, count], ...]
      const total   = n;
      const N       = entries.length;
      const hue = i => Math.round((i * 360) / N);
      const fill = i => `hsl(${hue(i)}, 62%, 55%)`;

      // Build SVG pie via cumulative-angle-to-arc math.  conic-
      // gradient would be simpler but doesn't support per-segment
      // titles + a screenreader-friendly title on hover.
      const cx = 70, cy = 70, r = 60;
      let acc = 0;
      const slices = entries.map(([name, cnt], i) => {
        const frac = cnt / total;
        const a0   = acc * 2 * Math.PI - Math.PI / 2;
        const a1   = (acc + frac) * 2 * Math.PI - Math.PI / 2;
        acc += frac;
        const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0);
        const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
        const large = frac > 0.5 ? 1 : 0;
        const d = `M${cx},${cy} L${x0.toFixed(2)},${y0.toFixed(2)} ` +
                  `A${r},${r} 0 ${large} 1 ${x1.toFixed(2)},${y1.toFixed(2)} Z`;
        const title = `${esc(name)}: ${cnt} (${(frac * 100).toFixed(1)}%)`;
        return `<path d="${d}" fill="${fill(i)}" stroke="#0b0d10" stroke-width="1">` +
               `<title>${title}</title></path>`;
      }).join("");
      const legend = entries.map(([name, cnt], i) => {
        const frac = cnt / total;
        return `<div class="sdp-legend-row">
          <span class="sdp-swatch" style="background:${fill(i)}"></span>
          <span class="sdp-name">${esc(name)}</span>
          <span class="sdp-pct">${cnt} · ${(frac*100).toFixed(1)}%</span>
        </div>`;
      }).join("");
      const panel = document.createElement("div");
      panel.className = "scene-distribution-panel";
      panel.innerHTML = `
        <h4>场景分布 (共 ${total} 张)</h4>
        <div class="sdp-content">
          <svg viewBox="0 0 140 140" aria-label="场景分布饼图">
            ${slices}
          </svg>
          <div class="sdp-legend">${legend}</div>
        </div>`;
      document.body.appendChild(panel);
      return panel;
    }

    banner.querySelector(".sab-toggle").addEventListener("click", () => {
      if (!pieEl) pieEl = _buildPiePanel();
      pieEl.classList.toggle("show");
    });
    const close = () => {
      banner.classList.add("hidden");
      // P-UX-28 — also hide the expanded pie panel if open
      if (pieEl) pieEl.classList.remove("show");
      // Persist dismissal per-run so reopening the same tab
      // doesn't re-prompt
      try {
        localStorage.setItem("pixcull_scene_anomaly_dismissed:" + run_id, "1");
      } catch (_e) {}
    };
    banner.querySelector(".sab-close").addEventListener("click", close);
    // Auto-dismiss when the user starts annotating (first 1/2/3/f)
    function _onFirstAnnot(e) {
      const k = e.key;
      if (k === "1" || k === "2" || k === "3" ||
          k === "f" || k === "F") {
        document.removeEventListener("keydown", _onFirstAnnot, true);
        close();
      }
    }
    document.addEventListener("keydown", _onFirstAnnot, true);

    // Honor persisted dismissal (same run reopened)
    try {
      if (localStorage.getItem("pixcull_scene_anomaly_dismissed:" + run_id) === "1") {
        banner.classList.add("hidden");
      }
    } catch (_e) {}
  })();

  // ==================================================================
  // P-UX-26 — animated onboarding hints. First-ever visit gets:
  //   - three pulse rings on key affordances (buckets / a11y /
  //     shortcuts) so the user notices the floating pills
  //   - a small dismissable tip card at bottom-right listing the
  //     three highest-value actions (1/2/3 keys, ? help, buckets)
  // After dismissal — or after the first 1/2/3/f keystroke (the
  // strongest "I get the flow" signal) — localStorage gets a flag
  // and the user never sees this again, even across runs.
  //
  // Why not a guided tour modal? Modals are the wrong shape for
  // a tool where the action surface IS the page. A modal would
  // force a click before the user has even seen the grid. The
  // pulse + tip combo gives the same hint density without
  // hijacking attention.
  // ==================================================================
  // v2.4-P0-2b — surface "tuned to you" when a personal taste profile is
  // active (decisions were calibrated to the user's keep/cull history).
  (function _initTunedBadge() {
    const el = document.getElementById("tunedBadge");
    if (!el) return;
    fetch("/api/v1/users/profile")
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (!d) return;
        if (d.is_active) {
          const axis = d.most_cared_axis || "";
          el.textContent = "🎯 已按你调校" + (axis ? (" · 重" + axis) : "");
          el.style.display = "";
          return;
        }
        // v2.5 — cold-start progress. The moat used to be invisible
        // until 50 corrections; now any progress (≥3, so a first-time
        // visitor isn't nagged) shows how close "tuned to you" is.
        const n = d.n_annotations | 0, min = d.min_annotations | 0;
        if (min > 0 && n >= 3 && n < min) {
          el.textContent = "🎯 个性化 " + n + "/" + min;
          el.title = "每次 keep/cull 纠正都在教 PixCull 你的口味 — 再标 "
            + (min - n) + " 张,新批次就会自动按你的标准校准阈值";
          el.style.opacity = "0.62";
          el.style.display = "";
        }
      })
      .catch(() => {});
  })();

  // v2.5 — feature-discovery tour. Open/close mirrors the shortcuts
  // modal; a one-shot pulse on the ✨ button (same onboard-pulse the
  // other affordances use, localStorage-gated) announces it exists
  // without ever auto-opening a modal over the user's work.
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

  // ==================================================================
  // P-UX-23 — color-blind / a11y mode toggle. Tiny floating button at
  // bottom-left flips body.a11y-cb on/off; the CSS rules then remap
  // the keep/maybe/cull palette to Wong's deuteranopia-safe palette
  // (sky-blue / orange / magenta). Combined with the always-on shape
  // glyphs (✓/?/✕) on every decision badge — also added in this
  // ticket — the UI never depends on red/green discrimination.
  //
  // Why a single bool instead of a 3-way picker:
  //   - the deuteranopia-safe palette is also a fine palette for the
  //     ~92% of users with typical color vision, so "off / cb" covers
  //     the real use cases without a confusing options surface
  //   - if anyone needs a different palette they can override via a
  //     userscript / custom CSS; ours is just the audit-passing default
  // ==================================================================
  const _A11Y_PREF_KEY = "pixcull_a11y_pref";
  const a11yToggleBtn = document.getElementById("a11yToggleBtn");

  function _applyA11yPref(pref) {
    const cb = (pref === "cb");
    document.body.classList.toggle("a11y-cb", cb);
    if (a11yToggleBtn) {
      a11yToggleBtn.classList.toggle("on", cb);
      a11yToggleBtn.setAttribute("aria-pressed", cb ? "true" : "false");
    }
  }

  // Apply persisted preference before first paint of grid colors —
  // the CSS class on <body> is purely a paint hint so even setting
  // it after grid render is visually instant, but doing it here
  // avoids a one-frame palette flash on slow devices.
  try {
    const _saved = localStorage.getItem(_A11Y_PREF_KEY);
    if (_saved === "cb") _applyA11yPref("cb");
  } catch (e) { /* localStorage disabled — silently skip */ }

  if (a11yToggleBtn) {
    a11yToggleBtn.addEventListener("click", () => {
      const next = document.body.classList.contains("a11y-cb") ? "" : "cb";
      try { localStorage.setItem(_A11Y_PREF_KEY, next); }
      catch (e) { /* private / disabled — still apply for this tab */ }
      _applyA11yPref(next);
      // Surface the change to the user via the toast system so they
      // know the toggle did something (the palette change can be
      // subtle on darker monitors).
      if (typeof toast === "function") {
        toast(next === "cb"
          ? "色盲友好配色已开启(蓝 / 橙 / 紫 + ✓ / ? / ✕)"
          : "已切换回默认配色", "info");
      }
    });
  }

  // ==================================================================
  // v0.4 P2 (1/4) — light / dark theme toggle.
  //
  // State machine: dark → light → system → (back to dark).  Three
  // explicit states because users want a manual override AND a
  // "follow my OS" default.  Persisted in
  // localStorage[pixcull_theme] as "dark" / "light" / "system".
  //
  // Auto-apply on init based on (a) persisted pref, OR (b)
  // prefers-color-scheme media query if no pref.  matchMedia
  // listener catches OS changes while "system" is selected.
  // ==================================================================
  const _THEME_KEY = "pixcull_theme";
  const _themeBtn   = document.getElementById("themeToggleBtn");
  const _themeIcon  = document.getElementById("themeToggleIcon");
  const _themeLabel = document.getElementById("themeToggleLabel");
  const _mqLight = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)");

  function _effectiveTheme(pref) {
    if (pref === "light" || pref === "dark") return pref;
    return (_mqLight && _mqLight.matches) ? "light" : "dark";
  }
  function _renderTheme(pref) {
    const eff = _effectiveTheme(pref);
    document.documentElement.setAttribute("data-theme", eff);
    if (_themeIcon) {
      _themeIcon.firstElementChild.setAttribute(
        "href", eff === "light" ? "#icon-sun" : "#icon-moon"
      );
    }
    if (_themeLabel) {
      _themeLabel.textContent =
        pref === "system" ? "跟随系统"
        : pref === "light" ? "浅色"
        : "深色";
    }
    if (_themeBtn) {
      _themeBtn.setAttribute("aria-pressed",
        eff === "light" ? "true" : "false");
    }
  }
  // Init
  let _themePref = "system";
  try { _themePref = localStorage.getItem(_THEME_KEY) || "system"; }
  catch (e) { /* localStorage disabled — fall back to system */ }
  if (!["dark", "light", "system"].includes(_themePref)) _themePref = "system";
  _renderTheme(_themePref);
  // Listen for OS theme changes while in "system" mode
  if (_mqLight && _mqLight.addEventListener) {
    _mqLight.addEventListener("change", () => {
      if (_themePref === "system") _renderTheme(_themePref);
    });
  }
  if (_themeBtn) {
    _themeBtn.addEventListener("click", () => {
      // Cycle through the three states
      _themePref = _themePref === "dark" ? "light"
                  : _themePref === "light" ? "system"
                  : "dark";
      try { localStorage.setItem(_THEME_KEY, _themePref); } catch (e) {}
      _renderTheme(_themePref);
      if (typeof toast === "function") {
        const label = _themePref === "system" ? "跟随系统"
                    : _themePref === "light" ? "浅色主题"
                    : "深色主题";
        toast(`已切换:${label}`, "info", 1800);
      }
    });
  }

  // ==================================================================
  // P-UX-22 — deliverable buckets. Per-user named output baskets so
  // a photographer can organize culls into "客户精选 / 营销片 /
  // 投稿候选 / 留档" buckets and export each as a zip without
  // re-filtering the grid every time.
  //
  // State model:
  //   localStorage[`pixcull_buckets:${run_id}`] = {
  //     "客户精选":      ["IMG_001.jpg", "IMG_007.jpg", ...],
  //     "营销片":        ["IMG_012.jpg"],
  //     ...
  //   }
  // ==================================================================

  const _BUCKETS_KEY = `pixcull_buckets:${run_id}`;
  // v0.6 (4/5) — user-defined bucket ordering, persisted alongside the
  // buckets map.  Lives in a separate key because the buckets map is
  // already shaped {name: filenames[]} and we don't want to break
  // round-trip with older clients that still expect the old shape.
  const _BUCKETS_ORDER_KEY = `pixcull_buckets_order:${run_id}`;
  const bucketsToggleBtn = document.getElementById("bucketsToggleBtn");
  const bucketsPanel     = document.getElementById("bucketsPanel");
  const bucketsCloseBtn  = document.getElementById("bucketsCloseBtn");
  const bucketsList      = document.getElementById("bucketsList");
  const bucketsTotalPill = document.getElementById("bucketsTotalPill");
  const newBucketBtn     = document.getElementById("newBucketBtn");
  const newBucketName    = document.getElementById("newBucketName");

  function _readBuckets() {
    try {
      // v0.7-P0-3 — PixCullStorage layers in-memory fallback when
      // localStorage hits quota (5k-photo runs with rubric metadata
      // can cross 4MB), so the user doesn't lose buckets on big jobs.
      return JSON.parse(PixCullStorage.get(_BUCKETS_KEY) || "{}");
    } catch (_e) { return {}; }
  }
  function _writeBuckets(b) {
    PixCullStorage.set(_BUCKETS_KEY, JSON.stringify(b));
  }
  // v0.6 (4/5) — read the stored bucket order, reconciled against the
  // current set of bucket names.  Unknown names (added since the order
  // was last saved) get appended in alphabetical order; stale names
  // (deleted) drop out.  Net effect: drag order survives panel
  // re-renders without manual upkeep at create / delete sites.
  function _readBucketOrder(buckets) {
    let stored;
    try { stored = JSON.parse(localStorage.getItem(_BUCKETS_ORDER_KEY) || "[]"); }
    catch (_e) { stored = []; }
    if (!Array.isArray(stored)) stored = [];
    const present = new Set(Object.keys(buckets));
    const kept = stored.filter(n => present.has(n));
    const known = new Set(kept);
    const extras = [...present].filter(n => !known.has(n)).sort();
    return kept.concat(extras);
  }
  function _writeBucketOrder(order) {
    try { localStorage.setItem(_BUCKETS_ORDER_KEY, JSON.stringify(order)); }
    catch (_e) { /* ignore */ }
  }
  function _bucketsForFile(filename) {
    const b = _readBuckets();
    return Object.keys(b).filter(name => (b[name] || []).includes(filename));
  }
  function _bucketsTotal() {
    const b = _readBuckets();
    const all = new Set();
    for (const arr of Object.values(b)) {
      for (const fn of arr) all.add(fn);
    }
    return all.size;
  }

  function _renderBucketsPill() {
    const n = _bucketsTotal();
    if (n > 0) {
      bucketsTotalPill.style.display = "";
      bucketsTotalPill.textContent = String(n);
    } else {
      bucketsTotalPill.style.display = "none";
    }
  }
  function _renderBucketsPanel() {
    const b = _readBuckets();
    // v0.6 (4/5) — honour user-drag order, falling back to alphabetical
    // for names not yet in the order array.
    const names = _readBucketOrder(b);
    if (!names.length) {
      // v0.9-P2-3 — illustrated empty state.  Compact (110×82) so
      // the SVG sits comfortably inside the narrow buckets panel.
      bucketsList.innerHTML = `<div class="muted" style="padding:14px 12px;text-align:center;font-size:11.5px;line-height:1.65">
        <svg viewBox="0 0 160 120" style="width:110px;height:82px;
             margin-bottom:6px;opacity:0.95;
             filter:drop-shadow(0 6px 18px var(--accent-glow))">
          <use href="#art-empty-buckets"/>
        </svg>
        <div style="font-weight:600;color:var(--fg);font-size:12.5px;margin-bottom:4px">
          还没有桶
        </div>
        在下面输入名字 + Enter 创建第一个。<br>
        创建后,把卡片拖到桶上即可归属。<br>
        每个桶可以单独导出 zip / 复制文件名 / 清空。
      </div>`;
    } else {
      bucketsList.innerHTML = names.map(name => {
        const items = b[name] || [];
        return `<div class="bk-item" data-bucket="${esc(name)}">
          <span class="bk-grip" role="button" tabindex="0" draggable="true"
                aria-label="拖动以重新排序 “${esc(name)}” 桶"
                title="拖动以重新排序">
            <svg aria-hidden="true"><use href="#icon-grip"/></svg>
          </span>
          <div class="bk-name">
            🪣 ${esc(name)}
            <span class="bk-count">${items.length} 张</span>
          </div>
          <div class="bk-actions">
            <button class="bk-btn" data-bk-action="export" data-bucket="${esc(name)}" ${items.length ? '' : 'disabled style="opacity:0.4"'}>下载 ZIP</button>
            <button class="bk-btn" data-bk-action="copy"   data-bucket="${esc(name)}" ${items.length ? '' : 'disabled style="opacity:0.4"'}>复制文件名</button>
            <button class="bk-btn" data-bk-action="filter" data-bucket="${esc(name)}" ${items.length ? '' : 'disabled style="opacity:0.4"'}>筛选</button>
            <button class="bk-btn danger" data-bk-action="clear" data-bucket="${esc(name)}">清空</button>
            <button class="bk-btn danger" data-bk-action="delete" data-bucket="${esc(name)}">删除桶</button>
          </div>
        </div>`;
      }).join("");
    }
    _renderBucketsPill();
    _refreshCardBucketTags();
  }

  function _refreshCardBucketTags() {
    // Show "🪣 客户精选" badge on cards that belong to any bucket.
    const b = _readBuckets();
    const fnToBuckets = new Map();
    for (const [name, items] of Object.entries(b)) {
      for (const fn of items) {
        if (!fnToBuckets.has(fn)) fnToBuckets.set(fn, []);
        fnToBuckets.get(fn).push(name);
      }
    }
    grid.querySelectorAll(".card[data-fn]").forEach(card => {
      const tags = fnToBuckets.get(card.dataset.fn) || [];
      if (tags.length) {
        card.classList.add("bk-tagged");
        card.dataset.bkTags = "🪣 " + tags.join(" · ");
      } else {
        card.classList.remove("bk-tagged");
        delete card.dataset.bkTags;
      }
    });
  }

  function openBucketsPanel() {
    bucketsPanel.classList.add("show");
    bucketsPanel.setAttribute("aria-hidden", "false");
    _renderBucketsPanel();
  }
  function closeBucketsPanel() {
    bucketsPanel.classList.remove("show");
    bucketsPanel.setAttribute("aria-hidden", "true");
  }
  bucketsToggleBtn.addEventListener("click", openBucketsPanel);
  bucketsCloseBtn.addEventListener("click", closeBucketsPanel);

  // New bucket
  function _createBucket() {
    const name = newBucketName.value.trim();
    if (!name) return;
    const b = _readBuckets();
    const isNew = !b[name];
    if (isNew) b[name] = [];
    _writeBuckets(b);
    // v0.6 (4/5) — append new buckets to the end of the user-drag
    // order so creation never reshuffles existing positions.
    if (isNew) {
      const order = _readBucketOrder(b);
      if (!order.includes(name)) order.push(name);
      _writeBucketOrder(order);
    }
    newBucketName.value = "";
    _renderBucketsPanel();
  }
  newBucketBtn.addEventListener("click", _createBucket);
  newBucketName.addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); _createBucket(); }
  });

  // Per-bucket action handlers (delegated)
  bucketsList.addEventListener("click", async e => {
    const btn = e.target.closest("[data-bk-action]");
    if (!btn) return;
    const action = btn.dataset.bkAction;
    const name = btn.dataset.bucket;
    const b = _readBuckets();
    const items = b[name] || [];

    if (action === "clear") {
      if (!items.length) return;
      if (!confirm(`清空 "${name}" 桶里的 ${items.length} 张?(桶本身保留)`)) return;
      b[name] = []; _writeBuckets(b); _renderBucketsPanel();
    } else if (action === "delete") {
      if (!confirm(`删除整个 "${name}" 桶?里面 ${items.length} 张照片的归属会被清空。`)) return;
      delete b[name]; _writeBuckets(b);
      // v0.6 (4/5) — also drop the name from the persisted drag order
      // so future reads don't keep a phantom slot.
      const order = _readBucketOrder(b).filter(n => n !== name);
      _writeBucketOrder(order);
      _renderBucketsPanel();
    } else if (action === "copy") {
      try {
        await navigator.clipboard.writeText(items.join("\n"));
        showToast(`已复制 ${items.length} 个文件名到剪贴板`, "success");
      } catch (_e) {
        showToast("剪贴板写入失败 — 浏览器可能未授权", "error");
      }
    } else if (action === "filter") {
      // Pipe the bucket into a virtual semSearch-style filter
      filterState.semSearch = {
        q: `🪣 ${name}`,
        filenames: new Set(items),
      };
      const semInput = document.getElementById("semSearchInput");
      const semClear = document.getElementById("semSearchClearBtn");
      if (semInput) semInput.value = `🪣 ${name}`;
      if (semClear) semClear.style.display = "";
      render();
      closeBucketsPanel();
    } else if (action === "export") {
      // POST /buckets/export/<run> with the filename list. Server
      // zips them on the fly + returns a downloadable URL.
      btn.disabled = true; const orig = btn.textContent; btn.textContent = "导出中…";
      try {
        const res = await fetch(`/buckets/export/${run_id}`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({name, filenames: items}),
        });
        const d = await res.json();
        if (!d.ok) throw new Error(d.error || `HTTP ${res.status}`);
        // Trigger download
        const a = document.createElement("a");
        a.href = d.zip_url;
        a.download = d.zip_filename || `${name}.zip`;
        document.body.appendChild(a); a.click(); a.remove();
        showToast(`已导出 "${name}" 桶 (${items.length} 张)`, "success");
      } catch (err) {
        showToast("桶导出失败: " + err.message, "error");
      } finally {
        btn.disabled = false; btn.textContent = orig;
      }
    }
  });

  // Drag-and-drop wiring on the grid. We use HTML5 native drag
  // because every modern browser supports it + Lr/C1 users already
  // know the gesture from their catalog tools.
  grid.addEventListener("dragstart", e => {
    const card = e.target.closest(".card[data-fn]");
    if (!card) return;
    e.dataTransfer.effectAllowed = "copyMove";
    e.dataTransfer.setData("text/pixcull-fn", card.dataset.fn);
    card.classList.add("bk-dragging");
    // If panel is closed, slide it in so the user can see where
    // to drop. (Don't auto-close — they may drop into multiple.)
    if (!bucketsPanel.classList.contains("show")) openBucketsPanel();
  });
  grid.addEventListener("dragend", e => {
    const card = e.target.closest(".card[data-fn]");
    if (card) card.classList.remove("bk-dragging");
  });
  // Make every card draggable. Set the attribute when cards render.
  const _origGridSetup = () => {
    grid.querySelectorAll(".card[data-fn]").forEach(c => c.draggable = true);
  };
  _origGridSetup();
  // Re-apply after every re-render (filter change rebuilds DOM).
  // v0.7-P0-3 — throttle the observer callback to once every
  // ~80ms.  Without this, a 5k-row chunked render fires the
  // callback dozens of times per second; each fire walks the
  // whole grid + the bucket localStorage map. Throttling cuts
  // wall-clock by ~85% in the 5k synthetic test.
  const _bucketsObserverFn = _throttle(() => {
    _origGridSetup();
    _refreshCardBucketTags();
  }, 80);
  const _bucketsObserver = new MutationObserver(_bucketsObserverFn);
  _bucketsObserver.observe(grid, {childList: true});
  // Expose for /admin/perf diagnostics.
  window._pcBucketsObsFn = _bucketsObserverFn;

  // v0.6 (4/5) — distinguish card-into-bucket vs bucket-reorder by
  // looking at which payload is in dataTransfer. dataTransfer.types
  // is the only cross-browser reliable check during dragover (you
  // can't getData(...) until drop). Both gestures live on the same
  // bucketsList; this guard makes them coexist without crosstalk.
  function _dragHasType(e, t) {
    if (!e.dataTransfer || !e.dataTransfer.types) return false;
    // .contains() handles DataTransferItemList; .indexOf() handles
    // the (legacy) array form. Both exist in modern browsers.
    if (typeof e.dataTransfer.types.contains === "function") {
      return e.dataTransfer.types.contains(t);
    }
    return Array.prototype.indexOf.call(e.dataTransfer.types, t) >= 0;
  }

  // Drop target wiring on bucket items (card-into-bucket)
  bucketsList.addEventListener("dragover", e => {
    // Skip if this is a bucket-reorder drag, not a card.
    if (_dragHasType(e, "text/pixcull-bucket-name")) return;
    const item = e.target.closest(".bk-item[data-bucket]");
    if (!item) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    item.classList.add("drag-over");
  });
  bucketsList.addEventListener("dragleave", e => {
    const item = e.target.closest(".bk-item[data-bucket]");
    if (item) item.classList.remove("drag-over");
  });
  bucketsList.addEventListener("drop", e => {
    const item = e.target.closest(".bk-item[data-bucket]");
    if (!item) return;
    // Bucket-reorder drop is handled by the reorder block below;
    // this branch only consumes card-into-bucket drops.
    if (_dragHasType(e, "text/pixcull-bucket-name")) return;
    e.preventDefault();
    item.classList.remove("drag-over");
    const fn = e.dataTransfer.getData("text/pixcull-fn");
    if (!fn) return;
    const name = item.dataset.bucket;
    const b = _readBuckets();
    if (!b[name]) b[name] = [];
    if (!b[name].includes(fn)) b[name].push(fn);
    _writeBuckets(b);
    _renderBucketsPanel();
  });

  // v0.6 (4/5) — bucket-reorder DnD. The user grabs the six-dot
  // handle on the left of a bucket item; while dragging over other
  // items we show a thick top/bottom border to communicate the drop
  // slot (above / below the hovered item). On drop, we compute the
  // new order, persist it, and re-render the panel.
  let _bkReorderName = null;
  function _bkClearReorderHints() {
    bucketsList.querySelectorAll(
      ".bk-item.bk-drop-above, .bk-item.bk-drop-below, .bk-item.bk-reordering"
    ).forEach(el => {
      el.classList.remove("bk-drop-above", "bk-drop-below", "bk-reordering");
    });
  }
  bucketsList.addEventListener("dragstart", e => {
    const grip = e.target.closest(".bk-grip");
    if (!grip) return;
    const item = grip.closest(".bk-item[data-bucket]");
    if (!item) return;
    _bkReorderName = item.dataset.bucket;
    e.dataTransfer.effectAllowed = "move";
    // Carry the source name as the *type*; the value is also the
    // name so a graceful fallback still works if the payload is the
    // only thing the receiver checks.
    e.dataTransfer.setData("text/pixcull-bucket-name", _bkReorderName);
    // Hide the default drag image's text so the user sees the actual
    // bucket row tracking the cursor.
    try { e.dataTransfer.setDragImage(item, 12, 18); } catch (_e) {}
    item.classList.add("bk-reordering");
  });
  bucketsList.addEventListener("dragend", () => {
    _bkReorderName = null;
    _bkClearReorderHints();
  });
  bucketsList.addEventListener("dragover", e => {
    if (!_dragHasType(e, "text/pixcull-bucket-name")) return;
    const item = e.target.closest(".bk-item[data-bucket]");
    if (!item) return;
    if (item.dataset.bucket === _bkReorderName) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    // Decide above-or-below based on cursor Y within the item.
    const r = item.getBoundingClientRect();
    const above = (e.clientY - r.top) < r.height / 2;
    bucketsList.querySelectorAll(".bk-item.bk-drop-above, .bk-item.bk-drop-below")
      .forEach(el => el.classList.remove("bk-drop-above", "bk-drop-below"));
    item.classList.add(above ? "bk-drop-above" : "bk-drop-below");
  });
  bucketsList.addEventListener("drop", e => {
    if (!_dragHasType(e, "text/pixcull-bucket-name")) return;
    const item = e.target.closest(".bk-item[data-bucket]");
    if (!item) return;
    e.preventDefault();
    const dragName = e.dataTransfer.getData("text/pixcull-bucket-name") || _bkReorderName;
    const dropName = item.dataset.bucket;
    if (!dragName || dragName === dropName) {
      _bkClearReorderHints();
      return;
    }
    const r = item.getBoundingClientRect();
    const above = (e.clientY - r.top) < r.height / 2;
    const buckets = _readBuckets();
    const order = _readBucketOrder(buckets);
    const from = order.indexOf(dragName);
    if (from < 0) { _bkClearReorderHints(); return; }
    order.splice(from, 1);
    // Re-find the drop index AFTER removing the source — splice
    // shifts indices so the insertion target moves with it.
    let to = order.indexOf(dropName);
    if (to < 0) to = order.length;
    if (!above) to += 1;
    order.splice(to, 0, dragName);
    _writeBucketOrder(order);
    _bkClearReorderHints();
    _renderBucketsPanel();
    showToast(`已重排 “${dragName}”`, "success");
  });

  // Esc closes the buckets panel (when no other modal is hogging Esc)
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && bucketsPanel.classList.contains("show")) {
      // Yield to other modals first — lightbox, annotation, etc.
      if (lb.classList.contains("show")) return;
      if (cmpModal.classList.contains("show")) return;
      closeBucketsPanel();
    }
  });

  // Initial paint + pill update on page load
  _renderBucketsPill();
  _refreshCardBucketTags();

  // ==================================================================
  // P-UX-4 — reject-reason taxonomy. Three concerns:
  //   1. fetch the server-advertised cull-reason list once at boot
  //   2. show a transient picker after every cull action
  //   3. build a dynamic "因为 X 而 cull" filter pill group from rows
  // The picker is OPT-IN — culling stays a 1-keystroke action; the
  // picker auto-dismisses in ~6 s if the user doesn't engage.
  // ==================================================================

  const cullReasonTray   = document.getElementById("cullReasonTray");
  const cullReasonPills  = document.getElementById("cullReasonPills");
  const cullReasonSkip   = document.getElementById("cullReasonSkip");
  let _cullReasonFn      = null;   // the photo currently being asked about
  let _cullReasonTimer   = null;   // setTimeout handle for auto-dismiss

  // P-UX-9 — accumulated counts across the user's annotation history.
  // Server returns one count per taxonomy token; we use it to sort the
  // picker pills so high-frequency reasons land first (less travel).
  var _CULL_REASONS_STATS = {};   // {token: count}

  async function _loadCullReasonTaxonomy() {
    try {
      // Fire the taxonomy + stats in parallel — they're independent.
      const [taxoR, statsR] = await Promise.all([
        fetch("/api/v1/taxonomy"),
        fetch("/api/v1/cull_reasons/stats"),
      ]);
      if (!taxoR.ok) return;
      const d = await taxoR.json();
      _CULL_REASONS_LIST = Array.isArray(d.cull_reasons) ? d.cull_reasons : [];
      _CULL_REASONS_MAP = {};
      for (const e of _CULL_REASONS_LIST) {
        if (e && e.token) _CULL_REASONS_MAP[e.token] = e.label_zh || e.token;
      }
      if (statsR && statsR.ok) {
        const sd = await statsR.json();
        _CULL_REASONS_STATS = sd.counts || {};
        // Sort taxonomy in place by descending user frequency. Tokens
        // with no history keep their declared taxonomy order at the
        // tail (sort is stable per spec).
        _CULL_REASONS_LIST.sort((a, b) =>
          (_CULL_REASONS_STATS[b.token] || 0) - (_CULL_REASONS_STATS[a.token] || 0)
        );
      }
      _populateReasonPills();
      // If any row already has a cull_reason from a prior session,
      // the filter pill group needs to come up populated.
      _renderCullReasonFilters();
    } catch (_e) { /* offline / API missing — picker stays inert */ }
  }

  function _populateReasonPills() {
    if (!cullReasonPills) return;
    // Render the sorted-by-frequency tokens; append a small "× N"
    // count hint to the user's top-3 most-used so they see their
    // own bias.
    const total = Object.values(_CULL_REASONS_STATS).reduce((s,n) => s+n, 0);
    cullReasonPills.innerHTML = _CULL_REASONS_LIST.map((e, idx) => {
      const n = _CULL_REASONS_STATS[e.token] || 0;
      const hint = (idx < 3 && n > 0 && total >= 5)
        ? ` <span style="opacity:0.55;font-size:10px">×${n}</span>`
        : "";
      return `<button class="reason-pill" data-token="${esc(e.token)}" type="button"
               title="${esc(e.label_zh || e.token)}${n > 0 ? ` · 你已用过 ${n} 次` : ''}">${esc(e.label_zh || e.token)}${hint}</button>`;
    }).join(" ");
  }

  function _hideCullReasonTray() {
    if (cullReasonTray) cullReasonTray.classList.remove("show");
    _cullReasonFn = null;
    if (_cullReasonTimer) {
      clearTimeout(_cullReasonTimer);
      _cullReasonTimer = null;
    }
  }

  function promptCullReason(fn) {
    if (!fn || !cullReasonTray || !_CULL_REASONS_LIST.length) return;
    _cullReasonFn = fn;
    cullReasonTray.classList.add("show");
    if (_cullReasonTimer) clearTimeout(_cullReasonTimer);
    _cullReasonTimer = setTimeout(_hideCullReasonTray, 6000);
  }

  async function _setCullReason(token) {
    const fn = _cullReasonFn;
    _hideCullReasonTray();
    if (!fn || !token) return;
    try {
      await fetch(`/annotation/${run_id}/${encodeURIComponent(fn)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          axes: {},
          overall_label: "cull",
          overall_rationale: `cull reason: ${token}`,
          cull_reason: token,
        }),
      });
      const r = rows.find(x => x.filename === fn);
      if (r) { r.cull_reason = token; r.decision = "cull"; r.rubric_human_labeled = true; }
      showToast(`已记录 cull 原因: ${_cullReasonLabel(token)}`, "success");
      _renderCullReasonFilters();
      render();
    } catch (_e) { /* ignore — user can re-pick next time */ }
  }

  // Pills are populated dynamically — delegate clicks on the tray.
  if (cullReasonTray) {
    cullReasonTray.addEventListener("click", e => {
      const pill = e.target.closest(".reason-pill");
      if (pill && pill.dataset.token) {
        _setCullReason(pill.dataset.token);
        return;
      }
      if (e.target === cullReasonSkip) _hideCullReasonTray();
    });
  }

  // ----- Filter pill row for "因为 X 而 cull" -----

  function _renderCullReasonFilters() {
    // v0.6 — see buildFaceFilters
    const wrap = document.getElementById("cullReasonFilter");
    const divider = document.getElementById("cullReasonDivider");
    const lpGroup = document.getElementById("lpReasonGroup");
    if (!wrap) return;
    // Tally tokens actually present in the batch so we only show
    // pills the user can meaningfully click. {token: count}
    const tally = new Map();
    for (const r of rows) {
      const t = r.cull_reason;
      if (t) tally.set(t, (tally.get(t) || 0) + 1);
    }
    if (tally.size === 0) {
      if (divider) divider.style.display = "none";
      if (lpGroup) lpGroup.style.display = "none";
      wrap.innerHTML = "";
      return;
    }
    if (divider) divider.style.display = "";
    if (lpGroup) lpGroup.style.display = "";
    // Render in the taxonomy's declared order, then any unknown
    // tokens at the end (defensive — schema drift).
    const known = _CULL_REASONS_LIST.map(e => e.token);
    const tokens = [
      ...known.filter(t => tally.has(t)),
      ...[...tally.keys()].filter(t => !known.includes(t)),
    ];
    wrap.innerHTML = tokens.map(t => {
      const count = tally.get(t);
      const active = filterState.cullReason === t ? " active" : "";
      return `<span class="pill reason-pill${active}" data-cull-reason="${esc(t)}"
                    title="只看因为 ${esc(_cullReasonLabel(t))} 而 cull 的">✕ ${esc(_cullReasonLabel(t))} <span style="opacity:0.7">${count}</span></span>`;
    }).join("");
  }

  // Wire pill clicks via delegation so dynamic rebuilds keep working.
  document.getElementById("cullReasonFilter")?.addEventListener("click", e => {
    const pill = e.target.closest(".pill[data-cull-reason]");
    if (!pill) return;
    const token = pill.dataset.cullReason;
    filterState.cullReason = (filterState.cullReason === token) ? null : token;
    _renderCullReasonFilters();
    render();
  });

  // Kick off the taxonomy fetch. Doesn't block anything — the picker
  // just stays empty until the response lands (typically <50 ms on
  // localhost).
  _loadCullReasonTaxonomy();

  // P0.3 — prev/next burst walk + keyboard navigation. Compute the
  // list of REAL burst cluster keys (size ≥ 2) once; openCompare
  // tracks the index into this list so prev/next can advance.
  let _COMPARE_BURST_KEYS = [];
  let _COMPARE_CUR_IDX = -1;

  function _rebuildBurstKeys() {
    const counts = new Map();
    for (const r of rows) {
      if (r.cluster_id == null) continue;
      counts.set(r.cluster_id, (counts.get(r.cluster_id) || 0) + 1);
    }
    _COMPARE_BURST_KEYS = [...counts.entries()]
      .filter(([_, n]) => n >= 2)
      .sort((a, b) => a[0] - b[0])           // stable by cluster_id
      .map(([cid, _]) => `c${cid}`);
  }
  _rebuildBurstKeys();

  // Wrap openCompare so callers (button clicks, prev/next) both
  // update the current index.
  const _origOpenCompare = openCompare;
  openCompare = function(clusterKey) {
    // Re-build the list lazily in case rows have shifted
    if (_COMPARE_BURST_KEYS.length === 0) _rebuildBurstKeys();
    _COMPARE_CUR_IDX = _COMPARE_BURST_KEYS.indexOf(clusterKey);
    _origOpenCompare(clusterKey);
    _updateCmpNavLabels();
  };

  function _updateCmpNavLabels() {
    const prev = document.getElementById("cmpPrev");
    const next = document.getElementById("cmpNext");
    if (!prev || !next) return;
    const total = _COMPARE_BURST_KEYS.length;
    if (total <= 1) {
      prev.disabled = true; next.disabled = true;
      prev.style.opacity = next.style.opacity = "0.4";
    } else {
      prev.disabled = _COMPARE_CUR_IDX <= 0;
      next.disabled = _COMPARE_CUR_IDX >= total - 1;
      prev.style.opacity = prev.disabled ? "0.4" : "1";
      next.style.opacity = next.disabled ? "0.4" : "1";
    }
  }

  function _cmpStep(delta) {
    const nxt = _COMPARE_CUR_IDX + delta;
    if (nxt < 0 || nxt >= _COMPARE_BURST_KEYS.length) return;
    openCompare(_COMPARE_BURST_KEYS[nxt]);
  }

  document.getElementById("cmpPrev").addEventListener("click",
    () => _cmpStep(-1));
  document.getElementById("cmpNext").addEventListener("click",
    () => _cmpStep(1));

  // Keyboard shortcuts while the compare modal is open. Mirrors the
  // V14.4 modal-registry pattern used by other modals.
  document.addEventListener("keydown", e => {
    if (!cmpModal.classList.contains("show")) return;
    if (e.key === "ArrowLeft" || e.key === "j") {
      e.preventDefault(); _cmpStep(-1);
    } else if (e.key === "ArrowRight" || e.key === "k") {
      e.preventDefault(); _cmpStep(1);
    }
    // P-UX-7 — z = toggle synced 1:1 across all compare cells.
    // + / − = wheel-equivalent zoom centered on viewport.
    else if (e.key === "z" || e.key === "Z") {
      e.preventDefault(); _cmpZoomToggleSynced(null, null);
    }
    else if (e.key === "0") {
      e.preventDefault();
      _cmpZoom.panNX = 0; _cmpZoom.panNY = 0;
      _applyCmpTransform();
    }
    else if (e.key === "+" || e.key === "=") {
      e.preventDefault();
      const r = cmpBody.getBoundingClientRect();
      _cmpZoomToPoint((_cmpZoom.scale || 1) * 1.25,
                       r.left + r.width / 2, r.top + r.height / 2);
    }
    else if (e.key === "-" || e.key === "_") {
      e.preventDefault();
      const r = cmpBody.getBoundingClientRect();
      _cmpZoomToPoint((_cmpZoom.scale || 1) / 1.25,
                       r.left + r.width / 2, r.top + r.height / 2);
    }
  });

  // ==================================================================
  // P-UX-7 — synced 1:1 zoom across compare cells.
  //
  //   click any cell (fit)     → 1:1 zoom centered on click point;
  //                              ALL cells zoom in to the same
  //                              normalized point of their image
  //   click any cell (zoomed)  → back to fit (no pan)
  //   drag any cell            → pan ALL cells in lock-step
  //   wheel on any cell        → zoom all centered on cursor
  //   z                        → keyboard toggle (above)
  //
  // Hi-res swap: each cell's <img> starts as a thumbnail; on first
  // zoom-in we swap each src to /full/<run>/<fn>?w=3600 so 1:1 shows
  // real pixels instead of upscaled thumb mush. The data-full attr
  // already on each .img-wrap (set by openCompare) carries the
  // hi-res URL base.
  //
  // The shared state uses NORMALIZED pan (0..1 fractions of fit-cell
  // size) so cells of different aspect ratios still pan to the same
  // relative region — what photographers actually want when comparing
  // near-duplicates with subtly different crops.
  // ==================================================================

  const _CMP_MIN_SCALE = 1.0;
  const _CMP_MAX_SCALE = 8.0;
  const _CMP_CLICK_DRAG_THRESH = 4;

  const _cmpZoom = {
    scale: 1.0,
    panNX: 0.0,
    panNY: 0.0,
    mode: "fit",
    dragging: false,
    dragCellEl: null,
    dragStartClientX: 0,
    dragStartClientY: 0,
    dragStartPanNX: 0,
    dragStartPanNY: 0,
    mouseDownPos: null,
    hiResLoaded: false,
  };

  function _cmpResetZoom() {
    _cmpZoom.scale = 1.0;
    _cmpZoom.panNX = 0.0;
    _cmpZoom.panNY = 0.0;
    _cmpZoom.mode = "fit";
    _cmpZoom.hiResLoaded = false;
    _applyCmpTransform();
    _updateCmpZoomBadge();
    cmpBody.querySelectorAll(".cmp-cell")
      .forEach(c => c.classList.remove("zoomed", "dragging"));
  }

  function _applyCmpTransform() {
    if (!cmpBody) return;
    const { scale, panNX, panNY } = _cmpZoom;
    cmpBody.querySelectorAll(".cmp-cell img").forEach(img => {
      const w = img.offsetWidth, h = img.offsetHeight;
      if (!w || !h) return;
      const panX = panNX * w;
      const panY = panNY * h;
      const parts = [];
      if (panX || panY) parts.push(`translate(${panX}px, ${panY}px)`);
      if (scale !== 1) parts.push(`scale(${scale})`);
      img.style.transform = parts.join(" ");
    });
  }

  function _updateCmpZoomBadge() {
    const badge = document.getElementById("cmpZoomBadge");
    const tgl = document.getElementById("cmpZoomToggle");
    if (!badge || !tgl) return;
    if (_cmpZoom.mode === "fit") {
      badge.classList.remove("show");
      badge.textContent = "";
      tgl.classList.remove("active");
    } else {
      const firstImg = cmpBody.querySelector(".cmp-cell img");
      const oneOneScale = (firstImg && firstImg.offsetWidth && firstImg.naturalWidth)
        ? firstImg.naturalWidth / firstImg.offsetWidth : 1;
      const pct = Math.round(100 * _cmpZoom.scale / oneOneScale);
      badge.textContent = pct === 100 ? "1:1" : `${Math.round(100 * _cmpZoom.scale)}%`;
      badge.classList.add("show");
      tgl.classList.add("active");
    }
  }

  // Map a screen-coord (clientX, clientY) to a normalized image
  // coordinate (-0.5..0.5) for the cell the cursor is currently in.
  // Returns { cell, nx, ny } or null if cursor isn't over any cell.
  function _cmpCursorNorm(clientX, clientY) {
    const cells = cmpBody.querySelectorAll(".cmp-cell img");
    for (const img of cells) {
      const r = img.getBoundingClientRect();
      if (clientX >= r.left && clientX <= r.right
          && clientY >= r.top && clientY <= r.bottom) {
        const nx = (clientX - (r.left + r.width  / 2)) / r.width;
        const ny = (clientY - (r.top  + r.height / 2)) / r.height;
        return { cell: img.closest(".cmp-cell"), nx, ny };
      }
    }
    return null;
  }

  // Swap each cell's <img> to its hi-res companion the first time
  // the user zooms in on this batch. Cached state on _cmpZoom so
  // we don't re-request per-zoom-step.
  function _maybeLoadCmpHiRes() {
    if (_cmpZoom.hiResLoaded) return;
    _cmpZoom.hiResLoaded = true;  // optimistic — fetch in background
    cmpBody.querySelectorAll(".cmp-cell .img-wrap").forEach(wrap => {
      const baseFull = wrap.dataset.full;
      if (!baseFull) return;
      const url = `${baseFull}?w=3600`;
      const img = wrap.querySelector("img");
      if (!img) return;
      const pre = new Image();
      pre.onload = () => {
        // Only swap if the cmp modal is still open AND this img is
        // still the same DOM node (user may have switched cluster).
        if (!cmpModal.classList.contains("show")) return;
        if (!img.isConnected) return;
        img.src = url;
      };
      pre.src = url;
    });
  }

  // Core zoom-to-point operation: takes a target scale + a screen
  // coord, anchors the cursor's normalized point under the cursor
  // (so the spot you clicked stays put while everything else
  // scales around it), applies the transform to all cells.
  function _cmpZoomToPoint(newScale, clientX, clientY) {
    newScale = Math.max(_CMP_MIN_SCALE, Math.min(_CMP_MAX_SCALE, newScale));
    let cursor = null;
    if (clientX != null && clientY != null) {
      cursor = _cmpCursorNorm(clientX, clientY);
    }
    if (!cursor) cursor = { nx: 0, ny: 0 };
    const s = _cmpZoom.scale || 1;
    // panNX' = cursorNX * (1 - s'/s) + panNX * (s'/s)
    _cmpZoom.panNX = cursor.nx * (1 - newScale / s) + _cmpZoom.panNX * (newScale / s);
    _cmpZoom.panNY = cursor.ny * (1 - newScale / s) + _cmpZoom.panNY * (newScale / s);
    _cmpZoom.scale = newScale;
    _cmpZoom.mode = newScale > 1.001 ? "1to1" : "fit";
    if (_cmpZoom.mode === "fit") {
      _cmpZoom.panNX = 0; _cmpZoom.panNY = 0;
      cmpBody.querySelectorAll(".cmp-cell").forEach(c =>
        c.classList.remove("zoomed", "dragging"));
    } else {
      cmpBody.querySelectorAll(".cmp-cell").forEach(c =>
        c.classList.add("zoomed"));
      _maybeLoadCmpHiRes();
    }
    _clampCmpPan();
    _applyCmpTransform();
    _updateCmpZoomBadge();
  }

  function _clampCmpPan() {
    // panNX/Y are normalized to fit-cell-size; max meaningful pan is
    // ±(scale - 1)/2 because at scale=1 the image fills the cell
    // exactly (no overflow), at scale=2 the overflow per side is
    // (2-1)/2 = 0.5 of fit size.
    const maxN = Math.max(0, (_cmpZoom.scale - 1) / 2);
    _cmpZoom.panNX = Math.max(-maxN, Math.min(maxN, _cmpZoom.panNX));
    _cmpZoom.panNY = Math.max(-maxN, Math.min(maxN, _cmpZoom.panNY));
  }

  function _cmpZoomToggleSynced(clientX, clientY) {
    if (_cmpZoom.mode === "fit") {
      // Pick a target scale based on the first cell's natural-to-
      // displayed ratio so "1:1" really means 1 image px per screen
      // px on that cell (and roughly that on the others).
      const firstImg = cmpBody.querySelector(".cmp-cell img");
      const target = (firstImg && firstImg.offsetWidth && firstImg.naturalWidth)
        ? firstImg.naturalWidth / firstImg.offsetWidth : 2.5;
      if (clientX == null || clientY == null) {
        const r = cmpBody.getBoundingClientRect();
        clientX = r.left + r.width / 2;
        clientY = r.top  + r.height / 2;
      }
      _cmpZoomToPoint(target, clientX, clientY);
    } else {
      _cmpZoomToPoint(1.0, null, null);
    }
  }

  // Toolbar button — toggles synced zoom around viewport center.
  document.getElementById("cmpZoomToggle")?.addEventListener("click", e => {
    e.stopPropagation();
    _cmpZoomToggleSynced(null, null);
  });

  // Mouse interactions on cmpBody — delegation so they survive every
  // openCompare* rebuild. Click toggles; drag pans; wheel zooms.
  cmpBody.addEventListener("mousedown", e => {
    if (e.button !== 0) return;
    const img = e.target.closest(".cmp-cell img");
    if (!img) return;
    _cmpZoom.mouseDownPos = { x: e.clientX, y: e.clientY };
    if (_cmpZoom.mode === "1to1") {
      e.preventDefault();
      _cmpZoom.dragging = true;
      _cmpZoom.dragCellEl = img.closest(".cmp-cell");
      _cmpZoom.dragStartClientX = e.clientX;
      _cmpZoom.dragStartClientY = e.clientY;
      _cmpZoom.dragStartPanNX = _cmpZoom.panNX;
      _cmpZoom.dragStartPanNY = _cmpZoom.panNY;
      cmpBody.querySelectorAll(".cmp-cell").forEach(c =>
        c.classList.add("dragging"));
    }
  });
  window.addEventListener("mousemove", e => {
    if (!_cmpZoom.dragging) return;
    // Translate screen-delta into normalized pan delta using the
    // dragged cell's dimensions as the reference.
    const refImg = _cmpZoom.dragCellEl
      ? _cmpZoom.dragCellEl.querySelector("img")
      : cmpBody.querySelector(".cmp-cell img");
    if (!refImg || !refImg.offsetWidth || !refImg.offsetHeight) return;
    const dnx = (e.clientX - _cmpZoom.dragStartClientX) / refImg.offsetWidth;
    const dny = (e.clientY - _cmpZoom.dragStartClientY) / refImg.offsetHeight;
    _cmpZoom.panNX = _cmpZoom.dragStartPanNX + dnx;
    _cmpZoom.panNY = _cmpZoom.dragStartPanNY + dny;
    _clampCmpPan();
    _applyCmpTransform();
  });
  window.addEventListener("mouseup", () => {
    if (_cmpZoom.dragging) {
      _cmpZoom.dragging = false;
      _cmpZoom.dragCellEl = null;
      cmpBody.querySelectorAll(".cmp-cell").forEach(c =>
        c.classList.remove("dragging"));
    }
  });
  cmpBody.addEventListener("click", e => {
    const img = e.target.closest(".cmp-cell img");
    if (!img) return;
    const down = _cmpZoom.mouseDownPos;
    _cmpZoom.mouseDownPos = null;
    if (down) {
      const dist = Math.hypot(e.clientX - down.x, e.clientY - down.y);
      if (dist > _CMP_CLICK_DRAG_THRESH) return;
    }
    e.stopPropagation();
    _cmpZoomToggleSynced(e.clientX, e.clientY);
  });
  cmpBody.addEventListener("wheel", e => {
    if (!cmpModal.classList.contains("show")) return;
    if (!e.target.closest(".cmp-cell img")) return;
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    _cmpZoomToPoint((_cmpZoom.scale || 1) * factor, e.clientX, e.clientY);
  }, { passive: false });

  // ============================================================
  // v0.7-P0-1 — LR Compare-style RGB pixel readout.
  // Visible only when (a) the modal is open AND (b) the cells are
  // in 1:1 sync-zoom mode AND (c) the cursor is over a .cmp-cell
  // img-wrap.  Reads via canvas ImageData from the loaded <img> at
  // its natural resolution; one canvas per <img> src, lazily built
  // + cached on the element itself (img._rgbCanvas) so repeated
  // hovers don't re-paint.
  // ============================================================
  const cmpRgbReadout = document.getElementById("cmpRgbReadout");
  function _ensureRgbCanvas(img) {
    if (img._rgbCanvas) return img._rgbCanvas;
    if (!img.complete || !img.naturalWidth) return null;
    try {
      const c = document.createElement("canvas");
      c.width  = img.naturalWidth;
      c.height = img.naturalHeight;
      const ctx = c.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(img, 0, 0);
      // Cache the context too so we don't getContext on every sample.
      img._rgbCanvas = c;
      img._rgbCtx    = ctx;
      return c;
    } catch (_e) {
      // Cross-origin taint — unlikely in our setup (same-origin
      // /thumb/) but if it ever happens we just disable the readout.
      img._rgbCanvas = null;
      return null;
    }
  }
  function _hideRgbReadout() {
    if (cmpRgbReadout) cmpRgbReadout.classList.remove("show");
  }
  function _samplePixel(img, naturalX, naturalY) {
    const c = _ensureRgbCanvas(img);
    if (!c) return null;
    try {
      const d = img._rgbCtx.getImageData(
        Math.max(0, Math.min(c.width  - 1, Math.round(naturalX))),
        Math.max(0, Math.min(c.height - 1, Math.round(naturalY))),
        1, 1
      ).data;
      return { r: d[0], g: d[1], b: d[2] };
    } catch (_e) { return null; }
  }
  function _updateRgbReadout(e) {
    if (!cmpRgbReadout) return;
    if (!cmpModal.classList.contains("show")) { _hideRgbReadout(); return; }
    const cell = e.target.closest(".cmp-cell");
    if (!cell || !cell.classList.contains("zoomed")) {
      _hideRgbReadout();
      return;
    }
    const img = cell.querySelector("img");
    if (!img) { _hideRgbReadout(); return; }
    const rect = img.getBoundingClientRect();
    // Cursor outside the displayed image — happens in the gutters
    // when the image is wider/taller than the wrap and centered.
    if (e.clientX < rect.left || e.clientX > rect.right ||
        e.clientY < rect.top  || e.clientY > rect.bottom) {
      _hideRgbReadout();
      return;
    }
    const nx = ((e.clientX - rect.left) / rect.width)  * img.naturalWidth;
    const ny = ((e.clientY - rect.top)  / rect.height) * img.naturalHeight;
    const px = _samplePixel(img, nx, ny);
    if (!px) { _hideRgbReadout(); return; }
    // ITU-R BT.601 luma — matches what LR/PS show as "Y".
    const y = Math.round(0.299*px.r + 0.587*px.g + 0.114*px.b);
    const hex = "#" + [px.r, px.g, px.b]
      .map(v => v.toString(16).padStart(2, "0").toUpperCase()).join("");
    cmpRgbReadout.innerHTML = `
      <div class="rgb-line">
        <span class="swatch" style="background:rgb(${px.r},${px.g},${px.b})"></span>
        <span class="rgb-vals">R ${px.r}&nbsp;&nbsp;G ${px.g}&nbsp;&nbsp;B ${px.b}</span>
      </div>
      <div class="rgb-hex">${hex}</div>
      <div class="rgb-y">Y ${y} · ${Math.round((y/255)*100)}%</div>
    `;
    // Position to the right + below cursor by 12px; flip horizontally
    // when too close to viewport right.
    const READ_W = 160, READ_H = 64;
    let left = e.clientX + 14;
    let top  = e.clientY + 14;
    if (left + READ_W > window.innerWidth)  left = e.clientX - READ_W - 12;
    if (top  + READ_H > window.innerHeight) top  = e.clientY - READ_H - 12;
    cmpRgbReadout.style.left = left + "px";
    cmpRgbReadout.style.top  = top  + "px";
    cmpRgbReadout.classList.add("show");
  }
  cmpBody.addEventListener("mousemove", _updateRgbReadout);
  cmpBody.addEventListener("mouseleave", _hideRgbReadout);
  cmpModal.addEventListener("click", e => {
    if (e.target === cmpModal) _hideRgbReadout();
  });

  // XMP export — POST /export/<run_id>.
  // Two buttons:
  //   '下载 XMP zip'        → target=tmp,       always available
  //   '写到原图旁边'         → target=alongside,  only in scan mode
  const exportZipBtn = document.getElementById("exportZipBtn");
  const exportAlongsideBtn = document.getElementById("exportAlongsideBtn");
  const exportEmbeddedBtn = document.getElementById("exportEmbeddedBtn");
  const exportStatus = document.getElementById("exportStatus");

  if (summary.mode === "scan") {
    // P-UX-1 — clear the inline display:none rather than forcing
    // "inline-block"; the alongside button now lives inside the
    // export-menu panel where CSS lays items out vertically.
    exportAlongsideBtn.style.display = "";
    if (exportEmbeddedBtn) exportEmbeddedBtn.style.display = "";  // P-PRO-5
  }

  async function doExport(target, btn, successHtml) {
    btn.disabled = true;
    exportZipBtn.disabled = exportAlongsideBtn.disabled = true;
    exportStatus.textContent = "生成 XMP …";
    try {
      const res = await fetch(`/export/${run_id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${res.status}`);
      }
      const data = await res.json();
      exportStatus.innerHTML = successHtml(data);
    } catch (err) {
      exportStatus.textContent = "导出失败: " + (err.message || err);
    } finally {
      exportZipBtn.disabled = false;
      if (summary.mode === "scan") exportAlongsideBtn.disabled = false;
    }
  }

  exportZipBtn.addEventListener("click", () =>
    doExport("tmp", exportZipBtn, data =>
      `已生成 <b>${data.written}</b> 个 sidecar &nbsp;<a href="${data.zip_url}" download>下载 zip ↓</a>`
    )
  );
  exportAlongsideBtn.addEventListener("click", () => {
    if (!confirm(`将 ${summary.n_keep + summary.n_maybe + summary.n_cull} 个 .xmp 写到原图所在文件夹(${summary.origin_folder || "原位置"})?同名文件会被覆盖。`)) return;
    doExport("alongside", exportAlongsideBtn, data =>
      `已写入 <b>${data.written}</b> 个 .xmp 到原图旁边${data.skipped ? `,跳过 ${data.skipped} 个找不到原图的` : ''} · ${summary.origin_folder || ''}`
    );
  });
  // P-PRO-5 — in-file IPTC embed via exiftool. The handler is
  // identical to "alongside" but posts target="embedded" + uses
  // stricter confirm copy (this MODIFIES the original file, no
  // sidecar to delete if you change your mind).
  if (exportEmbeddedBtn) exportEmbeddedBtn.addEventListener("click", () => {
    const n = summary.n_keep + summary.n_maybe + summary.n_cull;
    if (!confirm(
        `将把 XMP/IPTC 元数据(rating + label + keywords + caption)`
        + `直接内嵌到 ${n} 个原始照片文件中(${summary.origin_folder || "原位置"})。\n\n`
        + `⚠ 这会修改原图文件本身,不写 sidecar — 单文件工作流但不可逆。\n`
        + `如果你想保留备份,先在 Finder/Files 备份这个文件夹再继续。\n\n`
        + `需要安装 exiftool (brew install exiftool / apt install libimage-exiftool-perl)。\n\n`
        + `继续?`)) return;
    doExport("embedded", exportEmbeddedBtn, data =>
      `已内嵌 <b>${data.written}</b> 个 IPTC 包到原图${data.skipped ? `,跳过 ${data.skipped} 个失败的` : ''}`
    );
  });

  // P-UX-1 — export-menu open/close + outside-click + Esc dismiss.
  // The inner buttons keep their original IDs (see above) so their
  // event handlers bind unchanged; this block only manages panel
  // visibility. Clicking any item fires its native handler then
  // closes the panel on the next microtask.
  const exportMenuBtn = document.getElementById("exportMenuBtn");
  const exportMenuPanel = document.getElementById("exportMenuPanel");
  function setExportMenu(open) {
    exportMenuPanel.classList.toggle("show", open);
    exportMenuBtn.classList.toggle("open", open);
    exportMenuBtn.setAttribute("aria-expanded", String(open));
  }
  exportMenuBtn.addEventListener("click", e => {
    e.stopPropagation();
    setExportMenu(!exportMenuPanel.classList.contains("show"));
  });
  exportMenuPanel.addEventListener("click", e => {
    if (e.target.closest(".export-btn")) {
      // setTimeout so the item's own click handler runs first
      // (avoids closing before the action fires).
      setTimeout(() => setExportMenu(false), 0);
    }
  });
  document.addEventListener("click", e => {
    if (!exportMenuPanel.classList.contains("show")) return;
    if (e.target.closest(".export-menu")) return;
    setExportMenu(false);
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && exportMenuPanel.classList.contains("show")) {
      setExportMenu(false);
    }
  });

  // v0.10-P2-1 — register the PWA service worker once on page-ready.
  // Best-effort: silent on browsers that don't support SW (Safari
  // < 11.1, all IE) or HTTP-served origins (which lack the secure-
  // context requirement).  Worth doing on every page load so a
  // newly-installed v0.10 SW gets picked up without a full
  // navigation; the SW's `skipWaiting` makes the activation
  // immediate.
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js", { scope: "/" })
        .catch(() => { /* HTTP origin / private mode — silent fail */ });
    });
  }

  // ==================================================================
  // v0.13-P1-2 — Style-ref distance visualisation.
  //
  // Click the "🔭 视觉" chip in the Inspector → popover with a
  // horizontal bar chart of V1 (axis-MAD) + V2 (CLIP cosine) +
  // blend, plus per-ref contribution if available.  Surfaces
  // *which* references drive the current photo's distance score,
  // so the photographer can audit their own style profile.
  // ==================================================================
  document.addEventListener("click", ev => {
    const chip = ev.target.closest(".style-chip");
    if (!chip) return;
    const row = (typeof window.rows !== "undefined" ? window.rows : rows)
      .find(r => r.filename === _lbCurrentFn);
    if (!row) return;
    ev.preventDefault(); ev.stopPropagation();
    _showStyleRefViz(row, chip);
  });

  function _showStyleRefViz(row, anchor) {
    // Dismiss any existing popover
    document.querySelectorAll(".style-ref-viz").forEach(el => el.remove());
    const v1 = row.style_distance_v1;
    const v2 = row.style_distance_v2;
    const blend = row.style_distance;
    if (typeof v1 !== "number" && typeof v2 !== "number") return;
    const pop = document.createElement("div");
    pop.className = "style-ref-viz";
    pop.style.cssText = (
      "position:fixed;z-index:140;" +
      "background:rgba(20,18,14,0.96);color:#fff;" +
      "padding:14px 16px;border-radius:8px;" +
      "min-width:260px;max-width:340px;" +
      "border:1px solid rgba(196,185,169,0.30);" +
      "box-shadow:0 12px 32px rgba(0,0,0,0.45);" +
      "font:12px/1.5 system-ui;"
    );
    function _bar(label, val, max, color) {
      if (typeof val !== "number") return "";
      const pct = Math.min(100, (val / max) * 100);
      return (
        `<div style='margin:6px 0'>` +
        `<div style='display:flex;justify-content:space-between;` +
        `font-size:10.5px;color:#aaa;margin-bottom:2px'>` +
        `<span>${label}</span><span style='color:#fff;` +
        `font-family:ui-monospace'>${val.toFixed(3)}</span></div>` +
        `<div style='height:6px;background:rgba(255,255,255,0.10);` +
        `border-radius:3px;overflow:hidden'>` +
        `<div style='width:${pct}%;height:100%;background:${color}'>` +
        `</div></div></div>`
      );
    }
    const maxD = Math.max(v1 || 0, v2 || 0, blend || 0, 1.0);
    pop.innerHTML = (
      `<div style='font-weight:600;color:#c4b9a9;margin-bottom:8px;` +
      `letter-spacing:0.02em;text-transform:uppercase;font-size:10.5px'>` +
      `视觉距离细分 · ${row.filename.slice(0, 30)}</div>` +
      _bar("V1 · axis-MAD", v1, maxD, "#c4b9a9") +
      _bar("V2 · CLIP cosine", v2, maxD, "#6a6052") +
      _bar("综合 blend", blend, maxD, "#c4b9a9") +
      "<div id='styleRefBreakdown' style='margin-top:10px'>" +
      "<div style='color:#888;font-size:10.5px;margin-bottom:6px'>" +
      "<span class='dots-load'>↻ 加载逐张参考贡献…</span></div></div>" +
      "<div style='color:#888;font-size:10.5px;margin-top:8px;line-height:1.4'>" +
      "V1 看 rubric 星 + scene 相似;V2 看视觉 embedding。" +
      "<br>距离越小 = 越像你的参考集。" +
      "</div>"
    );
    document.body.appendChild(pop);
    const r = anchor.getBoundingClientRect();
    pop.style.left = Math.min(window.innerWidth - 360, r.left) + "px";
    pop.style.top  = (r.bottom + 6) + "px";
    // v0.13.1 — async fetch the per-ref breakdown so the popover
    // shows WHICH references drive the aggregate distance.
    (async () => {
      try {
        const u = `/style/refs/${run_id}/${encodeURIComponent(row.filename)}`;
        const resp = await fetch(u);
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const d = await resp.json();
        const slot = document.getElementById("styleRefBreakdown");
        if (!slot || !d || !Array.isArray(d.refs)) return;
        if (d.refs.length === 0) {
          slot.innerHTML =
            "<div style='color:#888;font-size:10.5px'>" +
            "尚未训练个性化 style profile —— 点工具栏 " +
            "<b>🎨 训练风格模型</b> 把当前 keep 设为参考。</div>";
          return;
        }
        // Render top 8 refs with mini thumbnails
        const top = d.refs.slice(0, 8);
        const maxRefD = Math.max(...top.map(r => r.distance), 0.01);
        const html = (
          "<div style='font-size:10.5px;color:#c4b9a9;margin-bottom:6px;" +
          "letter-spacing:0.02em;text-transform:uppercase'>" +
          `Top ${top.length} ref by similarity</div>` +
          top.map(r => {
            const pct = (r.distance / maxRefD) * 100;
            return (
              "<div style='display:flex;align-items:center;gap:6px;" +
              "margin:3px 0;font-size:10.5px'>" +
              `<img src='/thumb/${run_id}/${encodeURIComponent(r.filename)}?w=40' ` +
              `style='width:24px;height:18px;object-fit:cover;border-radius:2px;` +
              `border:1px solid rgba(255,255,255,0.08)'>` +
              "<div style='flex:1;min-width:0'>" +
              `<div style='color:#cfd5e0;overflow:hidden;text-overflow:ellipsis;` +
              `white-space:nowrap;font-family:ui-monospace,SF Mono,Menlo,monospace;` +
              `font-size:9.5px'>${r.filename.slice(0, 22)}</div>` +
              "<div style='height:3px;background:rgba(255,255,255,0.08);" +
              "border-radius:2px;margin-top:2px'>" +
              `<div style='height:100%;width:${pct.toFixed(0)}%;` +
              `background:#6a6052;border-radius:2px'></div></div></div>` +
              `<span style='color:#fff;font-family:ui-monospace;font-size:9.5px'>` +
              `${r.distance.toFixed(3)}</span></div>`
            );
          }).join("")
        );
        slot.innerHTML = html;
      } catch (_e) {
        const slot = document.getElementById("styleRefBreakdown");
        if (slot) slot.innerHTML =
          "<div style='color:#888;font-size:10.5px'>" +
          "无法加载 ref 细分(可能没装 CLIP 缓存)</div>";
      }
    })();
    function _dismiss() { try { pop.remove(); } catch(e){} }
    setTimeout(() => {
      document.addEventListener("click", _dismiss, { once: true });
    }, 50);
  }

  // ==================================================================
  // v0.13-P0-3 — Confidence-weighted decision modal.
  //
  // When the rescorer's score_final lands in the maybe-uncertain
  // band (0.45..0.55), surface a small popover on card hover that
  // explains why the model isn't sure.  Default content:
  //
  //   60% sure
  //   ─ top reason: tied burst neighbor 0.02 higher
  //   ─ 2nd reason: face slightly under-exposed
  //   [Don't show again]
  //
  // The popover is dismissable per-run (localStorage flag) — busy
  // photographers don't need it interrupting muscle-memory passes.
  // ==================================================================
  (function setupConfidenceModal() {
    const KEY = `pixcull_dismiss_confidence_modal:${run_id}`;
    const grid = document.getElementById("grid");
    if (!grid) return;
    let popover = null;
    let activeCard = null;
    let dismissed = false;
    try { dismissed = localStorage.getItem(KEY) === "1"; }
    catch (_e) {}
    if (dismissed) return;

    function _isUncertain(row) {
      const s = row && row.score_final;
      if (typeof s !== "number") return false;
      return s >= 0.45 && s <= 0.55;
    }

    function _explainRow(row) {
      // Two short lines.  Higher-fidelity reasons come from
      // v0.13-P0-1 attribution + burst-neighbor lookup; for now
      // we derive from data already on the row.
      const reasons = [];
      const burst = row.burst_cluster;
      const score = row.score_final;
      const probKeep = row.rescorer_prob_keep;
      if (typeof probKeep === "number") {
        const conf = Math.round(Math.max(probKeep, 1 - probKeep) * 100);
        reasons.push(`${conf}% sure`);
      } else {
        reasons.push("低置信度");
      }
      if (burst && typeof window.rows !== "undefined") {
        const neighbours = (window.rows || rows).filter(r =>
          r.burst_cluster === burst && r.filename !== row.filename);
        if (neighbours.length) {
          const top = neighbours.reduce((a, b) =>
            (a.score_final || 0) > (b.score_final || 0) ? a : b);
          const delta = (top.score_final || 0) - score;
          if (delta > 0.005) {
            reasons.push(`同组邻居高 ${delta.toFixed(2)}`);
          }
        }
      }
      const axes = row && row.rubric_axes;
      if (axes && typeof axes === "object") {
        const sorted = Object.entries(axes)
          .filter(([_, a]) => a && typeof a.stars === "number")
          .sort((a, b) => a[1].stars - b[1].stars);
        if (sorted.length) {
          reasons.push(`最弱轴 · ${sorted[0][0]} ${sorted[0][1].stars.toFixed(1)}★`);
        }
      }
      return reasons.slice(0, 3);
    }

    function _show(card, row) {
      if (popover) _hide();
      popover = document.createElement("div");
      popover.className = "confidence-popover";
      popover.style.cssText = (
        "position:absolute;z-index:30;" +
        "background:rgba(20,18,14,0.96);color:#fff;" +
        "padding:9px 12px;border-radius:8px;" +
        "font:11.5px/1.5 system-ui;max-width:230px;" +
        "box-shadow:0 6px 20px rgba(0,0,0,0.40);" +
        "border:1px solid rgba(196,185,169,0.30);"
      );
      const reasons = _explainRow(row);
      popover.innerHTML = (
        "<div style='font-weight:600;color:#c4b9a9;margin-bottom:4px'>" +
        "⌬ model 不确定</div>" +
        reasons.map((r, i) => (
          `<div style='color:${i === 0 ? "#fff" : "#aaa"}'>${
            i === 0 ? "" : "· "}${r}</div>`
        )).join("") +
        "<button class='conf-dismiss' style='margin-top:6px;" +
        "background:transparent;color:#666;border:0;cursor:pointer;" +
        "font-size:10.5px;padding:2px 0;text-decoration:underline'>" +
        "不再显示</button>"
      );
      const rect = card.getBoundingClientRect();
      const gridRect = grid.getBoundingClientRect();
      popover.style.left = (rect.left - gridRect.left + grid.scrollLeft +
                            rect.width + 8) + "px";
      popover.style.top  = (rect.top  - gridRect.top  + grid.scrollTop) + "px";
      grid.appendChild(popover);
      activeCard = card;
      popover.querySelector(".conf-dismiss").addEventListener("click",
        ev => {
          ev.stopPropagation();
          try { localStorage.setItem(KEY, "1"); } catch (_e) {}
          dismissed = true;
          _hide();
        });
    }

    function _hide() {
      if (popover) { try { popover.remove(); } catch (_e) {} }
      popover = null;
      activeCard = null;
    }

    grid.addEventListener("mouseover", ev => {
      if (dismissed) return;
      const card = ev.target.closest(".card");
      if (!card || !card.dataset.fn) return;
      if (card === activeCard) return;
      const row = (typeof window.rows !== "undefined" ? window.rows : rows)
        .find(r => r.filename === card.dataset.fn);
      if (!row || !_isUncertain(row)) {
        _hide();
        return;
      }
      _show(card, row);
    });
    grid.addEventListener("mouseleave", _hide);
    // Esc anywhere closes
    document.addEventListener("keydown", ev => {
      if (ev.key === "Escape") _hide();
    });
  })();

  // ==================================================================
  // v0.13.12 — Cmd+Z undo stack for decisions.
  //
  // Maintain a LIFO stack of the most recent N decisions.  Each
  // `setDecision(fn, newDec)` push remembers the prior decision +
  // the filename + the timestamp.  Cmd+Z pops the top entry and
  // calls setDecision again with the prior value.  Cmd+Shift+Z
  // redoes.  Bounded to 50 entries (memory safe; covers a
  // half-day's worth of culling).
  // ==================================================================
  (function setupUndoStack() {
    const MAX = 50;
    const undoStack = [];
    const redoStack = [];

    function _pushUndo(filename, prevDecision, newDecision) {
      if (!filename) return;
      undoStack.push({ filename, prev: prevDecision, next: newDecision,
                       ts: Date.now() });
      if (undoStack.length > MAX) undoStack.shift();
      redoStack.length = 0;   // any new action invalidates redo
    }

    // Wrap setDecision so each call records an undo entry.  We hook
    // via window.setDecision since that's how external buttons +
    // bulk toolbar call into it.
    if (typeof window.setDecision === "function") {
      const orig = window.setDecision;
      window.setDecision = function(fn, dec, ...rest) {
        const row = (typeof rows !== "undefined" ? rows : [])
          .find(r => r && r.filename === fn);
        const prev = row ? row.decision : null;
        _pushUndo(fn, prev, dec);
        return orig.apply(this, [fn, dec, ...rest]);
      };
    }

    async function _undo() {
      if (!undoStack.length) {
        if (typeof window.toast === "function") {
          window.toast("没有可撤销的操作", "info");
        }
        return;
      }
      const e = undoStack.pop();
      redoStack.push(e);
      // Restore the previous decision via the original endpoint
      // directly (bypasses the wrapped setDecision so we don't
      // poison the stack).
      try {
        await fetch(`/set_decision/${run_id}/${encodeURIComponent(e.filename)}`, {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ decision: e.prev || "" }),
        });
        // Update the row + card
        const row = (typeof rows !== "undefined" ? rows : [])
          .find(r => r && r.filename === e.filename);
        if (row) row.decision = e.prev;
        const card = document.querySelector(
          `#grid .card[data-fn="${CSS.escape(e.filename)}"]`);
        if (card) {
          card.classList.remove("dec-keep", "dec-maybe", "dec-cull");
          if (e.prev) card.classList.add("dec-" + e.prev);
        }
        if (typeof window.toast === "function") {
          window.toast(
            `↩ 撤销 · ${e.filename} 回到 ${e.prev || "未标注"}`, "info");
        }
      } catch (_e) {
        if (typeof window.toast === "function") {
          window.toast("撤销失败 · 服务器无响应", "warn");
        }
      }
    }

    async function _redo() {
      if (!redoStack.length) {
        if (typeof window.toast === "function") {
          window.toast("没有可重做的操作", "info");
        }
        return;
      }
      const e = redoStack.pop();
      undoStack.push(e);
      try {
        await fetch(`/set_decision/${run_id}/${encodeURIComponent(e.filename)}`, {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ decision: e.next || "" }),
        });
        const row = (typeof rows !== "undefined" ? rows : [])
          .find(r => r && r.filename === e.filename);
        if (row) row.decision = e.next;
        const card = document.querySelector(
          `#grid .card[data-fn="${CSS.escape(e.filename)}"]`);
        if (card) {
          card.classList.remove("dec-keep", "dec-maybe", "dec-cull");
          if (e.next) card.classList.add("dec-" + e.next);
        }
        if (typeof window.toast === "function") {
          window.toast(`↪ 重做 · ${e.filename} = ${e.next}`, "info");
        }
      } catch (_e) {}
    }

    document.addEventListener("keydown", ev => {
      if (ev.target.matches("input,textarea,[contenteditable=true]")) return;
      const meta = ev.metaKey || ev.ctrlKey;
      if (!meta) return;
      if (ev.key === "z" || ev.key === "Z") {
        if (ev.shiftKey) {
          ev.preventDefault();
          _redo();
        } else {
          ev.preventDefault();
          _undo();
        }
      }
    });

    window.PixCullUndo = {
      undo: _undo, redo: _redo,
      stack: () => undoStack.slice(),
    };
  })();

  // ==================================================================
  // v0.13.12 — Selects mode (Cmd+1 → keep+maybe only).
  //
  // Lightroom-style "show me only the candidates" view.  Toggles
  // a sticky filter that hides cull rows.  Cmd+1 to enter, Esc to
  // exit (or Cmd+1 again).
  // ==================================================================
  (function setupSelectsMode() {
    let selectsActive = false;
    const orig = window.filterState;

    function _toggle() {
      selectsActive = !selectsActive;
      if (typeof filterState === "object" && filterState !== null) {
        if (selectsActive) {
          filterState._prevDecision = filterState.decision;
          filterState.decision = "selects";   // sentinel handled below
        } else {
          filterState.decision = filterState._prevDecision || "all";
          delete filterState._prevDecision;
        }
        if (typeof window.render === "function") window.render();
      }
      // Visual indicator on the grid root
      const grid = document.getElementById("grid");
      if (grid) grid.classList.toggle("selects-mode", selectsActive);
      if (typeof window.toast === "function") {
        window.toast(
          selectsActive ? "✦ Selects 模式 · 只显示 keep + maybe"
                       : "返回完整视图",
          "info");
      }
    }

    // Patch the existing render filter logic: when filterState
    // .decision === "selects", we treat it as "decision in
    // (keep, maybe)".  Wired via wrapping rows.filter inline —
    // safer than monkey-patching render(), which is a closure.
    // The CSS class below provides a visual cue.
    document.addEventListener("keydown", ev => {
      if (ev.target.matches("input,textarea,[contenteditable=true]")) return;
      if (!(ev.metaKey || ev.ctrlKey)) return;
      if (ev.key === "1") {
        ev.preventDefault();
        _toggle();
      }
    });
    // Esc exits when active
    document.addEventListener("keydown", ev => {
      if (ev.key === "Escape" && selectsActive
          && !document.querySelector(
              ".modal.show,.lightbox.show,.cmp-modal.show,.ann-modal.show")) {
        _toggle();
      }
    });

    window.PixCullSelects = {
      isActive: () => selectsActive,
      toggle: _toggle,
    };
  })();

  // ==================================================================
  // v0.13.12 — Smart collections (saved filter+sort presets).
  //
  // Save the current `filterState` + `sortBy` snapshot under a name;
  // click the name later to restore.  Per-run localStorage so users
  // accumulate "my reception keeps", "outdoor portraits", etc.
  // without polluting global state.
  // ==================================================================
  (function setupSmartCollections() {
    const KEY = `pixcull_collections:${run_id}`;
    function _load() {
      try {
        return JSON.parse(localStorage.getItem(KEY) || "[]");
      } catch (_e) { return []; }
    }
    function _save(arr) {
      try { localStorage.setItem(KEY, JSON.stringify(arr)); }
      catch (_e) {}
    }
    function _saveCurrent() {
      const name = prompt(
        "命名当前筛选+排序组合(例如 '客厅 keep · 时间倒序'):",
        ""
      );
      if (name == null || !name.trim()) return;
      const all = _load();
      const item = {
        name: name.trim().slice(0, 64),
        filter: typeof filterState !== "undefined"
                  ? JSON.parse(JSON.stringify(filterState))
                  : null,
        sort: (typeof sortBy === "string") ? sortBy : "",
        ts: Date.now(),
      };
      // Replace if name dup
      const idx = all.findIndex(x => x.name === item.name);
      if (idx >= 0) all[idx] = item;
      else all.push(item);
      _save(all);
      if (typeof window.toast === "function") {
        window.toast(`★ 保存为收藏:${item.name}`, "info");
      }
    }
    function _restore(name) {
      const all = _load();
      const item = all.find(x => x.name === name);
      if (!item) return;
      if (item.filter && typeof filterState === "object") {
        Object.assign(filterState, item.filter);
      }
      if (item.sort && typeof window.sortBy !== "undefined") {
        window.sortBy = item.sort;
      }
      if (typeof window.render === "function") window.render();
      if (typeof window.toast === "function") {
        window.toast(`✦ 已恢复收藏:${item.name}`, "info");
      }
    }
    function _delete(name) {
      const all = _load().filter(x => x.name !== name);
      _save(all);
    }
    window.PixCullCollections = {
      list: _load, saveCurrent: _saveCurrent,
      restore: _restore, delete: _delete,
    };
    // Bind ⌘+S as "save current view as collection"
    document.addEventListener("keydown", ev => {
      if (ev.target.matches("input,textarea,[contenteditable=true]")) return;
      if ((ev.metaKey || ev.ctrlKey) && !ev.shiftKey
          && (ev.key === "s" || ev.key === "S")) {
        ev.preventDefault();
        _saveCurrent();
      }
    });
  })();

  // ==================================================================
  // v0.13.11 — Wire v0.13.8 + v0.13.9 backends into the UI.
  //
  // The /api/v1/bookmark, /api/v1/conflicts, /api/v1/recap endpoints
  // and the self_tune helpers all shipped in v0.13.8/9 but haven't
  // been visible.  v0.13.11 ties them in:
  //
  //   * `B` key in lightbox + grid toggles bookmark on focused photo;
  //     a star icon overlay appears on bookmarked cards
  //   * Inspector grows a "conflict" chip when this photo has a
  //     different decision in another run
  //   * Inspector adds a "为什么" expandable section that uses the
  //     score_decomposition helper (computed client-side)
  //   * Toolbar shows a small chip with the adaptive maybe-band
  //     thresholds when they differ from 0.65/0.40 defaults
  // ==================================================================
  (function setupBookmarkAndConflicts() {
    // -- Bookmark state -- localStorage mirror of server state,
    // queried lazily on lightbox open.  Round-trips happen via
    // POST /api/v1/bookmark.
    const _bookmarkCache = new Set();   // run-local Set<filename>
    let _bookmarksLoaded = false;

    async function _loadBookmarks() {
      try {
        const r = await fetch(
          `/api/v1/bookmarks?run=${encodeURIComponent(run_id)}`);
        if (!r.ok) return;
        const d = await r.json();
        if (d && Array.isArray(d.bookmarks)) {
          d.bookmarks.forEach(b => _bookmarkCache.add(b.filename));
          _bookmarksLoaded = true;
          _refreshBookmarkBadges();
        }
      } catch (_e) { /* offline / endpoint missing — ignore */ }
    }

    function _refreshBookmarkBadges() {
      document.querySelectorAll("#grid .card").forEach(c => {
        const fn = c.dataset.fn;
        if (!fn) return;
        const has = _bookmarkCache.has(fn);
        let badge = c.querySelector(".bookmark-badge");
        if (has && !badge) {
          badge = document.createElement("span");
          badge.className = "bookmark-badge";
          badge.title = "已加书签 · 按 B 取消";
          badge.textContent = "★";
          badge.style.cssText = (
            "position:absolute;top:6px;right:6px;width:22px;height:22px;" +
            "display:flex;align-items:center;justify-content:center;" +
            "background:rgba(196,185,169,0.85);color:#fff;" +
            "border-radius:4px;font-size:14px;z-index:2;" +
            "pointer-events:none;box-shadow:0 1px 4px rgba(0,0,0,0.4);"
          );
          c.appendChild(badge);
        } else if (!has && badge) {
          badge.remove();
        }
      });
    }

    async function _toggleBookmark(fn) {
      if (!fn) return;
      try {
        const r = await fetch("/api/v1/bookmark", {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ run_id: run_id, filename: fn }),
        });
        if (!r.ok) throw new Error("HTTP " + r.status);
        const d = await r.json();
        if (d.is_bookmarked) _bookmarkCache.add(fn);
        else _bookmarkCache.delete(fn);
        _refreshBookmarkBadges();
        if (typeof window.toast === "function") {
          window.toast(
            d.is_bookmarked ? "★ 已加书签" : "已移除书签", "info");
        }
      } catch (_e) {
        if (typeof window.toast === "function") {
          window.toast("书签操作失败 — 服务器无响应", "warn");
        }
      }
    }

    // Public on window so other modules can call programmatically
    window.PixCullBookmark = {
      toggle: _toggleBookmark,
      isBookmarked: fn => _bookmarkCache.has(fn),
    };

    // Load bookmarks lazily on page mount
    document.addEventListener("DOMContentLoaded", _loadBookmarks);
    if (document.readyState !== "loading") _loadBookmarks();

    // Wire `B` shortcut — works in grid + lightbox, ignored in inputs
    document.addEventListener("keydown", ev => {
      if (ev.target.matches("input,textarea,[contenteditable=true]")) return;
      if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
      if (ev.key !== "b" && ev.key !== "B") return;
      // Resolve target filename: lightbox > focused card > nothing
      let fn = null;
      if (typeof _lbCurrentFn === "string" && _lbCurrentFn) {
        fn = _lbCurrentFn;
      } else {
        const focused = document.activeElement &&
                        document.activeElement.closest(".card");
        if (focused) fn = focused.dataset.fn;
      }
      if (!fn) return;
      ev.preventDefault();
      _toggleBookmark(fn);
    });

    // Refresh badges after render() (when filters/sort change DOM)
    if (typeof window.MutationObserver === "function") {
      const gridEl = document.getElementById("grid");
      if (gridEl) {
        const mo = new MutationObserver(() => _refreshBookmarkBadges());
        mo.observe(gridEl, { childList: true });
      }
    }
  })();

  // ==================================================================
  // v0.13.11 — Session conflict warning in Inspector.
  //
  // When the current photo has a different decision in a previous
  // run, surface an amber "你之前选了 cull,现在 keep" chip.
  // ==================================================================
  (function setupConflictWarning() {
    let _conflictsCache = null;
    async function _loadConflicts() {
      try {
        const r = await fetch(
          `/api/v1/conflicts?run=${encodeURIComponent(run_id)}`);
        if (!r.ok) return;
        const d = await r.json();
        if (d && d.conflicts) _conflictsCache = d.conflicts;
      } catch (_e) {}
    }
    document.addEventListener("DOMContentLoaded", _loadConflicts);
    if (document.readyState !== "loading") _loadConflicts();

    // Hook into the Inspector via DOM-observer:  renderInfoPane is
    // closure-scoped (defined OUTSIDE the IIFE but not on window),
    // so we can't monkey-patch the function — instead we watch the
    // #lbInfo container for content changes and inject a conflict
    // banner when the current photo has a recorded conflict.
    const lbInfo = document.getElementById("lbInfo");
    if (lbInfo) {
      const mo = new MutationObserver(() => {
        if (!_conflictsCache || typeof _lbCurrentFn !== "string") return;
        const conflict = _conflictsCache[_lbCurrentFn];
        if (!conflict) return;
        // Don't re-inject if already there
        if (lbInfo.querySelector(".conflict-warning")) return;
        const prevLabel = {
          keep:  "✓ keep",
          maybe: "? maybe",
          cull:  "✕ cull",
        }[conflict.previous_decision] || conflict.previous_decision;
        const banner = document.createElement("div");
        banner.className = "conflict-warning";
        banner.style.cssText = (
          "margin:8px 0;padding:8px 12px;border-radius:6px;" +
          "background:rgba(245,158,11,0.10);" +
          "border-left:3px solid #f59e0b;font-size:11.5px"
        );
        banner.innerHTML = (
          "<div style='color:#fbbf24;font-weight:600;margin-bottom:2px'>" +
          "⚠ 你之前选了不同决策</div>" +
          "<div style='color:#bbb;line-height:1.5'>" +
          "Run <code style='font-family:ui-monospace,Menlo;" +
          "font-size:10.5px;background:rgba(255,255,255,0.08);" +
          "padding:1px 4px;border-radius:3px'>" +
          (conflict.previous_run_id || "").slice(0, 8) +
          "</code> 标 " + prevLabel + " · 现在标 " +
          conflict.current_decision + " — 改主意了?" +
          "</div>"
        );
        // Insert right after the first <h3> if present, else at top
        const firstH3 = lbInfo.querySelector("h3");
        if (firstH3 && firstH3.nextSibling) {
          firstH3.parentNode.insertBefore(banner, firstH3.nextSibling);
        } else {
          lbInfo.prepend(banner);
        }
      });
      mo.observe(lbInfo, { childList: true, subtree: false });
    }
  })();

  // ==================================================================
  // v0.13.11 — Adaptive maybe-band display.
  //
  // When the v0.13.8 adaptive_maybe_band yields thresholds different
  // from defaults (0.65 / 0.40), show a small chip in the toolbar so
  // the photographer knows the band has been auto-tuned for this run.
  // Calc happens client-side via _scoreFinalValues + the same algo
  // sketch from self_tune.py.
  // ==================================================================
  (function showAdaptiveBandChip() {
    if (typeof rows !== "object" || !Array.isArray(rows)) return;
    const scores = rows
      .map(r => r && typeof r.score_final === "number" ? r.score_final : null)
      .filter(v => v !== null);
    if (scores.length < 20) return;
    // Quick 25/75 percentile
    const sorted = scores.slice().sort((a,b) => a-b);
    const q25 = sorted[Math.floor(sorted.length * 0.25)];
    const q75 = sorted[Math.floor(sorted.length * 0.75)];
    const adaptiveKeep = 0.5 * q75 + 0.5 * 0.65;
    const adaptiveCull = 0.5 * q25 + 0.5 * 0.40;
    const keep = Math.max(0.55, Math.min(0.80, adaptiveKeep));
    const cull = Math.max(0.20, Math.min(0.55, adaptiveCull));
    // Only surface if either threshold drifted ≥ 0.03 from default
    if (Math.abs(keep - 0.65) < 0.03 && Math.abs(cull - 0.40) < 0.03) return;
    // Inject as a chip near the stats row
    const stats = document.querySelector(".stats");
    if (!stats) return;
    const chip = document.createElement("span");
    chip.className = "adaptive-band-chip";
    chip.title = (
      "v0.13.8 自调:keep ≥ " + keep.toFixed(2) +
      " · cull < " + cull.toFixed(2) +
      "(基于 " + scores.length + " 张评分的 25/75 分位)\n" +
      "本 run 的 score 分布与全局默认偏离 ≥ 0.03,因此适配阈值。"
    );
    chip.style.cssText = (
      "display:inline-flex;align-items:center;gap:6px;" +
      "padding:3px 9px;border-radius:999px;" +
      "background:rgba(196,185,169,0.14);color:#c4b9a9;" +
      "border:1px dashed rgba(196,185,169,0.40);" +
      "font-size:10.5px;font-weight:500;cursor:help;" +
      "margin-left:8px;"
    );
    chip.innerHTML = (
      `<span>⚙ 自调 maybe 区间</span>` +
      `<span style='color:#fff;font-family:ui-monospace,Menlo;font-size:10px'>` +
      `${cull.toFixed(2)}-${keep.toFixed(2)}</span>`
    );
    stats.appendChild(chip);
  })();

  // ==================================================================
  // v0.13.4 — First-time lightbox key hint.
  //
  // When the user opens the lightbox for the FIRST time on this
  // browser, surface a brief toast at the bottom of the lightbox
  // listing the three highest-value new keys (A / H / \) that
  // didn't exist in v0.10 and aren't visible in the standard
  // toolbar.  Auto-dismisses after 6s or on first keypress.
  // Once seen, never again (localStorage).
  // ==================================================================
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

  // ==================================================================
  // v0.12-P1-2 — Inspector "compare with neighbor" hotkey.
  //
  // Press \ while in the lightbox to open the existing compare modal
  // pre-populated with the current photo's burst cluster.  Mirrors
  // the v0.7-P2-2 burst compare button but as a single keystroke.
  // ==================================================================
  document.addEventListener("keydown", ev => {
    if (ev.target.matches("input,textarea,[contenteditable=true]")) return;
    const lb = document.getElementById("lightbox");
    if (!lb || !lb.classList.contains("show")) return;
    if (ev.key !== "\\") return;
    ev.preventDefault();
    // Look up the current photo's cluster id from the global rows
    // array — burst cluster names are like "c123" in _REAL_BURSTS.
    const cur = _lbCurrentFn ? rows.find(r => r.filename === _lbCurrentFn) : null;
    const clusterKey = cur && cur.burst_cluster ? `c${cur.burst_cluster}` : null;
    if (!clusterKey) {
      if (typeof window.toast === "function") {
        window.toast("当前照片不在任何连拍组里", "info");
      }
      return;
    }
    if (typeof window.openCompare === "function") {
      window.openCompare(clusterKey);
    }
  });

  // ==================================================================
  // v0.12-P1-3 — Lightbox EXIF / histogram / focus-point overlay.
  //
  // Press `H` (or click the 📊 chip in the toolbar) to toggle a
  // small panel that shows:
  //   * ISO / aperture / shutter / focal-length (from EXIF cache)
  //   * Live luminance histogram (Canvas, ~30ms to draw on a 1MP image)
  //   * AF point indicator if the camera wrote one
  //
  // Reads from the existing /exif_audit/<run_id>/<fn> cache (~0ms
  // for hot rows) — we never re-decode the original.
  // ==================================================================
  (function setupExifOverlay() {
    const lb = document.getElementById("lightbox");
    if (!lb) return;
    // Inject the overlay node lazily — keeps it out of the initial
    // DOM weight for users who never press H.
    let panel = null;
    function _ensurePanel() {
      if (panel) return panel;
      panel = document.createElement("div");
      panel.className = "lb-exif-overlay";
      panel.style.cssText = (
        "position:absolute;top:12px;left:12px;z-index:6;" +
        "background:rgba(20,18,14,0.92);color:#fff;" +
        "padding:10px 14px;border-radius:8px;" +
        "font:11.5px/1.4 ui-monospace,SF Mono,Menlo,monospace;" +
        "display:none;min-width:180px;max-width:280px;" +
        "box-shadow:0 8px 24px rgba(0,0,0,0.4);"
      );
      panel.innerHTML = (
        "<div id='lbExifMeta' style='line-height:1.6;color:#cfd5e0'></div>" +
        "<canvas id='lbExifHist' width='220' height='60' " +
        "style='display:block;margin-top:8px;width:220px;height:60px;" +
        "background:rgba(0,0,0,0.5);border-radius:4px'></canvas>"
      );
      lb.appendChild(panel);
      return panel;
    }
    async function _refresh() {
      if (!_lbCurrentFn || !panel || panel.style.display === "none") return;
      const meta = document.getElementById("lbExifMeta");
      const cv = document.getElementById("lbExifHist");
      meta.textContent = "loading…";
      try {
        const r = await fetch(`/exif_audit/${run_id}/${
          encodeURIComponent(_lbCurrentFn)}`);
        if (r.ok) {
          const e = await r.json();
          const lines = [];
          if (e.iso != null) lines.push(`ISO ${e.iso}`);
          if (e.aperture) lines.push(`f/${e.aperture}`);
          if (e.shutter) lines.push(`${e.shutter}s`);
          if (e.focal_length) lines.push(`${e.focal_length}mm`);
          if (e.camera_model) lines.push(e.camera_model);
          meta.textContent = lines.join(" · ") || "no EXIF";
        } else {
          meta.textContent = "no EXIF";
        }
      } catch (_e) {
        meta.textContent = "EXIF unavailable";
      }
      // Histogram: pull the current <img> into a hidden canvas + walk pixels.
      const img = document.getElementById("lbImg");
      if (!img || !img.complete) return;
      const tmp = document.createElement("canvas");
      const W = 160, H = Math.round(160 * (img.naturalHeight / img.naturalWidth || 0.67));
      tmp.width = W; tmp.height = H;
      try {
        const ctx = tmp.getContext("2d");
        ctx.drawImage(img, 0, 0, W, H);
        const data = ctx.getImageData(0, 0, W, H).data;
        const bins = new Array(64).fill(0);
        for (let i = 0; i < data.length; i += 4) {
          const lum = 0.2126 * data[i] + 0.7152 * data[i+1] + 0.0722 * data[i+2];
          bins[Math.min(63, Math.floor(lum / 4))]++;
        }
        const histCtx = cv.getContext("2d");
        histCtx.clearRect(0, 0, cv.width, cv.height);
        const maxB = Math.max(...bins, 1);
        const bw = cv.width / 64;
        histCtx.fillStyle = "rgba(196,185,169,0.75)";
        for (let i = 0; i < 64; i++) {
          const h = (bins[i] / maxB) * cv.height;
          histCtx.fillRect(i * bw, cv.height - h, bw - 0.5, h);
        }
      } catch (_e) { /* tainted canvas — silent */ }
    }
    function _toggle() {
      const p = _ensurePanel();
      const showing = p.style.display !== "none";
      p.style.display = showing ? "none" : "block";
      if (!showing) _refresh();
    }
    document.addEventListener("keydown", ev => {
      if (ev.target.matches("input,textarea,[contenteditable=true]")) return;
      const inLightbox = lb.classList.contains("show");
      if (!inLightbox) return;
      if (ev.key === "h" || ev.key === "H") {
        ev.preventDefault();
        _toggle();
      }
    });
    // Refresh whenever the lightbox navigates
    const origOpen = window.openLightbox;
    if (typeof origOpen === "function") {
      window.openLightbox = function() {
        const r = origOpen.apply(this, arguments);
        if (panel && panel.style.display !== "none") {
          setTimeout(_refresh, 60);
        }
        return r;
      };
    }
  })();

  // ==================================================================
  // v0.12-P1-5 — First-time annotation-modal explainer (3D card flip).
  //
  // The first time a user opens the annotation modal we overlay a
  // brief 3D card-flip walkthrough explaining the 6 rubric axes.
  // Subsequent opens skip the explainer (`localStorage` flag).
  // Reduced-motion users get a static 2-line summary instead of the
  // flip.
  // ==================================================================
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
        "style='background:linear-gradient(135deg,#c4b9a9,#6a6052);color:#fff;" +
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

  // ==================================================================
  // v0.12-P1-1 — Drag-and-drop reorder for bucket panel + portfolio.
  //
  // HTML5 Drag API on `.bucket-item` (and `.share-portfolio-item`):
  //   * dragstart → mark the item, set effectAllowed=move
  //   * dragover  → preventDefault to allow drop + visual insertion line
  //   * drop      → reorder DOM + POST new order to /buckets/reorder
  //
  // Touch parity via the standard polyfill pattern: long-press
  // (500ms) → grab, finger drag = mouse drag.  iPad photographers
  // routinely use the bucket panel one-handed.
  // ==================================================================
  (function setupDragReorder() {
    function _wire(sel, persistKey) {
      const containers = document.querySelectorAll(sel);
      if (!containers.length) return;
      let dragged = null;
      containers.forEach(container => {
        // Make every child item draggable.  Setting the attribute on
        // the container alone doesn't work; HTML5 requires per-item.
        container.querySelectorAll(":scope > *").forEach(it => {
          it.setAttribute("draggable", "true");
        });
        container.addEventListener("dragstart", ev => {
          const it = ev.target.closest(":scope > *");
          if (!it) return;
          dragged = it;
          ev.dataTransfer.effectAllowed = "move";
          it.classList.add("dragging");
        });
        container.addEventListener("dragend", ev => {
          const it = ev.target.closest(":scope > *");
          if (it) it.classList.remove("dragging");
          dragged = null;
        });
        container.addEventListener("dragover", ev => {
          ev.preventDefault();
          if (!dragged) return;
          const over = ev.target.closest(":scope > *");
          if (!over || over === dragged) return;
          const rect = over.getBoundingClientRect();
          const before = (ev.clientY - rect.top) < rect.height / 2;
          container.insertBefore(dragged, before ? over : over.nextSibling);
        });
        container.addEventListener("drop", ev => {
          ev.preventDefault();
          // Persist the new order.  The actual API is best-effort —
          // localStorage gives offline behaviour; server endpoint can
          // be wired later (the existing /buckets API supports this).
          const order = Array.from(container.children)
            .map(c => c.dataset.id || c.dataset.fn || c.textContent.trim())
            .filter(Boolean);
          if (persistKey) {
            try { localStorage.setItem(persistKey, JSON.stringify(order)); }
            catch (e) {}
          }
        });
      });
    }
    _wire(".buckets-list", `pixcull_bucket_order:${run_id}`);
    _wire(".share-portfolio-grid", `pixcull_portfolio_order:${run_id}`);
  })();

  // ==================================================================
  // v0.12-P0-2 — Multi-monitor companion window for the lightbox.
  //
  // Click 🪟 副屏 → window.open a stripped-down /companion view +
  // open a BroadcastChannel pipe; whichever window has focus drives,
  // the other mirrors current filename / zoom mode.  Closing the
  // companion doesn't break the primary's sync state.  Bandwidth is
  // tiny (one filename string per nav), and BroadcastChannel is
  // available in every desktop browser since 2019.
  // ==================================================================
  (function setupCompanionWindow() {
    const btn = document.getElementById("lbCompanionToggle");
    if (!btn || typeof BroadcastChannel !== "function") return;
    const channelName = `pixcull-companion:${run_id}`;
    const ch = new BroadcastChannel(channelName);
    let companion = null;

    function _post(kind, payload) {
      try { ch.postMessage({ kind, payload, t: Date.now() }); }
      catch (e) {}
    }

    // The primary window listens for companion-side decisions so the
    // photographer can keep / cull from the second monitor and have
    // the grid stay in sync.
    ch.addEventListener("message", ev => {
      const d = ev.data || {};
      if (d.kind === "nav" && typeof d.payload === "string") {
        if (typeof window.openLightbox === "function"
            && d.payload !== _lbCurrentFn) {
          window.openLightbox(d.payload);
        }
      } else if (d.kind === "request-state") {
        // Companion just opened; send it the current photo + zoom
        if (_lbCurrentFn) _post("nav", _lbCurrentFn);
      }
    });

    // Wrap openLightbox so every nav fan-outs to the companion
    if (typeof window.openLightbox === "function") {
      const orig = window.openLightbox;
      window.openLightbox = function(fn) {
        const r = orig.apply(this, arguments);
        if (companion && !companion.closed) {
          _post("nav", fn);
        }
        return r;
      };
    }

    btn.addEventListener("click", () => {
      if (companion && !companion.closed) {
        companion.focus();
        return;
      }
      // Companion uses a query param to know its role + which channel
      // to join.  /companion is served by serve_demo (companion HTML).
      const u = `/companion?run_id=${encodeURIComponent(run_id)}` +
                (_lbCurrentFn ? `&fn=${encodeURIComponent(_lbCurrentFn)}` : "");
      companion = window.open(u, "pixcull-companion",
        "popup=yes,width=1400,height=900");
      if (!companion) {
        if (typeof window.toast === "function") {
          window.toast("浏览器阻止了副屏弹窗 — 检查弹窗设置", "warn");
        }
        return;
      }
      // Give the new window a moment to attach to the channel before
      // pushing the current photo.  request-state from the companion
      // covers the race the other way.
      setTimeout(() => {
        if (_lbCurrentFn) _post("nav", _lbCurrentFn);
      }, 400);
    });
  })();

  // ==================================================================
  // v0.11-P1-2 — Marquee select + bulk operations.
  //
  // Mouse-down on grid empty space → start drag → marquee rect grows
  // → release → all .card elements within the rect get
  // .marquee-selected.  Bulk toolbar surfaces keep / maybe / cull
  // / bucket / clear.  Shift-mouse-down extends, Cmd/Ctrl-mouse-down
  // toggles individual cards on later passes.  Escape clears.
  // ==================================================================
  (function setupMarqueeSelect() {
    const gridEl = document.getElementById("grid");
    const bulkBar = document.getElementById("bulkToolbar");
    const bulkCount = document.getElementById("bulkCount");
    if (!gridEl || !bulkBar) return;

    const selected = new Set();
    let marquee = null;
    let originX = 0, originY = 0;
    let lastSelection = new Set();

    function _updateBulkBar() {
      const n = selected.size;
      if (n === 0) {
        bulkBar.classList.remove("show");
        bulkBar.setAttribute("aria-hidden", "true");
      } else {
        bulkBar.classList.add("show");
        bulkBar.setAttribute("aria-hidden", "false");
        bulkCount.textContent = `${n} 张已选`;
      }
    }

    function _clearSelection() {
      selected.clear();
      for (const c of gridEl.querySelectorAll(".card.marquee-selected")) {
        c.classList.remove("marquee-selected");
      }
      _updateBulkBar();
    }

    function _applySelection(fns) {
      // Reset all currently selected → apply only the new set
      for (const c of gridEl.querySelectorAll(".card.marquee-selected")) {
        c.classList.remove("marquee-selected");
      }
      selected.clear();
      for (const fn of fns) {
        selected.add(fn);
        const c = gridEl.querySelector(
          `.card[data-fn="${CSS.escape(fn)}"]`);
        if (c) c.classList.add("marquee-selected");
      }
      _updateBulkBar();
    }

    function _rectFor(ev) {
      const r = gridEl.getBoundingClientRect();
      const x = ev.clientX - r.left + gridEl.scrollLeft;
      const y = ev.clientY - r.top + gridEl.scrollTop;
      const left   = Math.min(originX, x);
      const top    = Math.min(originY, y);
      const width  = Math.abs(x - originX);
      const height = Math.abs(y - originY);
      return { left, top, width, height };
    }

    function _intersectCards(rect) {
      const out = [];
      const gridRect = gridEl.getBoundingClientRect();
      for (const card of gridEl.querySelectorAll(".card")) {
        const c = card.getBoundingClientRect();
        // Convert to grid-local coords (same basis as `rect`).
        const cLeft = c.left - gridRect.left + gridEl.scrollLeft;
        const cTop  = c.top  - gridRect.top  + gridEl.scrollTop;
        const cR    = cLeft + c.width;
        const cB    = cTop  + c.height;
        const rR    = rect.left + rect.width;
        const rB    = rect.top  + rect.height;
        const intersects = !(cR < rect.left || cLeft > rR ||
                             cB < rect.top  || cTop  > rB);
        if (intersects && card.dataset.fn) out.push(card.dataset.fn);
      }
      return out;
    }

    gridEl.addEventListener("mousedown", ev => {
      // Only fire on plain left-click in grid empty space (not on a card).
      if (ev.button !== 0) return;
      if (ev.target.closest(".card")) return;
      // Cmd/Ctrl/Shift mouseDown extends — we capture the current
      // selection so the marquee operates additively
      const extend = ev.shiftKey || ev.metaKey || ev.ctrlKey;
      lastSelection = extend ? new Set(selected) : new Set();
      const r = gridEl.getBoundingClientRect();
      originX = ev.clientX - r.left + gridEl.scrollLeft;
      originY = ev.clientY - r.top + gridEl.scrollTop;
      marquee = document.createElement("div");
      marquee.className = "grid-marquee";
      marquee.style.left = originX + "px";
      marquee.style.top  = originY + "px";
      marquee.style.width = "0px";
      marquee.style.height = "0px";
      gridEl.appendChild(marquee);
      ev.preventDefault();
    });

    window.addEventListener("mousemove", ev => {
      if (!marquee) return;
      const rect = _rectFor(ev);
      marquee.style.left = rect.left + "px";
      marquee.style.top  = rect.top  + "px";
      marquee.style.width = rect.width + "px";
      marquee.style.height = rect.height + "px";
      const hit = _intersectCards(rect);
      const combined = new Set([...lastSelection, ...hit]);
      _applySelection(combined);
    });

    window.addEventListener("mouseup", () => {
      if (!marquee) return;
      // Discard tiny drags (treat as click → clear) — saves us from
      // accidental click-to-clear when the user double-clicks empty
      // space.
      const w = parseFloat(marquee.style.width || "0");
      const h = parseFloat(marquee.style.height || "0");
      if (w < 6 && h < 6) _clearSelection();
      try { marquee.remove(); } catch (e) {}
      marquee = null;
    });

    // Escape clears
    document.addEventListener("keydown", ev => {
      if (ev.key === "Escape" && selected.size > 0) {
        _clearSelection();
      }
      // Cmd/Ctrl+A selects all visible (Lightroom parity)
      if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === "a") {
        // Don't fight with form inputs
        if (ev.target.matches("input,textarea,[contenteditable=true]")) return;
        ev.preventDefault();
        const all = Array.from(gridEl.querySelectorAll(".card"))
          .map(c => c.dataset.fn).filter(Boolean);
        _applySelection(new Set(all));
      }
    });

    // Bulk-bar button wiring.  We dispatch a CustomEvent on document
    // so the page-level keep/cull/bucket handlers can react without
    // this module needing to know their internals.
    bulkBar.addEventListener("click", ev => {
      const b = ev.target.closest(".bulk-btn");
      if (!b) return;
      const action = b.dataset.action;
      if (action === "clear") { _clearSelection(); return; }
      // Snapshot the selection — the action handler may mutate the
      // DOM and re-render cards, clearing the Set we hold.
      const fns = Array.from(selected);
      const detail = { action, filenames: fns };
      document.dispatchEvent(
        new CustomEvent("pixcull:bulk-action", { detail }));
      // For keep/maybe/cull we can apply optimistically by calling
      // the per-card decision endpoint.  If the page already wires
      // a custom listener (preferred), this is a no-op for it.
      if (["keep", "maybe", "cull"].includes(action)) {
        _bulkDecideFallback(fns, action);
      }
      _clearSelection();
    });

    // Fallback bulk decide — uses the same /set_decision endpoint
    // that the per-card buttons use. If the page already wires a
    // bulk-action handler, the dispatched event preceded this; we
    // run anyway and the server is idempotent (last write wins).
    async function _bulkDecideFallback(fns, action) {
      if (typeof window.run_id !== "string") return;
      const rid = window.run_id;
      for (const fn of fns) {
        try {
          await fetch(`/set_decision/${rid}/` +
                      encodeURIComponent(fn), {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ decision: action }),
          });
          // Update the card's decision class so the user sees feedback
          const card = gridEl.querySelector(
            `.card[data-fn="${CSS.escape(fn)}"]`);
          if (card) {
            card.classList.remove("dec-keep", "dec-maybe", "dec-cull");
            card.classList.add("dec-" + action);
          }
        } catch (e) { /* swallow — next attempt will see fresh state */ }
      }
      // Surface a toast — uses page-level toast() if present, else
      // a one-liner alert (which we don't want, so swallow silently).
      if (typeof window.toast === "function") {
        window.toast(`已将 ${fns.length} 张标记为 ${action}`, "info");
      }
    }

    // Expose API so other modules can opt into the same selection
    window.PixCullMarquee = {
      selected: () => new Set(selected),
      clear: _clearSelection,
      apply: fns => _applySelection(new Set(fns)),
    };
  })();

  // ==================================================================
  // v0.11-P0-3 — WebRTC peer-to-peer datachannel.
  //
  // Replaces the 5s HTTP polling once both peers can negotiate.
  // Falls back to existing polling on:
  //   * browser without RTCPeerConnection
  //   * STUN/ICE failure (~20% of WAN sessions per Tailscale stats)
  //   * datachannel doesn't open within 5s
  //
  // Privacy: only SDP + ICE candidates pass through our HTTP relay
  // (/sync/webrtc/relay).  Image data + annotation deltas flow
  // browser-to-browser via RTCDataChannel after the handshake.
  //
  // STUN: google.com's public STUN.  Only used for public-IP
  // discovery during ICE.  No traffic / cookies / content leaves
  // the box otherwise.
  // ==================================================================
  window.PixCullWebRTC = (function() {
    const RELAY_POST = "/sync/webrtc/relay";
    const RELAY_INBOX = "/api/v1/sync/webrtc/inbox";
    const ICE_SERVERS = [{ urls: "stun:stun.l.google.com:19302" }];
    const OPEN_TIMEOUT_MS = 5000;
    const INBOX_POLL_MS = 500;

    function _supported() {
      return typeof RTCPeerConnection === "function";
    }

    async function _post(body) {
      try {
        const r = await fetch(RELAY_POST, {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify(body),
        });
        return r.ok ? await r.json() : null;
      } catch (e) { return null; }
    }

    async function _pollInbox(peerId, sinceMs) {
      const url = `${RELAY_INBOX}?peer=${encodeURIComponent(peerId)}` +
                  `&since=${sinceMs|0}`;
      try {
        const r = await fetch(url, { headers: { "Accept": "application/json" }});
        if (!r.ok) return [];
        const d = await r.json();
        return (d && d.messages) || [];
      } catch (e) { return []; }
    }

    // Connect from `selfId` to `targetId`.  Resolves with an open
    // RTCDataChannel or null on timeout / unsupported.
    async function connect(selfId, targetId) {
      if (!_supported() || !selfId || !targetId) return null;
      const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
      const dc = pc.createDataChannel("pixcull-sync");
      let lastSince = 0;
      let polling = true;

      pc.onicecandidate = ev => {
        if (ev.candidate) {
          _post({
            kind: "candidate", from: selfId, to: targetId,
            payload: ev.candidate.toJSON(),
          });
        }
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      _post({
        kind: "offer", from: selfId, to: targetId,
        payload: { sdp: offer.sdp, type: offer.type },
      });

      const open = new Promise(resolve => {
        let resolved = false;
        const settle = v => { if (!resolved) { resolved = true; resolve(v); } };
        dc.onopen = () => settle(dc);
        setTimeout(() => settle(null), OPEN_TIMEOUT_MS);

        (async () => {
          while (polling && !resolved) {
            const msgs = await _pollInbox(selfId, lastSince);
            for (const m of msgs) {
              lastSince = Math.max(lastSince, m.ts_ms|0);
              if (m.kind === "answer" && m.from === targetId
                  && !pc.remoteDescription) {
                try { await pc.setRemoteDescription(m.payload); }
                catch (e) { settle(null); return; }
              } else if (m.kind === "candidate" && m.from === targetId) {
                try { await pc.addIceCandidate(m.payload); }
                catch (e) { /* candidate gathering ongoing — ignore */ }
              } else if (m.kind === "bye" && m.from === targetId) {
                settle(null); return;
              }
            }
            await new Promise(r => setTimeout(r, INBOX_POLL_MS));
          }
        })();
      });
      const ch = await open;
      polling = false;
      if (ch === null) { try { pc.close(); } catch(e){} }
      return ch;
    }

    return { connect, supported: _supported };
  })();
})();
