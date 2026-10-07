#!/usr/bin/env python3
"""v3.94.1 — can the package install, on every platform and Python we
advertise, on a machine with no compiler?

3.94.0 could not, on Windows with Python 3.13: `imagededup` has wheels for
3.9-3.12 only and a mandatory C++ extension, and nothing in CI noticed
because every runner has a compiler. This resolves the whole dependency
tree for each (platform, Python) the way an installer on that machine
would, from metadata only, installing nothing:

    uv pip compile --python-platform P --python-version V --no-build

uv rather than `pip install --dry-run --platform`: pip's --platform changes
which wheel tags it accepts but evaluates environment markers for the
machine pip runs on. On the Linux CI runner that pulled torch's
`platform_system == "Linux"` CUDA dependencies into the Windows and macOS
resolutions and failed them on nvidia-nccl-cu12; on a Mac it would have
left them out of the Linux one. uv evaluates markers for the target.

Binary-only is stricter than a user's installer: a dependency that ships
only an sdist still installs without a compiler if it is pure Python
(`openai-clip`, under pyiqa, is one). So when resolution stops on a
package with no wheel, its sdist is built here; a universal `py3-none-any`
wheel means pure Python, and it is offered to the next resolution. Anything
else needs a compiler on that platform, and the check fails.

Usage:  python scripts/check_installs_without_compiler.py dist/pixcull-*.whl
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = "https://pypi.org/simple"   # serves PEP 658 metadata; resolving is cheap

#: Each platform as uv names it. Linux is a glibc 2.28 machine; uv accepts
#: every older manylinux tag for it, which pip's --platform did not.
#: tests/test_installs_without_compiler.py holds this list to the claims.
PLATFORMS = {
    "Windows x64": "x86_64-pc-windows-msvc",
    "macOS, Apple Silicon": "aarch64-apple-darwin",
    "Linux x86_64": "x86_64-manylinux_2_28",
}

NO_WHEEL = re.compile(r"Wheels are required for `([^`]+)` because building from source is disabled")


def advertised_pythons() -> list[str]:
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    return sorted(c.rsplit("::", 1)[1].strip() for c in meta["classifiers"]
                  if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c))


def _pip(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "pip", *args, "--disable-pip-version-check"],
                          capture_output=True, text=True)


def is_universal_pure(wheel_name: str) -> bool:
    """A wheel any Python 3 on any platform accepts: no ABI, no platform,
    and a python tag that is not one version's. `cp312-none-any` is not —
    it would satisfy the Python it was built on and be refused by the
    others, which the check would then report as a compiler dependency."""
    parts = wheel_name[:-len(".whl")].split("-")
    return (wheel_name.endswith(".whl") and len(parts) >= 5
            and parts[-1] == "any" and parts[-2] == "none"
            and set(parts[-3].split(".")) <= {"py3", "py2"})


def _build_pure(name: str, work: Path, pure: Path) -> str | None:
    """Build `name` from its sdist. Return the wheel's tag if it is pure."""
    src = work / f"sdist-{name}"
    got = _pip("download", "--no-deps", "--no-binary=:all:", "-d", str(src), "-i", INDEX, name)
    if got.returncode:
        return None
    out = work / f"wheel-{name}"
    built = _pip("wheel", "--no-deps", "-w", str(out), *map(str, src.iterdir()))
    wheels = list(out.glob("*.whl")) if not built.returncode else []
    if len(wheels) == 1 and is_universal_pure(wheels[0].name):
        wheels[0].rename(pure / wheels[0].name)
        return wheels[0].name
    return None


def _uv() -> list[str]:
    exe = shutil.which("uv")
    return [exe] if exe else [sys.executable, "-m", "uv"]


def resolve(wheel: str, platform: str, python: str, work: Path, pure: Path,
            built: dict[str, str]) -> tuple[bool, str]:
    req = work / "requirement.in"
    path = Path(wheel)
    req.write_text(f"pixcull @ {path.resolve().as_uri()}\n" if path.is_file()
                   else f"{wheel}\n", encoding="utf-8")
    for _ in range(6):
        r = subprocess.run(
            [*_uv(), "pip", "compile", str(req), "--python-platform", platform,
             "--python-version", python, "--no-build", "--index-url", INDEX,
             "--find-links", str(pure), "--quiet", "--no-header", "-o", str(work / "out.txt")],
            capture_output=True, text=True)
        if r.returncode == 0:
            return True, ""
        m = NO_WHEEL.search(r.stdout + r.stderr)
        if not m:
            return False, ((r.stderr or r.stdout).strip().splitlines() or ["uv failed"])[-1]
        name = m.group(1)
        if name in built:
            return False, f"{name}: no wheel, and the pure build did not satisfy it"
        tag = _build_pure(name, work, pure)
        if tag is None:
            return False, (f"{name} has no wheel for this platform and Python, "
                           "and its sdist does not build pure — a compiler is required")
        built[name] = tag
    return False, "gave up after six rounds"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    wheel = argv[0]
    pythons = advertised_pythons()
    if not pythons:
        # A check with nothing to check would pass; pyproject.toml has
        # lost its Python classifiers, which is its own failure.
        print("FAIL  pyproject.toml advertises no Python version — nothing was checked")
        return 1
    failures = 0
    built: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        pure = work / "pure"
        pure.mkdir()
        for label, platform in PLATFORMS.items():
            for python in pythons:
                ok, why = resolve(wheel, platform, python, work, pure, built)
                print(f"{'OK  ' if ok else 'FAIL'}  {label:22} Python {python}"
                      + ("" if ok else f"  — {why}"), flush=True)
                failures += not ok
    if built:
        print("sdist-only dependencies that build pure: "
              + ", ".join(f"{k} ({v})" for k, v in sorted(built.items())))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
