"""v2.1-P0-1 — tests for pixcull.scoring.audio_tagger."""

from __future__ import annotations

import json

import numpy as np
import pytest

from pixcull.scoring import audio_tagger as T

SR = 16000


def _laughter(seconds=4):
    t = np.arange(int(seconds * SR)) / SR
    rng = np.random.default_rng(1)
    mod = 0.5 * (1 + np.sin(2 * np.pi * 5 * t))
    harm = sum(np.sin(2 * np.pi * 180 * k * t) / k for k in (1, 2, 3, 4, 5))
    return mod * (0.8 * harm + 0.4 * rng.standard_normal(t.size)) * 0.25


# --------------------------------------------------------------------------
# pure helpers
# --------------------------------------------------------------------------

def test_map_label_to_kind():
    assert T.map_label_to_kind("Laughter") == "laughter"
    assert T.map_label_to_kind("Giggle, snicker") == "laughter"
    assert T.map_label_to_kind("Applause") == "applause"
    assert T.map_label_to_kind("Cheering") == "applause"
    assert T.map_label_to_kind("Music") == "music"
    assert T.map_label_to_kind("Speech") is None
    assert T.map_label_to_kind("") is None


def test_calibrate_softens_toward_half():
    assert T.calibrate_confidence(1.0, temperature=2.0) == pytest.approx(0.75)
    assert T.calibrate_confidence(0.5, temperature=2.0) == pytest.approx(0.5)
    assert T.calibrate_confidence(0.9, temperature=1.0) == pytest.approx(0.9)  # identity
    # T>1 reduces an over-confident score.
    assert T.calibrate_confidence(0.95, temperature=1.5) < 0.95


def test_probs_to_events_basic():
    # 10 frames, classes [speech, laughter, music]; laughter high in frames 2-6.
    n = 10
    probs = np.zeros((n, 3))
    probs[:, 0] = 0.3                      # speech (ignored)
    probs[2:7, 1] = 0.9                    # laughter run
    times = [i * 0.5 for i in range(n)]
    evs = T.probs_to_events(probs, times, ["speech", "laughter", "music"],
                            hop_s=0.5, thresh=0.5, min_dur_s=0.6)
    assert len(evs) == 1
    assert evs[0].kind == "laughter"
    assert evs[0].start_s == 1.0 and evs[0].end_s == pytest.approx(3.5)
    assert 0.0 < evs[0].confidence <= 1.0


def test_probs_to_events_min_duration_filters():
    probs = np.zeros((4, 3)); probs[1, 1] = 0.9   # single laughter frame
    evs = T.probs_to_events(probs, [0, 0.5, 1.0, 1.5],
                            ["s", "laughter", "m"], hop_s=0.5, min_dur_s=1.0)
    assert evs == []


def test_probs_to_events_empty():
    assert T.probs_to_events(np.zeros((0, 3)), [], ["a", "b", "c"],
                             hop_s=0.5) == []


# --------------------------------------------------------------------------
# v2.4-P1-3 — per-kind threshold calibration
# --------------------------------------------------------------------------

def test_probs_to_events_per_kind_threshold():
    n = 6
    probs = np.zeros((n, 3))
    probs[1:5, 0] = 0.4                    # laughter run @ 0.4
    probs[1:5, 1] = 0.4                    # applause run @ 0.4
    times = [i * 0.5 for i in range(n)]
    labels = ["laughter", "applause", "music"]
    evs = T.probs_to_events(probs, times, labels, hop_s=0.5,
                            thresh={"laughter": 0.3, "applause": 0.5},
                            min_dur_s=0.6)
    kinds = {e.kind for e in evs}
    assert "laughter" in kinds            # 0.4 > 0.3 → fires
    assert "applause" not in kinds        # 0.4 < 0.5 → suppressed
    # A kind absent from the mapping falls back to the 0.5 default.
    probs2 = np.zeros((n, 3)); probs2[1:5, 2] = 0.6
    evs2 = T.probs_to_events(probs2, times, labels, hop_s=0.5,
                             thresh={"laughter": 0.3}, min_dur_s=0.6)
    assert any(e.kind == "music" for e in evs2)   # 0.6 > 0.5 default


def test_best_threshold_recovers_recall():
    # 4 positives [0.1,0.2,0.3,0.6], 2 negatives [0.0,0.05]. At 0.5 only 1/4
    # positives caught (recall .25); at 0.05 all 4 and no negative leaks
    # (precision 1) → F1-best is the low, recall-recovering threshold.
    scores = [0.1, 0.2, 0.3, 0.6, 0.0, 0.05]
    truth = [True, True, True, True, False, False]
    thr, f1 = T.best_threshold(truth, lambda t: [s > t for s in scores],
                               grid=[0.05, 0.25, 0.5, 0.75])
    assert thr == 0.05
    assert f1 == pytest.approx(1.0)


def test_best_threshold_tie_breaks_toward_recall():
    # both grid points score F1=1 → the smaller (higher-recall) one wins.
    thr, f1 = T.best_threshold([True, True],
                               lambda t: [s > t for s in (0.4, 0.6)],
                               grid=[0.3, 0.1])
    assert thr == 0.1 and f1 == pytest.approx(1.0)


def test_best_threshold_degenerate():
    assert T.best_threshold([], lambda t: [], grid=[0.5]) == (0.5, 0.0)
    assert T.best_threshold([False], lambda t: [False], grid=[]) == (0.5, 0.0)


def test_onnx_thresholds_packaged_default(tmp_path):
    # No per-model sidecar → the packaged calibrated default loads.
    tg = T.OnnxTagger(model_path=str(tmp_path / "nope.onnx"))
    th = tg._thresholds()
    assert isinstance(th, dict)
    assert th.get("laughter") == pytest.approx(0.05)


def test_onnx_thresholds_sidecar_overrides(tmp_path):
    model = tmp_path / "m.onnx"; model.write_bytes(b"x")
    (tmp_path / "m.onnx.thresholds.json").write_text(
        json.dumps({"laughter": 0.2, "applause": 0.4}))
    tg = T.OnnxTagger(model_path=str(model))
    assert tg._thresholds() == {"laughter": 0.2, "applause": 0.4}


# --------------------------------------------------------------------------
# HeuristicTagger (always available)
# --------------------------------------------------------------------------

def test_heuristic_tagger_available_and_tags():
    tg = T.HeuristicTagger()
    assert tg.available() is True
    assert tg.name == "heuristic-dsp"
    evs = tg.tag(_laughter(), SR)
    assert any(e.kind == "laughter" for e in evs)


# --------------------------------------------------------------------------
# OnnxTagger availability / fallback
# --------------------------------------------------------------------------

def test_onnx_tagger_unavailable_without_model(tmp_path):
    tg = T.OnnxTagger(model_path=str(tmp_path / "nope.onnx"))
    assert tg.available() is False
    assert tg.tag(_laughter(), SR) == []


def test_get_tagger_falls_back_to_heuristic(monkeypatch):
    # No model on the search path ⇒ heuristic.
    monkeypatch.setattr(T, "find_model", lambda: None)
    tg = T.get_tagger()
    assert isinstance(tg, T.HeuristicTagger)


def test_find_model_none(monkeypatch):
    monkeypatch.setattr(T, "_MODEL_SEARCH", ["", "/no/such/model.onnx"])
    assert T.find_model() is None


def test_tag_audio_default_is_heuristic(monkeypatch):
    monkeypatch.setattr(T, "find_model", lambda: None)
    evs = T.tag_audio(_laughter(), SR)
    assert any(e.kind == "laughter" for e in evs)


# --------------------------------------------------------------------------
# OnnxTagger end-to-end with a tiny synthetic ONNX (proves the pipeline)
# --------------------------------------------------------------------------

def test_onnx_tagger_end_to_end(tmp_path):
    onnx = pytest.importorskip("onnx")
    from onnx import helper, TensorProto
    import numpy as _np
    frame_len = 16000
    # Y = Sigmoid(MatMul(X[N,frame_len], W[frame_len,3]=0) + B[-2,+2,-2])
    # → constant per-frame probs ≈ [0.12, 0.88, 0.12] (laughter high).
    W = helper.make_tensor("W", TensorProto.FLOAT, [frame_len, 3],
                           _np.zeros(frame_len * 3, dtype=_np.float32))
    B = helper.make_tensor("B", TensorProto.FLOAT, [3],
                           _np.array([-2, 2, -2], dtype=_np.float32))
    nodes = [
        helper.make_node("MatMul", ["X", "W"], ["mm"]),
        helper.make_node("Add", ["mm", "B"], ["logits"]),
        helper.make_node("Sigmoid", ["logits"], ["Y"]),
    ]
    graph = helper.make_graph(
        nodes, "tagger",
        [helper.make_tensor_value_info("X", TensorProto.FLOAT, ["N", frame_len])],
        [helper.make_tensor_value_info("Y", TensorProto.FLOAT, ["N", 3])],
        initializer=[W, B])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 9
    mp = tmp_path / "audio_tagger.onnx"
    onnx.save(model, str(mp))
    (tmp_path / "audio_tagger.onnx.labels.json").write_text(
        json.dumps(["speech", "laughter", "music"]))

    tg = T.OnnxTagger(model_path=str(mp), frame_s=1.0, hop_s=1.0)
    assert tg.available() is True
    evs = tg.tag(_laughter(seconds=3), SR)
    assert evs and all(e.kind == "laughter" for e in evs)
    assert evs[0].confidence > 0.0
