"""v3.94.1 — the check that the package installs without a compiler has to
be the one CI runs, and has to cover what the project claims.

The check itself (scripts/check_installs_without_compiler.py) needs the
network, so it runs as its own CI job. What is held here, offline: that
the job runs it (parsed, not grepped — a command in a comment is not a
command), that it covers every advertised Python and the platform that
broke, that the README's platform badge claims nothing it does not
check, and that it reads pip's failure in the words pip actually uses.
"""
from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_installs_without_compiler.py"


def _check():
    spec = importlib.util.spec_from_file_location("_check_installs", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _job_commands() -> list[str]:
    jobs = yaml.safe_load((ROOT / ".github" / "workflows" / "tests.yml")
                          .read_text("utf-8"))["jobs"]
    out = []
    for job in jobs.values():
        lines = [re.sub(r"(^|\s)#.*$", "", line)
                 for step in job.get("steps", [])
                 for line in (step.get("run") or "").splitlines()]
        out.append("\n".join(l for l in lines if l.strip()))
    return out


def test_ci_runs_the_check_on_the_wheel_it_builds():
    jobs = [c for c in _job_commands()
            if "scripts/check_installs_without_compiler.py" in c]
    assert jobs, "no CI job runs scripts/check_installs_without_compiler.py"
    job = jobs[0]
    assert "python -m build --wheel" in job, (
        "the check must run on a wheel built from this tree, not on the "
        "last release")
    assert job.index("python -m build") < job.index("check_installs_without_compiler"), job


def test_it_covers_every_advertised_python():
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    advertised = sorted(c.rsplit("::", 1)[1].strip() for c in meta["classifiers"]
                        if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c))
    assert advertised and "3.13" in advertised
    assert _check().advertised_pythons() == advertised


def _tags() -> list[str]:
    return list(_check().PLATFORMS.values())


def test_it_covers_the_platform_that_broke():
    assert "x86_64-pc-windows-msvc" in _tags()


def test_it_resolves_for_the_target_not_for_the_runner():
    """Its first CI run used `pip install --dry-run --platform`, which keeps
    evaluating environment markers for the machine pip runs on: on the
    Linux runner, torch's Linux-only CUDA dependencies were pulled into the
    Windows and macOS resolutions and failed them on nvidia-nccl-cu12. (A
    first local version also gave pip a single PEP 600 manylinux tag, which
    pip does not expand, and blamed safetensors.) uv evaluates markers for
    the target and expands manylinux compatibility itself."""
    import inspect
    src = inspect.getsource(_check().resolve)
    code = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
    assert '"--python-platform"' in code and '"compile"' in code, code
    assert '"--platform"' not in code

def test_the_platform_badge_claims_only_what_is_checked():
    """3.94.0's badge said "macOS — Apple Silicon & Intel". torch has had
    no Intel macOS wheel since 2.2.2 and the floor is 2.7, so on an Intel
    Mac `pip install pixcull` cannot succeed; nothing checked the claim."""
    readme = (ROOT / "README.md").read_text("utf-8")
    badge = re.search(r'<img alt="Platform" src="([^"]+)"', readme)
    assert badge, "the README has no Platform badge to check"
    text = badge.group(1).replace("%20", " ").replace("%26", "&").lower()
    platforms = _tags()
    # Exact platform tags: "intel" once matched manylinux_2_28_x86_64 here
    # and passed a badge that claimed Intel Macs.
    claims = {"apple silicon": r"aarch64-apple-darwin",
              "intel": r"x86_64-apple-darwin",
              "windows": r"x86_64-pc-windows-msvc",
              "linux": r"x86_64-(manylinux_\d+_\d+|unknown-linux-gnu)"}
    for word, tag in claims.items():
        if word in text:
            assert any(re.fullmatch(tag, p) for p in platforms), (
                f"the Platform badge claims {word!r} and the install check does "
                f"not cover it ({sorted(_check().PLATFORMS)})")


def test_it_reads_the_failure_as_uv_writes_it():
    """Copied from uv 0.12 resolving 3.94.0 (imagededup, no cp313 wheel) and
    the 3.94.1 tree before the pure build (openai-clip, sdist only), both
    for Windows / Python 3.13 with --no-build."""
    pattern = _check().NO_WHEEL
    no_cp313 = (
        "hint: You require CPython 3.13 (`cp313`), but we only found wheels for "
        "`imagededup` (v0.3.2) with the following Python ABI tags: `cp38`, `cp39`, `cp310`\n\n"
        "hint: Wheels are required for `imagededup` because building from source is "
        "disabled for all packages (i.e., with `--no-build`)\n")
    sdist_only = (
        "  cause: Because all versions of openai-clip have no usable wheels and "
        "pyiqa>=0.1.15 depends on openai-clip, we can conclude that pyiqa>=0.1.15 "
        "cannot be used.\n\n"
        "hint: Wheels are required for `openai-clip` because building from source is "
        "disabled for all packages (i.e., with `--no-build`)\n")
    got = [pattern.search(t).group(1) for t in (no_cp313, sdist_only)]
    assert got == ["imagededup", "openai-clip"], got


def test_only_a_universal_wheel_counts_as_pure():
    """Found in review: `-none-any` alone accepted `cp312-none-any`, which
    only the Python it was built on accepts."""
    pure = _check().is_universal_pure
    assert pure("openai_clip-1.0.1-py3-none-any.whl")
    assert pure("six-1.16.0-py2.py3-none-any.whl")
    assert not pure("pkg-1.0-cp312-none-any.whl")
    assert not pure("pkg-1.0-cp312-cp312-manylinux_2_28_x86_64.whl")
    assert not pure("pkg-1.0-py3-none-win_amd64.whl")


def test_a_check_with_no_python_to_check_fails(monkeypatch):
    """Found in review: with no Python classifiers the loop ran zero times
    and the job went green having checked nothing."""
    check = _check()
    monkeypatch.setattr(check, "advertised_pythons", lambda: [])
    monkeypatch.setattr(check, "resolve", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("nothing should be resolved")))
    assert check.main(["dist/pixcull-0-py3-none-any.whl"]) != 0
