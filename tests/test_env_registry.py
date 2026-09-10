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
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUFFIXES = {".py", ".sh", ".yml", ".yaml", ".toml", ".cfg"}
_NAME = re.compile(r"\bPIXCULL_[A-Z0-9_]+\b")


def _names_in_tree() -> set:
    """Every ``PIXCULL_*`` name the tracked source mentions."""
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                         capture_output=True, text=True)
    assert out.returncode == 0, "not a git checkout"
    found = set()
    for rel in out.stdout.split():
        p = ROOT / rel
        if p.suffix.lower() not in SUFFIXES or not p.is_file():
            continue
        if p.name == "env_registry.py" or p.name == Path(__file__).name:
            continue          # the registry and this file list them all
        try:
            found.update(_NAME.findall(p.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):
            continue
    return found


def test_the_registry_matches_what_the_tree_actually_reads():
    """Both directions. A name in the code and not the registry gets no
    warning and no documentation; a name in the registry and nowhere else
    is a setting that has been removed and still looks supported."""
    from pixcull.env_registry import KNOWN

    found = _names_in_tree()
    # The data source has to be alive — comparing an empty set against
    # the registry would report perfect agreement.
    assert len(found) >= 40, (
        f"only {len(found)} PIXCULL_* names found in the tree; the scan "
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
