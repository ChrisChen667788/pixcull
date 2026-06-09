"""v2.5-P0-1 — unit tests for the helpers extracted from serve_demo.py.

These were previously buried in the 18k-line serve_demo monolith with no
direct coverage; lifting them into pixcull.report.serve_util lets them be
tested in isolation (the point of the split).
"""
from __future__ import annotations

import math

from pixcull.report.serve_util import (
    _clean_csv_string,
    _f,
    _html_escape,
    _opt_int,
    _parse_int_list,
    _safe_dumps,
    _scrub_nan,
)


def test_scrub_nan_replaces_nan_and_inf():
    assert _scrub_nan(float("nan")) is None
    assert _scrub_nan(float("inf")) is None
    assert _scrub_nan(1.5) == 1.5
    assert _scrub_nan({"a": float("nan"), "b": [float("inf"), 2]}) == {
        "a": None, "b": [None, 2]}
    assert _scrub_nan("x") == "x"


def test_safe_dumps_never_emits_nan_token():
    out = _safe_dumps({"a": float("nan"), "b": 1.5})
    assert "NaN" not in out and "Infinity" not in out
    assert out == '{"a": null, "b": 1.5}'
    # non-ascii passes through (ensure_ascii defaults False)
    assert "连拍" in _safe_dumps({"k": "连拍"})


def test_html_escape():
    assert _html_escape('<a href="x">&\'') == "&lt;a href=&quot;x&quot;&gt;&amp;&#39;"
    assert _html_escape(None) == ""
    assert _html_escape(42) == "42"


def test_f_coerce():
    assert _f("3.14159") == 3.142          # rounds to 3dp
    assert _f(2) == 2.0
    assert _f("nan") is None
    assert _f("") is None
    assert _f(None) is None
    assert _f("abc") is None


def test_clean_csv_string():
    assert _clean_csv_string("nan") == ""
    assert _clean_csv_string(float("nan")) == ""
    assert _clean_csv_string(None) == ""
    assert _clean_csv_string("  x  ") == "x"
    assert _clean_csv_string(0) == "0"


def test_opt_int():
    assert _opt_int("7") == 7
    assert _opt_int("7.9") == 7
    assert _opt_int("nan") is None
    assert _opt_int(float("nan")) is None
    assert _opt_int(None) is None
    assert _opt_int("") is None


def test_parse_int_list():
    assert _parse_int_list("[0, 1, -1]") == [0, 1, -1]
    assert _parse_int_list([0, 1, None, 2]) == [0, 1, 2]
    assert _parse_int_list("nan") == []
    assert _parse_int_list("[]") == []
    assert _parse_int_list(None) == []
    assert _parse_int_list("garbage") == []
