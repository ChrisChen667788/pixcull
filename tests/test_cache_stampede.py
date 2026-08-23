"""v2.77 — a cold cache key must be loaded once, not once per caller.

The lock is deliberately not held across the loader, so a slow load does
not block readers of other keys. Until v2.77 the price of that was a
stampede: every thread that missed ran the loader. On a thumbnail server
the number of threads arriving together is however many images the
browser fetches in parallel, and _SCORES_PATH_CACHE's loader parses a
5,069-row CSV and stats every file in it.

Measured on the demo run before the fix: one caller 141 ms, eighteen
callers arriving together 3,001 ms. Duplicated CPU work under the GIL
becomes wall-clock, and that is the first page load.
"""
import threading
import time

import pytest

from pixcull.report.serve_app import _MtimeLRUCache


@pytest.fixture()
def keyfile(tmp_path):
    p = tmp_path / "k.csv"
    p.write_text("a", encoding="utf-8")
    return p


def _hammer(cache, path, loader, n=16):
    """n threads released as close to simultaneously as possible."""
    go = threading.Event()
    out: list = [None] * n
    errs: list = []

    def one(i):
        go.wait()
        try:
            out[i] = cache.get_or_load(path, loader)
        except Exception as exc:  # noqa: BLE001
            errs.append(exc)

    ts = [threading.Thread(target=one, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    go.set()
    for t in ts:
        t.join(timeout=90)
    return out, errs


def test_cold_key_is_loaded_exactly_once(keyfile):
    cache = _MtimeLRUCache()
    calls = []
    lk = threading.Lock()

    def loader():
        with lk:
            calls.append(1)
        time.sleep(0.05)          # long enough for the others to pile up
        return {"v": 1}

    out, errs = _hammer(cache, keyfile, loader, n=16)
    assert not errs
    assert len(calls) == 1, f"loader ran {len(calls)} times for one cold key"
    assert all(o == {"v": 1} for o in out)


def test_every_caller_gets_the_same_object(keyfile):
    """Not merely an equal one — callers must share the cached instance,
    or the memory saving evaporates along with the time saving."""
    cache = _MtimeLRUCache()

    def loader():
        time.sleep(0.03)
        return {"v": object()}

    out, errs = _hammer(cache, keyfile, loader, n=12)
    assert not errs
    assert len({id(o) for o in out}) == 1


def test_a_raising_loader_does_not_wedge_the_followers(keyfile):
    """The leader failing must not leave 15 threads waiting on an Event
    that is never set. Each follower falls back to loading itself, which
    is exactly the pre-v2.77 behaviour."""
    cache = _MtimeLRUCache()
    calls = []
    lk = threading.Lock()

    def loader():
        with lk:
            calls.append(1)
        time.sleep(0.02)
        raise RuntimeError("disk gone")

    started = time.perf_counter()
    _out, errs = _hammer(cache, keyfile, loader, n=8)
    elapsed = time.perf_counter() - started
    assert len(errs) == 8, "every caller should see the failure"
    assert elapsed < 30, f"followers waited out a timeout ({elapsed:.1f}s)"
    assert len(calls) >= 1


def test_a_slow_key_does_not_block_a_different_key(tmp_path):
    """The whole reason the lock is not held across the loader."""
    cache = _MtimeLRUCache()
    slow_p = tmp_path / "slow.csv"
    slow_p.write_text("s", encoding="utf-8")
    fast_p = tmp_path / "fast.csv"
    fast_p.write_text("f", encoding="utf-8")

    entered = threading.Event()

    def slow():
        entered.set()
        time.sleep(1.0)
        return "slow"

    t = threading.Thread(target=lambda: cache.get_or_load(slow_p, slow))
    t.start()
    entered.wait(timeout=10)
    began = time.perf_counter()
    assert cache.get_or_load(fast_p, lambda: "fast") == "fast"
    took = time.perf_counter() - began
    t.join(timeout=30)
    assert took < 0.5, f"a different key waited {took:.2f}s on the slow one"


def test_a_rewrite_still_busts_the_entry(keyfile):
    """Single-flight must not turn the cache into a permanent one."""
    cache = _MtimeLRUCache()
    assert cache.get_or_load(keyfile, lambda: "first") == "first"
    time.sleep(0.02)
    keyfile.write_text("bb", encoding="utf-8")
    assert cache.get_or_load(keyfile, lambda: "second") == "second"


def test_inflight_table_does_not_leak(keyfile):
    cache = _MtimeLRUCache()
    _hammer(cache, keyfile, lambda: "v", n=8)
    assert cache._inflight == {}
    try:
        cache.get_or_load(keyfile, lambda: (_ for _ in ()).throw(ValueError()))
    except ValueError:
        pass
    assert cache._inflight == {}, "a failed load left an Event behind"


def test_value_is_cached_before_followers_are_released(keyfile, monkeypatch):
    """The invariant, asserted directly rather than raced for.

    Signalling before storing sends every woken follower to a cache that
    does not have the value yet, so they all run the loader — the exact
    stampede this machinery exists to prevent, reintroduced by two
    statements in the wrong order.

    A timing test cannot catch this reliably: under the GIL the leader
    almost always reaches the store before any follower is scheduled, so
    the window is real but rarely observed. Checking the invariant at the
    moment of release is deterministic.
    """
    cache = _MtimeLRUCache()
    observed = {}
    real_set = threading.Event.set

    def spy_set(self):
        observed.setdefault(
            "cached_at_release",
            any(k[0] == str(keyfile) for k in cache._d),
        )
        return real_set(self)

    monkeypatch.setattr(threading.Event, "set", spy_set, raising=True)
    assert cache.get_or_load(keyfile, lambda: "v") == "v"
    assert observed.get("cached_at_release") is True, \
        "followers were released before the value was in the cache"
