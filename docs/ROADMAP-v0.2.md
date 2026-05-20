# PixCull v0.2 Roadmap — Next-Iteration Plan

A scoped + sized plan across four product dimensions: **professionalism**,
**user experience**, **intelligence**, **core feature precision**.

> Cross-references P-UX-N / INFRA-N / OSS-N tickets already shipped in
> v0.1 — see commit log + `ROADMAP.md` for v0.1 detail.

## Reading this document

- **Sizing** — S (≤ 3 days) · M (~1 week) · L (≤ 1 month) · XL (≥ 1 sprint)
- **Status** — 🆕 proposed · 🔬 needs design · 🚧 dep blocked
- **Reference** — earlier P-UX work this builds on

---

## 1 · 专业度 (Professionalism)

Real-photographer workflow gaps. Each of these closes a "but does it
actually work with my Lr catalog?" objection.

### P-PRO-1 · DNG develop-settings round-trip — M 🔬

Currently we WRITE XMP rating/label; read it BACK after Lr edits
(P-UX-15). But Lr also writes develop settings (`crs:Exposure2012`,
`crs:Whites2012`, ToneCurve, etc) into XMP. If the photographer
applies a uniform color grade across a series, the rubric should
respect it — currently we score on the RAW pixels and miss the
intended look.

**Concrete plan:**
- Extend `pixcull.io.xmp.read_xmp` to also parse `crs:*` develop
  settings into a normalized dict
- In `pixcull.io.loader`, optionally apply read-back develop settings
  to the displayed preview (already half-done — V26 RAW pipeline
  has `apply_develop_settings` hook)
- Rescore against the developed preview, not the RAW, when XMP
  develop settings are present
- Surface "scored against your Lr edit" badge in the lightbox so
  the user knows the difference

**Dependency:** none. Builds on P-UX-15.

### P-PRO-2 · Capture One round-trip parity — S 🆕

Lr round-trip works (xmp:Rating, xmp:Label). Capture One uses the
same XMP namespace but its color labels differ slightly (different
slot mapping). Plus C1 uses session catalogs not catalogs, so the
sidecar location convention is different.

**Concrete plan:**
- Audit C1's actual sidecar conventions (.cos sidecars + session.cooexpdb)
- Add session-mode detection to `_handle_lr_sync`
- Add per-tool color-label mapping table

### P-PRO-3 · Print-readiness check — S 🆕

For working photographers selling prints, the rubric ignores the
physical-delivery question: at the print size the client asked for,
is this image actually printable? 5K of nice 24MP can't print as a
40×30 inch poster.

**Concrete plan:**
- Add `score_print_readiness` axis (0..1) = min(1, naturalW * naturalH / threshold(delivery_size))
- Per-vertical default delivery sizes (wedding/album, landscape/print, journalism/screen-only)
- Surface "printable up to N×M at 300 dpi" in the lightbox

### P-PRO-4 · Wedding moment-list classifier — L 🔬

A wedding has predictable beats: getting-ready → ceremony → kiss →
recessional → cocktail hour → first dance → cake-cut → toasts →
exit. Currently we just say "wedding"; the editor still has to
hand-bucket frames per moment.

**Concrete plan:**
- New scene-template variant: wedding-specific 8-class moment
  classifier (vs current global 14-class scene)
- Train on labeled wedding subset of training data (need ~200
  labeled frames per moment = 1,600 total)
- Surface "ceremony" / "first-dance" / etc. as scene chips
- Filter pill row gains "by moment" group

### P-PRO-5 · DNG sidecar embedding (one-file workflow) — M 🆕

Some workflows prefer XMP embedded in the DNG itself (single file
travels). Pillow + exiftool can write back into DNG. Add an export
option "embed in DNG" alongside "write XMP sidecar".

### P-PRO-6 · IPTC keyword expansion — S 🆕

V29 IPTC auto-caption is done. Keywords are basic. Pros need:
- Per-face keyword from face library (`person:John`)
- Per-location keyword from GPS cluster (`location:Yangshuo`)
- Per-style keyword from style_modes (`style:silhouette`)
- Per-vertical default keyword set

---

## 2 · 用户体验 (User Experience)

Friction reduction. Most of the v0.1 ux work focused on the
results-page surface; v0.2 spreads it across the whole funnel.

### P-UX-20 · Saved view presets — S 🆕

Power users build the same filter combo over and over: "keep + with-face + score>0.7"
for "best face shots" or "maybe + same-cluster" for "review later".
The current state-bundle is gone the moment you reload.

**Concrete plan:**
- "保存当前视图" button in the filter row → names the combo + persists
  to localStorage
- Saved views dropdown beside the existing sort dropdown
- Per-vertical default presets ("婚礼默认 = keep + has-face + score-desc")

### P-UX-21 · Sample-data demo button — S 🆕

The "30秒 demo" we promote in the README requires the user to clone +
install + bring photos. There's no "click here to try it" affordance.

**Concrete plan:**
- Ship a 12-photo public-domain dataset under `samples/`
- New "用示例数据立刻体验" button on the upload page that loads it
- Skips the model warm-up by shipping pre-computed scores.csv
- Renders the full /results experience in <2s

### P-UX-22 · Drag-and-drop deliverable buckets — M 🆕

After the cull, the photographer manually moves keeps into a
"deliverable" folder, maybes into "review", etc. Make this a
drag-target inside PixCull.

**Concrete plan:**
- "Buckets" panel (collapsible sidebar) with custom-named
  destination folders
- Drag any card into a bucket → records the bucket assignment
- "Export bucket" button writes the bucket's photos to a folder
  (or zip / cloud destination)
- Each bucket can have its own XMP rating + IPTC keyword set

### P-UX-23 · Color-blind mode — S 🆕

Keep / maybe / cull rely on green / yellow / red, plus the
decision pill text. ~8% of male photographers can't easily
distinguish green/red. The decision indicator should ALSO carry
a shape (✓ / ? / ✕) or pattern (solid / striped / outlined).

**Concrete plan:**
- Add `prefers-color-scheme` aware + new `pixcull-color-blind`
  body class
- Replace decision-color-only signals with shape+color
- A11y audit checklist for the rest

### P-UX-24 · Keyboard shortcut overlay improvements — S 🆕

Cheat sheet exists (V14.5) but doesn't react to the user's
context. Show only shortcuts relevant to the current modal/mode
(lightbox-only when lightbox open, compare-only when compare open).

### P-UX-25 · Multi-window / multi-tab safety — S 🆕

Two tabs open on the same run can clobber each other's
annotations (last write wins, no merge). At minimum, detect
this case and warn.

### P-UX-26 · Onboarding video — S 🆕

The opt-in 👋 pill (P-UX-19) is good. Add a 60-second silent
embedded video showing the core flow. Lower friction than the
5-step modal tour but more concrete than text.

---

## 3 · 智能化 (Intelligence)

The model side. v0.1 closed the data-collection loop (cull-reason
taxonomy, per-axis stddev, taste profile); v0.2 closes the
training loop.

### P-AI-1 · Cull-reason → rescorer retraining — L 🚧

Currently P-UX-12 surfaces the user's taste profile on the admin
page (axis weights when keep vs cull). NOTHING in the system uses
that to adapt scoring. Close the loop:

**Concrete plan:**
- Periodic background job: when user has ≥50 new annotations,
  retrain a per-user LoRA-style adjustment on top of the global
  rescorer
- Per-user threshold table for keep/maybe/cull (replaces the
  global 0.6/0.4 split)
- Surface "personalized" badge when this kicks in
- Manual "retrain my model now" button on the admin page

**Dependency:** P-UX-12 (data layer), V2.1 rescorer architecture.

### P-AI-2 · Semantic search via embeddings — M 🆕

Currently we filter by scene / face / location / cluster. We DON'T
search by content. Photographers want to type "bride looking at
groom" or "long-exposure waterfall" and find matching frames.

**Concrete plan:**
- CLIP embeddings already computed per row (we use them for face
  clustering). Cache them per-run in `embeddings.npz`
- New `/api/v1/runs/<id>/semantic_search?q=...` endpoint:
  encode query text via CLIP text encoder, cosine sim against
  cached image embeddings, return top-N
- Search bar in the filter row (next to the existing sort
  dropdown)

### P-AI-3 · Per-vertical fine-tuning prompts — S 🔬

Each vertical has different rules of thumb. Wedding photographers
forgive eye-direction; sports photographers don't. The VLM judge
(V3.0) uses ONE prompt across all verticals. Per-vertical
prompts should improve recall.

**Concrete plan:**
- `pixcull/scoring/vlm_prompts/` directory with one prompt per
  vertical
- `vlm_judge.score()` picks the right prompt based on
  `run.vertical`
- A/B test wedding vertical-specific vs global prompt; promote
  the better

### P-AI-4 · Cross-run face library quality — M 🔬

V22.2 inherits face labels across runs by ArcFace cosine. Some
known edge cases:
- Children's faces grow → same person, embedding drifts
- Same person in profile vs front-on → low cosine
- Low-light frames → noisy embedding

**Concrete plan:**
- Audit a 12-month face_library.npz on real shooting history;
  compute cluster purity per "true person" (manual labels)
- If purity < 0.85, add a multi-embedding-per-person model
  (each "person" = K nearest exemplars, not 1 centroid)

### P-AI-5 · Burst peak picker with motion-aware model — M 🆕

Current burst-peak is rule-based (highest sharpness + composition
+ moment combined). Sports / action benefits from a model that
considers motion vectors between frames.

**Concrete plan:**
- Compute frame-pair optical flow for each cluster (cluster size
  ≥ 2). Add features: max flow magnitude, peak-flow frame index
- Train a small head on labeled "best frame in burst" data
  (1k pairs needed)
- Surface the new pick alongside the current rule-based one;
  let user A/B vote which is better

### P-AI-6 · Active learning v2 — S 🆕

P2.4 active-learning queue ranks by rescorer disagreement. v0.2
should add:
- ε-greedy exploration: 80% high-disagreement + 20% random under-
  represented scenes
- "Confidence-collapse" detection: when a single user keeps
  picking the rule's verdict, slow down asks (don't waste their
  time)

---

## 4 · 核心功能效果 (Core Feature Precision)

The "is the model actually good?" axis. Less visible than UX work
but it's what makes the rubric trustworthy.

### P-CORE-1 · Rescorer V2 — retrain with all v0.1 data — M 🆕

The current rescorer (V1.1, V19.3) was trained on 130 labeled
photos. v0.1 collected substantially more data:
- Cull-reason annotations (P-UX-4)
- Sanitized training.csv + training_axis.csv (3,000 rows)
- User-flagged inconsistency cases (P-UX-10)

Retraining should improve accuracy across all axes.

**Concrete plan:**
- Aggregate all annotations.jsonl across all runs into a single
  training csv
- Re-run `train_rescorer.py` with the bigger dataset + tighter
  CV folds (10x vs current 5x)
- Per-vertical rescorer heads (wedding vs landscape vs wildlife)
  if data supports it
- A/B against current rescorer on a held-out set

### P-CORE-2 · Scene classifier debiasing — S 🆕

Known issue (V20 already partial fix): stilllife often
mis-classifies indoor portraits with face_count >= 1. Other known
biases:
- Backlit silhouette → "abstract"
- Long-exposure waterfall → "wildlife" (because of motion blur)

**Concrete plan:**
- Build a confusion matrix on the user's labeled history
- For each high-confusion pair, add a CLIP-prompt disambiguator
  (already exists for stilllife/face_count pair)
- Document the bias matrix in `pixcull/scoring/scene_biases.md`

### P-CORE-3 · GPS clustering algorithmic upgrade — S 🆕

V23's haversine DBSCAN works but has known failure modes:
- Linear trajectory (a road trip's photos) gets clustered as
  one giant "location" because every consecutive pair is < 100m
- Two unrelated locations 50m apart (e.g., adjacent restaurants)
  get merged

**Concrete plan:**
- Add temporal feature: cluster only photos within ±30 minutes
  of each other (catches "different visit to same spot" → same
  cluster; "linear road trip" → many clusters)
- Optional: trajectory analysis using DBSCAN on (lat, lon, time)
  in 3D

### P-CORE-4 · 1:1 zoom hi-res preload smoothing — S 🆕

P-UX-2 swaps to hi-res on first zoom-in but there's a ~300ms
flash. Speed it up by:
- Preload the hi-res IMG in a hidden `<img>` immediately when
  the lightbox opens (don't wait for first zoom)
- Use `decoding="async"` to avoid main-thread blocking
- Cross-fade transition on swap instead of hard replace

### P-CORE-5 · Per-axis rescorer confidence calibration — S 🔬

P-UX-11 surfaces ± stddev across 4 sources. The stddev is RAW
disagreement, not calibrated probability. A "±0.5★" on technical
might mean different reliability than on aesthetic.

**Concrete plan:**
- Build a calibration curve per axis: collect 1000 (predicted ± stddev,
  actual user verdict) pairs
- Fit isotonic regression to map raw stddev → calibrated
  confidence
- Display "high confidence" / "needs review" labels instead of
  raw stddev numbers (more user-friendly)

### P-CORE-6 · Exposure outlier accuracy — S 🆕

P-UX-14 ships the within-burst exposure check at thresholds
(luma 18, highlight 4%). These were picked from one batch.
Re-tune against the user's actual labeled "this is exposure-
broken" history.

---

## Recommended sequencing

A 12-week plan based on:
1. ROI per hour-of-work
2. dependency chain
3. user-facing first, model second

### Sprint 1 (week 1-2) · Quick wins to ship visible improvements

```
P-UX-20  saved view presets             S    Day 1-2
P-UX-21  sample-data demo button         S    Day 3-4  → boosts OSS adoption
P-CORE-4 1:1 zoom hi-res preload         S    Day 5
P-AI-3   per-vertical VLM prompts        S    Day 6-7
P-PRO-2  Capture One round-trip          S    Day 8-10
```

### Sprint 2 (week 3-5) · Intelligence loop closing

```
P-AI-2   semantic search via CLIP       M    Week 3
P-CORE-1 rescorer V2 retrain             M    Week 4
P-AI-1   cull-reason → rescorer loop     L    Week 5 (depends on P-CORE-1)
```

### Sprint 3 (week 6-7) · Pro-grade workflows

```
P-PRO-1  DNG develop-settings round-trip M    Week 6
P-PRO-5  DNG sidecar embed                M    Week 7
P-UX-22  drag-drop deliverable buckets   M    Week 7 (parallel)
```

### Sprint 4 (week 8-9) · Polish + a11y

```
P-UX-23  color-blind mode                 S    Day 1-2
P-UX-24  context-aware shortcut overlay  S    Day 3-4
P-UX-25  multi-tab safety                 S    Day 5
P-UX-26  onboarding video                 S    Day 6-7
P-CORE-2 scene classifier debiasing       S    Day 8-10
```

### Sprint 5 (week 10-12) · Specialized feature R&D

```
P-PRO-4  wedding moment-list classifier   L    Week 10
P-AI-5   motion-aware burst peak picker    M    Week 11
P-AI-4   face library quality improvement L    Week 12
```

### Deferred / R&D (no fixed sprint)

```
P-CORE-3  GPS algorithmic upgrade
P-CORE-5  rescorer calibration
P-CORE-6  exposure threshold re-tune
P-UX-?    further mobile companion work
```

---

## Cross-cutting infrastructure (not in any sprint)

- **CI improvements**: cache ML model weights between GHA runs;
  unblock the currently-skipped `test_v1_1_scripts.py`
- **Tests**: add e2e Playwright test that exercises the full
  results page (P-UX-8 caught the TDZ bug — more like this)
- **Localization**: extract user-facing strings into a single i18n
  table to support English UI
- **Stability**: more `--strict` mypy passes; ruff lint clean-up

---

## What this doesn't do

Deliberately out-of-scope for v0.2:

- **Cloud SaaS hosting** of PixCull itself — stays MIT + self-host
- **GPU training pipeline** — Apple Silicon CPU is enough; cloud
  training is later
- **Mobile app maturity beyond V0.4** — defer to V0.5+
- **Multi-tenant / multi-org features** — stay solo / team scale
- **Auto-edit / develop suggestions** — Lr / C1 own that
- **Stock-photo marketplace integration** — outside scope

---

## How to read progress

Each ticket lives as a separate GitHub issue under its dimension
label (`pro`, `ux`, `ai`, `core`). Closed = shipped + has a
P-* commit. Add a `roadmap-v0.2` tag to filter the milestone.

If a sprint slips, that's expected — these are rough estimates,
not commitments. Reorder by what feedback drives.

— Chris Chen / `@ChrisChen667788`
