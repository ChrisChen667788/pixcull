# v2.48 — M3-first: the judge moves to the cloud

**Owner decision, 2026-08-12:** stop optimising for zero-egress. Optimise
for output quality. MiniMax M3 becomes the primary vision engine for both
photos and video.

This is a **positioning change, not a feature**. It invalidates the
product's central public claim ("no photo ever leaves your disk"), so the
charter treats the marketing rewrite as a shipping requirement, not a
follow-up.

---

## The architectural idea

The naive reading of "use M3 instead" is *delete the local stack, POST the
JPEG*. That is worse than what exists, because half the current signal is
**measurement**, and a VLM measures badly:

| signal | how it is obtained today | can M3 do it by looking? |
|---|---|---|
| sharpness | Laplacian variance on the subject crop | no — it is a number, not a judgement |
| highlight clipping | histogram, % of pixels at 255 | no |
| eyes closed | MediaPipe FaceMesh EAR | unreliably |
| near-duplicate | dHash Hamming distance | no — needs pairwise compare over 3000 |
| same person across a shoot | ArcFace 512-d embedding → DBSCAN | **no — needs a vector, M3 returns text** |
| "is this the moment" | proxy: burst z-score, face count | **this is what M3 is for** |
| "is this composition working" | rule heuristics + LAION-Aesthetic | **this is what M3 is for** |

So the refactor is an **inversion, not a replacement**:

> Local detectors stop being an *opinion* and become an **instrument
> panel**. Their readings are serialised into the prompt as evidence. M3
> looks at the photo **and** reads the measurements, then delivers the
> verdict.

Concretely: today `score_final` and `decision` are computed by
`fuse_score()` + `decide()` and written at
`orchestrator.py:370-372` — **before** the VLM loop even opens, and
rule-CULL rows are `continue`d at line 465 so the VLM never sees them.
A 5-star VLM verdict currently cannot change a single decision. That is
the thing this version changes.

---

## Slices

### P0 — a correct M3 adapter, and proof it is correct ✅ this version

The existing MiniMax wiring is stale in three places and has never been
executed even once (verified 2026-08-12: no `vlm_verdicts.jsonl` newer
than 2026-05-01, and the only two that exist name the *local* MLX model):

| where | is | must be |
|---|---|---|
| `vlm_judge.py:540` | `https://api.minimax.chat/v1` | `https://api.minimax.io/v1` |
| `vlm_judge.py:535` | `model="MiniMax-VL-01"` | `model="minimax-m3"` |
| `vlm_judge.py:631` | `model_override or "MiniMax-VL-01"` | `… or "minimax-m3"` |

A partial patch is worse than none: the new endpoint rejects the old
model and vice versa, and `score()`'s blanket `except Exception` turns
either failure into `verdict.error` — so **2100 null verdicts look
exactly like a successful run.** Hence P0 ships a `doctor` command.

New `pixcull/scoring/m3.py`:

- `MiniMaxM3Judge.score(image)` — image evidence-fused, JSON out
- `MiniMaxM3Judge.score_video(clip)` — **native video input**, the
  capability nothing in the current stack has
- `RateLimiter` — token bucket at the published **200 RPM**
- `VerdictCache` — keyed by **content hash**, so an interrupted
  3000-photo run resumes instead of re-billing
- retry with exponential backoff on 429/5xx (today: none)
- budget gate — `check_budget` / `record_call` (today `vlm_judge.py`
  has **neither**, so the ¥10 daily cap is silently blown past)

`pixcull m3 doctor` makes **one real call** and reports, per capability,
what the endpoint actually accepted.

> **Why a doctor rather than just writing the code:** the vendor's video
> content-part schema is not in any public mirror I could reach — only
> the field *name* (`video_url`), the limits (50 MB, fps 0.2–5) and the
> formats. I will not hard-code a guessed wire format into the scoring
> path and let it fail as a silent null. The doctor probes the shapes
> against the live endpoint and writes the winner to a capability file.

### P1 — M3 becomes the judge, not a fourth opinion

- `build_evidence_block()` — local metrics → a `MEASUREMENTS` section
- rule-CULL rows are no longer skipped when M3 is primary (that skip
  exists to save money on a *second* opinion; it is wrong for a *first* one)
- M3's verdict feeds `decide()` instead of landing in a parallel column

### P2 — throughput

`ThreadPoolExecutor` + `as_completed` (the meta-judge at
`orchestrator.py:545` already does this correctly; the VLM loop at
line 464 is plain serial). **Must collect and write after
`as_completed`** — parallel `df.at[]` from workers races.

At 200 RPM, 3000 photos is ~15 min. Serial at 3 s/call it is ~105 min.

### P3 — M3 writes the advice

`photo_advice.py` is 1576 lines of templates and **zero** LLM calls. It
is the weakest surface in the product and the one M3 most obviously
improves. Seam: `build_advice()` at line 1469 — preserve the 9-key
output shape or `caption_gen.compose_caption()`, the XMP exporter and
the lightbox citation pane all break silently.

### P4 — video content understanding

`reel.py` ranks candidates on `mean_final + max_temporal` — **100%
proxy**. A clip of the vows and a clip of someone fixing a mic score
identically if camera motion and face count match. M3 can tell them apart.

Watch: 1–3 s candidates are 7.5 MB at 1080p/20 Mbps but **187 MB at 4K
ProRes** — needs a transcode gate before the 50 MB limit.

### P5 — say the true thing

47 separate public claims must change. Non-negotiable, because they are
promises: `pyproject.toml` keywords, the README no-upload badge, both
READMEs' hero copy, `tour.foot` in **all 13 locales**, `upload.html`'s
feature card, `SECURITY.md`'s threat model, and `docs/launch-post-en.md`,
whose entire competitive argument is the NDA/no-upload case.

Plus new: a **consent gate** before the first upload, and a per-photo
"analysed in the cloud" indicator.

---

---

## What landed in 2.48.0

**P0, P1 and P2.** P3/P4/P5 moved to their own versions — see
`ROADMAP-M3-remaining.md`, which also inserts a measurement version
*before* the positioning rewrite. Nothing yet shows M3 judges better than
the rule stack; rewriting 47 public promises on an unverified assumption
would be a bet, not a decision.

**No default changed.** Deliberately: P0 changes **no default**. `vlm_mode` is still
`"off"`, so the product is still local-first as shipped and every public
claim in P5 is still true. That keeps this a safe checkpoint — the
version that flips the default must land P1 **and** P5 together, or the
README becomes a lie the moment it is pushed.

| | |
|---|---|
| `pixcull/scoring/m3.py` | new — judge, rate limiter, cache, evidence |
| `vlm_judge.py` | 3 stale constants fixed; MiniMax now routes to `m3` |
| `llm_budget.py` | `minimax-m3` pricing (was billing at DeepSeek-Pro rates) |
| `cli.py` | `pixcull m3 doctor` / `pixcull m3 status` |
| `tests/test_m3.py` | 36 tests, **8/8 mutations caught** |
| `test_repo_hygiene.py` | MiniMax key shapes added to the banned list |
| `orchestrator.run_vlm_stage` | extracted + concurrent (P2); nothing tested it before |
| `orchestrator._reapply_decisions_with_vlm` | P1 — the verdict finally reaches `decide()` |
| `decision.decide` | `vlm_label` / `vlm_axes` / `vlm_authority`, default `off` |
| `pyproject.toml` | **openai declared** — 5 modules imported it, none declared it |
| `cli.py run` | `--vlm-mode` / `--meta-mode`; M3 was unreachable from the CLI |

Gate: **1799 passed, 9 skipped, 0 failed** (9 = the documented 5 + 4 ASR
weights-not-mounted). Mutation rounds: 8/8, 3/3, 8/8, 8/8.

Mutations verified caught: stale endpoint · stale model · 4xx retried ·
video-shape guard removed · evidence dropped from the prompt · cache
bypassed · budget gate removed · fps unclamped.

**Owner action before P1 can be verified:** run
`pixcull m3 doctor --image <photo> --video <clip.mp4>` once. Until it
does, `score_video()` refuses to run rather than guess the wire format.

## Gate

- `pytest tests/ --ignore=tests/test_v1_1_scripts.py` green, 5 skips
- **no test may reach the network** — CI has no MiniMax key, and
  `conftest.py` has no global network block. Every M3 test stubs
  `pixcull.scoring.m3.OpenAI`.
- `test_repo_hygiene.py` — the banned-prefix list does **not** currently
  match MiniMax keys. Extend it, and build any fixture key at runtime.
