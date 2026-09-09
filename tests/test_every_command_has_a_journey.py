"""v3.59 — invoke every command once, the way its own help says to.

v2.45 recorded "four of seventeen CLI commands had a journey test" and
built the video journey to fix its share. Eight commands have arrived
since and the ratio did not move: seven of twenty-five.

The two defects this block opened with were both found by hand, in five
minutes, by running commands against a real run — `export --xmp`, an
option that does not exist and was printed on the PyPI page, and
`view-folder` raising FileNotFoundError at a photographer. Neither
needed a clever test. They needed *a* test.

So this is deliberately the shallowest useful thing: call the command,
assert it exits zero, assert the file it promises appears. Eighteen
thorough tests is a month and will not be written. Eighteen shallow ones
run in seconds and would have caught both.

Commands that need something CI cannot supply are listed with the reason
rather than skipped quietly — `NEEDS` below is the whole of that list,
and a command missing from both tables fails the census test.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "present_run"

#: Commands this cannot drive here, and the honest reason for each.
NEEDS = {
    "run":         "real photographs and the scoring models",
    "video":       "a video file and the temporal pass",
    "reel":        "a scored video run",
    "cut":         "a rendered video",
    "proxy":       "a RAW file and ffmpeg's ProRes encoder",
    "transcribe":  "an audio track and an ASR engine",
    "serve":       "a long-running HTTP server; the browser lane drives it",
    "bench":       "a timing baseline that is machine-specific",
    "m3":          "a funded MiniMax key; refusing without one is its own test",
    "calibrate":   "a blind labelling pass by a person",
    "flag-lift":   "a labelled golden set",
    "import-catalog": "a real Lightroom catalogue (open item 4)",
    "dedup-across": "two or more scored runs",
    "trim-dupes":  "an extracted-frames directory",
    "scan":        "a photo folder; covered by test_cli_audit_smoke",
    "plugins":     "no side-effect-free subcommand to drive",
    "models":      "a model download",
    "personalize": "a corrections history",
    "library":     "a populated cross-run index",
    "picks":       "a client reply file; driven below via proof-sheet",
    "transcribe-engines": "an installed ASR engine to enumerate",
}

#: command -> (argv after `pixcull`, path that must exist afterwards)
DRIVEN = {
    "export":        (["export", "{run}"], None),
    "contact-sheet": (["contact-sheet", "{run}", "--out", "{tmp}/cs"], "{tmp}/cs"),
    "proof-sheet":   (["proof-sheet", "{run}", "--out", "{tmp}/ps"], "{tmp}/ps"),
    "view-folder":   (["view-folder", "{run}", "--out", "{tmp}/vf",
                       "--only", "all"], "{tmp}/vf"),
}


def _cli(*argv: str, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, COLUMNS="200", PYTHONPATH=str(ROOT))
    # Never let a key on the developer's machine turn a journey into a
    # cloud call. v3.56: clearing the env var is not enough on macOS.
    env.pop("MINIMAX_API_KEY", None)
    return subprocess.run([sys.executable, "-m", "pixcull.cli", *argv,
                           "--vlm-mode", "off"] if argv[0] == "run"
                          else [sys.executable, "-m", "pixcull.cli", *argv],
                          cwd=cwd, capture_output=True, text=True, env=env)


def _top_level_commands() -> set[str]:
    """Ask the Typer app, not its rendered help.

    The first version parsed `--help` with a regex over Rich's box
    drawing. That works on a developer's terminal and found zero
    commands on the CI runner, where Rich renders without a TTY — the
    census then reported that every command it knew about had been
    deleted. A test whose subject is "does this command exist" must not
    depend on how a table looks.
    """
    from pixcull.cli import app

    names = {c.name or c.callback.__name__.replace("_", "-")
             for c in app.registered_commands}
    names |= {g.name for g in app.registered_groups if g.name}
    return names


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory) -> Path:
    """A scored run over the committed sample photographs.

    The synthetic `present_run` fixture is rows without pictures, which
    is right for the client-present probe and useless here: `export`,
    `contact-sheet` and `view-folder` all resolve a filename to an
    original on disk, and with no originals they correctly do nothing.
    The first draft of this file used it and three journeys failed for
    that reason — which is the fixture being wrong, not the commands.

    So the run points at `samples/input`, six real JPEGs in the
    repository. No models and no network: the rows are written here.
    """
    import csv
    import shutil

    photos = ROOT / "samples" / "input"
    originals = sorted(photos.glob("*.jpg"))
    if len(originals) < 3:
        pytest.fail(f"expected the sample photographs in {photos}")

    root = tmp_path_factory.mktemp("journeys")
    src = root / "photos"
    src.mkdir()
    for p in originals:
        shutil.copy2(p, src / p.name)

    out = root / "out"
    out.mkdir()
    decisions = ("keep", "maybe", "cull")
    with (out / "scores.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "path", "filename", "decision", "score_final", "reason",
            "scene", "datetime", "flags"])
        w.writeheader()
        for i, p in enumerate(sorted(src.iterdir())):
            w.writerow({
                "path": str(p), "filename": p.name,
                "decision": decisions[i % 3],
                "score_final": f"{0.42 + i * 0.07:.4f}",
                "reason": f"score={0.42 + i * 0.07:.2f}",
                "scene": "landscape",
                "datetime": f"2026:01:01 10:{i:02d}:00", "flags": ""})
    return out


def test_every_command_is_either_driven_or_listed_with_a_reason():
    """The census. A new command that nobody drives has to be a decision
    somebody wrote down, which is the same rule v3.51 applied to skips."""
    top = _top_level_commands()
    assert len(top) >= 20, f"only found {len(top)} commands: {sorted(top)}"
    accounted = set(DRIVEN) | set(NEEDS)
    orphans = sorted(c for c in top if c not in accounted)
    assert not orphans, (
        "these commands are neither driven by a journey here nor listed "
        f"with the reason they cannot be: {orphans}")


def test_nothing_is_listed_that_no_longer_exists():
    top = _top_level_commands()
    stale = sorted(c for c in (set(DRIVEN) | set(NEEDS)) if c not in top)
    assert not stale, f"listed but not a command any more: {stale}"


@pytest.mark.parametrize("name", sorted(DRIVEN))
def test_the_command_runs_and_produces_what_it_promises(name, run_dir,
                                                        tmp_path):
    argv_t, expect_t = DRIVEN[name]
    subs = {"run": str(run_dir), "tmp": str(tmp_path)}
    argv = [a.format(**subs) for a in argv_t]
    proc = _cli(*argv, cwd=tmp_path)
    assert proc.returncode == 0, (
        f"`pixcull {' '.join(argv)}` exited {proc.returncode}\n"
        f"{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}")
    if expect_t:
        out = Path(expect_t.format(**subs))
        assert out.exists(), f"{name} exited 0 but {out} was not created"
        # `--out` is a directory for some of these and a single file for
        # others (contact-sheet writes one sheet). Either way it has to
        # have something in it — "exited 0 and wrote nothing" is the
        # shape of defect this whole file exists to catch.
        if out.is_dir():
            assert any(out.iterdir()), f"{name} created {out} and left it empty"
        else:
            assert out.stat().st_size > 0, f"{name} wrote {out} empty"


def test_a_delivery_with_nothing_in_it_is_refused_not_reported_as_done(
        run_dir, tmp_path):
    """v3.58's crash, driven end to end.

    The first version of this used `--only client`, which exits early on
    "no client picks recorded" *before* reaching the code that used to
    crash — it passed while a mutation restoring the defect went
    unnoticed. A test that passes for the wrong reason is the thing this
    whole file is against.

    So: a run whose every frame is culled, `--only keep`, and an --out
    that does not exist yet. Before the fix that raised FileNotFoundError
    on the manifest write; now it says what is empty and exits non-zero.
    """
    import csv

    culled = tmp_path / "all-cull"
    culled.mkdir()
    with (run_dir / "scores.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    with (culled / "scores.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({**r, "decision": "cull"})

    dest = tmp_path / "does-not-exist-yet"
    proc = _cli("view-folder", str(culled), "--out", str(dest),
                cwd=tmp_path)
    combined = proc.stdout + proc.stderr
    assert "FileNotFoundError" not in combined and "Traceback" not in combined, (
        "view-folder raised at a photographer instead of explaining:\n"
        + combined[-1200:])
    assert proc.returncode != 0, (
        "a delivery folder with no photographs in it reported success:\n"
        + combined[-800:])
    assert "Nothing to deliver" in combined
