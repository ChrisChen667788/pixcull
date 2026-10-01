"""v3.91.1 — the lane that runs the real models has to run them.

Found by reading the log of a green run. The weekly "real-model
integration" lane finished successfully with this as its entire output:

    SKIPPED  CLIP weights not cached locally
    SKIPPED  captioning VLM not cached locally
    SKIPPED  pipeline weights not cached
    SKIPPED  ffmpeg not installed
    SKIPPED  CLIP is not in the local hub cache on this machine

Its step was named "downloads CLIP + BLIP" and downloaded nothing. Each
test is gated on the weights already being cached — right on a laptop,
since v2.40 — and a fresh runner never has them. The same five lines are
in the scheduled runs of 2026-09-14 and 2026-09-28. Three rows of
``tests/ci_skip_dispositions.tsv`` call those tests "covered elsewhere",
and this is the elsewhere.

v3.61 wrote, in this lane's own comment, that "covered elsewhere" is only
true if somewhere covers it. It checked that the lane *named* the test.
So did v3.89, about its own new test, one release ago.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

from tests import _model_gate as G

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"

#: The tests the lane exists for, and the files their gates live in.
LANE_TESTS = (
    "tests/test_semantic_search.py::test_build_search_real_clip_end_to_end",
    "tests/test_reel_caption.py::test_vlm_caption_real_model",
    "tests/test_e2e_smoke.py",
    "tests/test_runs_without_network.py::"
    "test_loading_a_cached_model_opens_no_socket",
)
GATED_FILES = ("tests/_model_gate.py", "tests/test_reel_caption.py",
               "tests/test_e2e_smoke.py", "tests/test_runs_without_network.py")


# -- the gate ----------------------------------------------------------------

def _outcome(fn) -> str:
    """What ``fn`` did: "skip", "fail" or "returned".

    Not ``pytest.raises(pytest.fail.Exception)``. A skip raised inside that
    block is not the expected exception, so it propagates — and pytest
    reports the *test* as skipped. The first version of these tests did
    exactly that: with ``absent`` broken so that it always skipped, the
    tests guarding it did not fail, they skipped. A check on whether a
    skip is masquerading as a pass must not be able to skip.
    """
    try:
        fn()
    except pytest.skip.Exception:
        return "skip"
    except pytest.fail.Exception:
        return "fail"
    return "returned"


def test_absent_weights_skip_on_a_laptop(monkeypatch):
    monkeypatch.delenv(G.REQUIRE_ENV, raising=False)
    assert _outcome(lambda: G.absent("CLIP weights not cached")) == "skip"


def test_absent_weights_fail_where_running_them_is_the_point(monkeypatch):
    monkeypatch.setenv(G.REQUIRE_ENV, "1")
    assert _outcome(lambda: G.absent("CLIP weights not cached")) == "fail"


@pytest.mark.parametrize("value", ["", "0", "true", "yes"])
def test_only_the_exact_switch_turns_a_skip_into_a_failure(monkeypatch, value):
    """A stray value in someone's shell must not fail their local run."""
    monkeypatch.setenv(G.REQUIRE_ENV, value)
    assert _outcome(lambda: G.absent("weights not cached")) == "skip"


def test_the_failure_says_what_was_missing_and_why_it_is_a_failure(monkeypatch):
    monkeypatch.setenv(G.REQUIRE_ENV, "1")
    with pytest.raises(pytest.fail.Exception) as err:
        try:
            G.absent("CLIP weights not cached locally (openai/clip)")
        except pytest.skip.Exception:            # must not escape as a skip
            raise AssertionError("absent() skipped with the switch on")
    assert "openai/clip" in str(err.value) and G.REQUIRE_ENV in str(err.value)


def test_require_model_goes_through_the_same_gate(monkeypatch):
    monkeypatch.setattr(G, "is_cached", lambda repo: False)
    call = lambda: G.require_model("some/model", lambda: None, what="X")
    monkeypatch.setenv(G.REQUIRE_ENV, "1")
    assert _outcome(call) == "fail"
    monkeypatch.delenv(G.REQUIRE_ENV)
    assert _outcome(call) == "skip"


def test_weights_that_are_here_are_loaded_either_way(monkeypatch):
    """The other side: the switch changes nothing when the model is cached."""
    monkeypatch.setattr(G, "is_cached", lambda repo: True)
    for value in ("1", ""):
        monkeypatch.setenv(G.REQUIRE_ENV, value)
        assert G.require_model("some/model", lambda: "loaded", what="X") \
            == "loaded"


def _text_of(node: ast.AST) -> str:
    """The literal text inside a string, f-string or implicit join."""
    return " ".join(c.value for c in ast.walk(node)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str))


def _bare_weight_skips(path: Path) -> list[int]:
    """``pytest.skip(...)`` / ``skipif(...)`` about missing weights, outside
    ``absent`` — each would skip in the lane that must not."""
    tree = ast.parse(path.read_text("utf-8"))
    allowed = {n for fn in ast.walk(tree)
               if isinstance(fn, ast.FunctionDef) and fn.name == "absent"
               for n in ast.walk(fn)}
    lines = []
    for c in ast.walk(tree):
        if c in allowed or not isinstance(c, ast.Call):
            continue
        name = getattr(c.func, "attr", getattr(c.func, "id", ""))
        if name not in ("skip", "skipif"):
            continue
        text = _text_of(c).lower()
        if "not cached" in text or "hub cache" in text:
            lines.append(c.lineno)
    return sorted(lines)


def test_no_weight_gate_skips_on_its_own():
    offenders = [f"{rel}:{line}" for rel in GATED_FILES
                 for line in _bare_weight_skips(ROOT / rel)]
    assert not offenders, (
        "use tests._model_gate.absent(reason): a bare skip stays a skip in "
        f"the real-model lane, which then runs nothing: {offenders}")


def test_the_scan_sees_a_bare_skip_and_a_skipif(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import pytest\n"
        "def absent(r): pytest.skip(r + ' not cached')\n"
        "def a(): pytest.skip(f'weights not cached locally ({1})')\n"
        "@pytest.mark.skipif(True, reason='CLIP is not in the local '\n"
        "                    'hub cache on this machine')\n"
        "def b(): pass\n"
        "def c(): pytest.skip('ffmpeg not installed')\n", "utf-8")
    assert _bare_weight_skips(probe) == [3, 4]


# -- the lane ----------------------------------------------------------------

def _lane() -> dict:
    jobs = yaml.safe_load(WORKFLOW.read_text("utf-8"))["jobs"]
    found = [j for j in jobs.values() if "real-model" in j.get("name", "")]
    assert len(found) == 1, "the real-model lane is missing or duplicated"
    return found[0]


def _step_index(steps: list[dict], needle: str) -> int:
    hits = [i for i, s in enumerate(steps) if needle in (s.get("run") or "")]
    assert hits, f"no step in the real-model lane runs {needle!r}"
    return hits[0]


def test_the_lane_downloads_before_it_tests():
    steps = _lane()["steps"]
    download = _step_index(steps, "from_pretrained(cls, repo)")
    tests = _step_index(steps, LANE_TESTS[0])
    assert download < tests, "the weights must be fetched before the tests"
    script = steps[download]["run"]
    for name in ("CLIP_REPO", "VLM_REPO", "facebook/dinov2-base"):
        assert name in script, f"the download step does not fetch {name}"
    assert "is_cached(repo)" in script, (
        "the download step must confirm the weights landed in the cache")


def test_the_lane_treats_missing_weights_as_a_failure():
    steps = _lane()["steps"]
    step = steps[_step_index(steps, LANE_TESTS[0])]
    assert (step.get("env") or {}).get(G.REQUIRE_ENV) == "1", (
        f"without {G.REQUIRE_ENV}=1 every gated test skips on a fresh runner "
        "and the lane is green having run nothing")
    for test in LANE_TESTS:
        assert test in step["run"], f"the lane no longer runs {test}"


def test_the_lane_has_ffmpeg_for_the_journey():
    """`-m slow tests/test_e2e_smoke.py` cuts a clip; without ffmpeg that
    half skipped too."""
    steps = _lane()["steps"]
    ffmpeg = _step_index(steps, "apt-get install -y -qq ffmpeg")
    assert ffmpeg < _step_index(steps, LANE_TESTS[0])
