"""v3.94.1 — what the package declares and what it imports have to agree.

`imagededup` was a base dependency, declared for "duplicate detection",
and nothing in the package imported it: near-duplicates have been CLIP
and DINOv2 for a long time. It still had to install, and it is a C++
build with wheels for Python 3.9-3.12 only, so on Python 3.13 every
install compiled it — and on Windows without a compiler `pip install
pixcull` failed outright. Resolved for Windows / Python 3.13 with
binaries only, 3.94.0 stops at "No matching distribution found for
imagededup". CI never saw it: every runner has a compiler.

The opposite direction is how v3.49 began: scikit-learn was imported and
undeclared, arriving through imagededup at whatever version that graph
chose. Removing imagededup found one more of those, scipy
(detectors/canon.py), which only scikit-learn now guarantees.

So both directions are held here, from the source, not from a list
someone keeps by hand: every declared dependency is imported somewhere
in the package, and every third-party import is declared — each
exception named, with its reason.
"""
from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "pixcull"

#: Distribution -> the top-level modules it provides, where the names differ.
MODULES = {
    "pillow": {"PIL"},
    "opencv-python": {"cv2"},
    "pyyaml": {"yaml"},
    "scikit-learn": {"sklearn"},
}

#: Declared, never imported by the package. Each needs a reason to stay.
NOT_IMPORTED = {
    "safetensors": "transformers reads the model weights through it; "
                   "declared for its floor, not for an import of ours",
    "jinja2": "not imported by the package any more; a pure-Python wheel "
              "on every platform, so it costs no install. A patch release "
              "removes only what blocks installs — drop it in the next minor",
}

#: Imported, deliberately undeclared: each is behind ImportError handling,
#: an opt-in path, or exists only in a source checkout.
OPTIONAL_UNDECLARED = {
    "sentry_sdk": "telemetry.py — opt-in tier, ImportError turns it off",
    "llama_cpp": "nl_explain.py — opt-in local GGUF model, ImportError -> None",
    "mlx_vlm": "vlm_judge.py — opt-in on-device VLM on Apple Silicon",
    "whisper": "transcribe.py — last fallback after the declared ASR extras",
    "build_axis_training_set": "scripts/ in a source checkout; serve_app "
                               "refuses retraining from an install",
    "train_axis_rescorers": "same as build_axis_training_set",
}


def _norm(req: str) -> str:
    return re.split(r"[<>=!~;\[ ]", req, maxsplit=1)[0].strip().lower().replace("_", "-")


def _project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]


def _base() -> set[str]:
    return {_norm(r) for r in _project()["dependencies"]}


def _extras() -> set[str]:
    return {_norm(r) for reqs in _project().get("optional-dependencies", {}).values()
            for r in reqs}


def _modules_of(dist: str) -> set[str]:
    return MODULES.get(dist, {dist.replace("-", "_")})


def _imported() -> dict[str, str]:
    """Every third-party top-level module the package imports, lazily or
    not, with one file that does it."""
    stdlib = set(sys.stdlib_module_names) | {"__future__", "pixcull"}
    found: dict[str, str] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top not in stdlib:
                    found.setdefault(top, str(path.relative_to(ROOT)))
    return found


def test_the_scan_sees_the_package():
    """A scan that finds nothing passes both tests below for nothing."""
    found = _imported()
    for module in ("numpy", "torch", "transformers", "cv2", "PIL", "sklearn"):
        assert module in found, f"the import scan no longer sees {module}"


def test_every_declared_dependency_is_imported():
    imported = set(_imported())
    unused = sorted(d for d in _base() - set(NOT_IMPORTED)
                    if not _modules_of(d) & imported)
    assert not unused, (
        f"declared in pyproject.toml and imported nowhere in the package: "
        f"{unused}. Every base dependency has to install on every platform "
        "and Python we advertise, so one that is not used is only cost — "
        "imagededup's cost was every Windows install on Python 3.13. Remove "
        "it, or add it to NOT_IMPORTED with the reason it stays.")


def test_every_import_is_declared():
    declared = _base() | _extras()
    provided = {m for d in declared for m in _modules_of(d)}
    undeclared = {m: f for m, f in _imported().items()
                  if m not in provided and m not in OPTIONAL_UNDECLARED}
    assert not undeclared, (
        f"imported by the package and not declared: {undeclared}. Arriving "
        "through another package's dependencies means its version is "
        "chosen by that package — v3.49 (scikit-learn via imagededup). "
        "Declare it, or add it to OPTIONAL_UNDECLARED if the import is "
        "guarded or opt-in.")


def test_the_exceptions_are_still_exceptions():
    """An allowlist entry that is no longer true hides the next one."""
    imported = set(_imported())
    base = _base()
    for dist in NOT_IMPORTED:
        assert dist in base, f"NOT_IMPORTED lists {dist}, which is not declared"
        assert not _modules_of(dist) & imported, (
            f"{dist} is imported now; take it off NOT_IMPORTED")
    provided = {m for d in base | _extras() for m in _modules_of(d)}
    for module in OPTIONAL_UNDECLARED:
        assert module in imported, (
            f"OPTIONAL_UNDECLARED lists {module}, which nothing imports now")
        assert module not in provided, (
            f"{module} is declared now; take it off OPTIONAL_UNDECLARED")
