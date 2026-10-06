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

import re
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
    # v3.93 — the review server runs this as a subprocess for the
    # delivery-audit page. It lived in scripts/, which is not shipped, and
    # the page answered 500 on every installed copy.
    "pixcull/report/cli_audit.py",
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
    # v3.39 — pixcull/tether_drift.py reads finished_run_columns.txt from
    # beside itself, and the allowlist had no pattern for pixcull/data.
    # The module shipped; the file it opens did not. Same shape as the
    # .txt lexicon above, found the same way: by looking.
    "pixcull/data/finished_run_columns.txt",
    "pixcull/data/deferrals.tsv",
    # v3.44 — v3.38's reachability sweep: RescorerConfig.model_path is
    # relative to the working directory and these were not in the wheel,
    # so every pip install ran rule-only. The README lists the learned
    # head as something you get.
    "pixcull/models/rescorer_v1.joblib",
    "pixcull/models/rescorer_axis_technical.joblib",
    "pixcull/models/rescorer_axis_meta.json",
    # v3.93.1 — tracked, opened by the package, and never shipped until
    # now. The face models (without them `pixcull[face]` detects nothing),
    # and what the review server serves from report/static.
    "pixcull/detectors/_models/blaze_face_short_range.tflite",
    "pixcull/detectors/_models/face_landmarker.task",
    "pixcull/report/static/brand/geist-variable.woff2",
    "pixcull/report/static/brand/Geist-LICENSE-OFL.txt",
    "pixcull/report/static/brand/pixcull-icon.svg",
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


#: Fingerprints of a checkout directory rather than of a home directory.
#: The leak this guards was
#: `~/Downloads/zero-basics-python/2/pixcull-restored/pixcull/training_axis.csv`
#: — the build machine's own tree, recorded at training time.
#:
#: Deliberately narrower than "any /Users/ path". The first cut flagged
#: fifteen files and every one was a false positive: `/Users/you/Pictures/
#: tether` is the tether page's placeholder, and it is *localised*, so
#: the second cut still tripped on `sie`, `tu`, `vous`, `jij`, `voce`
#: and `sen`. `pixcull/error_reporting.py` matched because it is the
#: module that does the redacting and its docstring shows the pattern.
#: A broad rule here is a rule somebody switches off.
_BUILD_MACHINE_MARKERS = (
    "zero-basics-python", "pixcull-restored",
    "~/Downloads", "~/Desktop", "~/Documents",
)


def test_no_shipped_file_carries_a_path_from_the_build_machine(built):
    """v3.55 — what goes to PyPI is permanent.

    `models/rescorer_axis_meta.json` recorded the training CSV as a path
    inside the maintainer's own checkout, written at training time and
    shipped inside every wheel. There was no username in it, so the repo
    hygiene check passed it, and it was on its way to a package index
    that never forgets.

    The useful content of that field is which file trained the model,
    not where it happened to live on one laptop.
    """
    _sdist_names, wheel_names = built
    readable = (".json", ".txt", ".tsv", ".yaml", ".yml", ".py", ".cfg")
    bad = []
    for name in wheel_names:
        if not name.endswith(readable):
            continue
        f = ROOT / name
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for marker in _BUILD_MACHINE_MARKERS:
            if marker in text:
                bad.append(f"{name}: {marker}")
    assert not bad, (
        "these files ship a path from the machine that built them: "
        + "; ".join(sorted(set(bad))))


# -- v3.93.1: what the package opens, the wheel must carry -------------------
#
# MUST_HAVE_DATA above is a list someone has to remember to extend. Every
# entry in it was added the day its absence was found, which is the
# problem: the face models were opened by the package from the first
# wheel and nobody added them, because nobody was looking. These derive
# the list from the code instead.

import ast  # noqa: E402

PACKAGE = ROOT / "pixcull"

#: Paths the package builds from its own location that point OUT of the
#: package on purpose, keyed ``module:resolved-path``. Each is a checkout
#: convenience that an installed copy is not meant to have.
CHECKOUT_ONLY = {
    "pixcull/cli.py:pyproject.toml":
        "checkout detection — its absence is how `pixcull serve` knows it "
        "was pip-installed",
    "pixcull/report/serve_app.py:.":
        "_repo_root() — checkout detection; returns None from an install, "
        "and every caller handles None",
    "pixcull/scoring/color_grade.py:luts":
        "a checkout's drop-in folder; an install reads PIXCULL_LUTS_DIR and "
        "~/.pixcull/luts first (v3.93.1)",
    "pixcull/scoring/nl_explain.py:.":
        "a local GGUF beside a checkout; PIXCULL_NL_MODEL_PATH is the way "
        "for an install, and without either the template explanation runs",
    "pixcull/scoring/composition_classifier.py:models/composition_classifier.joblib":
        "detect_rule's optional ML path; nothing in the pipeline calls it — "
        "the pipeline's composition detector is pixcull/detectors/composition.py",
}


def _eval_path(node: ast.AST, here: Path, names: dict[str, Path],
               path_names: frozenset = frozenset({"Path"})) -> Path | None:
    """Statically resolve ``Path(__file__)…/"lit"`` and friends, or None.

    Understands ``Path(__file__)``, ``.resolve()``, ``.parent``,
    ``.parents[n]``, ``/ "literal"``, ``_pkg_root()``, and module-level
    names bound to any of those. Anything else is not a path this scan
    can follow and is left alone.
    """
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id in path_names and len(node.args) == 1 \
                and isinstance(node.args[0], ast.Name) \
                and node.args[0].id == "__file__":
            return here
        if isinstance(fn, ast.Name) and fn.id == "_pkg_root" and not node.args:
            return PACKAGE
        if isinstance(fn, ast.Attribute) and fn.attr == "resolve":
            return _eval_path(fn.value, here, names, path_names)
        return None
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        base = _eval_path(node.value, here, names, path_names)
        return base.parent if base is not None else None
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) \
            and node.value.attr == "parents" and isinstance(node.slice, ast.Constant):
        base = _eval_path(node.value.value, here, names, path_names)
        return base.parents[node.slice.value] if base is not None else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) \
            and isinstance(node.right, ast.Constant) \
            and isinstance(node.right.value, str):
        base = _eval_path(node.left, here, names, path_names)
        return base / node.right.value if base is not None else None
    if isinstance(node, ast.Name) and node.id in names:
        return names[node.id]
    return None


def _paths_built_from_the_package(path: Path) -> list[tuple[int, Path]]:
    """Every maximal path expression in ``path`` that resolves statically."""
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    # `from pathlib import Path as P` — the scan follows the alias too.
    path_names = frozenset({"Path"} | {
        a.asname for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module == "pathlib"
        for a in n.names if a.name == "Path" and a.asname})
    names: dict[str, Path] = {}
    for st in tree.body:                         # module-level bindings
        targets = st.targets if isinstance(st, ast.Assign) else (
            [st.target] if isinstance(st, ast.AnnAssign) and st.value else [])
        for tg in targets:
            if isinstance(tg, ast.Name):
                got = _eval_path(st.value, path, names, path_names)
                if got is not None:
                    names[tg.id] = got
    inner: set[int] = set()
    found: list[tuple[int, Path]] = []
    for node in ast.walk(tree):
        if id(node) in inner:
            continue
        got = _eval_path(node, path, names, path_names)
        if got is None or isinstance(node, ast.Name):
            continue
        found.append((node.lineno, got))
        for sub in ast.walk(node):               # keep the longest chain only
            if sub is not node:
                inner.add(id(sub))
    return found


def _package_reaches() -> list[tuple[str, int, Path]]:
    out = []
    for py in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        for line, target in _paths_built_from_the_package(py):
            out.append((str(py.relative_to(ROOT)), line, target))
    return out


def test_the_scan_follows_the_shapes_the_package_uses(tmp_path):
    mod = tmp_path / "pixcull" / "detectors" / "face.py"
    mod.parent.mkdir(parents=True)
    mod.write_text(
        "from pathlib import Path\n"
        "_DIR = Path(__file__).parent / '_models'\n"
        "MODEL = _DIR / 'm.tflite'\n"
        "UP = Path(__file__).resolve().parent.parent.parent / 'luts'\n"
        "P2 = Path(__file__).parents[1] / 'data' / 'x.txt'\n"
        "from pathlib import Path as _P\n"
        "AL = _P(__file__).parent / 'aliased.json'\n"
        "# Path(__file__).parent / 'in_a_comment'\n", "utf-8")
    got = sorted(str(p.relative_to(tmp_path)) for _, p in
                 _paths_built_from_the_package(mod))
    assert got == ["luts", "pixcull/data/x.txt", "pixcull/detectors/_models",
                   "pixcull/detectors/_models/m.tflite",
                   "pixcull/detectors/aliased.json"], got


def test_the_scan_still_sees_the_face_models():
    """The finding that made this file grow: if the scan cannot see this,
    it cannot see the next one."""
    targets = {str(p.relative_to(ROOT)) for _, _, p in _package_reaches()
               if p.is_relative_to(ROOT)}
    assert "pixcull/detectors/_models/blaze_face_short_range.tflite" in targets
    assert "pixcull/detectors/_models/face_landmarker.task" in targets
    assert len(targets) >= 15, f"only {len(targets)} paths found — scan broken"


def test_every_file_the_package_opens_from_itself_is_in_the_wheel(built):
    _, wheel = built
    shipped = set(wheel)
    missing = []
    for rel, line, target in _package_reaches():
        if not target.is_relative_to(PACKAGE):
            continue
        name = target.relative_to(ROOT).as_posix()
        if target.is_file():
            if name not in shipped:
                missing.append(f"{rel}:{line} -> {name}")
        elif target.is_dir():
            if not any(w.startswith(name + "/") for w in shipped):
                missing.append(f"{rel}:{line} -> {name}/ (nothing under it)")
    assert not missing, (
        "the package opens these from beside itself and the wheel does not "
        "carry them, so the feature is gone on every installed copy — add a "
        f"pattern to [tool.hatch.build] include: {missing}")


def test_nothing_reaches_out_of_the_package_without_saying_why():
    """``Path(__file__).parent.parent.parent`` from inside the package is
    the repository — in a checkout. Installed, it is the directory above
    site-packages."""
    out = set()
    for rel, line, target in _package_reaches():
        if target.is_relative_to(PACKAGE):
            continue
        key = f"{rel}:{target.relative_to(ROOT).as_posix() if target.is_relative_to(ROOT) else target}"
        if key not in CHECKOUT_ONLY:
            out.add(f"{key} (line {line})")
    assert not out, (
        "these build a path that climbs out of the package, which only "
        "exists in a checkout. Ship the file inside the package, or add an "
        f"entry to CHECKOUT_ONLY with the reason an install does not need "
        f"it: {sorted(out)}")
    stale = [k for k in CHECKOUT_ONLY
             if not any(f"{r}:{(t.relative_to(ROOT).as_posix() if t.is_relative_to(ROOT) else t)}" == k
                        for r, _, t in _package_reaches())]
    assert not stale, f"exemptions for paths no longer built: {stale}"


def test_every_asset_a_page_asks_for_is_in_the_wheel(built):
    """The URLs, from the other end. ``/docs/brand/<f>`` and
    ``/docs/illustrations/<f>`` are served from ``report/static/`` in an
    install; a page that names a file not shipped there gets a 404 on
    every installed copy, which is what the font did."""
    _, wheel = built
    shipped = set(wheel)
    asked = set()
    for f in PACKAGE.rglob("*"):
        if f.suffix not in (".py", ".html", ".js", ".css") or not f.is_file():
            continue
        for m in re.finditer(r"/docs/(brand|illustrations)/([A-Za-z0-9._-]+\.[a-z0-9]+)",
                             f.read_text("utf-8", errors="replace")):
            asked.add((m.group(1), m.group(2)))
    assert len(asked) >= 5, f"only {len(asked)} asset URLs found — scan broken"
    missing = sorted(f"/docs/{d}/{n}" for d, n in asked
                     if f"pixcull/report/static/{d}/{n}" not in shipped)
    assert not missing, f"pages ask for assets the wheel does not ship: {missing}"


def test_the_icon_is_the_brand_mark():
    """Twin: the packaged icon is written by gen_brand_svg.py from the same
    function as docs/brand/pixcull-mark-only.svg; edited by hand, they part."""
    icon = PACKAGE / "report" / "static" / "brand" / "pixcull-icon.svg"
    mark = ROOT / "docs" / "brand" / "pixcull-mark-only.svg"
    assert icon.read_bytes() == mark.read_bytes(), (
        "regenerate with scripts/brand/gen_brand_svg.py")

