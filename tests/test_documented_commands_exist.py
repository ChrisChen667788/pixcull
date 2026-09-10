"""v3.67 — the README named a command that has never existed.

`pixcull deliver` was the headline of v2.99's entry in **What's new**:
"`pixcull deliver` writes the folder you actually hand over". The command
v2.99 actually shipped is `pixcull view-folder`, which is what v2.99's own
commit message says. The line was written in v3.53 — the version whose
entire purpose was fixing a public description that had gone stale — and
it stayed on the front page for twelve releases and went to PyPI with
3.53.1. It left in v3.65 as a side effect of rewriting that section, not
because anybody noticed.

`tests/test_readme_claims_inventory.py` exists for exactly this and could
not have caught it: `readme_claims()` splits the README on
`## What you get today` and reads only that section, so every command
named anywhere else in the file is invisible to it by construction.

The same class, found a third and fourth time by the sweep that wrote
this file:

* `pixcull export --xmp` — v3.57 found this in `README-PYPI.md` and fixed
  it there. `docs/USER-GUIDE.md` carried the identical line and still did
  today, so the second command a Chinese-reading user is told to run
  exited 2 with `No such option: --xmp`. v3.52's defect exactly: the same
  claim, corrected on one front door and not the other.
* `pixcull view-folder` on an empty selection (v3.58) and
  `pixcull export --xmp` (v3.57) were both found by hand, one at a time.

So this checks the whole surface instead: every `pixcull …` invocation in
every public document, resolved against the live CLI — walking into
sub-command groups such as `m3`, because a checker that stops at the
group reports `pixcull m3 eval --labels` as a bad flag on `m3`.

It asks the installed program, not the source tree. A quickstart is a
promise made to somebody who has no other information.
"""
import functools
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Everything a stranger might read and type. Roadmap and charter files are
#: deliberately absent: they quote broken commands as the defect under
#: discussion, and correcting those quotes would erase the record.
PUBLIC_DOCS = (
    "README.md",
    "modelscope/README.md",
    "README-PYPI.md",
    "CONTRIBUTING.md",
    "docs/USER-GUIDE.md",
)

#: `pixcull` followed by its words. Stops at the end of the line, so a
#: sentence that mentions "pixcull" and wraps does not swallow the next
#: line's prose.
_INVOCATION = re.compile(r"pixcull((?:[ \t]+[A-Za-z0-9_./~$<>{}\[\]*-]+)*)")
_VERB = re.compile(r"^[a-z][a-z0-9-]*$")
_FLAG = re.compile(r"^--[a-z][a-z0-9-]*$")


@functools.lru_cache(maxsize=None)
def _root():
    """The command tree as Click holds it.

    v3.67 fixup — the first cut parsed `--help` output for lines starting
    with `│`, which is Rich's box drawing. On this laptop that works; on
    the CI runner Typer renders without it, so `_subcommands("")` came
    back empty, every documented command resolved to "not a command", and
    three tests went red at once.

    They went red rather than green, which was the point of writing
    `test_the_cli_is_importable_at_all` separately — a sweep that finds
    nothing must not read as a sweep that found nothing wrong. But the
    right source was never the rendered text: help output wraps, hides
    options behind a narrower terminal, and changes with the Rich
    version. Click's own tree is what the program will actually accept.
    """
    import typer.main
    from pixcull.cli import app
    return typer.main.get_command(app)


def _node(path: str):
    """The command at `path` ("" is the root), or None."""
    cmd = _root()
    for part in path.split():
        children = getattr(cmd, "commands", None)
        if not children or part not in children:
            return None
        cmd = children[part]
    return cmd


@functools.lru_cache(maxsize=None)
def _subcommands(path: str) -> frozenset:
    cmd = _node(path)
    return frozenset(getattr(cmd, "commands", {}) or {})


@functools.lru_cache(maxsize=None)
def _flags(path: str) -> frozenset:
    cmd = _node(path)
    if cmd is None:
        return frozenset()
    out = set()
    for param in getattr(cmd, "params", []):
        out.update(o for o in getattr(param, "opts", []) if o.startswith("--"))
        out.update(o for o in getattr(param, "secondary_opts", [])
                   if o.startswith("--"))
    out.add("--help")
    return frozenset(out)


def _scan(root: Path = None):
    """(kind, what, file, line) for everything the CLI would reject."""
    root = root or ROOT
    problems = []
    for rel in PUBLIC_DOCS:
        p = root / rel
        if not p.exists():
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for m in _INVOCATION.finditer(line):
                words = m.group(1).split()
                if not words:
                    continue
                path, i = [], 0
                while i < len(words) and words[i] in _subcommands(" ".join(path)):
                    path.append(words[i])
                    i += 1
                if not path:
                    # `pixcull <something>` where something is a plain word
                    # and not a command. A path, a placeholder or a flag is
                    # fine; a bare verb is the `deliver` shape.
                    if _VERB.match(words[0]):
                        problems.append(("command", f"pixcull {words[0]}", rel, n))
                    continue
                joined = " ".join(path)
                for w in words[i:]:
                    if _FLAG.match(w) and w not in _flags(joined) \
                            and w not in _flags(""):
                        problems.append(
                            ("flag", f"pixcull {joined} {w}", rel, n))
    return problems


def test_the_cli_is_importable_at_all():
    """Stated separately so the sweep below cannot pass by finding
    nothing. If the command tree comes back empty, every invocation in
    every document resolves to "not a command" — and a sweep that finds
    nothing must not read as a sweep that found nothing wrong.

    This is not hypothetical. The first cut of this file read the tree
    out of `--help` text, and on the CI runner that output has no box
    drawing in it, so the tree was empty and three tests failed at once.
    That is the behaviour this assertion is for."""
    assert _subcommands(""), "the CLI reports no commands at all"
    assert len(_subcommands("")) > 10, (
        f"only {len(_subcommands(''))} top-level commands — the tree "
        "looks truncated")

    # And it has to run as a program, not only import as a module.
    r = subprocess.run([sys.executable, "-m", "pixcull", "--help"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, (
        f"python -m pixcull --help exited {r.returncode}: {r.stderr[:200]}")


def test_every_documented_command_exists():
    missing = [(w, f, n) for kind, w, f, n in _scan() if kind == "command"]
    assert not missing, (
        "these documents tell a reader to run a command the CLI does not "
        "have:\n  " + "\n  ".join(f"{w}   ({f}:{n})" for w, f, n in missing))


def test_every_documented_flag_exists():
    bad = [(w, f, n) for kind, w, f, n in _scan() if kind == "flag"]
    assert not bad, (
        "these documents pass a flag the command does not accept — the "
        "reader gets `No such option` and exit 2:\n  "
        + "\n  ".join(f"{w}   ({f}:{n})" for w, f, n in bad))


def test_the_sweep_reaches_past_the_claims_section():
    """The reason the older gate missed `pixcull deliver`.
    `test_readme_claims_inventory.py` splits the README on a section
    header and reads only what follows, so a command named anywhere else
    is invisible to it. This one has to see the whole file.

    Checked by behaviour, not by grepping this file for the header's
    name — the first cut did that and failed on its own assertion
    string, which is the same shape as the "guard satisfied by its own
    prose" defect this repository keeps finding. A test that greps
    itself is testing its own comments.
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## What you get today" in readme, "the claims section is gone"
    # Plant a command that does not exist ABOVE that header — i.e. in the
    # half of the README the older gate never reads — and require the
    # sweep to find it.
    import tempfile, shutil
    with tempfile.TemporaryDirectory() as tmp:
        fake = Path(tmp)
        (fake / "README.md").write_text(
            readme.replace("## What you get today",
                           "Run `pixcull nosuchverb` first.\n\n"
                           "## What you get today", 1),
            encoding="utf-8")
        for rel in PUBLIC_DOCS[1:]:
            src, dst = ROOT / rel, fake / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                shutil.copy(src, dst)
        found = [w for kind, w, _f, _n in _scan(fake) if kind == "command"]
    assert any("nosuchverb" in w for w in found), (
        "the sweep did not see a bogus command placed above "
        "'## What you get today' — it has been narrowed to the same "
        "section that hid `pixcull deliver` for twelve releases")


def test_the_two_commands_this_was_built_from_stay_fixed():
    """Named, because a general sweep can be quietly narrowed and still
    look green. These two are the measurements."""
    assert _node("view-folder") is not None, (
        "pixcull view-folder is gone — it is what v2.99 actually shipped "
        "and what the README's `deliver` should have said")
    assert _node("deliver") is None, (
        "a `deliver` command now exists; update this test and the history "
        "note in it rather than deleting them")
    assert "--xmp" not in _flags("export"), (
        "pixcull export now takes --xmp; the docs corrected in v3.57 and "
        "v3.67 said it did not")
    assert "--target" in _flags("export")
