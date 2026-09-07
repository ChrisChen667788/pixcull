"""v3.33 / v3.34 / v3.35 — making the owner's three remaining asks cheap.

None of these closes by an agent deciding it is close enough.  Each is
the work of turning "we need a human" into a specific, bounded request.
"""
import inspect
import tempfile
from pathlib import Path

from pixcull.scoring.personal_learn import (
    MIN_PER_VERTICAL, Example, readiness,
)


def _code_only(mod_or_fn) -> str:
    """Source with docstrings stripped.

    The fifth time across these blocks that a guard was satisfied by the
    explanation instead of the code: `strip_effect` says "no HTTP client
    of any kind" in its own docstring, and a substring search for `http`
    found the promise.
    """
    import ast
    tree = ast.parse(inspect.getsource(mod_or_fn))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            node.value.value = ""
    return ast.unparse(tree)


def _rows(n, vertical):
    return [Example({"technical": 4}, "keep", vertical=vertical)
            for _ in range(n)]


# -- v3.33 ------------------------------------------------------------

def test_it_says_how_many_more_not_just_that_it_refused():
    """"Refused" does not tell a photographer whether they are twelve
    corrections away or two hundred, and nobody labels for an afternoon
    against an unknown target."""
    got = readiness(_rows(22, "wedding") + _rows(31, "wildlife"))
    assert got["ready"] is False
    assert got["corrections_to_unblock"] == MIN_PER_VERTICAL - 22


def test_it_counts_the_cheapest_route_not_every_vertical():
    """Two eligible verticals is the bar. Finishing all four when two
    would do is a worse afternoon for the same result."""
    got = readiness(_rows(29, "a") + _rows(29, "b") + _rows(1, "c")
                    + _rows(1, "d"))
    assert got["corrections_to_unblock"] == 2


def test_already_ready_asks_for_nothing():
    got = readiness(_rows(MIN_PER_VERTICAL, "a") + _rows(MIN_PER_VERTICAL, "b"))
    assert got["ready"] and got["corrections_to_unblock"] == 0


def test_unlabelled_corrections_are_counted_apart():
    """They are not short of anything. Nobody recorded which shoot they
    came from, and labelling more of the same will not help."""
    got = readiness(_rows(5, "wedding") + [Example({}, "keep")] * 7)
    assert got["unlabelled"] == 7
    assert "" not in got["verticals"]


# -- v3.34 ------------------------------------------------------------

def test_the_strip_measurement_is_local_and_opt_in(monkeypatch):
    monkeypatch.delenv("PIXCULL_MEASURE_STRIP", raising=False)
    """Instrumenting a photographer to measure them is a different act
    from instrumenting a model."""
    from pixcull import strip_effect as SE
    assert SE.enabled() is False
    code = _code_only(SE).lower()
    for leak in ("requests", "urllib", "http", "post(", "socket"):
        assert leak not in code, leak


def test_it_records_an_override_not_an_opinion(monkeypatch):
    from pixcull import strip_effect as SE
    monkeypatch.setenv(SE.ENV_FLAG, "1")
    with tempfile.TemporaryDirectory() as d:
        SE.record(d, cluster="c7", strip_open=True, overrode=True)
        SE.record(d, cluster="c8", strip_open=False, overrode=False)
        got = SE.rates(d)
        assert got["with_strip"] == {"n": 1, "overrides": 1}
        assert got["without_strip"] == {"n": 1, "overrides": 0}


def test_it_refuses_to_report_a_rate_on_one_sample(monkeypatch):
    """Two sessions is not a finding, and a percentage printed over n=1
    is how a number gets quoted later."""
    from pixcull import strip_effect as SE
    monkeypatch.setenv(SE.ENV_FLAG, "1")
    with tempfile.TemporaryDirectory() as d:
        SE.record(d, cluster="c1", strip_open=True, overrode=True)
        assert SE.rates(d)["verdict"].startswith("too few")


# -- v3.35 ------------------------------------------------------------

def test_the_catalogue_import_is_one_command_and_says_what_it_would_do():
    from pixcull import cli
    src = inspect.getsource(cli)
    assert '"import-catalog"' in src or "import_catalog" in src
    assert "--dry-run" in src


def test_the_import_cannot_write_to_the_catalogue():
    from pixcull.io import lrcat
    src = inspect.getsource(lrcat.read_labels)
    assert "mode=ro" in src
