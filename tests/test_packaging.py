"""v2.43.4 — check the artifact that actually ships, not the config.

Every GitHub Release from v2.23 to v2.43.3 shipped a wheel containing 35
data files and **zero Python modules**.  `pip install pixcull` installed
`pixcull/locale`, `pixcull/report` and `pixcull/scoring` — three
directories of JSON and HTML — and no code at all.

Two independent mistakes had to line up, which is why nine releases went
out before anyone noticed:

1. ``[tool.hatch.build] include`` is an allowlist and applies to the
   **sdist**.  It listed only data globs, so the sdist had no ``*.py``.
   ``python -m build`` (what release.yml runs) builds the wheel *from
   that sdist*, so the wheel inherited the emptiness.  Building locally
   with ``--wheel`` goes straight from the source tree, where the wheel
   target's ``packages`` applies, and looks perfectly healthy — so the
   one command a human runs by hand is the one that hides it.

2. The release smoke test ran ``python -c "import pixcull"`` from the
   checkout root, where the cwd is on ``sys.path``.  It imported the
   source tree and never touched the wheel it had just installed.

So this file builds the real artifacts and looks inside them.  Config
assertions would not have caught #1: the config *looks* right, and the
wheel built the way a human builds it *is* right.

``--no-isolation`` keeps it at ~0.1s (it reuses the installed hatchling
instead of provisioning a build env), which is cheap enough to sit in
the default gate rather than behind the ``slow`` marker — this must run
on every change, not weekly.
"""

from __future__ import annotations

import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# A module from each layer that must survive packaging.
MUST_HAVE_CODE = (
    "pixcull/__init__.py",
    "pixcull/cli.py",
    "pixcull/scoring/transcribe.py",
    "pixcull/report/serve_app.py",
    "pixcull/pipeline/orchestrator.py",
)
# Runtime data that is loaded from disk — the reason the allowlist exists.
MUST_HAVE_DATA = (
    "pixcull/report/templates/results.html",
    "pixcull/locale/zh_CN.json",
    "pixcull/scoring/data/audio_tagger_thresholds.json",
    # v2.44 — added the day the .txt lexicon was written, because the
    # allowlist globbed data/*.json and dropped it. Every new runtime
    # data file needs a line here; that is the cost of an allowlist, and
    # it is cheaper than shipping a feature that silently does nothing.
    "pixcull/scoring/data/asr_hotwords_zh.txt",
    "pixcull/scoring/templates/scene_templates.yaml",
)


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> tuple[list[str], list[str]]:
    """Build sdist + wheel exactly as release.yml does, and list both.

    Returns ``(sdist_names, wheel_names)`` with the leading
    ``pixcull-<version>/`` stripped from the sdist entries so both sides
    are comparable.
    """
    out = tmp_path_factory.mktemp("dist")

    # Fast path reuses an installed hatchling (~0.1s). Falling back to an
    # isolated build (~3s) rather than skipping is deliberate: this repo
    # has already been bitten by a skip standing in for a pass, and a
    # guard that quietly opts out on the machine with the wrong extras
    # installed is not a guard. Both hatchling and build are declared in
    # the dev extra, so the fast path is the normal one.
    try:
        import hatchling  # noqa: F401
        argv = ["--no-isolation"]
    except ImportError:
        argv = []

    proc = subprocess.run(
        [sys.executable, "-m", "build", *argv, "--outdir", str(out)],
        cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        # Only a genuinely absent build frontend is skippable — a build
        # that runs and fails is a real failure.
        if "No module named build" in (proc.stderr + proc.stdout):
            pytest.skip("python -m build is not installed")
        pytest.fail(f"build failed:\n{proc.stderr.strip()[-800:]}")

    sdists = list(out.glob("*.tar.gz"))
    wheels = list(out.glob("*.whl"))
    assert sdists and wheels, f"build produced {[p.name for p in out.iterdir()]}"

    with tarfile.open(sdists[0]) as tf:
        # sdist entries are prefixed with pixcull-<version>/
        sdist_names = [n.split("/", 1)[1] for n in tf.getnames() if "/" in n]
    with zipfile.ZipFile(wheels[0]) as zf:
        wheel_names = zf.namelist()
    return sdist_names, wheel_names


def test_sdist_carries_the_python_package(built):
    """The sdist is the artifact the wheel is built from in CI.

    This is the assertion that fails on the historical bug.
    """
    sdist, _ = built
    missing = [m for m in MUST_HAVE_CODE if m not in sdist]
    n_py = len([n for n in sdist if n.endswith(".py")])
    assert not missing, (
        f"sdist is missing {missing} (it has {n_py} .py files in total) — "
        "check the [tool.hatch.build] include allowlist covers *.py")


def test_wheel_carries_the_python_package(built):
    """What `pip install pixcull` actually unpacks."""
    _, wheel = built
    missing = [m for m in MUST_HAVE_CODE if m not in wheel]
    n_py = len([n for n in wheel if n.endswith(".py")])
    assert not missing, (
        f"wheel is missing {missing} (it has {n_py} .py files in total)")
    assert n_py > 50, f"only {n_py} modules in the wheel; the package is bigger"


def test_runtime_data_files_still_ship(built):
    """The allowlist exists for these; adding *.py must not drop them."""
    sdist, wheel = built
    for name in MUST_HAVE_DATA:
        assert name in wheel, f"{name} missing from wheel"
        assert name in sdist, f"{name} missing from sdist"


def test_private_files_never_ship(built):
    """`pixcull/` on disk holds files that must not be distributed.

    The market-analysis doc lives inside the package directory and is
    gitignored; hatchling honours that, but the wheel is the last place
    to find out otherwise.
    """
    sdist, wheel = built
    for names, label in ((sdist, "sdist"), (wheel, "wheel")):
        bad = [n for n in names
               if "MARKET_ANALYSIS" in n
               or "/.venv/" in n
               or n.endswith((".pyc", ".key", ".pem"))]
        assert not bad, f"{label} ships private/unwanted files: {bad}"


def test_console_script_is_declared(built):
    """`pixcull --help` is the first thing a new user runs."""
    _, wheel = built
    entry = [n for n in wheel if n.endswith("dist-info/entry_points.txt")]
    assert entry, "no entry_points.txt in the wheel"
