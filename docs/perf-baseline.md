# PixCull performance baseline

This doc captures the **target numbers** that v0.7-P0-3 hardens
against, so future iterations can A/B compare and notice regressions
early. Numbers are taken on a 2024 MacBook Pro M3 Pro 18GB unless
otherwise noted.

## Target metrics

| Surface | Target | Tested at |
|---|---|---|
| `/results` page render (1k rows) | < 800 ms first paint | manual + 5k smoke |
| `/results` page render (5k rows) | < 2.5 s first paint, ≤ 50 cards materialized ahead | manual |
| `/results` page render (5k rows) | < 6 GB peak RSS (server) | `Activity Monitor` |
| Grid scroll (5k rows) | 60 fps sustained, no jank | DevTools Perf |
| Bucket DnD reorder (50 buckets) | < 16 ms per drop | manual |
| Thumb request (1280×853 JPEG) | < 80 ms cache miss, < 5 ms cache hit | curl loop |
| `/admin/perf.json` | < 50 ms (5 runs in memory) | curl loop |
| MutationObserver fires per render | ≤ 1 per 80 ms (throttled) | `window._pcBucketsObsFn._fires` |

## Knobs to tune

### IntersectionObserver `rootMargin`
Lives in `pixcull/report/templates/results.html`, function
`_adaptiveRootMargin(n)`. Curve:

| rows | rootMargin |
|---|---|
| < 1000 | `200% 0px 200% 0px` (snappy default — no scroll-empty) |
| 1000-3000 | `100% 0px 100% 0px` |
| 3000-5000 | `60% 0px 60% 0px` |
| > 5000 | `40% 0px 40% 0px` |

If users at 5k+ report empty cards on fast scroll, bump the >5000
bucket to 60%. If 1k users report mem pressure, drop the <1000
bucket to 150%.

### MutationObserver throttle
`_bucketsObserver` callback wrapped in `_throttle(fn, 80)`.

| grid size | callback fires/s observed (before / after) |
|---|---|
| 1k rows, single filter change | ~80 / ~12 |
| 5k rows, single filter change | ~340 / ~12 |
| 5k rows, scroll-to-end | ~1100 / ~12 |

If a future feature needs faster reactions to grid mutation,
lower the throttle ms — but watch the observed-fires/s above.

### `PixCullStorage` quota fallback
Wraps `localStorage` with an in-memory fallback when
QuotaExceededError fires. Currently in use by:

- `_BUCKETS_KEY` (drag-deliverable buckets)
- `_BUCKETS_ORDER_KEY` (bucket order)
- `_INSPECTOR_KEY` (LR Develop-style section fold state)

Other writers still use `localStorage` directly. To migrate, swap
`localStorage.setItem(k, v)` → `PixCullStorage.set(k, v)` and
`localStorage.getItem(k)` → `PixCullStorage.get(k)`.

## How to measure

### Synthetic 5k row smoke (pytest)
```sh
pytest tests/test_5k_scale.py -v
```
Should finish under 2s. Catches CSV parse regressions.

### Live render with `/admin/perf` dashboard
```sh
PYTHONPATH=. python scripts/serve_demo.py --port 8989
open http://127.0.0.1:8989/admin/perf
# Now upload a real 5k folder via /; watch RSS + disk-per-run grow
```

### DevTools recipe
1. Open `/results/<run>` in Chrome with DevTools → Performance tab
2. Click ⚡ Record
3. Scroll to the bottom of a 5k-row grid
4. Stop recording — look for:
   - **FPS** stays ≥ 55 sustained
   - **Long Tasks** count ≤ 4
   - **Heap** grows < 2× start
5. If any of these fail, the regression is real — fix before merge.

### Bucket DnD micro-bench
```js
// In DevTools console on a /results page with > 10 buckets:
const t0 = performance.now();
for (let i = 0; i < 100; i++) {
  document.querySelector(".bk-item").dispatchEvent(new DragEvent("dragstart"));
  document.querySelector(".bk-item:nth-child(2)").dispatchEvent(new DragEvent("drop"));
}
console.log("100 drops:", performance.now() - t0, "ms");
```
Should be < 1600 ms (16 ms per drop budget × 100).

## v0.7-P0-3 baseline (2026-05-23, M3 Pro 18GB)

| metric | value |
|---|---|
| `_bucketsObserver` callback fires (5k row scroll) | 12 / s ✓ |
| `_adaptiveRootMargin(5000)` | `"40% 0px 40% 0px"` ✓ |
| `pytest tests/test_5k_scale.py` | 0.9s wall ✓ |
| `/admin/perf.json` for 1 active run | 23ms ✓ |

These numbers are the starting point; future iterations can quote
them as deltas. If you find yourself adding a measurement that this
doc doesn't cover, please PR an extra row.
