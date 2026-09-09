"""v3.57 — the quickstart on the PyPI page has to be a command that exists.

`README-PYPI.md` is the package's long description, so it *is* the PyPI
landing page. Its Quickstart said:

    pixcull export ./out --xmp

`export` takes `--format`, `--target` and `--out`. There is no `--xmp`,
and there never was one in this file's lifetime — the flag it wants is
the default, so the whole option was superfluous as well as wrong. The
second command a new user runs exited 2 with "No such option".

It survived because the line exists only in `README-PYPI.md`. The main
README documents export differently, so every reading of the repo's own
documentation missed it, and it went to PyPI on 2026-09-09 where it is
the first instruction a stranger sees.

These checks parse the flags out of the page and ask the CLI whether it
has them. That is deliberately weaker than running each command — a
quickstart that needs photographs, a server or a video cannot be run
here — but it is exactly the check that would have caught this, and it
needs no fixtures.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "README-PYPI.md"

#: `pixcull <command> ...` lines inside a ```bash fence.
_FENCE = re.compile(r"```bash\n(.*?)```", re.S)
_OPTION = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")


def quickstart_commands() -> list[str]:
    out = []
    for block in _FENCE.findall(PAGE.read_text(encoding="utf-8")):
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("pixcull "):
                out.append(line)
    return out


def _help(*args: str) -> str:
    """`--help` for a command, from the source tree, without installing."""
    proc = subprocess.run(
        [sys.executable, "-m", "pixcull.cli", *args, "--help"],
        cwd=ROOT, capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": "/tmp",
             "PYTHONPATH": str(ROOT), "COLUMNS": "200"})
    return proc.stdout + proc.stderr


def test_the_page_actually_carries_a_quickstart():
    """A parser that matches nothing passes for the wrong reason."""
    cmds = quickstart_commands()
    assert len(cmds) >= 4, f"only found {len(cmds)} pixcull commands: {cmds}"
    assert any(c.startswith("pixcull run") for c in cmds)


def test_every_command_on_the_pypi_page_exists():
    top = _help()
    missing = []
    for cmd in quickstart_commands():
        parts = cmd.split()
        if len(parts) < 2 or parts[1].startswith("-"):
            continue                      # `pixcull --help`
        if parts[1] not in top:
            missing.append(parts[1])
    assert not missing, (
        f"the PyPI page tells people to run commands that do not exist: "
        f"{missing}")


def test_every_option_on_the_pypi_page_exists():
    """The one that was wrong. `--xmp` read plausibly, was never a flag,
    and shipped to a package index."""
    bad = []
    for cmd in quickstart_commands():
        parts = cmd.split()
        if len(parts) < 2 or parts[1].startswith("-"):
            continue
        options = _OPTION.findall(cmd)
        if not options:
            continue
        text = _help(parts[1])
        for opt in options:
            if opt not in text:
                bad.append(f"`{cmd}` — {parts[1]} has no {opt}")
    assert not bad, (
        "the PyPI page's quickstart uses options that do not exist: "
        + "; ".join(bad))


def test_the_page_and_the_wheel_describe_the_same_package():
    """README-PYPI.md is only the landing page because pyproject points
    at it. If that ever changes, these checks are guarding a file nobody
    renders."""
    toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^readme\s*=\s*"README-PYPI\.md"', toml, re.M), (
        "pyproject no longer points at README-PYPI.md — this file is "
        "checking something that is not the PyPI page any more")


def test_both_ways_of_starting_the_cli_offer_the_same_commands():
    """v3.57 — they did not, and the difference was three commands.

    Typer registers a command when its decorator runs, and
    `if __name__ == "__main__": app()` had been sitting in the middle of
    `cli.py` — around line 2814 of 3000. `python -m pixcull.cli` reached
    that call before `serve`, `cut` and `library` were defined, so it
    offered twenty-two commands. The `pixcull` console script imports the
    whole module before calling the entry point, so it offered
    twenty-five. Two front doors to one CLI, disagreeing by three, one of
    them the command that opens the review page.

    Found by the quickstart check above asking `python -m` whether
    `serve` existed and being told no.
    """
    module_help = _help()
    module_cmds = set(re.findall(r"^\s*│?\s*([a-z][a-z0-9-]+)\s{2,}",
                                 module_help, re.M))
    src = (ROOT / "pixcull" / "cli.py").read_text(encoding="utf-8")
    declared = set(re.findall(r'^@app\.command\(\)\ndef ([a-z_][a-z0-9_]*)',
                              src, re.M))
    declared |= set(re.findall(r'^app\.add_typer\([a-z_]+,\s*name="([a-z-]+)"',
                               src, re.M))
    declared = {d.replace("_", "-") for d in declared}
    missing = sorted(d for d in declared if d not in module_cmds)
    assert not missing, (
        "`python -m pixcull.cli` does not offer these commands, which the "
        f"console script does: {missing}. Is the __main__ block still the "
        "last thing in cli.py?")


def test_the_main_block_is_the_last_thing_in_the_file():
    """The invariant behind it, stated where somebody editing will see it.

    Anything appended after `app()` is invisible to `python -m`, and the
    failure is silent — the command simply is not listed.
    """
    src = (ROOT / "pixcull" / "cli.py").read_text(encoding="utf-8")
    at = src.index('if __name__ == "__main__":')
    after = src[at:]
    assert "@app.command" not in after and "add_typer" not in after, (
        "a command is registered after the __main__ block in cli.py; "
        "`python -m pixcull.cli` will not see it")
