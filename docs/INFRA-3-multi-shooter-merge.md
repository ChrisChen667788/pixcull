# INFRA-3 · Multi-shooter event merge

## The use case

A wedding studio sends two photographers to cover the same event.
Each shoots ~1,500 frames. Each runs PixCull on their own machine
and gets:

    user A: a47a4… (1,503 frames, mostly ceremony angle)
    user B: 7c9d1… (1,418 frames, mostly reception angle)

A and B's runs overlap in time: a kiss is captured by both shooters,
sometimes from different angles, sometimes from nearly the same one.
The studio editor wants:

1. **A combined view** of both shooters' photos in one batch — every
   "moment" represented at least once.
2. **Cross-camera near-duplicate detection** so the editor doesn't
   present the client both shooters' nearly-identical kiss frames.
3. **A "best per moment" picker** — when both shooters covered the
   same beat from different angles, surface BOTH if the angles are
   distinct, ONE if they're effectively the same.

PhotoMechanic, Lightroom catalogs, and current SaaS culling tools
all force the editor to manually merge in catalog-level operations.
The current PixCull experience requires sync (INFRA-2) to share
runs but still leaves the merge entirely to humans.

## The proposed feature

```
POST /api/v1/events/merge
  body: { source_runs: [run_id_a, run_id_b, ...],
          name: "2026-05-16 wedding" }
  → returns merged_run_id

GET  /events/<merged_id>
  → results page showing both shooters' photos in one grid,
    with per-photo "from: A" / "from: B" badges
```

## MVP scope (this commit)

The MVP creates the **merged run record** and the **basic grid view**,
deferring the smart per-moment picker to a follow-up. Concretely:

- `pixcull.events.merge_runs(run_ids: list[str]) → str` — builds a
  unified scores.csv by concatenating each source run's scores.csv
  with an added `source_run` column. Cluster IDs renamed to avoid
  collisions (`{source_run}_{cluster_id}`).
- A new entry `/tmp/pixcull_demo/<merged_id>/output/` with a
  pointer-style manifest mapping each filename back to the source
  run + path.
- `/results/<merged_id>` works through the existing route (the merged
  scores.csv looks like a normal run).

The follow-ups (NOT in this MVP):

- Cross-camera face cluster reconciliation — A's face cluster #3 and
  B's face cluster #5 may be the same bride. Need cross-run face
  identity matching (V22.2-style embeddings exist; need the merger
  to consult them).
- Time-aligned "moments" detection — group photos taken within
  ±2 s of each other from different shooters into the same "moment"
  bucket. Then the picker can choose best frame per moment from any
  shooter.
- Conflict UI when both shooters' face_label for the same person
  disagree (one called her "Lily", the other "Bride").
- Per-shooter color-correction baseline merge.

## Wire format additions

Two new fields in the row dict for merged-run views:

    "source_run":  "a47a4…"        # the original run this came from
    "source_user": "alice"         # who ran the source run

So the UI grows a small "by: alice" chip on each card without
breaking the existing render.

## Why we defer the smart picker

The good news: with INFRA-2 sync in place, two photographers can
already merge their data manually by running scores.csv concat +
re-running the cluster/face passes. The MVP here automates that.

The bad news: the smart per-moment picker is genuinely a new
piece of ML work — needs time-window grouping + per-moment best-
picking + cross-camera face merging — that's at least a sprint
on its own. Designing it together with the user feedback from
the MVP avoids guessing.

— ChrisChen667788, P-UX-19 sprint
