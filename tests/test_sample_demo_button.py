"""v3.63 — the in-product demo button returned 500 for everybody.

`/sample_demo` is what the "示例数据" button in the upload page calls. It
copies `samples/output` into a fresh run and serves it, so a visitor can
see the product work without having any photographs of their own. It is
the shortest path from curiosity to understanding that this repository
has.

`samples/output` was not in the repository. `.gitignore` carries a bare
`output/`, which matches a directory of that name at any depth, so the
directory could never be committed and the endpoint's own guard fired
every time:

    500 samples/ not bundled with this build

Second time that rule has eaten something load-bearing — v3.51 found it
swallowing a committed test fixture — which is why the exception is a
glob now rather than another single name.

Nothing tested it. There was no journey for the demo button because the
v3.59 sweep enumerated CLI commands, and this is an HTTP endpoint behind
a button.
"""
import csv
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_OUT = ROOT / "samples" / "output"
SAMPLES_IN = ROOT / "samples" / "input"


def test_the_sample_run_is_committed_and_git_can_see_it():
    """On disk is not the same as in the commit — the whole defect."""
    assert (SAMPLES_OUT / "scores.csv").is_file(), (
        "samples/output/scores.csv is missing; the demo button will 500")
    tracked = subprocess.run(["git", "ls-files", "samples/output"], cwd=ROOT,
                             capture_output=True, text=True).stdout.split()
    assert any(f.endswith("scores.csv") for f in tracked), (
        "samples/output is not tracked by git — check .gitignore, which "
        f"has eaten this directory before. git ls-files said {tracked}")


def test_the_sample_run_points_at_photographs_that_exist():
    """The endpoint rewrites the manifest but not the CSV, so the `path`
    column has to resolve from the project root on somebody else's
    checkout. An absolute path from the machine that generated it does
    not."""
    rows = list(csv.DictReader((SAMPLES_OUT / "scores.csv").open()))
    assert rows, "the sample run has no rows"
    missing = []
    for r in rows:
        p = r.get("path") or ""
        assert not p.startswith("/"), (
            f"absolute path in the shipped sample run: {p}")
        if not (ROOT / p).is_file():
            missing.append(p)
    assert not missing, f"sample run references photographs that are gone: {missing[:4]}"


def test_the_sample_run_shows_the_product_doing_something():
    """A demo where every frame is identical teaches nothing. This one
    is a real sunset take: near-duplicate bursts, and not every frame
    survives."""
    rows = list(csv.DictReader((SAMPLES_OUT / "scores.csv").open()))
    assert len(rows) >= 12, f"only {len(rows)} frames; too few to read as a shoot"

    clusters = [r.get("cluster_id") for r in rows if r.get("cluster_id")]
    assert len(clusters) == len(rows), "cluster_id is missing on some rows"
    folded = len(clusters) - len(set(clusters))
    assert folded >= 3, (
        f"only {folded} frames fold into a burst — near-duplicate folding "
        "is the feature this demo exists to show. Capture timestamps are "
        "what it groups on, so check EXIF DateTimeOriginal survived.")

    decisions = {r["decision"] for r in rows}
    assert len(decisions) >= 2, (
        f"every frame got the same verdict ({decisions}); a culling demo "
        "in which nothing is culled or held shows nothing")


def test_the_photographs_carry_a_capture_time_and_no_location():
    """Burst folding groups on DateTimeOriginal, so stripping EXIF
    wholesale breaks the feature — which is exactly what the first cut
    of this sample set did. GPS is the half that must go: these are real
    frames from a real trip."""
    from PIL import Image

    jpgs = sorted(SAMPLES_IN.glob("*.jpg"))
    assert len(jpgs) >= 12, f"only {len(jpgs)} sample photographs"
    for p in jpgs:
        exif = Image.open(p).getexif()
        assert 0x8825 not in exif, f"{p.name} still carries GPS"
        ifd = exif.get_ifd(0x8769)
        assert ifd.get(0x9003), f"{p.name} has no DateTimeOriginal"
        assert 0xA431 not in ifd, f"{p.name} still carries a body serial number"
