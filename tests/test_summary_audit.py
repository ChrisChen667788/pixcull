"""v3.31 — the numbers on screen against the file on disk.

v2.95 found the run summary counting a list built during scoring while
the CSV was written from a dataframe the judge had since rewritten.  Two
sources, one stale: the console said "Keep=6" while every row in
scores.csv said cull.

That was one number.  The report renders a dozen, each computed in memory
beside a file that is the actual deliverable — the one the photographer
opens in Lightroom, hands to a client, and still has in a year.  When
they disagree, the file is right.
"""
import csv
import inspect
import tempfile
from pathlib import Path

from pixcull.report import summary_audit as SA


def _run(tmp: Path, decisions):
    out = tmp / "output"
    out.mkdir(parents=True)
    with (out / "scores.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["filename", "decision"])
        w.writeheader()
        for i, d in enumerate(decisions):
            w.writerow({"filename": f"{i:03d}.jpg", "decision": d})
    return out


def test_matching_numbers_pass():
    with tempfile.TemporaryDirectory() as d:
        out = _run(Path(d), ["keep"] * 3 + ["cull"] * 2)
        got = SA.audit({"n_total": 5, "n_keep": 3, "n_cull": 2,
                        "n_maybe": 0}, out)
        assert got["ok"] and got["mismatches"] == []


def test_the_v2_95_failure_is_caught():
    """The console said Keep=6 and every row said cull."""
    with tempfile.TemporaryDirectory() as d:
        out = _run(Path(d), ["cull"] * 6)
        got = SA.audit({"n_total": 6, "n_keep": 6, "n_cull": 0,
                        "n_maybe": 0}, out)
        assert not got["ok"]
        fields = {m["field"] for m in got["mismatches"]}
        assert {"n_keep", "n_cull"} <= fields


def test_a_mismatch_says_both_numbers():
    """"They disagree" is not actionable. Which is which is."""
    with tempfile.TemporaryDirectory() as d:
        out = _run(Path(d), ["cull"] * 4)
        m = SA.audit({"n_keep": 4}, out)["mismatches"][0]
        assert m["on_screen"] == 4 and m["in_the_file"] == 0


def test_a_new_number_nobody_classified_is_reported_as_unexamined():
    """The half that keeps this honest as the report grows. A number in
    neither dict is one nobody has thought about, and silence about it
    would read as coverage."""
    with tempfile.TemporaryDirectory() as d:
        out = _run(Path(d), ["keep"])
        got = SA.audit({"n_total": 1, "brand_new_number": 9}, out)
        assert got["unexamined"] == ["brand_new_number"]


def test_fields_that_may_drift_are_named_with_a_reason():
    """A skip list without reasons becomes the place things go to be
    forgotten."""
    assert SA.NOT_CHECKED
    for field, why in SA.NOT_CHECKED.items():
        assert why.strip(), field


def test_annotation_derived_counts_are_deliberately_not_checked():
    """They come from annotations.jsonl. Checking them against scores.csv
    would fail correctly-working software."""
    for f in ("n_human_labeled", "n_human_decided"):
        assert f in SA.NOT_CHECKED


def test_the_audit_recomputes_rather_than_reusing_the_reports_helper():
    """A shared helper between the report and its audit defeats the
    audit. That sharing is exactly how v2.95 happened."""
    src = inspect.getsource(SA)
    assert "serve_app" not in src
    assert "_build_results" not in src


def test_a_missing_csv_is_not_silently_a_pass():
    with tempfile.TemporaryDirectory() as d:
        got = SA.audit({"n_total": 5, "n_keep": 5}, Path(d))
        assert not got["ok"]
        assert got["n_rows_on_disk"] == 0


def test_string_counts_from_a_csv_compare_as_numbers():
    with tempfile.TemporaryDirectory() as d:
        out = _run(Path(d), ["keep"] * 2)
        assert SA.audit({"n_keep": "2", "n_total": "2"}, out)["ok"]


# -- reachability -----------------------------------------------------

def test_the_status_endpoint_publishes_what_the_file_says():
    src = inspect.getsource(
        __import__("pixcull.report.serve_app", fromlist=["x"]))
    assert 'view["decision_counts_on_disk"]' in src


def test_the_page_compares_the_two_sides_and_calls_it_a_fault():
    """A disagreement is not a rate. One of the two numbers is simply
    wrong, and it is the one on screen."""
    js = (Path(__file__).resolve().parent.parent / "pixcull" / "report"
          / "templates" / "src" / "modules"
          / "35-session-health.js").read_text(encoding="utf-8")
    code = "\n".join(l.split("//", 1)[0] for l in js.splitlines())
    assert "summaryFaults(view.decision_counts_on_disk)" in code
    assert "function summaryFaults" in code
