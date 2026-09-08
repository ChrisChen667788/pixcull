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
    known = ("SKIPPED [1] tests/test_x.py:9: zeroconf not installed "
             "(pip install -e '.[sync]')\n")
    assert aud.unmatched(known) == []


def test_the_matcher_reads_a_real_pytest_report(tmp_path):
    """End to end through the CLI, on the exact line shape pytest emits."""
    r = tmp_path / "report.txt"
    r.write_text("SKIPPED [2] tests/test_a.py:1: zeroconf not installed\n"
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
