"""v3.76 — fifteen pictures of a product that changed underneath them.

`docs/screenshots` holds 27 images. `scripts/brand/capture_screenshots.sh`
produces 12. The other 15 are frozen at whatever the UI looked like the
day somebody took them — the oldest in May 2026 — and nothing recorded
which day, or whether the product still behaves that way.

That is how `17-attribution-heatmap.png` survived four months on the
front door of both READMEs. Its caption promises an attribution overlay
that was never implemented and a 6-axis chip strip that is not in the
current page. The screenshot was the evidence for a feature that did not
exist, and re-encoding every image in v3.66 changed its bytes without
anybody looking at what it showed.

So: a screenshot is either produced by the capture script, or somebody
has said in `docs/screenshot-dispositions.tsv` what it is and when they
last confirmed it. `stale` is an allowed answer — an honest one beats a
silent one. `retired` is not allowed to stay on a README.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"
SCRIPT = ROOT / "scripts" / "brand" / "capture_screenshots.sh"
LEDGER = ROOT / "docs" / "screenshot-dispositions.tsv"
READMES = (ROOT / "README.md", ROOT / "modelscope" / "README.md",
           ROOT / "README-PYPI.md")

DISPOSITIONS = {"scripted", "manual-verified", "stale", "retired"}


def _committed() -> set:
    return {p.name for p in SHOTS.glob("*.png")}


def _scripted() -> set:
    text = SCRIPT.read_text(encoding="utf-8")
    return set(re.findall(r"[\"']((?:\d\d)-[a-z0-9-]+\.png)[\"']", text))


def _ledger() -> dict:
    out = {}
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        out[parts[0].strip()] = {
            "disposition": parts[1].strip(),
            "confirmed": parts[2].strip(),
            "note": parts[3].strip(),
        }
    return out


def test_the_scan_sees_the_screenshots_and_the_script():
    """Both sides have to be alive, or this compares two empty sets and
    agrees with itself."""
    assert len(_committed()) >= 20, "the screenshots directory looks empty"
    assert len(_scripted()) >= 8, (
        "the capture script produces no filenames this scan can see — the "
        "parser is broken, not the script")


def test_every_screenshot_is_scripted_or_written_down():
    committed, scripted, ledger = _committed(), _scripted(), _ledger()
    unaccounted = sorted(committed - scripted - set(ledger))
    assert not unaccounted, (
        f"these are committed, are not produced by the capture script, and "
        f"have no row in {LEDGER.name}: {unaccounted}. Add them to the "
        "script, or say in the ledger what they show and when it was last "
        "true.")


def test_the_ledger_has_no_rows_for_images_that_are_gone():
    ledger, committed = _ledger(), _committed()
    orphans = sorted(set(ledger) - committed)
    assert not orphans, (
        f"{LEDGER.name} disposes of images that no longer exist: {orphans}")


def test_a_disposition_is_one_of_the_four_and_carries_a_note():
    for name, row in _ledger().items():
        assert row["disposition"] in DISPOSITIONS, (
            f"{name}: unknown disposition {row['disposition']!r}")
        assert len(row["note"]) > 20, f"{name}: no real note"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["confirmed"]), (
            f"{name}: 'last confirmed' is not a date: {row['confirmed']!r}")


def test_a_retired_screenshot_is_not_on_a_readme():
    """The one rule with teeth. `stale` is honest; `retired` means the UI
    is gone, and a picture of a UI that is gone is a false claim with a
    picture attached."""
    retired = {n for n, r in _ledger().items() if r["disposition"] == "retired"}
    offences = []
    for readme in READMES:
        if not readme.exists():
            continue
        text = readme.read_text(encoding="utf-8")
        for name in retired:
            if name in text:
                offences.append(f"{readme.name} still shows {name}")
    assert not offences, (
        f"{offences}. A retired screenshot shows a UI that no longer "
        "exists; remove the reference or re-shoot it and change the "
        "disposition.")


def test_the_scripted_ones_are_not_also_in_the_ledger():
    """Two sources of truth for the same image is how they drift."""
    both = sorted(_scripted() & set(_ledger()))
    assert not both, (
        f"{both} are produced by the capture script AND dispositioned as "
        "though they were not; drop the ledger row")
