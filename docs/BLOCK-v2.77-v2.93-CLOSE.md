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

## The one thing left open — closed 2026-09-01, and it was not a regression

This section previously reported cold TTFB at 1432 ms against 1134 ms at v2.84,
with non-overlapping ranges, as a possible regression the pass had failed to
isolate. It was neither.

Measured back to back on the same machine, in the same sitting, with only the
server files swapped:

| | cold TTFB, median | range |
|---|---|---|
| v2.84's `serve_app.py` + `fallback_ledger.py` | 1410 ms | 1102–1907 |
| HEAD | 1398 ms | 1141–1739 |

Identical, with ranges that overlap almost entirely. The two figures that looked
like a 26% regression were recorded weeks apart and were **two machine loads**.

The reason the harness reads high at all: the server builds a 3 MB page while
Chromium starts up beside it, and cold TTFB is where that contention lands. By
plain HTTP with no browser running, the same build answers in **680 ms**. That
is not a defect to fix — a photographer always has a browser open — but it makes
the figure incomparable across sessions.

Two hypotheses were tested and dropped on the way: that v2.77's prewarm thread
contends with an early request (cold TTFB is ~680 ms whether the request arrives
1 s or 16 s after the port binds), and that measuring TTFB over plain HTTP inside
the harness would isolate it (it does not — the browser process is already
running by then, and it doubled the server boots per sample).

`scripts/measure_first_screen.py` now prints the spread and flags a wide one, so
the number cannot be quoted as a comparison it will not support. To compare two
builds, swap the files and re-run in one sitting.

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
