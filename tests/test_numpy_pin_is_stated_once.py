"""v3.64 — three files carried the numpy pin and two of them were wrong.

`pyproject.toml` moved to `numpy>=2.0,<2.5`. Left behind:

* `pixcull/__init__.py`'s runtime guard still fired on numpy 2.x and
  told the user to run ``pip install 'numpy<2'`` — advice that breaks a
  correctly installed copy, printed on every single import.
* `modelscope/requirements.txt` still pinned `numpy>=1.26,<2`, so the
  Studio build resolved a different numpy than the package it installs
  alongside it.

Twin-path drift, which this repository keeps rediscovering. The fix is
not to remember: it is for the copies to be read from the source and
compared.
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_SPEC = re.compile(r"numpy\s*>=\s*([\d.]+)\s*,\s*<\s*([\d.]+)")


def _ver(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in text.rstrip(".").split("."))


def _pyproject_band() -> tuple[tuple[int, ...], tuple[int, ...]]:
    src = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    # Strip comments first: the reason the pin moved is written above it
    # and names the old band, which a raw search happily matches — a
    # guard satisfied by its own prose is this repo's other classic.
    body = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
    m = _SPEC.search(body)
    assert m, "pyproject.toml declares no numpy band"
    return _ver(m.group(1)), _ver(m.group(2))


def test_the_runtime_guard_agrees_with_the_pin():
    """The guard's job is to notice numpy leaving the supported band. A
    guard reading a different band than the installer enforces reports
    a correct install as broken."""
    lo, hi = _pyproject_band()
    tree = ast.parse((ROOT / "pixcull" / "__init__.py").read_text(encoding="utf-8"))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Tuple):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in (
                        "_NUMPY_MIN", "_NUMPY_MAX_EXCLUSIVE"):
                    found[t.id] = tuple(
                        e.value for e in node.value.elts
                        if isinstance(e, ast.Constant))
    assert set(found) == {"_NUMPY_MIN", "_NUMPY_MAX_EXCLUSIVE"}, (
        f"pixcull/__init__.py no longer states its band as two tuples: {found}")
    assert found["_NUMPY_MIN"] == lo[:len(found["_NUMPY_MIN"])], (
        f"guard floor {found['_NUMPY_MIN']} vs pin floor {lo}")
    assert found["_NUMPY_MAX_EXCLUSIVE"] == hi[:len(found["_NUMPY_MAX_EXCLUSIVE"])], (
        f"guard ceiling {found['_NUMPY_MAX_EXCLUSIVE']} vs pin ceiling {hi}")


def test_the_guard_does_not_tell_a_correct_install_to_downgrade():
    """Stated separately from the band check because it is the part a
    user actually sees, and because it is what went wrong: the numbers
    could agree while the printed instruction still said `numpy<2`."""
    src = (ROOT / "pixcull" / "__init__.py").read_text(encoding="utf-8")
    body = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
    lo, _ = _pyproject_band()
    for bad in re.findall(r"pip install ['\"]?numpy([<>=][^'\"\\n]*)", body):
        m = re.match(r"<\s*([\d.]+)", bad.strip())
        assert not m or _ver(m.group(1)) > lo, (
            f"the guard prints `pip install numpy{bad}`, which is below "
            f"the pinned floor {lo} — following it breaks the install")


def test_the_modelscope_studio_pins_the_same_numpy():
    """The Studio vendors the package and resolves its own dependencies.
    A different band there means the demo everyone can click runs on a
    numpy the package is not tested against."""
    lo, hi = _pyproject_band()
    req = (ROOT / "modelscope" / "requirements.txt").read_text(encoding="utf-8")
    body = "\n".join(l.split("#", 1)[0] for l in req.splitlines())
    m = _SPEC.search(body)
    assert m, "modelscope/requirements.txt declares no numpy band"
    assert (_ver(m.group(1)), _ver(m.group(2))) == (lo, hi), (
        f"Studio pins numpy>={m.group(1)},<{m.group(2)} but the package "
        f"pins >={'.'.join(map(str, lo))},<{'.'.join(map(str, hi))}")


def test_no_document_still_advertises_the_old_ceiling():
    """`README.md` explained the Python 3.12 ceiling as "mediapipe pins
    numpy<2", which stopped being the reason and was never the whole
    one — mediapipe 0.10.x classifies up to 3.12 and no further."""
    lo, _ = _pyproject_band()
    stale = []
    for rel in ("README.md", "modelscope/README.md", "README-PYPI.md",
                "docs/USER-GUIDE.md", "CONTRIBUTING.md"):
        p = ROOT / rel
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for m in re.finditer(r"numpy\s*<\s*([\d.]+)", line):
                if _ver(m.group(1)) <= lo:
                    stale.append(f"{rel}:{i}: {line.strip()}")
    assert not stale, ("these still tell the reader numpy is capped below "
                       f"the version the project now requires: {stale}")
