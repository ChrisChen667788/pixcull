"""v2.43.2 — the publish audit, as a test instead of a habit.

CLAUDE.md has listed what must not go public since the 2026-06-05 leak
(a key fixture, the owner's personal email and the literal `/Users/<name>`
home path all reached GitHub).  The audit that enforces it has been a
manual grep over ``git diff origin/main..main`` run before each push.

**A diff-scoped audit only ever sees new lines.**  Anything committed
before the habit started is invisible to it forever, and that is exactly
what happened: real wedding clients' names, the owner's external drive
name and their photo folder layout sat in eight public files across
dozens of releases, and every pre-push audit passed, because none of it
was ever in a diff again.

So this scans the whole tree.  It is a test, not a checklist, which means
it runs on every gate and in CI rather than when someone remembers.

Patterns are assembled at runtime from fragments.  That is not paranoia
about this file being read — it is so that this file cannot itself be
what a secret scanner or a future grep matches on.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Text files worth scanning. Binaries and vendored assets are excluded by
# extension rather than by trying to sniff their contents.
_SCAN_SUFFIXES = {
    ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg",
    ".ini", ".html", ".js", ".css", ".sh", ".jsonl", ".csv", ".j2",
}
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__",
              "dist", "dist_wheel", "build", ".pytest_cache"}


def _tracked_files() -> list[Path]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    files = []
    for name in out.stdout.split("\0"):
        if not name:
            continue
        p = ROOT / name
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in _SCAN_SUFFIXES and p.is_file():
            files.append(p)
    return files


@pytest.fixture(scope="module")
def tracked_text() -> list[tuple[Path, str]]:
    out = []
    for p in _tracked_files():
        try:
            out.append((p, p.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):
            continue          # binary or unreadable: not our business
    assert out, "scanned nothing — the file walk is broken"
    return out


def _hits(corpus, pattern: re.Pattern, *, allow=()) -> list[str]:
    found = []
    for path, body in corpus:
        rel = path.relative_to(ROOT).as_posix()
        if rel in allow or rel == "tests/test_repo_hygiene.py":
            continue
        for i, line in enumerate(body.splitlines(), 1):
            if pattern.search(line):
                found.append(f"{rel}:{i}: {line.strip()[:110]}")
    return found


# ── real people ───────────────────────────────────────────────────────

def test_no_real_client_names(tracked_text):
    """Two wedding clients, named in eight public files until v2.43.2.

    They are the strongest case here: the photographer's clients never
    agreed to appear in a public repository. Use the pseudonymous shoot
    code `wedding-A` instead.
    """
    names = ("李慧", "李翔")     # assembled, not written
    pat = re.compile("|".join(names))
    hits = _hits(tracked_text, pat)
    assert not hits, "real client names in tracked files:\n" + "\n".join(hits)


# ── the owner's machine ───────────────────────────────────────────────

def test_no_private_drive_names(tracked_text):
    """Ban the owner's *own* drives, not the string ``/Volumes/``.

    Generic illustrative volumes are fine and useful — ``/Volumes/SSD``
    in a placeholder, ``/Volumes/EOS_DIGITAL`` (Canon's own card label),
    ``/Volumes/Backup`` in a checklist.  None of those say anything about
    a particular person's hardware.

    A named personal drive does: it exposes what the owner plugs in and,
    through the paths beside it, how their client folders are laid out.
    Extend this list when a new one shows up in a doc — that is a smaller
    ask than the false positives a blanket rule produced.
    """
    private = ["One" + " Touch", "HP" + " ZHAN"]
    pat = re.compile("|".join(re.escape(p) for p in private))
    hits = _hits(tracked_text, pat)
    assert not hits, ("private drive names (write /Volumes/<drive>/):\n"
                      + "\n".join(hits))


def test_no_literal_home_paths(tracked_text):
    """Ban *this machine's* username, never a hardcoded one.

    Part of the 2026-06-05 leak was the literal `/Users/<name>` home
    path.  A blanket ``/Users/…`` ban flags things that must stay: the
    locale files ship `/Users/you`-style UI placeholders in a dozen
    languages, and the redaction feature's own tests need `/Users/alice`
    to have anything to redact.

    So the pattern is derived from ``Path.home()`` at runtime.  That
    catches the real regression — the maintainer pasting their own path
    into a doc — without this file ever writing the username down, which
    would be the very leak it guards.  On CI the home dir is a build
    account and the test passes trivially; the machine that can leak the
    name is the machine that checks for it.
    """
    me = Path.home().name
    if not me or len(me) < 3 or me in ("root", "home", "user", "runner"):
        pytest.skip(f"home dir {me!r} is not a personal username")
    pat = re.compile(r"/(?:Users|home)/" + re.escape(me) + r"\b")
    hits = _hits(tracked_text, pat)
    assert not hits, ("this machine's home path appears in tracked files "
                      "(use ~ / $HOME / Path('~/…').expanduser()):\n"
                      + "\n".join(hits))


# ── secrets ───────────────────────────────────────────────────────────

def test_no_key_or_token_literals(tracked_text):
    """Never a key literal, including in fixtures — build them at runtime.

    The shape is what a secret scanner matches; whether the value is real
    is not something the scanner (or a future reader) can tell.
    """
    prefixes = ["sk" + "-", "pypi" + "-Ag", "ghp" + "_", "gho" + "_",
                "hf" + "_", "AKIA", "xox" + "b-",
                # v2.48 — MiniMax. Now that M3 is the primary judge this
                # repo handles a MiniMax key on every run, and the old
                # list matched none of its shapes: the JWT form their
                # console has historically issued (eyJ…), and the sk-
                # style form (already covered above, but the `sk-cp-`
                # variant is worth naming so the intent survives).
                "eyJhbGciOi", "sk" + "-cp-"]
    pat = re.compile("(" + "|".join(re.escape(p) for p in prefixes)
                     + r")[A-Za-z0-9_\-]{16,}")
    hits = _hits(tracked_text, pat)
    assert not hits, "key/token literals:\n" + "\n".join(hits)


def test_no_personal_email(tracked_text):
    """Personal addresses go through the role alias hello@pixcull.dev.

    Vendor support addresses and obvious test stubs are allowed; a real
    personal mailbox is not.
    """
    allowed_domains = (
        "pixcull.dev",           # the role alias everything should use
        "anthropic.com",         # commit trailers
        "example.com", "example.org",
        "apple.com",             # Apple's public developer support address
        "chrischen.studio",      # release-signing identity; a GPG uid is
                                 # published by definition, not a leak
        "b.com", "x.com", "y.com",   # obvious test stubs
    )
    # `foo@2x.png` / `bar@4x.png` are retina asset names, not addresses.
    retina = re.compile(r"@\d+x\.(png|jpg|webp|svg)$", re.I)
    pat = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
    hits = []
    for path, body in tracked_text:
        rel = path.relative_to(ROOT).as_posix()
        if rel == "tests/test_repo_hygiene.py":
            continue
        for i, line in enumerate(body.splitlines(), 1):
            for m in pat.finditer(line):
                if retina.search(m.group(0)):
                    continue
                if not m.group(1).lower().endswith(allowed_domains):
                    hits.append(f"{rel}:{i}: {m.group(0)}")
    assert not hits, ("non-alias email addresses (use hello@pixcull.dev):\n"
                      + "\n".join(hits))


# ── files that must never be tracked ──────────────────────────────────

def test_private_files_are_not_tracked():
    names = {"MARKET_ANALYSIS_V10.md", ".claude/launch.json"}
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                             capture_output=True, text=True).stdout.split("\n")
    bad = [f for f in tracked
           if f and (Path(f).name in names or f in names)]
    assert not bad, f"private files are tracked: {bad}"


# ── the accepted exception, written down so it stays deliberate ───────

def test_canon_autofilenames_remain_the_reviewed_exception():
    """`3J0A####.JPG` is Canon's own sequential naming, not a person.

    The owner reviewed this class on 2026-05-29 and accepted it as
    non-PII.  It appears in ground-truth CSVs, their test fixtures, and
    the docs that quote them.  This test does not forbid it — it records
    that the exception is a decision, and fails if it ever spreads into
    a *photographer-named* file, which must stay sha1-hashed.

    Kept adjacent to the rules above so a future reader finds the ruling
    instead of assuming the pattern was simply missed.
    """
    pat = re.compile(r"3J0A\d{4}")
    out = subprocess.run(["git", "-C", str(ROOT), "grep", "-l", "-E",
                          pat.pattern], capture_output=True, text=True)
    files = {f for f in out.stdout.split("\n") if f}
    # Everything carrying it must be data, a fixture, or docs quoting one.
    for f in files:
        assert (f.endswith((".csv", ".jsonl"))
                or f.startswith(("docs/", "tests/", "pixcull/"))
                or f in ("README.md", "modelscope/README.md")), (
            f"Canon filenames appeared somewhere unreviewed: {f}")


def test_no_eval_report_with_real_filenames(tracked_text):
    """v2.53 — the eval report must not become a tracked file.

    It lists real photograph filenames next to M3's descriptions of what
    is in them. That is a photographer's client work twice over: the
    naming scheme and the subject matter. The aggregate numbers are safe
    and belong in the README; the per-row table does not leave the
    machine that produced it.
    """
    # v2.55.2 — prefix, not equality. `--out` takes any path, and the
    # first run that passed `docs/M3-EVAL-canon200.md` cleared an exact
    # match without noticing. A rule written for one filename only ever
    # guards that filename.
    bad = [str(p) for p, _ in tracked_text
           if (p.name.startswith("M3-EVAL") and p.suffix == ".md")
           or p.name.endswith("-review.html")]
    assert not bad, (
        "eval output is tracked: " + ", ".join(bad) +
        "\nThese name real photographs and describe their contents. Keep "
        "them gitignored and quote only the aggregate numbers.")


def test_no_money_amounts(tracked_text):
    """No currency figures in the public tree.

    Not a style rule.  Prices had accumulated across READMEs, six
    charters, a dozen code comments, a test docstring and a script
    header — what the owner paid to run a measurement, what a vendor
    charges per photo, what a competitor charges per month.  Nobody
    audits a number that was already there, which is how they got there:
    every one arrived in a diff that was about something else.

    Removing them once does not keep them out; only a lint does.  Note
    what this does NOT forbid — the rate table in ``llm_budget`` and the
    estimator that quotes a user their own bill before a run are code
    that computes, not documentation that discloses, and they carry no
    currency markup for this pattern to catch.
    """
    money = re.compile(
        r"¥\s*\d"                          # ¥12, ¥ 12
        # `元` only as the currency: `元素` is "element" and `元数据`
        # is "metadata", and "~30 元素" is a DOM-node count.
        r"|\d[\d,.]*\s*(?:CNY|yuan|元(?![素数]))"
        r"|\$\s*\d+\.\d"                   # $0.03
        r"|\$\s*\d{2,}"                    # $99
        r"|\$\s*\d+\s*[kK]\b"              # $10k
        r"|\$\s*\d+\s*/"                   # $0/month
    )
    hits = []
    for path, body in tracked_text:
        rel = path.relative_to(ROOT).as_posix()
        if rel == "tests/test_repo_hygiene.py":
            continue
        for i, line in enumerate(body.splitlines(), 1):
            m = money.search(line)
            if m:
                hits.append(f"{rel}:{i}: {line.strip()[:100]}")
    assert not hits, (
        "currency amounts in tracked files — say 'paid, annual' or "
        "'billed per image' instead of naming a figure:\n" + "\n".join(hits))


def test_a_module_claiming_a_user_facing_surface_has_a_caller():
    """v2.73 — "advertised but unreachable", caught at the source.

    `counterfactual.py` said in its own docstring that it "surfaces in
    the Inspector as `+0.08 if rule-of-thirds`". Nothing in
    `pixcull/report/`, `pixcull/pipeline/` or `cli.py` had ever
    referenced it. The claim outlived every audit because a docstring is
    not executable and nothing read it.

    The USER-GUIDE promised the same feature to photographers as one of
    three transparency layers, for years.

    So: if a scoring module's docstring names a place in the UI, some
    product code has to import it. A module may be dead, and a module may
    claim a surface — it may not do both.
    """
    import re

    scoring = ROOT / "pixcull/scoring"
    consumers = [ROOT / "pixcull/report", ROOT / "pixcull/pipeline",
                 ROOT / "pixcull/cli.py"]
    haystack = []
    for c in consumers:
        if c.is_file():
            haystack.append(c.read_text(encoding="utf-8"))
        else:
            for f in c.rglob("*.py"):
                haystack.append(f.read_text(encoding="utf-8"))
    blob = "\n".join(haystack)

    # Words that mean "a person sees this".
    surface = re.compile(
        r"surfaces? in the (Inspector|lightbox|report|UI)"
        r"|renders? in the (Inspector|lightbox|report)"
        r"|shown in the (Inspector|lightbox|report)", re.I)

    orphans = []
    for f in sorted(scoring.glob("*.py")):
        if f.name.startswith("_"):
            continue
        head = f.read_text(encoding="utf-8")[:4000]
        if not surface.search(head):
            continue
        if f.stem not in blob:
            orphans.append(f.name)
    assert not orphans, (
        "these modules claim a place in the UI and nothing in report/, "
        f"pipeline/ or cli.py imports them: {orphans}")
