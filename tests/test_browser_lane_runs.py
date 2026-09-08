"""v3.42 — the browser tests were green because they never ran.

Three files drive a real chromium: `test_visual_smoke.py`,
`test_lightbox_stability.py`, `test_client_present.py`.  Each opens with
`pytest.importorskip("playwright.sync_api")`, which is right on a
maintainer's laptop and wrong on a runner — playwright was never
installed on one, so all three skipped on every push since they were
written.  `test_lightbox_stability.py` even said so in its own
docstring: "the same launch-a-real-chromium path as test_visual_smoke
(which is green in CI)".  test_visual_smoke was green in CI because it
did nothing.

Fourth instance of skip-as-a-pass here (ffmpeg in v2.45, two model
lanes, exiftool in v3.41), so the guard reads the parsed workflow rather
than the file's text — a comment saying the word "playwright" must not
be able to satisfy it.
"""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parent.parent
BROWSER_TESTS = ("tests/test_visual_smoke.py",
                 "tests/test_lightbox_stability.py",
                 "tests/test_client_present.py",
                 # v3.45 — rasterizes every README image and counts the
                 # colours, because the hero demo shipped as 921,600
                 # pixels of pure black and nothing was looking.
                 "tests/test_readme_images_render.py")


def _workflow() -> dict:
    return yaml.safe_load(
        (ROOT / ".github" / "workflows" / "tests.yml").read_text("utf-8"))


def _run_script(job: dict) -> str:
    """Every `run:` in the job, joined. Comments inside a run block are
    shell comments and are stripped, so prose cannot satisfy a check."""
    out = []
    for step in job.get("steps", []):
        for line in str(step.get("run", "")).splitlines():
            out.append(line.split("#", 1)[0])
    return "\n".join(out)


def test_a_job_installs_playwright_and_a_browser():
    jobs = _workflow()["jobs"]
    assert "browser" in jobs, "no browser lane in CI"
    script = _run_script(jobs["browser"])
    assert "pip install playwright" in script
    assert "playwright install" in script and "chromium" in script


def test_that_job_runs_all_three_browser_files():
    """Named individually. A glob would quietly drop the next one."""
    script = _run_script(_workflow()["jobs"]["browser"])
    missing = [f for f in BROWSER_TESTS if f not in script]
    assert not missing, f"browser lane does not run: {missing}"


def test_the_lane_proves_a_browser_actually_launched():
    """Tied to something the skip path cannot satisfy.

    Without this the lane could install nothing, every file could skip
    on the missing import, and the tick would be green again — which is
    the exact failure this version exists to end.
    """
    script = _run_script(_workflow()["jobs"]["browser"])
    assert "chromium.launch()" in script


def test_the_browser_files_are_still_the_browser_files():
    """A new playwright test that nobody adds to the lane is the same
    bug wearing a different name."""
    found = sorted(
        f"tests/{p.name}" for p in (ROOT / "tests").glob("test_*.py")
        if "playwright" in p.read_text("utf-8"))
    assert found == sorted(BROWSER_TESTS + ("tests/test_browser_lane_runs.py",)), (
        "a file drives playwright and is not in the CI browser lane: "
        f"{found}")
