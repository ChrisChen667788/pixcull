# What the README claims, and what makes it true

v3.38. The README's **What you get today** list is eighteen numbered
claims. This is one row per claim: the code that makes it true, and —
separately — whether a photographer actually reaches it.

That third column is the point. This repository's recurring defect is
not a false claim; it is a true one nobody can get to. Four have shipped
that way (a library index resolving nothing, video runs unserveable, a
light theme with no switch, a near-dup fold behind a dead endpoint), so
"the code exists" is not the question being asked here.

**Reachability** is judged against `pip install pixcull` followed by
`pixcull run <folder>` and opening the review page — the path someone
takes who has read the README and nothing else.

| # | claim | what makes it true | reachable |
|---|---|---|---|
| 1 | 6-axis rubric scoring, per-axis rescorer | `scoring/rubric.py` (`RUBRIC_AXES`), `scoring/axis_rescorer.py` | **rubric yes, rescorer no** — see below |
| 2 | Per-genre verticals shift thresholds and tolerate flags | `verticals.py` (`VerticalPolicy`), applied in `scoring/decision.py` | yes |
| 2b | Axis weighting comes from your corrections; each vertical ships a curated cold start | `scoring/personal_learn.py`; `verticals.axis_weight_prior` | corrections yes; the prior is opt-in and the README says which flag |
| 3 | Advice envelope: verdict, strengths cited to canon, weaknesses, suggestions | `scoring/photo_advice.py`; canon in `scoring/rubric.py` | yes |
| 4 | InsightFace ArcFace → DBSCAN → cross-run face library | `pipeline/face_clustering.py`, `pipeline/face_library.py`; embedder prefers ArcFace and falls back to CLIP | needs `pixcull[face]` for detection (mediapipe); without it no faces are found and the rest is a no-op. The `.tflite`/`.task` files do ship in the wheel. |
| 5 | GPS clustering, haversine DBSCAN, ~100 m | `pipeline/location_clustering.py` | yes, when the frames carry EXIF GPS |
| 6 | Burst-peak ranking | `pipeline/burst_peak.py` (`rank_burst_peaks`) | yes |
| 7 | Cull-reason taxonomy, seven reasons, filter pill | `report/serve_app.py` (`CULL_REASONS`), pill in `results.js` | yes |
| 8 | Similar-photos: composite signature, top-5, Shift+click pins | `report/serve_app.py::_serve_api_v1_similar`, served at `/api/v1/runs/<id>/similar/<filename>` | yes |
| 9 | Free-pick A/B compare, synced 1:1 zoom | `results.js` `_cmpZoomToggleSynced` (P-UX-7) | yes |
| 10 | 1:1 focus check, auto-loads hi-res on zoom | `results.js` `_lbZoom.hiRes*` | yes |
| 11 | XMP sidecars, IPTC caption, gallery zip | `cli.py::_export_xmp`, `scoring/caption_gen.py`, `report/gallery.py::build_gallery_zip` | XMP/IPTC/gallery yes; the LLM-polished caption needs a DeepSeek key, which the README says |
| 12 | iOS swipe companion, SwiftUI, talks to `/api/v1/` | `mobile/PixCullCompanion/Sources/PixCullCompanion/APIClient.swift` and its Swift package | **source only** — it is not on the App Store and not in the wheel; you build it in Xcode |
| 13 | Tether mode; partial `scores.csv` survives Ctrl-C | `tether.py` appends one row per frame as it lands | yes |
| 14 | Multi-machine sync, symlink folder mirror | `sync.py` (`configure_sync_target`) | yes |
| 15 | Active-learning queue: disagreement, uncertainty, threshold proximity | `serve_app.py::_serve_next_to_label` | **partly** — priority 1 is rescorer/rule disagreement and priority 2 is the rescorer's uncertain band, so without a rescorer the queue falls through to its later tiers |
| 16 | Multi-user profiles, shared team verticals | `users.py`, `verticals.vertical_root_for_user` | yes |
| 17 | Video culling; shot boundaries so a candidate never spans a cut | `cli.py::video`, `cli.py::reel` | video yes; boundary splitting needs `pixcull[shots]`, which the README says |
| 18 | Transcription and edit-by-text, SRT, EDL, `--speakers` | `cli.py::transcribe` | needs `pixcull[asr]` or `[asr-whisper]`, which the README says |

## The one that failed

**The rescorer is not in the published package.** `RescorerConfig.model_path`
defaults to `models/rescorer_v1.joblib` — a path relative to the working
directory — and the eight artifacts under `models/` (1.8 MB in total)
are tracked in git but are not in the wheel. Measured on the built
artifact:

```
default rescorer path : models/rescorer_v1.joblib
resolves from cwd /tmp: False
joblibs inside pkg    : []
```

So anyone who installed from PyPI and ran `pixcull run` from their photo
folder has been running rule-only. It is not silent — `load_rescorer`
prints `[rescorer] model file not found: … — running rule-only` to
stderr — but the README states the learned head as something you get,
and claim 15's queue leans on it for its top two priorities.

Fixed in v3.44.

## What this list is not

It is not a claim that eighteen features are good. It records that each
sentence in that section has a file behind it and says who can reach it.
Nothing here was measured for quality; the rows that have been measured
say so in their own charters.
