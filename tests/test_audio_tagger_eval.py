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


def test_onnxtagger_waveform_branch(tmp_path):
    """A rank-1 (waveform-in) ONNX must route through the YAMNet-style
    branch: feed the whole signal, frame the [n,classes] output by hop."""
    import numpy as np
    onnx = __import__("pytest").importorskip("onnx")
    from onnx import TensorProto, helper, numpy_helper
    from pixcull.scoring.audio_tagger import OnnxTagger

    # tiny model: waveform[N] → scores[2,3]; output depends on input via a
    # zero-multiply (so the declared waveform input is genuinely consumed).
    probs = numpy_helper.from_array(
        np.array([[0.9, 0.05, 0.05], [0.9, 0.05, 0.05]], np.float32), "probs")
    zero = numpy_helper.from_array(np.array(0.0, np.float32), "zero")
    g = helper.make_graph(
        [helper.make_node("ReduceSum", ["waveform"], ["s"], keepdims=0),
         helper.make_node("Mul", ["s", "zero"], ["z"]),
         helper.make_node("Add", ["probs", "z"], ["scores"])],
        "wav",
        [helper.make_tensor_value_info("waveform", TensorProto.FLOAT, [None])],
        [helper.make_tensor_value_info("scores", TensorProto.FLOAT, [None, 3])],
        [probs, zero])
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 13)])
    mp = tmp_path / "wav_model.onnx"
    onnx.save(m, str(mp))
    (tmp_path / "wav_model.onnx.labels.json").write_text(
        '["Laughter", "Applause", "Music"]')

    tagger = OnnxTagger(model_path=str(mp))
    if not tagger.available():            # onnxruntime missing → skip
        __import__("pytest").skip("onnxruntime unavailable")
    events = tagger.tag(np.zeros(16000, dtype=np.float32), sr=16000)
    assert events and all(e.kind == "laughter" for e in events)
    assert events[0].start_s == 0.0       # frame times by hop, not [N,frame]
