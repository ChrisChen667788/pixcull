# First-screen render — the harness, and what has already been ruled out

`scripts/measure_first_screen.py` is the acceptance harness. Every claim about
render speed in this repository has to come from it or from something at least
as careful.

## The metric

**First-screen ready**: the moment every image intersecting the initial
1440×900 viewport has arrived.

Not LCP. On a lazy-loading gallery LCP keeps moving as more images paint below
the fold, so it measures when the last large image landed rather than when the
photographer can start working — two consecutive readings on an unchanged page
differed by 900 ms.

**Cold means the server restarts.** Anything else measures the in-process results
cache. That is how "1.8 seconds" was believed for several versions while the
first open actually took 3.4.

**The port is read back from the banner, never assumed.** `_pick_port` falls back
silently when the requested port cannot be bound, and a SIGKILLed predecessor
leaves the socket in TIME_WAIT long enough for that to happen routinely. Polling
the requested port then reports "server did not come up" about a server that came
up perfectly well somewhere else.

## Where it stands

Measured on a 5,069-row run, after v2.77 and v2.78:

| | cold | warm |
|---|---|---|
| TTFB | 1134 ms | 61 ms |
| load | 1439 ms | 316 ms |
| **first-screen ready** | **1959 ms** | **798 ms** |
| long tasks | 386 ms | 370 ms |

Cold was 3386 ms before v2.77.

## Ruled out, with numbers — do not re-litigate without new evidence

**The 3.2 MB payload.** 2.33 MB of it is one JSON literal. Deleting it entirely
saves 29 ms of a ~900 ms warm first screen. The first probe said 2.3 ms and was
wrong by 13×: the timer sat *inside* the script it was timing, so V8 had already
pre-parsed the whole thing before the clock started.

**gzip.** The page compresses 7.6×. On localhost the download is 11 ms either
way. Real for remote access over a network, which is a different metric and its
own version.

**Over-fetching images.** 107 image requests are issued for 12 visible
thumbnails. Blocking the 95 invisible ones — by URL, identified from an
unblocked run first — made first-screen ready *worse*: 794 ms → 851 ms across
three samples each. The first attempt at this experiment blocked by request
order instead of by URL, left 0 of 12 viewport images painted, and produced a
number that measured nothing; that is why the URLs are pinned first.

**Lazy loading on viewport images.** Forcing `loading=eager` and
`fetchpriority=high` on every image intersecting the viewport: 813 ms → 822 ms.
Noise.

**The duplicate image requests.** Every URL is fetched exactly twice when
hydration rebuilds the grid — 172 requests, 86 unique. All duplicates are
memory-cache hits and the second wave begins after first-screen ready. Real
waste, wrong metric.

## Corrected by v2.85 — the warm path was NOT closed

Everything above the line was measured correctly and concluded wrongly.

The viewport thumbnails were being requested **twice**: background
hydration ends with a full `render()`, which tore out the first hundred
cards and rebuilt them identically. First-screen ready takes the *later*
`responseEnd`, so it was reporting the second fetch.

Every experiment in the section above was therefore probing one layer
below the cause. "Blocking the invisible images does not help" is true
and irrelevant; "a cached thumbnail is served in 2.5 ms and takes 239 ms
in the browser" was the duplicate arriving late, not contention.

  first-screen ready, warm    798 ms -> 359 ms
  image requests             107 -> 55  (54 duplicates -> 2)
  long tasks after 600 ms    125 ms -> 67 ms

The refutations above still stand as refutations — payload size, gzip,
over-fetch and lazy loading really are not levers. What does not stand
is the conclusion drawn from them, which was that nothing was left. A
set of correct negative results is not a positive result about the
whole.

## What is actually left

Of 2170 ms of main-thread work in the load window, our own JavaScript is 82 ms,
layout 167 ms, style recalc 123 ms. The rest is paint, image decode and
compositing inside the browser. After v2.78 removed 742 ms of style recalc,
there is no remaining lever on the warm path that this repository controls.

A cached thumbnail is served in 2.5 ms measured serially, and takes 239 ms in
the browser during load — but blocking the other 95 requests does not help, so
the delay is client-side scheduling rather than server contention.

**Warm first-screen is therefore closed at ~800 ms and cold is the remaining
target.** Shipping a change whose saving sits inside the noise band would be
worse than shipping nothing, because it would be cited later as a win.

## Cold TTFB is only comparable within one invocation

The server builds a 3 MB page while Chromium starts up on the same machine.
Measured on this host: **680 ms** by plain HTTP with no browser running, **~1400 ms**
through the harness, on an identical build.

A v2.84 reading of 1134 ms and a v2.95 reading of 1432 ms were recorded weeks
apart, looked like a regression, and were two machine loads — re-measured back to
back with only the server files swapped, v2.84 gives 1410 ms and HEAD gives
1398 ms. The harness now flags a wide spread for exactly this reason. To compare
two builds, swap and re-run in one sitting; never quote a cold figure from a
previous session.

Warm TTFB does not have this problem — it varies by about 3%.

## A caveat about this measurement

`firstImgStart` was 313 ms in one session and 808 ms in another on the same
build, because which thumbnails land in the viewport depends on grid reflow.
Single samples of that field are not usable. First-screen ready itself is
stable to within about 60 ms across samples.
