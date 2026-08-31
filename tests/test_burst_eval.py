"""v2.90 — 97.6% of frames are "burst peaks", and the number is empty.

Counting `is_burst_peak` across the labelled set gives 405 of 415. A
cluster of one photograph has one peak by arithmetic. Asked only where a
choice was actually made:

    batch_1  81 clusters,  2 real bursts
    batch_2  80 clusters,  2
    batch_3  78 clusters,  3
    batch_4  83 clusters,  0
    batch_5  83 clusters,  0

Seven real decisions across 415 photographs. Every rival claims burst
grouping; PixCull still has no number for its own, and this version
explains why rather than inventing one.
"""
import pytest

from pixcull.scoring.burst_eval import MIN_REAL_BURSTS, evaluate_peaks, inventory


def _burst(cid, n, peak_at=0):
    return [{"filename": f"{cid}-{i}.jpg", "cluster_id": cid,
             "is_burst_peak": "True" if i == peak_at else "False"}
            for i in range(n)]


def _singletons(k, start=100):
    return [{"filename": f"s{i}.jpg", "cluster_id": f"s{i}",
             "is_burst_peak": "True"} for i in range(start, start + k)]


def test_a_single_photograph_is_not_a_burst():
    """The whole point. It is its own peak by arithmetic, and counting
    it is what turns seven decisions into 97.6%."""
    inv = inventory(_singletons(50))
    assert inv.clusters == 50
    assert inv.singletons == 50
    assert inv.real_bursts == 0
    assert inv.decisions == 0
    assert inv.flagged_peaks == 50, "the rows really are flagged; that is the trap"


def test_only_multi_frame_clusters_count_as_decisions():
    rows = _singletons(79) + _burst("b1", 3) + _burst("b2", 2)
    inv = inventory(rows)
    assert inv.real_bursts == 2
    assert inv.frames_in_real_bursts == 5
    assert inv.peaks_in_real_bursts == 2


def test_a_burst_with_two_heroes_is_reported():
    """The collapse view shows one frame per burst. Two peaks means it
    shows two, and none means the burst disappears from the view."""
    rows = _burst("b", 4)
    rows[2]["is_burst_peak"] = "True"
    inv = inventory(rows)
    assert inv.malformed and "2 peaks" in inv.malformed[0]


def test_a_burst_with_no_hero_is_reported():
    rows = _burst("b", 3, peak_at=-1)
    inv = inventory(rows)
    assert inv.malformed and "0 peaks" in inv.malformed[0]


def test_rows_with_no_cluster_are_ignored():
    inv = inventory([{"filename": "a.jpg", "cluster_id": "",
                      "is_burst_peak": "True"}])
    assert inv.clusters == 0


def test_too_few_judged_bursts_is_refused():
    rows = _singletons(200) + _burst("b1", 3)
    r = evaluate_peaks(rows, {"b1": "b1-0.jpg"})
    assert r["refused"]
    assert "below the floor" in r["refused"]
    assert "agreement" not in r, \
        "a refused evaluation must not carry a figure a caller can print"


def test_unjudged_bursts_are_not_counted_as_agreement():
    """A burst nobody looked at is not evidence. Treating it as a hit is
    exactly how a peak picker scores 97.6%."""
    rows = []
    truth = {}
    for i in range(MIN_REAL_BURSTS):
        rows += _burst(f"b{i}", 3)
        truth[f"b{i}"] = f"b{i}-0.jpg"
    rows += _burst("unjudged", 3)            # not in truth
    r = evaluate_peaks(rows, truth)
    assert r["n_bursts"] == MIN_REAL_BURSTS
    assert r["agreement"] == 1.0


def test_a_wrong_peak_lowers_the_figure():
    rows, truth = [], {}
    for i in range(MIN_REAL_BURSTS):
        rows += _burst(f"b{i}", 3, peak_at=0)
        truth[f"b{i}"] = f"b{i}-0.jpg"
    truth["b0"] = "b0-2.jpg"                 # the human picked another frame
    r = evaluate_peaks(rows, truth)
    assert r["agreement"] == pytest.approx((MIN_REAL_BURSTS - 1) / MIN_REAL_BURSTS)


def test_singletons_in_the_truth_map_do_not_pad_the_denominator():
    rows, truth = _singletons(80), {}
    for i in range(80, 80 + MIN_REAL_BURSTS):
        rows += _burst(f"b{i}", 2)
        truth[f"b{i}"] = f"b{i}-0.jpg"
    for s in rows[:10]:
        truth[s["cluster_id"]] = s["filename"]   # judged singletons
    r = evaluate_peaks(rows, truth)
    assert r["n_bursts"] == MIN_REAL_BURSTS
