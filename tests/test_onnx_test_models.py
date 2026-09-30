"""v3.88 — every ONNX model a test builds goes through one builder.

Two tests built ONNX models by hand.  One pinned ``ir_version``; the other
took the default, which is whatever IR the installed ``onnx`` writes.  When
CI resolved ``onnx`` 1.23 (IR 14) beside ``onnxruntime`` 1.30 (max IR 13)
the second one went red on the scheduled run and stayed red for nine days.
See ``tests/_onnx_models.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests._onnx_models import TEST_MODEL_IR_VERSION, build_model

TESTS = Path(__file__).parent
BUILDER = TESTS / "_onnx_models.py"


def _make_model_calls(path: Path) -> list[int]:
    """Line numbers of calls to anything named ``make_model``.

    Parsed rather than grepped: a comment or a docstring that mentions the
    name must not count, and ``helper.make_model``, ``onnx.helper.make_model``
    and a bare imported ``make_model`` all must.
    """
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else (
            fn.id if isinstance(fn, ast.Name) else None)
        if name == "make_model":
            lines.append(node.lineno)
    return lines


def test_no_test_builds_an_onnx_model_by_hand():
    offenders = []
    for path in sorted(TESTS.rglob("*.py")):
        if path == BUILDER:
            continue
        for line in _make_model_calls(path):
            offenders.append(f"{path.relative_to(TESTS.parent)}:{line}")
    assert not offenders, (
        "build ONNX test models with tests._onnx_models.build_model — a bare "
        "make_model stamps the installed onnx's IR version, which the "
        "installed onnxruntime may refuse:\n  " + "\n  ".join(offenders))


def test_the_scan_sees_the_shapes_it_must(tmp_path):
    """The gate above passes trivially if the scanner finds nothing."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        "from onnx import helper\n"
        "from onnx.helper import make_model\n"
        "import onnx\n"
        "# make_model(g) in a comment does not count\n"
        "'''nor make_model(g) in a docstring'''\n"
        "a = helper.make_model(g)\n"
        "b = onnx.helper.make_model(g)\n"
        "c = make_model(g)\n", "utf-8")
    assert _make_model_calls(probe) == [6, 7, 8]


def test_the_builder_pins_an_ir_the_runtime_loads(tmp_path):
    onnx = pytest.importorskip("onnx")
    ort = pytest.importorskip("onnxruntime")
    from onnx import TensorProto, helper

    g = helper.make_graph(
        [helper.make_node("Identity", ["x"], ["y"])], "id",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1])],
        [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1])])
    m = build_model(g)
    assert m.ir_version == TEST_MODEL_IR_VERSION
    mp = tmp_path / "id.onnx"
    onnx.save(m, str(mp))
    ort.InferenceSession(str(mp), providers=["CPUExecutionProvider"])
