# PixCull Roadmap — V30 status check

Living doc. Order = current best-guess priority but not commitments.
Last refreshed at the V22.2 + INFRA-5 commit (post-V29).

---

## Where we are now

| Layer | Status |
|---|---|
| Rule stack + 6-axis scoring | Solid; V1.1 acc 0.78, moment R² 0.92 |
| Vertical system (10 verticals) | Policy + sample banks + AI phrases; auto-seeder ships in V21.1; **wildlife/bird/cosplay/pet still need bad-bucket fills for full coverage** |
| Per-image advice | V20 — strengths cite measured values; maybe/cull always speak |
| Web UI / results grid | V20+V22.1+V23+V27 — face / location / burst-peak filter pills; ✎ rename face clusters |
| Lightroom plugin | V21.2 — **bidirectional write-back** (keep→5★/maybe→3★/cull→reject) |
| Performance | V21 — 1.7× speedup on 245-img bench (4w × 2t spawn pool) |
| Multi-user / team | V28 — per-user profiles + team sample-bank redirects |
| Mobile / tethered | V25 unblocked it via `/api/v1/` + CORS; native app deferred (P2.1) |
| RAW pipeline | V26 — quality-preserving display loader for CR3/DNG lightbox |
| Face identity | V22.0.1 — InsightFace ArcFace (CLIP fallback); **V22.2 cross-run label inheritance** |
| Output | V23.x — standalone HTML gallery zip; V29 — IPTC keywords + caption + headline in XMP |

---

## Shipped (V21 → V29)

| Commit | Item | Persona served |
|---|---|---|
| `ac33199` V21 | parallel per-image analyze (4w × 2t spawn) | Everyone >500 photos |
| `a33a0e1` V21.1 | auto-seed empty vertical sample buckets | Wildlife/bird/cosplay/pet |
| `960055f` V21.2 | LR write-back endpoint + WriteBackDecisions.lua | Wedding/event LR workflows |
| `f937c3c` V20 | per-image advice fallback + value-cited strengths | Everyone (UI clarity) |
| `f05a2e7` V22.0 | face embedding + DBSCAN cluster data layer | Wedding/event/kids/family |
| `e0ec82c` V22.1 | face cluster pills + inline rename + per-run persistence | Wedding/event/kids/family |
| `3fe2acc` V22.0.1 | **CLIP → InsightFace ArcFace** (V24 quality audit drove it) | Wedding/event/kids/family |
| `03292d2` V23 | GPS location clustering + per-location-best | Travel |
| `b42eca1` V23.x | standalone HTML gallery export (single-zip client deliverable) | Wedding/travel |
| `fab347c` V25 | `/api/v1/` namespace + CORS + discovery | Mobile + third-party |
| `d97235a` V26 | RAW display loader (CR3/DNG quality decode) | All RAW shooters (~80% pros) |
| `6de7f60` V27 | burst peak ranking + "🎯 每连拍峰值" toggle | Sports/event/kids bursts |
| `a9bb82e` V28 | multi-user profiles + team sample-bank redirects | Studio team |
| `02cea51` V29 | IPTC keywords + caption + headline in XMP export | Journalism/commercial |

---

## Still open

### P0 leftovers (V21–V23 era cleanup)
- **P0.3 — Cluster best-of-N picker UX**: similar pattern to V23's
  "per-location best" but for burst clusters. V27 added the action-peak
  ranking; this is the UI deep-dive (compare-modal with side-by-side,
  override picks). Effort ~2 days.
- **P0.4 — Re-scan-stilllife admin button**: V20's stilllife-with-face
  fix only takes effect on new scans. Older runs still mis-tag. An
  admin button on /runs that re-runs JUST SceneDetector on cached
  rows would fix them in-place. Effort ~1 day.

### P1 followups
- **V22.3** mini-avatar on face pill: display a small face crop next
  to "👤 Bride" pills so the user identifies clusters at-a-glance.
  Effort ~1.5 days; can reuse V26 display loader.
- **V23.1** location naming (reverse geocoding or inline rename like
  V22.1). Effort ~2 days for inline-rename, more for reverse geocoding
  if we add a third-party API dep.
- **V25.1** CORS allowlist (env-var configurable, default *). Tighten
  for production deployments. Effort ~0.5 day.
- **V26.1** DNG develop-settings: parse XMP sidecar's WB / exposure
  adjustments and apply during rawpy postprocess. Effort ~3 days.
- **V27.1** peak badge in lightbox: when `is_burst_peak` true, show
  🏆 next to the score in the info panel. Effort ~0.5 day.
- **V28.1** active-user UI dropdown on /verticals + /admin pages.
  Effort ~1 day.
- **V29.1** in-image IPTC write (pyexiv2 / exiftool wrapper). Sidecars
  work in every modern catalog tool, but agencies / commercial
  workflows sometimes need embedded metadata. Effort ~4 days incl.
  build-dep wrangling.

### P2 long-shots (unchanged from V20-era roadmap)
- **P2.1 Mobile companion app** — Now actually unblocked by V25.
  Native Swift + the `/api/v1/` JSON API. 3+ weeks.
- **P2.2 Lr / C1 tether integration** — Live cull during shoot.
  2+ weeks; tether watchers are reliability-sensitive.
- **P2.3 Style-guide enforcement** — Per-team `style_guide.yaml`
  + bespoke detectors. 2+ weeks; depends on V28 team mode.
- **P2.4 Active learning UI** — Surface
  `scripts/pick_next_to_label.py`'s output in the browser. 1 week.
- **P2.5 Auto-captioning** — VLM-generated captions, exported via
  the V29 IPTC pipeline. 2 weeks; cost-sensitive.

### Cross-cutting infra
- **INFRA-1 — Clean JSON API** ✅ shipped as V25.
- **INFRA-2 — Multi-machine sync** for sample banks + models. V28
  added user / team scoping but storage is still per-machine. Real
  sync (S3 / WebDAV / iCloud Drive) needs design + a real backend.
  2+ weeks.
- **INFRA-3 — RAW pipeline** ✅ shipped as V26 (display loader);
  develop-settings application is V26.1.
- **INFRA-4 — Cost-aware LLM call routing** for phrase gen + future
  captioning. Local VLM fallback when offline / hitting cost ceiling.
  1 week.
- **INFRA-5 — joblib / numpy version-drift discipline** ✅ shipped:
  pyproject pinned `numpy>=1.26,<2`; `pixcull/__init__.py` runtime
  guard warns loudly if numpy 2.x sneaks in via a transitive install.
  Bitten twice (V18.1, V22.0.1); won't be the third time.

---

## V22.2 cross-run label inheritance (ships alongside this doc)

Pre-V22.2 cluster ids were run-scoped: labeling "cluster 0 = Bride"
in run A had no effect on run B for the same couple. Photographer
re-labels every time.

V22.2 changes:
1. **Per-run centroids persisted** to `<output_dir>/face_centroids.npz`
   (alongside the existing face_labels.json). ~2 KB per cluster.
2. **Per-user face library** at `<user_root>/face_library.npz` —
   maps labels to up to 16 centroids each (variants over time /
   lighting / haircuts).
3. **Auto-promote on label save**: when the user names a cluster
   "Bride" in run A, that centroid joins the library.
4. **Auto-suggest on new runs**: each unlabeled cluster's centroid
   gets cosine-matched against the library; if sim ≥ 0.55 (looser
   than within-batch ε=0.50 because inter-run variance is wider),
   the cluster pill shows "≈ Bride" with a tooltip like
   "跨 run 推测,相似度 0.83". User clicks ✎ to confirm or override.

This is the "Bride photographer's second wedding for the same
couple" use case — V22.1 forced a re-label; V22.2 inherits with one
click.

---

## Next-iteration picks

After V29 + V22.2 + INFRA-5 ship, the highest-leverage remaining items
by impact-to-effort:

| Option | Persona | Effort | Why pick |
|---|---|---|---|
| **V28.1** active-user UI dropdown | Studio team | 1 day | V28 data layer is in but invisible in the UI; users can't see what user they're actually scoped to |
| **V27.1** peak badge in lightbox | Sports/event | 0.5 day | Tiny polish on V27 that closes the "did the picker get the right frame?" verification loop |
| **P0.3** cluster compare modal | Wedding/sports | 2 days | Most-requested UX gap — side-by-side burst comparison |
| **V22.3** mini-avatar on face pill | Wedding/event/kids | 1.5 days | "Person 3" → actual face image makes the filter unmistakable |
| **P2.1** mobile companion app | All | 3+ weeks | Now unblocked by V25; biggest single-feature delta |
| **INFRA-4** cost-aware LLM routing | All | 1 week | Lets us turn on auto-captioning + richer advice without runaway cost |

---

*Updated 2026-05-15. Living document.*
