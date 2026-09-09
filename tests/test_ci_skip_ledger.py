"""v3.51 — the ledger that makes a skip a decision.

`scripts/audit_ci_skips.py` runs in CI against the report an actual run
produced. This file checks the parts that can be checked without a
runner: that the ledger is well formed, that the matcher can see a new
reason, and that CI actually invokes the auditor — a gate nobody calls
being the exact defect this whole block is about.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "tests" / "ci_skip_dispositions.tsv"


def _audit():
    spec = importlib.util.spec_from_file_location(
        "audit_ci_skips", ROOT / "scripts" / "audit_ci_skips.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_row_is_well_formed():
    aud = _audit()
    rows = aud.ledger()
    assert len(rows) >= 8, f"only {len(rows)} rows; the census was longer"
    for pattern, disp, note in rows:
        assert disp in aud.DISPOSITIONS, f"{pattern}: {disp}"
        assert len(note.split()) >= 6, f"{pattern}: the note is too thin"


def test_a_gap_has_to_name_what_closes_it():
    """"gap" is the honest answer and the one that rots. A row that says
    a thing is missing without saying what would fix it is a shrug."""
    aud = _audit()
    for pattern, disp, note in aud.ledger():
        if disp == "gap":
            assert any(w in note.lower() for w in
                       ("closed by", "closes it", "adding", "install")), (
                f"{pattern}: a gap row must name what closes it — {note}")


def test_the_matcher_sees_a_reason_nobody_has_ruled_on():
    """A census that matches everything passes for the wrong reason."""
    aud = _audit()
    report = ("SKIPPED [1] tests/test_new.py:9: a brand new reason "
              "nobody has written down\n")
    assert aud.unmatched(report) == [
        "tests/test_new.py: a brand new reason nobody has written down"]
    known = ("SKIPPED [1] tests/test_x.py:9: chromium unavailable: "
             "no browser on this runner\n")
    assert aud.unmatched(known) == []


def test_the_matcher_reads_a_real_pytest_report(tmp_path):
    """End to end through the CLI, on the exact line shape pytest emits."""
    r = tmp_path / "report.txt"
    r.write_text("SKIPPED [2] tests/test_a.py:1: smoke fixture missing\n"
                 "SKIPPED [1] tests/test_b.py:4: chromium unavailable: boom\n",
                 encoding="utf-8")
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "audit_ci_skips.py"),
                           str(r)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    r.write_text("SKIPPED [1] tests/test_c.py:1: nobody ruled on this\n",
                 encoding="utf-8")
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "audit_ci_skips.py"),
                           str(r)], capture_output=True, text=True)
    assert proc.returncode == 2
    assert "nobody ruled on this" in proc.stderr


def test_ci_actually_runs_the_auditor_on_a_report_with_reasons_in_it():
    """Two halves, and the first is useless without the second: the run
    has to print skip reasons (-rs) and something has to read them."""
    ci = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "tests.yml").read_text("utf-8"))
    steps = ci["jobs"]["pytest"]["steps"]
    scripts = {s.get("name"): "\n".join(
        l.split("#", 1)[0] for l in str(s.get("run", "")).splitlines())
        for s in steps}
    hermetic = scripts.get("Run hermetic tests", "")
    assert "-rs" in hermetic, (
        "the hermetic run does not print skip reasons, so the audit "
        "below reads an empty list and passes on nothing")
    audit = scripts.get("Audit the skips", "")
    assert "audit_ci_skips.py" in audit, "CI does not run the skip auditor"
    names = [s.get("name") for s in steps]
    assert names.index("Audit the skips") > names.index("Run hermetic tests")


# ---------------------------------------------------------------------------
# v3.61 — the ledger's blind spot: a deselected test prints no SKIPPED line.
# ---------------------------------------------------------------------------

def _pytest_invocations() -> list[str]:
    ci = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "tests.yml").read_text("utf-8"))
    out = []
    for job in ci["jobs"].values():
        for step in job.get("steps", []):
            run = "\n".join(l.split("#", 1)[0]
                            for l in str(step.get("run", "")).splitlines())
            if "pytest" in run:
                out.append(run)
    return out


def test_every_marker_used_to_exclude_tests_is_run_by_some_lane():
    """The hole v3.51 left, found while closing the last `gap` row.

    Both pytest invocations said `-m "not slow"` and no lane said
    `-m slow`, so three tests had never run in CI — one of them
    shot-boundary detection, README claim 17, which takes 0.29 seconds.
    "Slow" had stopped meaning slow and become a place things went.

    The skip auditor could not have caught it. A deselected test emits no
    SKIPPED line, so it is invisible to a census built on reading them.
    Excluding a marker is a promise that something else runs it.
    """
    import re

    invocations = _pytest_invocations()
    assert invocations, "no pytest invocation found in the workflow"

    excluded = set()
    for run in invocations:
        for m in re.finditer(r'-m\s+"not ([a-z_]+)"', run):
            excluded.add(m.group(1))

    unrun = []
    for marker in sorted(excluded):
        if not any(re.search(rf'-m\s+{marker}\b', r) for r in invocations):
            unrun.append(marker)
    assert not unrun, (
        "these markers are excluded from every run and included by none, "
        f"so the tests carrying them never execute in CI: {unrun}")


def test_the_markers_in_the_suite_are_ones_the_workflow_knows_about():
    """A marker nobody excludes runs by default and is fine. A marker
    that exists only in the suite while the workflow filters on a
    different name is a filter that matches nothing."""
    import re

    suite = set()
    for f in (ROOT / "tests").glob("test_*.py"):
        suite |= set(re.findall(r"@pytest\.mark\.([a-z_]+)",
                                f.read_text(encoding="utf-8")))
    suite -= {"parametrize", "skipif", "skip", "xfail", "usefixtures",
              "filterwarnings", "timeout"}
    runs = "\n".join(_pytest_invocations())
    for marker in sorted(suite):
        if re.search(rf'-m\s+"?not {marker}\b', runs):
            assert re.search(rf'-m\s+{marker}\b', runs), (
                f"marker {marker!r} is excluded everywhere and run nowhere")
