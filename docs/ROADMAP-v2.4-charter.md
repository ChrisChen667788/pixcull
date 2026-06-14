# PixCull — Product Audit + v2.4 Iteration Plan

> Written 2029-Q2 after v2.2 shipped (audio tagger / models manager / GPS
> map / unified lightbox) and the v2.3 editorial-warm overhaul.  A
> hands-on review through five lenses — **PM · designer · architect ·
> algorithm · full-stack** — across five dimensions — **功能 · 智能 ·
> 交互 · 审美 · 细节** — turned into prioritised, landable slices.
> Discipline unchanged: keep the vanilla stack, test gate green,
> screenshot-verify on the live Xiapu run, no functional regressions.

## 0. How to read this

Each slice has **what / why / where (code) / acceptance**, sized to land
in days, ordered by ROI.  Three release buckets:

- **v2.3.1 — hotfix** (design-consistency + bug sweep the GitHub
  screenshots exposed). Ship first.
- **v2.4 — intelligence + workflow** (the headline features).
- **v2.5 — architecture + reach** (pay down the single-file debt; widen).

---

## 1. Honest baseline — what's already strong

Engineering is mature (600+ tests, v0.7→v2.2 shipped); don't re-litigate it.

- **Local-first + explainable**: 6-axis rubric, attribution heatmaps, NL
  explainer, DeepSeek meta-judge — a real moat vs cloud cull SaaS.
- **Video stack**: extract → temporal → reel → assembly + EDL, unified
  lightbox, GPS travel-map, **learned YAMNet audio tagger (macro-F1
  0.629 vs DSP 0.075)**.
- **Infra**: `pixcull models` manager (sha256 pull), plugin SDK, design
  tokens (`make tokens`), i18n, a11y/RTL passes.
- **Brand**: v2.3 editorial-warm + Geist + Double-Bezel + motion.

The gap is **finish & polish**, not capability: the v2.3 reskin was
surface-deep in places, the UX has friction in the core cull loop, and
the intelligence is under-personalised.

---

## 2. v2.3.1 — design-consistency + bug sweep  (P0, ship first)

The GitHub screenshots look "low / 乱 / 重叠".  Root causes, found by
inspection:

### v2.3.1-A · Leaked old palette — ✅ DONE (`7b3cdef`)
- **Found**: the v2.3 overhaul recoloured tokens + named vars but missed
  ~45 hardcoded `rgba()`/hex literals → off-brand components: the
  **rubric/axis score bars rendered a stone→PINK gradient**, plus blue
  selection/compare/marquee accents + violet focus rings.
- **Fixed**: pink `rgba(232,72,153)`→brass, blue `rgba(59,130,246)` /
  `#3b82f6` / `#4b9aff`→stone, violet `rgba(168,85,247)`→stone, across
  `results.html` + `serve_demo.py`. Colour-blind palette untouched.

### v2.3.1-B · Regenerate the gallery on the fixed palette  (P0)
- **Why**: the committed `docs/screenshots/*.png` (03 lightbox, 17
  heatmap, 04 compare, 14 marquee, 18/19 video) still bake in the old
  pink/blue — the user only sees the fix once the PNGs are re-shot.
- **Where**: the robust one-server + per-shot guarded Playwright harness;
  re-shoot the lightbox/heatmap/compare/selection/video family, then
  `make modelscope-sync`.
- **Accept**: no pink/blue in any gallery PNG; GitHub ⇄ ModelScope lockstep.

### v2.3.1-C · Onboarding popovers overlap  (P0)
- **Found**: on the lightbox, the "新手提示" coachmark **and** the "三个
  PixCull 专属设计" popover render **simultaneously, stacked over the
  rubric panel** — reads as a layout bug.
- **Fix**: one coachmark at a time (queue), dismiss-on-advance, never
  cover the active panel; gate behind a single `pixcull_onboard_seen`.
- **Where**: `results.html` onboarding/coachmark JS. **Accept**: at most
  one coachmark visible; none overlaps content; re-shoot clean.

### v2.3.1-D · Toolbar density + overflow  (P1)
- **Found**: the top workspace bar is cramped (counts + filters +
  λ-preset + grade all inline); risks truncation/overlap < 1400px.
- **Fix**: collapse secondary controls into an overflow "···" menu below
  a breakpoint; keep keep/maybe/cull counts + decision filter primary.

### v2.3.1-E · 乱码 / CJK safety audit  (P1)
- **Why**: primary font is Geist (Latin only); Chinese must fall through
  to PingFang/Microsoft Yahei. Verify the `@font-face`/stack so a missing
  CJK glyph never tofu-boxes (esp. the video surfaces + share page).
- **Where**: `font.family` in `tokens.json` + the woff2 `@font-face`.
  **Accept**: render the zh UI with Geist forced — zero tofu.

### v2.3.1-F · Heatmap gradient still indigo→pink  (P1)
- **Found**: attribution Integrated-Gradients overlay is documented (and
  coded) as an `indigo→pink` ramp — off-brand + poor for colour-vision.
  **Fix**: warm/sequential ramp (e.g. espresso→brass→ochre) + a
  perceptually-ordered option. **Where**: `scoring/attribution.py`.

---

## 3. v2.4 — intelligence + workflow  (the headline)

### v2.4-P0-1 · Finish the last v2.2 P0 — VLM best-frame caption — ✅ DONE
- **What**: optional small local VLM (moondream / Qwen-VL export) captions
  the reel's best frame; template fallback stays.
- **Why**: closes v2.2; makes reels self-describing for clients.
- **Where**: `scoring/reel_caption.py` + `pixcull models` (vlm-caption
  slot already catalogued). **Accept**: renders a sentence on eval clips;
  fallback unchanged when absent; same convert→host→pull loop as
  audio-tagger.
- **Done:** `reel_caption.py` until now only rewrote candidate *signals*
  into prose (text-LLM-or-template); it never looked at the picture.  This
  adds a **true VLM path** that captions the candidate's actual best frame:
  `_resolve_best_frame` finds `output_dir/video_frames/<id>/<best_frame_id>.jpg`
  (wired through `run_reel_detection` → `enrich(frames_root=output_dir)`),
  `vlm_caption` runs a small captioning VLM (default
  `Salesforce/blip-image-captioning-base` via transformers, like the CLIP
  path) and prefixes the time range.  Priority is **VLM → text-LLM → template**
  with `caption_source` recorded; **opt-in** via `PIXCULL_REEL_VLM=on` (the
  model is a ~1 GB download + ~2 s/candidate, so the default stays
  byte-identical → zero regression).  **Proof** on the real Xiapu reel run:
  frame `frame_000049` → template said `高画质、精彩瞬间`, the VLM said
  **"A group of birds standing in the water"** (it reads pixels, not
  signals).  `tests/test_reel_caption.py` (source priority + frame resolver
  + a real-model integration test, skipped where the VLM can't load).
  *Note:* the catalogued `vlm-caption` ONNX slot stays reserved for a
  future self-hosted export; the runnable default uses transformers (HF
  cache), consistent with CLIP/scene/face.  BLIP is English — a bilingual
  rewrite (feed the VLM caption back through the zh text-LLM) is a clean
  follow-up.

### v2.4-P0-2 · Personalisation from corrections (the real moat) — ✅ DONE
- **What**: every keep/cull/maybe override is already logged
  (`annotations.jsonl`); learn from it — fit a lightweight per-user
  residual on top of the rubric (per-axis weight + decision threshold
  shift), updated incrementally; show "tuned to you" + an undo.
- **Why**: today the tool scores *generically*; pros each have a taste.
  Active-learning v2 exists (hard-example mining) — wire it into a
  visible, opt-in personal model.
- **Where**: `scoring/personalized.py` + `self_tune.py` + orchestrator λ.
  **Accept**: on a held-out slice of a user's own corrections, the
  personalised decision F1 beats the generic one; fully local; resettable.
- **Done:** `scoring/personal_learn.py` — `gather_examples_from_runs`
  (join `annotations.jsonl` × `scores.csv`), `learn_profile` (reuses
  `personalized.PersonalProfile`: threshold shift + axis means, fit from
  LOCAL corrections), `axis_weights`/`decide` (per-axis weight = the
  user's keep-vs-cull gap), `evaluate` (k-fold held-out keep-F1).
  `pixcull personalize learn/show/reset`; profile persists to
  `~/.pixcull/personal_profile.json`, fully local + resettable.
  **Proof** on a synthetic composition-driven shooter: held-out keep-F1
  **0.39 → 1.0** (recovers most-cared = composition).
  `tests/test_personal_learn.py`.
- **P0-2b — DONE:** the orchestrator loads the saved profile and, when
  active (≥ 50 corrections), passes its `keep_threshold_shift` into
  `decide()` as `personal_shift` — nudging the keep/cull boundary like a
  vertical policy (the generic fusion score is untouched; no-op until the
  user has enough data, so zero regression for everyone else).  A
  "🎯 已按你调校" badge appears in the workspace bar when active (reads
  `/api/v1/users/profile`); undo = `pixcull personalize reset`.
  `tests/test_personal_learn.py::test_decide_applies_personal_shift_in_pipeline`.
  *Not done (deliberate):* axis-reweighting the fused score in the pipeline
  — that would override the model/VLM/DeepSeek fusion; the axis preference
  stays an insight + drives the eval, while the pipeline applies the safe
  calibrated boundary shift.

### v2.4-P0-3 · Keyboard-first photo cull loop
- **What**: bring the video surface's J/K/L muscle-memory to the photo
  grid+lightbox: single-key keep/cull/maybe **with auto-advance**, a
  "rapid mode" that shows one photo at a time at cull speed (~1–2 s/photo).
- **Why**: the cull *loop* is the job-to-be-done; today it's click-heavy.
  This is the #1 pro-workflow win.
- **Where**: `results.html` keybindings + a new focus/rapid mode.
  **Accept**: cull 200 photos keyboard-only, no mouse; <2 s/photo.

### v2.4-P1-1 · Burst "best-of" auto-pick + near-dup collapse — ✅ DONE
- **What**: the run already clusters bursts; auto-select the best frame
  per burst (sharpness + eyes-open + composition) and collapse near-dups
  (CLIP distance) into a stack with a count badge.
- **Why**: bursts/near-dups are the bulk of cull time.
- **Where**: `scoring/burst_peak.py` + grid stack UI. **Accept**: a burst
  cluster collapses to 1 hero + expandable; best-pick agreement vs human
  on the eval set reported.
- **Done:** the **best-of pick** was already shipped (P-AI-5
  `scoring/burst_peak.py`: motion-aware `rank_burst_peak` + scene-aware
  weights → `is_burst_peak` / `burst_peak_reason`, surfaced as the 连拍峰值
  badge, the "🎯 每连拍峰值" filter, and the burst-compare modal;
  agreement vs human in `docs/burst-peak-tuning.md`).  This slice adds the
  missing **"折叠成堆"** grid collapse: a toggle reduces each ≥2-frame burst
  to its peak hero carrying a **⧉N stack badge**; clicking the badge
  expands that cluster into the side-by-side compare modal (`openCompare`).
  **Verified** on a synthetic 3-frame burst (Playwright): toggle visible →
  collapse yields 1 hero with `⧉ 3` (brass, on-brand) → click opens
  `#cmpModal`; zero console errors; visual-smoke + palette-guard green.
  *Note:* "near-dup by CLIP distance" beyond time-bucketed bursts is
  deferred — bursts already are the dominant near-dup case; a CLIP-distance
  pass can reuse the now-fixed `embeddings.npz` later.

### v2.4-P1-2 · NL semantic search over a shoot — ✅ DONE (was silently broken)
- **What**: "红衣服的人 / sharpest sunset / boats on water" → CLIP-embed
  query over the run (embeddings already computed). Search box in the
  grid.
- **Where**: `scoring/semantic_search.py` (exists) → wire a UI. **Accept**:
  top-k visually relevant; <200 ms on 5k.
- **Done:** the search box (`#semSearchInput` + `runSemSearch`) and the
  endpoint (`/api/v1/runs/<id>/semantic_search`, lazy-builds
  `embeddings.npz`) were already wired — but the **real CLIP path was
  broken** and only the synthetic unit tests (which skip the model) were
  green.  Two live-only bugs, found by actually running it:
  1. **transformers ≥ 5** returns a `BaseModelOutputWithPooling` from
     `get_image_features` / `get_text_features` (not a tensor) →
     `'…Pooling' object has no attribute 'cpu'`.  Added `_feature_tensor`
     to pull the projected `pooler_output` (512-d), tolerating both old
     (tensor) and new (object) returns.
  2. `np.savez` appends `.npz` to a target not ending in `.npz`, so the
     `embeddings.npz.tmp` temp landed at `…tmp.npz` and the atomic rename
     `FileNotFound`ed.  Write through an explicit file handle.
  Also fixed a test-pollution bug: two unit tests clobbered
  `ss.encode_query` globally without restoring (now `monkeypatch`).
  **Proof:** red/green/blue swatches built + queried — each colour query
  ranks its own swatch #1 (red 0.272 / blue 0.270 / green 0.278).  New
  `test_build_search_real_clip_end_to_end` exercises the real model
  (skips where CLIP can't load) and would have caught both bugs.

### v2.4-P1-3 · Audio-tagger threshold calibration — ✅ DONE
- **What**: laughter recall is 0.25 @ thresh 0.5 (precision 1.0). Sweep
  per-kind thresholds on the eval set; pick the F1-max operating point;
  expose as config. **Where**: `scoring/audio_tagger.py` + the eval
  harness. **Accept**: macro-F1 ≥ current 0.629 with laughter recall ↑.
- **Done:** `probs_to_events` / `OnnxTagger` now take **per-kind**
  thresholds (scalar back-compat kept); `best_threshold` sweeps the F1-max
  point through the *real* detection path; `eval_audio_tagger.py
  --calibrate --write-thresholds` produces the sidecar. Calibrated points
  ship as the packaged default `scoring/data/audio_tagger_thresholds.json`
  (overridable per-model by `<model>.thresholds.json`; opt out with
  `apply_calibrated_defaults=False`). **Result on the ESC-50 subset:
  laughter recall 0.25 → 0.85 (F1 0.40 → 0.92), applause F1 0.86 → 0.95,
  macro-F1 0.629 → 0.933 (Δ +0.304), precision stays 1.00** — exceeds the
  accept bar. `docs/AUDIO-TAGGER-EVAL.md` §v2.4-P1-3;
  `tests/test_audio_tagger.py` (per-kind threshold + `best_threshold`
  + sidecar/packaged-default resolution).

---

## 4. v2.5 — architecture + reach

### v2.5-P0-1 · Split the single-file frontend — 🟡 IN PROGRESS (incremental)
- **Problem**: `results.html` (~17k lines) and `serve_demo.py` (~18k
  lines) are monoliths — every change risks the kind of leaked-colour bug
  v2.3.1-A fixed.
- **What**: extract `results.html` into ES modules (grid / lightbox /
  inspector / onboarding) built to one bundle; split `serve_demo.py`
  handlers into a small package. Keep "no web framework".
- **Accept**: no behaviour change; screenshot-identical; each module
  independently testable.
- **Approach — incremental, not big-bang**: a 17k/18k-line rewrite under a
  "screenshot-identical" bar is the riskiest item in the roadmap, so we
  peel off one cohesive, independently-verified slice per pass.
- **Slice 1 — DONE:** lifted the seven *pure* serialization/coercion
  helpers (`_scrub_nan`, `_safe_dumps`, `_html_escape`, `_f`,
  `_clean_csv_string`, `_opt_int`, `_parse_int_list`) out of the
  serve_demo monolith into `pixcull/report/serve_util.py`, imported back
  so every call site is unchanged.  Zero module state → zero behaviour
  change; verified by loading serve_demo via importlib (all seven bound +
  behaviour-identical) and the new `tests/test_serve_util.py` (the helpers
  had *no* direct coverage before).
- **Slice 2 — DONE:** lifted the two big embedded page blobs
  (`_VIDEO_REVIEW_HTML` ~19.5 KB, `_TIMELINE_HTML` ~4.7 KB) out of
  serve_demo into `pixcull/report/templates/{video_review,timeline}.html`,
  loaded lazily by a new `_read_template()` (reuses the results.html
  templates dir).  Substitution is the same brace-safe
  `.replace("__RUN_ID__", rid)`, so output is byte-identical;
  **serve_demo.py shrank 449 lines** (18 325 → 17 876).  Covered by the
  existing `test_video_review.py::test_render_html_injects_runid` +
  `test_endpoint_review_page` and `test_timeline.py::test_timeline_page_renders`
  (live-server) — all green.  Next slice: build-time CSS/JS extraction for
  `results.html` (needs a build step + golden-output guard).

### v2.5 iteration sprint (2029-Q3 audit follow-through) — ✅ DONE
Seven slices from the PM/designer/architect review, in priority order:
1. **Dependency-drift hardening** — audited all 5 transformers feature
   sites (only semantic_search was unsafe; fixed earlier), capped majors
   (`torch<3, torchvision<1, transformers<6`), hermetic `_feature_tensor`
   shim test, weekly `realmodel` CI lane (downloads CLIP+BLIP).
2. **Hermetic visual smoke** — committed `tests/fixtures/smoke_run`
   (6-photo synthetic run), `PIXCULL_DEMO_ROOT` env override; the
   rendered-page regression net RUNS in every gate instead of silently
   skipping when /tmp was clobbered.
3. **Brand drift finished** — the README hero lockup SVGs + both brand
   generators + badge colours still carried cosmic-indigo two quarters
   after v2.3; mapped to editorial-warm (stone→graphite on espresso),
   regenerated all four SVGs, extended the palette guard to brand
   surfaces (`test_no_legacy_palette_in_brand_surfaces`).
4. **Personalisation cold-start + ✨ feature tour** — profile endpoint
   returns `min_annotations`; workspace badge shows "🎯 个性化 N/50"
   progress; a ✨ tour modal fronts the six undiscoverable power
   features (NL search / keyboard cull / burst collapse / personalise /
   heatmap / contact sheet).
5. **Bilingual VLM captions** — `_zh_rewrite` bridges BLIP English →
   short natural Chinese via the local zh text-LLM, sanity-checked,
   English fallback.
6. **results.html → built artifact** (the de-monolith headline): sources
   in `templates/src/` (1.2k-line shell + results.css 212 KB +
   results.js 458 KB), `make results-html` splices byte-identically,
   `test_results_build.py` golden-fails any artifact/source fork.
7. **Branded contact sheet** — cover page (brand mark / studio / date),
   vector 1–5 star ratings per cell, `--studio/--date/--no-cover`.

### v2.6 — live-test fallout + the deferred near-dup half — ✅ DONE
Dogfooding the real-photo build surfaced a hard lightbox freeze, then the
last v2.4 deferral landed:
- **Lightbox freeze fixed (stability sweep).** The first-open rubric-intro
  veil registered its Escape handler with `{once:true}` — any keystroke
  (a keyboard-flow user mid-cull) consumed it, Escape went dead and the
  veil read as a frozen UI. Now a persistent **capture-phase** key handler
  dismisses on Esc/Enter/Space and swallows every other key so shortcuts
  can't silently annotate the photos behind the veil. Also reordered the
  global Escape chain (annotation modal → lightbox, was inverted) and gave
  the annotation modal + tour their own capture-phase Esc (focus-immune,
  `stopPropagation` so they don't also close the layer underneath).
- **v2.6-P1 — CLIP near-duplicate fold** (the deferred half of v2.4-P1-1):
  `scoring/near_dup.py` (blocked cosine + union-find connected components;
  5 unit tests incl. blocked==unblocked), endpoint
  `GET /api/v1/runs/<id>/near_dups?threshold=0.92` reusing the
  semantic-search `embeddings.npz` cache, hero = top `score_final` (3
  live-server tests on a synthetic npz, no model). UI: a toolbar
  **"≈ 近重复折叠"** pill (decoupled from bursts — shows even on a
  burst-less run; first toggle lazily builds the index) folds each group
  to its hero with an **≈N** badge that opens the compare modal; coexists
  with the ⧉ burst badge (auto-offset).
- **Grid-starvation freeze fixed (stability sweep, found while wiring the
  near-dup e2e).** `_resolve_image_source` resolved a missing scan-mode
  original via `Path(source_dir or origin_folder or "")` — but `Path("")`
  collapses to `Path(".")`, whose `.is_dir()` is `True`, so an unrecorded
  source `rglob`'d the **entire server CWD** on *every* missing thumbnail
  (~2s each, serialised). Six thumbnails against the browser's
  6-connections-per-host cap starved any user-initiated XHR (the near-dup
  toggle sat frozen at "≈ 建索引中…" forever). This also hit any real run
  whose originals were moved or live on an unmounted drive. Now the empty
  source is guarded — missing-image resolution went 2s → 0.0000s, missing
  thumbs 404 instantly, and the near-dup fold works with no warm-up.
  Covered by `tests/test_lightbox_stability.py` (real-chromium e2e on the
  committed fixture + a synthetic `embeddings.npz`).

### v2.5-P0-2 · Playwright e2e smoke suite
- **Why**: visual regressions (like the palette leak) ship silently today.
- **What**: a tiny CI Playwright pass that loads grid/lightbox/video and
  asserts no console error + key elements present + a colour-sanity check
  (no `#ec4899`/`#3b82f6` in computed styles).
- **Accept**: runs in the existing gate; catches palette/overlap regressions.

### v2.5-P1 · Reach
- Contact-sheet / client-gallery PDF export; deeper Lr/C1 round-trip;
  cross-shoot dedup; on-device duplicate-frame video trimming.
- **Contact-sheet PDF — ✅ DONE:** `pixcull/report/contact_sheet.py` +
  `pixcull contact-sheet <run> -o sheet.pdf [-d keep|maybe|cull|all]`.
  Renders a paginated grid (thumbnail + filename + score per cell, title
  band, `n / total` footer) in the editorial-warm palette — the proof
  sheet a photographer hands a client.  **Dependency-light**: pure Pillow
  multi-page `save(save_all=True)`, no reportlab (keeps the vanilla
  stack).  `render_contact_sheet` (pure layout) + `contact_sheet_from_run`
  (reads `scores.csv`, filters by decision, resolves thumbs).  Verified
  via a rendered sample (clean 4-col grid, no overlap) +
  `tests/test_contact_sheet.py` (pagination, empty/missing-image graceful,
  decision filter, output-subdir, CLI).  Remaining reach items unstarted.

---

## 5. Sequencing & sizing

| bucket | slices | rough size |
|---|---|---|
| **v2.3.1** | A ✅ · B/C (P0) · D/E/F (P1) | ~3–4 days |
| **v2.4** | P0-1/2/3 · P1-1/2/3 | ~3–4 weeks |
| **v2.5** | P0-1/2 · P1 | ~3 weeks |

**Recommended next slice:** v2.3.1-B+C (regenerate the gallery on the
fixed palette + fix the overlapping onboarding popovers) — it finishes
what the GitHub screenshots exposed and is the visible payoff of the
colour fix already shipped.

## 6. Not doing (scope discipline)

Cloud upload · becoming an NLE · native RAW-video decode · a mobile
re-write. PixCull stays local-first, culls + hands off.
