"""v3.94.2 — a name the code uses has to exist.

Two were found at once, each behind something that hid it:

* `report/contact_sheet.py` used `ImageOps`, imported only inside another
  function. The NameError landed in a per-cell `except`, and every cell of
  every contact sheet since v2.56.2 said "(image unavailable)".
* `cli.py`'s `m3 eval` read `lab` in the `--review` loop before assigning
  it, so any `--review` crashed with UnboundLocalError. No test passed
  `--review`.

Neither needs a test of its own feature to catch: an undefined name is a
static fact. This asks ruff (a dev dependency, installed in every CI lane
that runs pytest) for exactly that class and nothing else, so style rules
can never make it noisy.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES = "F821,F822,F823"   # undefined name, undefined in __all__, used before assignment


def _ruff(*paths: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--select", RULES,
         "--output-format", "concise", "--no-cache", *paths],
        cwd=ROOT, capture_output=True, text=True)


def test_ruff_is_installed():
    """Not a skip: a missing checker would make the test below vacuous."""
    r = subprocess.run([sys.executable, "-m", "ruff", "--version"],
                       capture_output=True, text=True)
    assert r.returncode == 0, "ruff is a dev dependency: pip install -e '.[dev]'"


def test_no_name_is_used_that_does_not_exist():
    r = _ruff("pixcull", "scripts")
    assert r.returncode == 0, "undefined names:\n" + r.stdout + r.stderr


def test_the_check_catches_the_shape_that_hid_for_two_months(tmp_path):
    """The control: the contact-sheet bug, reduced. If the rule selection
    or ruff's behaviour drifts, this goes red before a real one slips by."""
    bad = tmp_path / "bad.py"
    bad.write_text(
        "def _font():\n"
        "    from PIL import ImageOps\n"
        "    return ImageOps\n"
        "\n"
        "def render(img):\n"
        "    try:\n"
        "        return ImageOps.exif_transpose(img)\n"
        "    except Exception:\n"
        "        return None\n", encoding="utf-8")
    r = _ruff(str(bad))
    assert r.returncode == 1 and "ImageOps" in r.stdout, r.stdout + r.stderr
