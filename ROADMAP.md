# PixCull Roadmap — Post-V20

Living doc. Order = current best-guess priority but not commitments. Each
item lists: who it serves, what hurts today, what to ship, rough effort.

---

## Where we are after V20

| Layer | Status |
|---|---|
| Rule stack + 6-axis scoring | Solid; ~0.78 V1.1 accuracy, 0.92 moment R² |
| Vertical system (10 verticals) | Policy + sample banks + AI phrases; **half-empty buckets** for 4 verticals |
| Web UI / results grid | Works; lightbox; per-image advice now actionable (V20) |
| Lightroom plugin | One-way: LR → PixCull → browser. **No write-back.** |
| Performance | ~2 sec/image serial. 5000 photos = 2.7 h. |
| Multi-user / team | None. Per-machine sample banks + models. |
| Mobile / tethered | None. |

---

## Persona × Gap matrix

Where today's PixCull breaks down for each user type:

| Persona | Volume | Output | Today's pain |
|---|---|---|---|
| **Wedding** 婚纱 | 1–2k/event, 24–72h turnaround | 200–400 final | No bride/groom recognition; no posed-vs-candid; no album sequencer; "best of cluster" is manual |
| **Wildlife / Bird** | 500–2000/outing (mostly bursts) | 5–20 keepers | **wildlife bucket has 0 good samples** so can't tune; no eye-focus precision metric; no behavior/species tagging |
| **Event / Sports** | 1000–5000/event | 50–200 wire | No action-peak rank; no team/player face recognition; no IPTC/captioning output |
| **Family / Kids** | 100–500/session | 30–80 prints | Single-user only — parents can't co-review; no "best of month" auto-curation |
| **Travel** | 1000–3000/trip | 100–300 portfolio | No GPS clustering; no "one per location" auto-pick; no trip-summary view |
| **Studio commercial** | 50–300/shoot | 10–50 retouched | No WB consistency check; no product-framing repeatability; no style-guide enforcement |
| **Studio team** | 10k+/week | Multi-photographer brand | No multi-user accounts; no shared sample banks; no approval workflow |
| **Photojournalism** | varies | wire stories | No captioning; no GPS verification; no IPTC writeback |

---

## P0 — finish what V19/V20 started

These close real bugs / incomplete features in production. **Should ship in V21–V23 series.**

### P0.1 — Wildlife/Bird/Cosplay/Pet sample buckets (3 of these have 0-good or 0-bad samples)
- **Why now:** V17.4 tune impossible until both buckets ≥ 1; downstream advice / AI phrases also dry up.
- **Plan:**
  - Auto-route from V18+ scans by genre + face/subject heuristics, same pattern as the 137-bad-sample V18 routing.
  - For wildlife specifically, write a "good" heuristic: scene==wildlife AND face_count==0 AND clipiqa>0.6 AND subject_fraction>0.15.
  - Surface a `/verticals/<key>/auto_seed` admin button so the user clicks-to-fill.
- **Effort:** 1 day (mostly heuristic tuning + UI button).

### P0.2 — Lightroom write-back (V20 already in user's mind)
- **Persona:** wedding, event, anyone in LR-centric workflow.
- **Why now:** Today the loop is open. Decisions don't propagate back into the LR catalog, so the photographer manually clicks through every star in LR.
- **Plan:**
  - `LrPhoto:setRawMetadata('label', ...)` from a new `WriteBackDecisions.lua` menu entry.
  - Mapping: keep → 5★, maybe → 3★, cull → reject flag (`pickStatus=-1`).
  - HTTP `GET /run/<id>/decisions.json` so the plugin pulls the mapping.
- **Effort:** 2 days (Lua + 1 server endpoint).

### P0.3 — Cluster best-of-N picker UX
- **Persona:** wedding, sports, kids, anyone shooting bursts.
- **Why now:** Duplicate detector groups bursts into clusters, but UX is passive — the "compare modal" exists but doesn't make the choice easy.
- **Plan:**
  - "Pick best" button per cluster card → ranks by `score_final * (1 - shadow_clip - face_blink_penalty)` → highlights the winner, marks others as cluster-cull.
  - "Review N runners-up" expandable area so the user can override.
- **Effort:** 3 days (server endpoint + JS cluster-detail UI).

### P0.4 — Stilllife scene fix needs a re-scan to take effect
- **Why now:** V20 worker.py code fixes new scans, but the user's existing 5439-photo cached data still mis-tags 860+ photos as stilllife.
- **Plan:**
  - "重扫场景" admin button on /runs that re-runs JUST SceneDetector + face-aware correction on cached rows (skip full re-analyze).
  - Persists corrected scene + new advice into scores.csv.
- **Effort:** 1 day (re-uses worker components).

### P0.5 — Performance: parallelize per-image worker
- **Persona:** everyone with batches >500.
- **Why now:** 2 sec/photo serial means a 1000-photo wedding takes 33 min. Photographers expect "while I make coffee" not "while I make lunch".
- **Plan:**
  - `multiprocessing.Pool` over image paths in `pipeline/orchestrator.py`. Detector model singletons are per-process — load once per worker.
  - Target: 4× speed up on M1 Max (4 workers, GIL-free CPU bottleneck).
- **Risk:** MediaPipe / Torch fork safety. Mitigate with `forkserver` start method + warm models in worker init.
- **Effort:** 3 days (incl. fork safety testing + memory profiling).

---

## P1 — new capabilities (one per persona)

### P1.1 — Face recognition for repeated subjects (wedding/event/kids/family)
- **What:** Cluster faces across batch → label "bride" / "groom" / "child A" once, propagates.
- **Why:** Wedding photographer culls 1500 photos; bride should appear in 80% of keepers, can use that as a sanity filter.
- **Build:** MediaPipe face-embedding (already have FaceLandmarker) + KMeans clustering + per-cluster labeling UI.
- **Effort:** 4 days.

### P1.2 — Action-peak ranking (sports/event)
- **What:** Per-cluster moment-axis ranking that surfaces THE peak frame (gesture apex, eye-contact moment, peak action).
- **Why:** A 30-frame burst of a soccer player kicking — 1 frame is THE shot.
- **Build:** Already have face_max_blink + face_min_ear + composition_score. Add an `action_peakness` metric = combo of these + first-derivative of subject motion across burst.
- **Effort:** 3 days.

### P1.3 — GPS clustering + per-location best (travel)
- **What:** Read EXIF GPS, cluster by location, surface "best of location" per cluster.
- **Why:** Travel photographer's 2000-photo trip becomes ~30 location-best photos for the portfolio.
- **Build:** EXIF GPS read (rawpy / pyexiv2), DBSCAN clustering, results-page filter chip "按地点".
- **Effort:** 3 days.

### P1.4 — Multi-user mode + shared sample banks (team)
- **What:** Login-less local user accounts; sample banks per user OR per team.
- **Why:** A 3-person studio can't share style references today.
- **Build:**
  - Lightweight user-id (sign in with Google / Apple via SSO — or just nick + machine-id).
  - `~/Library/Application Support/PixCull/users/<uid>/verticals/<key>/...` namespace.
  - Per-vertical "team mode" flag: bank lives at `~/Library/.../teams/<team_id>/` symlinkable.
- **Risk:** SSO touches the prohibited-actions boundary (creating accounts on user's behalf). Build for OAuth-with-explicit-consent only.
- **Effort:** 1 week (account model + UI + sync).

### P1.5 — Photo-bag / collection export (everyone, but high impact for wedding+travel)
- **What:** Export selected keeper-set as a viewable web gallery (single-file HTML, photographer can share to clients).
- **Why:** Today PixCull's output dies at the results page — no way to send "here's my top 200" to a client.
- **Build:** Zip + minimal static HTML gallery with thumbnails + lightbox; no PixCull server required to view.
- **Effort:** 3 days.

### P1.6 — IPTC / XMP write-back (photojournalism + studio commercial)
- **What:** PixCull decisions + axis stars → IPTC keywords + XMP rating in the original file (or sidecar).
- **Why:** Lightroom / Capture One / Bridge all read these. Persistence beyond PixCull's own DB.
- **Build:** pyexiv2 or exiftool wrapper + new export route. Per-run "Apply XMP" button.
- **Effort:** 4 days.

---

## P2 — long-shot / ambitious

### P2.1 — Mobile companion app (iPad/iPhone)
- Review on the road during the shoot; tether to PixCull server over LAN.
- Native Swift + PixCull HTTP API (need to firm up JSON API first).
- 3+ weeks.

### P2.2 — Capture One / Lightroom tether integration
- Live cull during shoot: photo lands in tether folder → analyzed in 1-2 sec → decision shows up in tether app's metadata panel.
- 2+ weeks; depends on tether-watcher reliability.

### P2.3 — Style-guide enforcement (studio brand)
- "Cull anything that doesn't match brand color palette / aspect ratio / framing convention."
- Per-team `style_guide.yaml` + bespoke detectors.
- 2+ weeks.

### P2.4 — Active learning loop UI
- "PixCull is least confident about THESE 20 photos — label them and the model improves the most."
- We have `pick_next_to_label.py` but no UI yet.
- 1 week.

### P2.5 — Auto-captioning (photojournalism)
- VLM-generated captions per photo, edited inline, exported as IPTC caption.
- Cost-sensitive (¥0.01/photo with DeepSeek VL).
- 2 weeks.

---

## Cross-cutting infra (no single persona, blocks several)

| ID | Item | Blocks |
|---|---|---|
| INFRA-1 | **Clean JSON API** | Mobile app, third-party integrations, plugin write-back |
| INFRA-2 | **Multi-machine sync** for sample banks + models | Team mode, mobile app |
| INFRA-3 | **RAW (CR3 / DNG) full-quality pipeline** | All RAW-shooting personas (~80% of pros) |
| INFRA-4 | **Cost-aware LLM call routing** (local VLM fallback when offline) | Phrase gen, captioning, advice quality |
| INFRA-5 | **Stable upgrade path for joblib artifacts** (numpy / sklearn version drift bit us twice already) | Every retrain |

---

## What's the next iteration?

Three credible "next-V21" picks based on impact-to-effort ratio:

| Option | Persona impact | Effort | Why pick |
|---|---|---|---|
| **V21 = P0.1 + P0.2** | Wildlife + Wedding (the two most-vocal verticals) | 3 days | Closes V17.4 tune gap + LR loop in one shot |
| **V21 = P0.5 (perf)** | Everyone with >500 photos | 3 days | Single biggest UX complaint vector once batches scale |
| **V21 = P1.1 (face recognition)** | Wedding + event + kids + family | 4 days | Unlocks "bride/groom mode" and Family/Kids team review |

---

*Last updated: V20 (commit f937c3c, 2026-05-14).*
