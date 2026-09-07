# The live path and the finished path — v3.24, updated by v3.30

`tether.py` dates from P2.2.  Everything the last forty versions added to
the finished pipeline went into the finished path and stopped there.

The live path writes **15** columns.  The finished path
writes **73**.

v3.24 ruled on every difference.  v3.30 then carried five of the gaps and
found out why they were gaps: `_analyze_one_file` returned a hand-written
seven-key dict written in P2.2, and every metric added to the pipeline
since had been discarded on that one line.  The numbers were computed and
thrown away.

`tests/test_tether_drift.py` fails when a new pipeline column arrives
without a disposition.

| disposition | columns |
|---|---|
| deliberate | 43 |
| impossible | 5 |
| gap | 12 |

## Carried by v3.30

Chosen for what changes the NEXT frame, not for closing the list.

- `highlight_clip_pct`
- `shadow_clip_pct`
- `horizon_tilt_deg`
- `face_count`
- `face_max_blink`

Two of the five — `horizon_tilt_deg` and `face_max_blink` — are
conditional upstream: a frame with no horizon and no face has neither.
They are written when present and left ABSENT when not, because a 0 there
would say "level" and "eyes open" about a photograph nobody measured.
Neither could be verified end to end on this machine, which has no frame
with a face in it; the wiring is tested with a synthetic row.

## Still gaps

| column | why it would belong in a live view |
|---|---|
| `wedding_moment` | moment classification is per-frame and would be useful live |
| `wedding_moment_confidence` | moment classification is per-frame and would be useful live |
| `mean_luma` | exposure is what a tether session is watching |
| `face_min_ear` | same |
| `face_max_smile` | same |
| `face_max_brow_down` | same |
| `face_region_lap_var` | sharpness INSIDE the face — the tethered portrait question, and it is missing |
| `score_sharpness` | the sub-scores behind the verdict are hidden |
| `score_composition` | same |
| `score_exposure` | same |
| `score_aesthetic` | same |
| `score_moment` | same |

## Impossible during a shoot

- `face_clusters` — identity clustering is a whole-shoot pass
- `gps_cluster_id` — location clustering is a whole-shoot pass
- `cluster_id` — near-duplicate grouping needs the shoot
- `peak_rank` — rank within a burst that is still arriving
- `burst_peak_reason` — same

## Deliberately absent

- `rubric_*` — six axes and their pass flags is a table, not a glance
- `model_*` — the learned head's per-axis stars, same reason
- `canon_*` — quantified canon metrics are evidence for a critique nobody reads during a shoot
- `datetime` — the photographer knows what time it is
- `scene_probs` — a distribution is not glanceable
- `moment_score` — folded into score_final
- `gps_lat` — the photographer knows where they are
- `gps_lon` — same
- `elapsed_s` — per-frame timing is a diagnostic
- `subject_fraction` — a detector diagnostic
- `laplacian_global` — the live schema carries `sharpness`
- `laplacian_subject` — same
- `scene_confidence` — the scene NAME is already live
- `laion_aes` — an aesthetic model's raw output
- `clipiqa` — same
- `rule_of_thirds_offset` — composition diagnostics
- `composition_score` — same

## Refreshing this

`pixcull/data/finished_run_columns.txt` is a snapshot of a real run's CSV
header.  Re-run the pipeline, copy the header, and the gate will tell you
which new columns need a ruling.
