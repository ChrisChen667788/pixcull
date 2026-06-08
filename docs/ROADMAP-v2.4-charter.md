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

### v2.4-P0-1 · Finish the last v2.2 P0 — VLM best-frame caption
- **What**: optional small local VLM (moondream / Qwen-VL export) captions
  the reel's best frame; template fallback stays.
- **Why**: closes v2.2; makes reels self-describing for clients.
- **Where**: `scoring/reel_caption.py` + `pixcull models` (vlm-caption
  slot already catalogued). **Accept**: renders a sentence on eval clips;
  fallback unchanged when absent; same convert→host→pull loop as
  audio-tagger.

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

### v2.4-P1-1 · Burst "best-of" auto-pick + near-dup collapse
- **What**: the run already clusters bursts; auto-select the best frame
  per burst (sharpness + eyes-open + composition) and collapse near-dups
  (CLIP distance) into a stack with a count badge.
- **Why**: bursts/near-dups are the bulk of cull time.
- **Where**: `scoring/burst_peak.py` + grid stack UI. **Accept**: a burst
  cluster collapses to 1 hero + expandable; best-pick agreement vs human
  on the eval set reported.

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

### v2.5-P0-1 · Split the single-file frontend
- **Problem**: `results.html` (~14k lines) and `serve_demo.py` (~12k
  lines) are monoliths — every change risks the kind of leaked-colour bug
  v2.3.1-A fixed.
- **What**: extract `results.html` into ES modules (grid / lightbox /
  inspector / onboarding) built to one bundle; split `serve_demo.py`
  handlers into a small package. Keep "no web framework".
- **Accept**: no behaviour change; screenshot-identical; each module
  independently testable.

### v2.5-P0-2 · Playwright e2e smoke suite
- **Why**: visual regressions (like the palette leak) ship silently today.
- **What**: a tiny CI Playwright pass that loads grid/lightbox/video and
  asserts no console error + key elements present + a colour-sanity check
  (no `#ec4899`/`#3b82f6` in computed styles).
- **Accept**: runs in the existing gate; catches palette/overlap regressions.

### v2.5-P1 · Reach
- Contact-sheet / client-gallery PDF export; deeper Lr/C1 round-trip;
  cross-shoot dedup; on-device duplicate-frame video trimming.

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
