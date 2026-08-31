# Closing the block — v2.77 to v2.93, re-measured together

Seventeen versions. This is the pass that checks none of them undid another.

## First-screen ready, measured with `scripts/measure_first_screen.py`

5,069-row run, three cold samples (server restarted for each) and five warm.

| | before v2.77 | after v2.93 |
|---|---|---|
| cold first-screen | 3386 ms | **1925 ms** |
| warm first-screen | 971 ms | **316 ms** |
| warm TTFB | 62 ms | 58 ms |
| image requests | 121 | **69** |
| long tasks | ~508 ms | **278 ms** |
| style recalc, 6 s idle | 2420 ms | 30 ms |

Warm first-screen is down 67%, cold 43%.

## What the close-the-block pass found

Two defects that only appear when the versions are measured together.

**gzip was charging local users for a network they do not have.** v2.92
compressed every reply the browser asked to have compressed, which is right for
the LAN feature and for remote access and wrong for the default — a browser on
the same machine. Cold TTFB went from 1134 ms to 1383 ms for a transfer that was
already instant, handing back a fifth of what v2.77 spent two fixes reclaiming.
Loopback clients now skip compression; everyone else keeps the 8× reduction.

**The ledger's loudest warning fired on the most ordinary configuration.** Every
`--vlm-mode off` run printed *FALLBACK FAULT — 4,396 candidate rows, 0
attempted — the pass had work and did none*. The run asked to stay local and the
pass obeyed. `structural` now subtracts what policy withheld, which is the shape
v2.81 already built for exactly this. A genuinely silent pass still shouts, and
withholding some rows does not excuse skipping the rest.

That second one matters beyond its own fix. v2.82's commit says a ledger that
over-reports teaches people to ignore it, and the ledger was over-reporting on
every single local run while that sentence was being written.

## What did not close

Cold TTFB is 1432 ms against 1134 ms measured at v2.84, and the ranges do not
overlap. `_build_results` itself profiles at 573 ms, so the difference is not in
the page build. It may be accumulated load on a machine that has been running
tests for hours, or it may be a real regression this pass failed to isolate.
Reported as open rather than explained away.

## Still waiting on a human

Five versions built their machinery and refused their number, and the reason is
one thing: **there are no human labels on this machine** (`GROUND-TRUTH-INVENTORY.md`).

| version | what it needs |
|---|---|
| v2.80 advice quality | raters who are working photographers and not the author |
| v2.83 personalisation | corrections spanning at least two shoots |
| v2.88 accuracy baseline | a sample labelled before the labeller sees the verdict |
| v2.89 keep/maybe boundary | reclassifications that actually move frames between the two |
| v2.91 prompt A/B | an API budget the owner sets |

Each has its harness, its refusal guard and its tests. None will produce a figure
until a person supplies the input, and producing one synthetically would recreate
the defect v2.88 exists to prevent.
