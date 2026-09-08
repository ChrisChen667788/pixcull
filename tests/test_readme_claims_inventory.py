"""v3.38 — every claim in the README has a row, and the row names a file.

The sweep this version exists for. The rule "publish it even where
clean" is three blocks old now, and it exists because both defects the
previous block was built on had already survived ordinary attention.

The inventory lives in `docs/README-CLAIMS.md`. This keeps it honest:
adding a nineteenth feature to the README without saying what makes it
true, and whether anybody can reach it, fails the suite.

The third column is the one that matters. A claim can be true and
unreachable, which is this repository's signature defect and is not the
same thing as false — the sweep found exactly one of those (the rescorer
is not in the published wheel and its default path is relative to the
working directory), and it was the reachability column that surfaced it,
not the code column.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "docs" / "README-CLAIMS.md"
CLAIM_RE = re.compile(r"^(\d+)\. \*\*", re.M)
CODE_TOKEN = re.compile(r"`([A-Za-z0-9_./-]+\.(?:py|js|swift))(?:::\w+)?`")


def readme_claims() -> list[str]:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    section = text.split("## What you get today", 1)[1].split("\n## ", 1)[0]
    return CLAIM_RE.findall(section)


def inventory_rows() -> list[list[str]]:
    rows = []
    for line in INVENTORY.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells[0] in ("#", ""):
            continue
        rows.append(cells)
    return rows


def test_every_numbered_claim_has_a_row():
    numbered = {r[0] for r in inventory_rows()}
    missing = [c for c in readme_claims() if c not in numbered]
    assert not missing, (
        "these README claims have no row in docs/README-CLAIMS.md — say "
        f"what makes each true and who can reach it: {missing}")


def test_no_row_invents_a_claim_that_is_not_in_the_readme():
    """A row for a claim nobody makes is the inventory drifting into a
    feature list, which is the thing it is supposed to audit."""
    claims = set(readme_claims())
    # "2b" and friends are deliberate splits of one numbered claim.
    stray = [r[0] for r in inventory_rows()
             if r[0].rstrip("abc") not in claims]
    assert not stray, stray


def test_every_row_names_code_that_exists():
    tracked = {Path(f).name for f in subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True,
        text=True).stdout.split()}
    bad = []
    for row in inventory_rows():
        names = CODE_TOKEN.findall(row[2])
        if not names:
            bad.append(f"row {row[0]}: names no file")
            continue
        for n in names:
            if Path(n).name not in tracked:
                bad.append(f"row {row[0]}: {n} is not in the repository")
    assert not bad, bad


def test_every_row_answers_the_reachability_question():
    thin = [r[0] for r in inventory_rows() if len(r[3].split()) < 1 or not r[3]]
    assert not thin, f"rows with no reachability answer: {thin}"


def test_the_failure_it_found_is_written_down_with_its_measurement():
    """A sweep that reports "all clean" is worth nothing without the one
    it caught. If the rescorer gap is fixed, this section changes rather
    than disappears — that is what the "Fixed in" line is for."""
    text = INVENTORY.read_text(encoding="utf-8")
    assert "## The one that failed" in text
    assert "models/rescorer_v1.joblib" in text
    assert "joblibs inside pkg    : []" in text, (
        "the measurement, not the assertion — quote what was observed")


def test_the_parser_would_notice_a_new_claim():
    """A regex that matches nothing passes for the wrong reason."""
    assert len(readme_claims()) >= 18
    sample = "19. **A brand new thing.** It does something.\n"
    assert CLAIM_RE.findall(sample) == ["19"]
    assert CODE_TOKEN.findall("see `report/gallery.py::build_gallery_zip`") \
        == ["report/gallery.py"]
