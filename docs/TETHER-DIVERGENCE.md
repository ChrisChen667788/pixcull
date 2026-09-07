# The live path and the finished path — v3.24

`tether.py` dates from P2.2.  Everything the last forty versions added to
the finished pipeline went into the finished path and stopped there.

The live path writes **10** columns.  The finished path
writes **73**.

It is not obvious the live path should carry all of them — a photographer
watching frames land during a shoot does not want a four-sentence critique
between shutter releases.  What was not obvious is that **nobody had
decided**.  This page is the decision, and `tests/test_tether_drift.py`
fails when a new pipeline column arrives without one.

| disposition | columns |
|---|---|
| deliberate | 43 |
| impossible | 5 |
| gap | 17 |

## The gaps — things that should be live and are not

Named, not counted: "17 things are missing" is a number, and
"blown highlights are fixable next frame" is work.

| column | why it belongs in a live view |
|---|---|
| `wedding_moment` | moment classification is per-frame and would be useful live |
| `wedding_moment_confidence` | moment classification is per-frame and would be useful live |
| `mean_luma` | exposure is what a tether session is watching |
| `highlight_clip_pct` | blown highlights are fixable NEXT frame |
| `shadow_clip_pct` | same |
| `face_count` | eyes-open is the live question and it is absent |
| `horizon_tilt_deg` | a tilt is correctable while still on set |
| `face_max_blink` | same — this is THE tether-time signal |
| `face_min_ear` | same |
| `face_max_smile` | same |
| `face_max_brow_down` | same |
| `face_region_lap_var` | sharpness INSIDE the face — the tethered portrait question, and it is missing |
| `score_sharpness` | the sub-scores behind the verdict are hidden |
| `score_composition` | same |
| `score_exposure` | same |
| `score_aesthetic` | same |
| `score_moment` | same |

The shape of the list is itself the finding.  Almost every gap is either
**exposure** or **the face** — the two things a tethered photographer is
actually watching for, and the two the live path is silent about.  It
reports a verdict and withholds the one number that would let them fix the
next frame.

## Impossible during a shoot

Not work.  These need the whole shoot, and during a shoot there is no
whole shoot yet.

- `face_clusters` — identity clustering is a whole-shoot pass
- `gps_cluster_id` — location clustering is a whole-shoot pass
- `cluster_id` — near-duplicate grouping needs the shoot
- `peak_rank` — rank within a burst that is still arriving
- `burst_peak_reason` — same

## Deliberately absent

Handled as families where they come in families.

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
which new columns need a ruling.  That is the whole mechanism: the cost of
adding a column includes one sentence about whether the live path needs it,
paid at the only moment anyone knows the answer.
