"""v3.88 — ONNX models built by tests must load in the runtime CI installs.

``onnx.helper.make_model`` stamps the IR version of whichever ``onnx`` is
installed, and ``onnx`` and ``onnxruntime`` release on separate schedules.
CI resolves both freely: on 2026-09-21 it picked up ``onnx`` 1.23 (IR 14)
beside ``onnxruntime`` 1.30 (max IR 13), and the scheduled run went red for
nine days on a model three nodes long.  Locally ``onnx`` 1.21 wrote IR 13,
so nothing here saw it.

One sibling test already pinned ``ir_version = 9`` by hand; the other did
not, which is the whole story.  So there is one builder, and
``tests/test_onnx_test_models.py`` fails any test that calls ``make_model``
itself.

IR 9 is what onnxruntime 1.17 — the floor in ``pyproject.toml`` — reads,
and every later runtime reads it too.
"""

from __future__ import annotations

# The IR version every test-built model carries.  Must not exceed what the
# oldest supported onnxruntime (pyproject: onnxruntime>=1.17) can load.
TEST_MODEL_IR_VERSION = 9


def build_model(graph, *, opset: int = 13):
    """``helper.make_model`` with the IR version pinned for the runtime."""
    from onnx import helper

    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", opset)])
    model.ir_version = TEST_MODEL_IR_VERSION
    return model
