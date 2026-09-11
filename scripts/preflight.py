#!/usr/bin/env python3
"""v3.70 — the release bookkeeping, run before the push instead of after.

Eight fixup commits in the last twenty releases, and the recent ones
share a shape: the product change was right, the bookkeeping around it
was not, and CI said so nine minutes after the push.

    v3.68  the READMEs had not mentioned a release in four versions
    v3.68  a dependency ceiling stated in one of two install files
    v3.69  `pyproject.toml` five iterations behind the newest release

Each of those gates fired correctly. Each fired too late. They are cheap
— the whole set below runs in about eleven seconds, because none of it
loads a model — so there was never a reason to learn about them from a
runner.

Run `make preflight` before pushing a release.

Deliberately NOT wired into a test that executes it: when a unit test
shells out to a whole script, any failure inside it is reported at the
test's location and the signal points somewhere unrelated. What is
tested instead is that this list has not drifted from the set of
bookkeeping gates in the suite — see tests/test_preflight_covers.py.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: (test file, what it stops going out wrong)
GATES: list[tuple[str, str]] = [
    ("tests/test_release_rail.py",
     "the packaged version tracks the newest release"),
    ("tests/test_version.py",
     "the version is stated once and parses"),
    ("tests/test_readme_style.py",
     "both READMEs describe the releases that shipped"),
    ("tests/test_readme_claims_inventory.py",
     "every claim in the README is one the product makes"),
    ("tests/test_documented_commands_exist.py",
     "no document tells a reader to run a command the CLI lacks"),
    ("tests/test_dependency_pins_agree.py",
     "both install paths pin the same dependencies"),
    ("tests/test_env_registry.py",
     "the settings list matches what the code reads"),
    ("tests/test_repo_hygiene.py",
     "nothing private is about to be published"),
    ("tests/test_packaging.py",
     "the wheel carries the files it needs"),
    ("tests/test_ci_skip_ledger.py",
     "every CI skip has been ruled on"),
    ("tests/test_deferrals_are_dispositioned.py",
     "every deferral names what it waits for"),
    # v3.70 — the ten below were found by the drift check in
    # tests/test_preflight_covers.py, not by remembering them. Every one
    # asserts on the public description and every one was outside the
    # list this file shipped with an hour earlier.
    ("tests/test_claims_match_reality.py",
     "the README's numbers are the ones the product produces"),
    ("tests/test_comparative_claims_are_sourced.py",
     "every comparison against another tool cites something"),
    ("tests/test_docs_resolve_missing_modules.py",
     "no document points at a module that is not there"),
    ("tests/test_modelscope_sync_triggers.py",
     "the sync workflow watches what the model card shows"),
    ("tests/test_palette_guard.py",
     "no retired palette survives in a public surface"),
    ("tests/test_pypi_quickstart_runs.py",
     "the PyPI quickstart is a sequence that works"),
    ("tests/test_screenshots_are_dispositioned.py",
     "every screenshot is regenerated or written down as stale"),
    ("tests/test_readme_image_sources.py",
     "every README image resolves and renders on GitHub"),
    ("tests/test_sample_run_never_went_to_the_cloud.py",
     "the shipped sample output was produced on-device"),
    ("tests/test_sync_modelscope_readme.py",
     "the ModelScope card is generated, not hand-copied"),
    ("tests/test_vertical_axis_prior.py",
     "the per-vertical priors match what the README lists"),
]


#: Gates whose answer depends on where HEAD is, not on the working tree.
#: They ask "how far behind the newest release commit is X", so running
#: them before the release is committed always sees one release fewer.
COMMIT_RELATIVE = {
    "tests/test_release_rail.py",
    "tests/test_readme_style.py",
}


def _uncommitted() -> list[str]:
    out = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"],
                         capture_output=True, text=True)
    return [l for l in out.stdout.splitlines() if l.strip()]


def main() -> int:
    print(f"preflight — {len(GATES)} release gates\n")

    # v3.72 — preflight passed, the push went out, and CI failed on
    # `test_readme_style.py` anyway. Both were right: the gate measures
    # distance from the newest release commit, and at preflight time the
    # release being made was not a commit yet, so it counted one fewer.
    #
    # The tool built in v3.70 to stop learning about this from a runner
    # could not see the thing it was checking. Run it AFTER `git commit`
    # and before `git push`, and say so when it is being run too early.
    dirty = _uncommitted()
    if dirty:
        print(f"  ⚠  {len(dirty)} uncommitted change(s) in the tree.\n"
              f"     {', '.join(sorted(COMMIT_RELATIVE))}\n"
              "     measure distance from the newest release COMMIT, so "
              "running now\n"
              "     counts one release fewer than the push will. Commit "
              "first, then\n"
              "     run this, then push.\n")
    # v3.76 — say when the interpreter is the problem, not the code.
    #
    # Twice this reported "FAILED — 21 of 21 gates, 0.5s" and twice I
    # read it as a flaky tool and re-ran it. It was neither flaky nor
    # wrong: the invocation had lost its virtualenv, the shebang picked
    # up the system python, that python has no pytest, and every gate
    # "failed" identically in half a second.
    #
    # Twenty-one identical failures is not twenty-one problems. Check
    # the one thing they all depend on first and name it, so the reader
    # is not sent looking through their own diff for a fault that is in
    # their shell.
    probe = subprocess.run(
        [sys.executable, "-c", "import pytest"],
        capture_output=True, text=True)
    if probe.returncode != 0:
        print(f"  ✗  {sys.executable} cannot import pytest.\n"
              "     Every gate would fail here for that reason alone, "
              "which is not\n"
              "     a result. Run this with the project's virtualenv "
              "python.\n")
        return 2

    failed = []
    t0 = time.time()
    for path, why in GATES:
        started = time.time()
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", path, "-p", "no:warnings", "-q"],
            cwd=ROOT, capture_output=True, text=True)
        ms = int((time.time() - started) * 1000)
        ok = proc.returncode == 0
        print(f"  {'OK  ' if ok else 'FAIL'}  {path:46} {ms:5}ms  {why}")
        if not ok:
            failed.append((path, proc.stdout))
    total = time.time() - t0

    if failed:
        for path, out in failed:
            print(f"\n{'=' * 70}\n{path}\n{'=' * 70}")
            print("\n".join(out.splitlines()[-30:]))
        print(f"\npreflight FAILED — {len(failed)} of {len(GATES)} gates, "
              f"{total:.1f}s. These are the ones CI would have told you "
              "about after the push.")
        return 1

    note = ("  NOTE: run on a dirty tree — the commit-relative gates above "
            "have not\n        seen the release you are about to make.\n"
            if dirty else "")
    print(f"\npreflight OK — {len(GATES)} gates in {total:.1f}s. "
          "Product tests are a separate run; this is the bookkeeping.")
    if note:
        print(note)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
