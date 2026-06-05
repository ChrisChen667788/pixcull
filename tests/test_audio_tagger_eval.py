"""v2.2-P0-1 — tests for the audio-tagger eval primitive (binary_prf)."""
from pixcull.scoring.eval_metrics import binary_prf


def test_binary_prf_perfect():
    r = binary_prf([True, True, False], [True, True, False])
    assert r["precision"] == 1.0 and r["recall"] == 1.0 and r["f1"] == 1.0
    assert r["tp"] == 2 and r["fp"] == 0 and r["fn"] == 0 and r["n_pos"] == 2


def test_binary_prf_all_missed():
    r = binary_prf([True, True], [False, False])
    assert r["recall"] == 0.0 and r["f1"] == 0.0
    assert r["fn"] == 2 and r["tp"] == 0 and r["n_pos"] == 2


def test_binary_prf_all_false_positive():
    r = binary_prf([False, False], [True, True])
    assert r["precision"] == 0.0 and r["fp"] == 2 and r["n_pos"] == 0


def test_binary_prf_mixed():
    r = binary_prf([True, True, False, False], [True, False, True, False])
    assert r["tp"] == 1 and r["fp"] == 1 and r["fn"] == 1
    assert abs(r["precision"] - 0.5) < 1e-9
    assert abs(r["recall"] - 0.5) < 1e-9
    assert abs(r["f1"] - 0.5) < 1e-9


def test_binary_prf_empty():
    r = binary_prf([], [])
    assert r["f1"] == 0.0 and r["tp"] == 0 and r["n_pos"] == 0
