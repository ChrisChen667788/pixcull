"""v3.69 — the settings PixCull answers to, kept honest.

Fifty-five ``PIXCULL_*`` names are read across the tree and nothing
validated the one you set. For most that is a nuisance. For one it was a
privacy failure: whether photographs are uploaded to the cloud judge was
reachable only as ``--vlm-mode off``, while ``PIXCULL_VLM_MODEL``,
``PIXCULL_VLM_API_KEY`` and ``PIXCULL_VLM_WORKERS`` all existed — so
``PIXCULL_VLM_MODE`` was the obvious guess, one character from a real
name, and setting it did nothing without saying so.

Found by doing it. Nothing left the machine, but only because the
verdict cache was warm; the setting had no part in that.

v3.101 — the scan counted a name as read wherever it was *mentioned*,
so four entries passed that nothing reads: ``PIXCULL_HOME`` and
``PIXCULL_KEYWORD_PREFIX`` are the names of Python constants,
``PIXCULL_DATA_DIR`` was set by the Docker image and read by nothing, and
``PIXCULL_LICENSE_KEY`` appeared only in two scripts' docstrings promising
an override they never read. The user guide listed all four under
"PixCull reads these, and only these". A read is now a parsed read: an
``environ`` lookup, ``getenv``, an ``in environ`` test or a typer
``envvar`` in Python, ``$NAME`` in shell. A value the tree *sets* — the
Dockerfile, compose, the workflows, shell, Python — must be read too.
"""
import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_FULL = re.compile(r"^PIXCULL_[A-Z0-9_]+$")
_ENVIRON = re.compile(r"(^|\.)environ$")
# `$PIXCULL_X` / `${PIXCULL_X:-…}` in shell, and in a workflow's `run:` or
# a compose value; an assignment is `PIXCULL_X=` and is not matched here.
_SHELL_READ = re.compile(r"\$\{?(PIXCULL_[A-Z0-9_]+)")
_SHELL_WRITE = re.compile(r"(?:^|\s)(?:export\s+)?(PIXCULL_[A-Z0-9_]+)=")
# An assignment shown inside quotes (`echo "then export PIXCULL_X=…"`) is a
# message, not a write; writes are matched with quoted text removed.
_QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")
_YAML_WRITE = re.compile(r"^\s*-?\s*(PIXCULL_[A-Z0-9_]+)\s*[:=]")
_DOCKER_WRITE = re.compile(r"^\s*ENV\s+(PIXCULL_[A-Z0-9_]+)[=\s]")
_SKIP = {"env_registry.py", "test_env_registry.py"}   # they list every name


def _is_environ(node) -> bool:
    return bool(_ENVIRON.search(ast.unparse(node)))


def _python_reads_and_writes(src: str) -> tuple[set, set]:
    """Names this source reads from the environment, and names it sets."""
    tree = ast.parse(src)
    # `ENV = "PIXCULL_X"` and then `os.environ.get(ENV)` is a read of X;
    # so is a class attribute read back as `self.ENV`.
    consts = {}
    for n in ast.walk(tree):
        if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
                and isinstance(n.value.value, str) and _FULL.match(n.value.value)):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    consts[t.id] = n.value.value

    def name(e):
        if isinstance(e, ast.Constant) and isinstance(e.value, str):
            return e.value if _FULL.match(e.value) else None
        if isinstance(e, ast.Name):
            return consts.get(e.id)
        return consts.get(e.attr) if isinstance(e, ast.Attribute) else None

    reads, writes = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and n.args:
            f = n.func
            if isinstance(f, ast.Attribute) and _is_environ(f.value):
                if f.attr in ("get", "pop"):
                    reads.add(name(n.args[0]))
                elif f.attr == "setdefault":
                    writes.add(name(n.args[0]))
            elif ((isinstance(f, ast.Attribute) and f.attr == "getenv")
                  or (isinstance(f, ast.Name) and f.id == "getenv")):
                reads.add(name(n.args[0]))
        elif isinstance(n, ast.Subscript) and _is_environ(n.value):
            (reads if isinstance(n.ctx, ast.Load) else writes).add(name(n.slice))
        elif isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store):
            # env = os.environ.copy(); env["PIXCULL_X"] = … — a child's setting
            writes.add(name(n.slice))
        elif (isinstance(n, ast.Compare) and _is_environ(n.comparators[-1])
              and any(isinstance(o, (ast.In, ast.NotIn)) for o in n.ops)):
            reads.add(name(n.left))
        elif isinstance(n, ast.keyword) and n.arg == "envvar":
            reads.add(name(n.value))
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "dict"):
            writes.update(k.arg for k in n.keywords if k.arg and _FULL.match(k.arg))
    return reads - {None}, writes - {None}


def _uncommented(text: str) -> list[str]:
    return [l for l in text.splitlines() if not l.lstrip().startswith("#")]


def _text_reads_and_writes(text: str, kind: str) -> tuple[set, set]:
    """Shell (`sh`), Dockerfile (`docker`) or workflow/compose (`yaml`)."""
    reads, writes = set(), set()
    for line in _uncommented(text):
        reads.update(_SHELL_READ.findall(line))
        if kind == "sh":
            writes.update(_SHELL_WRITE.findall(_QUOTED.sub("", line)))
        elif kind == "docker":
            writes.update(_DOCKER_WRITE.findall(line))
        else:
            writes.update(_YAML_WRITE.findall(line))
    return reads, writes


def _reads_and_writes_in_tree() -> tuple[set, set]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                         capture_output=True, text=True)
    assert out.returncode == 0, "not a git checkout"
    reads, writes = set(), set()
    for rel in out.stdout.split():
        p = ROOT / rel
        if p.name in _SKIP or not p.is_file():
            continue
        suffix = p.suffix.lower()
        is_docker = p.name.startswith("Dockerfile")
        if suffix not in {".py", ".sh", ".yml", ".yaml"} and not is_docker:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if suffix == ".py":
            r, w = _python_reads_and_writes(text)
            reads |= r
            writes |= w
            continue
        kind = "sh" if suffix == ".sh" else "docker" if is_docker else "yaml"
        r, w = _text_reads_and_writes(text, kind)
        reads |= r
        writes |= w
    return reads, writes


def test_the_scan_tells_a_read_from_a_mention():
    """The shapes the v3.69 scan took for reads, and the ones that are."""
    src = (
        'import os\n'
        'PIXCULL_HOME = "x"                       # a constant, not a variable\n'
        'NOTE = "set PIXCULL_NOTE to change it"   # prose\n'
        'KEY = "PIXCULL_VIA_NAME"\n'
        'a = os.environ.get("PIXCULL_GET")\n'
        'b = os.environ.get(KEY)\n'
        'c = os.environ["PIXCULL_SUB"]\n'
        'd = "PIXCULL_IN" in os.environ\n'
        'e = os.getenv("PIXCULL_GETENV")\n'
        'os.environ["PIXCULL_SET"] = "1"\n'
        'os.environ.setdefault("PIXCULL_DEFAULT", "1")\n'
        'child = dict(os.environ, PIXCULL_CHILD="1")\n'
        'env = os.environ.copy()\n'
        'env["PIXCULL_COPY"] = "1"\n'
        'opt = Option(None, envvar="PIXCULL_TYPER")\n'
        'class Tether:\n'
        '    ENV = "PIXCULL_ATTR"\n'
        '    def on(self): return os.environ.get(self.ENV)\n'
    )
    reads, writes = _python_reads_and_writes(src)
    assert reads == {"PIXCULL_GET", "PIXCULL_VIA_NAME", "PIXCULL_SUB",
                     "PIXCULL_IN", "PIXCULL_GETENV", "PIXCULL_TYPER",
                     "PIXCULL_ATTR"}, reads
    assert writes == {"PIXCULL_SET", "PIXCULL_DEFAULT", "PIXCULL_CHILD",
                      "PIXCULL_COPY"}, writes
    shell = ('# export PIXCULL_COMMENTED=1\n'
             'export PIXCULL_EXPORTED=1\n'
             'echo "Then export PIXCULL_SHOWN=pixcull-notary"\n'
             'if [ -z "${PIXCULL_SHELL:-}" ]; then echo "$PIXCULL_BARE"; fi\n')
    assert _text_reads_and_writes(shell, "sh") == (
        {"PIXCULL_SHELL", "PIXCULL_BARE"}, {"PIXCULL_EXPORTED"})
    assert _text_reads_and_writes("ENV PIXCULL_DATA_DIR=/data\n", "docker") == (
        set(), {"PIXCULL_DATA_DIR"})
    assert _text_reads_and_writes(
        "      - PIXCULL_API_KEY=${PIXCULL_API_KEY:-}\n", "yaml") == (
        {"PIXCULL_API_KEY"}, {"PIXCULL_API_KEY"})


def test_the_registry_matches_what_the_tree_actually_reads():
    """Both directions. A name in the code and not the registry gets no
    warning and no documentation; a name in the registry and nowhere else
    is a setting that has been removed and still looks supported."""
    from pixcull.env_registry import KNOWN

    found, _ = _reads_and_writes_in_tree()
    # The data source has to be alive — comparing an empty set against
    # the registry would report perfect agreement.
    assert len(found) >= 40, (
        f"only {len(found)} PIXCULL_* reads found in the tree; the scan "
        "is broken, not the registry")

    missing = sorted(found - set(KNOWN))
    assert not missing, (
        f"read by the code, absent from the registry: {missing}. "
        "Add them to pixcull/env_registry.KNOWN with what they do, or "
        "they warn as typos and appear in no documentation.")

    stale = sorted(set(KNOWN) - found)
    assert not stale, (
        f"in the registry, read by nothing: {stale}. A setting that no "
        "longer exists must not keep looking supported.")


def test_nothing_sets_a_variable_nothing_reads():
    """`ENV PIXCULL_DATA_DIR=/data` sat in the Docker image and its
    compose file and changed nothing: a setting that looks load-bearing to
    anyone reading the deployment and is not."""
    reads, writes = _reads_and_writes_in_tree()
    # Seven today (compose, the workflows, shell, Python); far fewer means
    # the scan broke, not that the tree stopped setting things.
    assert len(writes) >= 5, (
        f"only {len(writes)} PIXCULL_* assignments found; the scan is broken")
    dead = sorted(writes - reads)
    assert not dead, f"set by the tree, read by nothing: {dead}"


def test_the_upload_switch_is_reachable_from_the_environment():
    """The specific defect. `--vlm-mode` was a flag and nothing else, so
    a person scripting PixCull — CI, a wrapper, a cron job — had no way
    to force the on-device path except by editing the command line."""
    import typer.main
    from pixcull.cli import app

    run = typer.main.get_command(app).commands["run"]
    param = next((p for p in run.params if "--vlm-mode" in p.opts), None)
    assert param is not None, "pixcull run has no --vlm-mode"
    assert param.envvar == "PIXCULL_VLM_MODE", (
        "--vlm-mode is not readable from PIXCULL_VLM_MODE; the setting "
        "that decides whether photographs are uploaded is command-line "
        f"only (envvar={param.envvar!r})")


def test_a_near_miss_on_a_privacy_setting_says_what_is_at_stake():
    """"Unknown option" is not enough when the option being ignored is
    the one keeping photographs on the machine."""
    from pixcull.env_registry import warn_about_unknown_variables
    import io

    buf = io.StringIO()
    n = warn_about_unknown_variables({"PIXCULL_VLM_MOD": "off"}, stream=buf)
    text = buf.getvalue()
    assert n == 1
    assert "PIXCULL_VLM_MODE" in text, "the near match is not offered"
    assert "photographs" in text, (
        "the warning does not say what being ignored costs here")


def test_a_correct_environment_says_nothing():
    """A warning that fires on a correct setup is a warning people learn
    to scroll past."""
    from pixcull.env_registry import KNOWN, warn_about_unknown_variables
    import io

    buf = io.StringIO()
    n = warn_about_unknown_variables({k: "1" for k in KNOWN}, stream=buf)
    assert n == 0 and buf.getvalue() == "", buf.getvalue()


def test_the_warning_does_not_advertise_a_command_that_does_not_exist():
    """Written after doing exactly that: the first draft of this message
    told the reader to run `pixcull doctor`, which has never existed —
    the v3.67 defect, committed inside the fix for a different one. The
    v3.67 sweep reads documents, so it could not have caught a string
    living in the product."""
    import typer.main
    from pixcull import env_registry
    from pixcull.cli import app

    commands = set(typer.main.get_command(app).commands)
    src = Path(env_registry.__file__).read_text(encoding="utf-8")
    body = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
    bad = [m for m in re.findall(r"`pixcull ([a-z][a-z-]*)", body)
           if m not in commands]
    assert not bad, f"names a command the CLI does not have: {bad}"


def test_the_guide_the_warning_points_at_lists_every_variable():
    """The warning tells the reader where the full list is. If that
    document does not carry it, the message is the same kind of
    unreachable promise as the setting it exists to report."""
    from pixcull import env_registry
    from pixcull.env_registry import KNOWN

    src = Path(env_registry.__file__).read_text(encoding="utf-8")
    named = re.findall(r"listed in (\S+\.md)", src)
    assert named, "the warning no longer names a document"

    guide = ROOT / named[0]
    assert guide.exists(), f"the warning points at {named[0]}, which is absent"
    text = guide.read_text(encoding="utf-8")
    absent = sorted(k for k in KNOWN if k not in text)
    assert not absent, (
        f"{named[0]} is missing {len(absent)} of the settings the warning "
        f"promises it lists: {absent[:6]}")
