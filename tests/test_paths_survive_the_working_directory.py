"""v3.75 — a run served from the wrong directory reported every photo lost.

`pixcull run photos/` writes into `scores.csv` exactly the path it was
given. Typer does not absolutise an argument, so an ordinary relative
invocation — the normal one — fills the `path` column with relative
paths. `_scores_path_map` then resolved them with `Path(raw).is_file()`,
which asks the question relative to wherever the process happens to be.

Serving that run from anywhere else resolved 0 of N images, and the page
said the originals had been moved or were unreadable: a confident,
wrong diagnosis pointing at the photographer's disk instead of at the
caller's working directory.

The CLI's own `_run_path_map` already had a sibling-`input/` fallback
and was immune, so `pixcull xmp` worked and `pixcull proof-sheet` did
not. Twin paths, one hardened — this repository's most frequent shape.
"""
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_RUN = ROOT / "samples" / "output"


def _fresh_map(out_dir: Path) -> dict:
    """`_scores_path_map` with its mtime cache defeated."""
    from pixcull.report import serve_app
    cache = serve_app._SCORES_PATH_CACHE
    cleared = False
    for attr in ("_d", "_cache", "cache", "_store"):
        d = getattr(cache, attr, None)
        if isinstance(d, dict):
            d.clear()
            cleared = True
    # If the cache silently stops being clearable this test starts
    # comparing a stale map against itself and passes for the wrong
    # reason — which is how the first draft of it "passed".
    assert cleared, "could not clear the scores-path cache; test is inert"
    return serve_app._scores_path_map(out_dir)


@pytest.mark.skipif(not (SAMPLE_RUN / "scores.csv").is_file(),
                    reason="sample run not present")
@pytest.mark.parametrize("cwd", ["/", "/tmp"])
def test_a_run_resolves_from_any_working_directory(cwd, monkeypatch):
    """The committed sample run has a relative `path` column on purpose —
    it has to work on a machine that is not this one. That makes it the
    exact case the old resolver failed, and a fixture for this test."""
    expected = len(_fresh_map(SAMPLE_RUN))
    assert expected > 0, "the sample run resolves nothing even from here"
    monkeypatch.chdir(cwd)
    got = _fresh_map(SAMPLE_RUN)
    assert len(got) == expected, (
        f"resolved {len(got)}/{expected} images with cwd={cwd}. A run's "
        "images must not depend on where the server was started.")
    for p in got.values():
        assert p.is_file(), f"{p} does not exist from cwd={cwd}"


@pytest.mark.skipif(not (SAMPLE_RUN / "scores.csv").is_file(),
                    reason="sample run not present")
def test_the_sample_run_is_the_relative_case_this_protects():
    """If the sample ever ships absolute paths the test above still
    passes and stops testing anything — absolute paths resolve from
    everywhere. Say so, so the fixture cannot quietly stop being one."""
    import csv
    with (SAMPLE_RUN / "scores.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows, "sample scores.csv has no rows"
    relative = [r["path"] for r in rows if r.get("path")
                and not Path(r["path"]).is_absolute()]
    assert len(relative) == len(rows), (
        f"only {len(relative)}/{len(rows)} sample paths are relative; this "
        "fixture only exercises the defect while they are")


def test_an_absolute_path_that_is_gone_is_not_guessed_at():
    """Tolerating relative paths must not become inventing files. An
    absolute path that does not exist is a moved original, and saying so
    is the correct answer."""
    from pixcull.report.serve_app import _resolve_scored_path
    got = _resolve_scored_path("/nonexistent/elsewhere/IMG_1.jpg",
                               SAMPLE_RUN, "IMG_1.jpg")
    assert got is None, f"invented {got} for an absolute path that is gone"
