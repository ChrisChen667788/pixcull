"""The two structural tells, and the length of the What's new section.

A complaint that the release notes read as machine-written turned out to be
about form rather than content: 39 of 49 entries opened with the same
bolded-headline template, the median entry carried three bold runs, and 43
of 49 were one unbroken paragraph.  Forty-nine paragraphs in identical
shape is what a generator produces.

Deliberately narrow.  A style linter that fires on prose gets switched off
within a month, and a switched-off linter is worse than none because it
reads as coverage.  These three rules are countable, and `docs/WRITING.md`
carries the ones that are not.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: How many releases the README keeps. The rest live in CHANGELOG.md.
MAX_ENTRIES = 6

#: Bold runs per entry. Emphasis used as structure is a substitute for
#: paragraph breaks; two leaves room for a genuine second emphasis.
MAX_BOLD_PER_ENTRY = 2


def _entries(path: Path, pattern: str) -> list[str]:
    text = path.read_text(encoding="utf-8")
    # v3.69 — pick the pair whose BOTH markers are present. The first cut
    # tested for the English opener alone, so the moment a Chinese entry
    # quoted the phrase "What's new" — describing the gate that reads
    # this very section — the Chinese README took the English branch and
    # died on a closing marker it has never had. Five tests failed at
    # once, all of them saying `ValueError: substring not found`, which
    # names neither the file nor the phrase.
    for opener, closer in (("What's new", "Earlier releases are in"),
                           ("最近更新", "更早的版本记录在")):
        if opener in text and closer in text:
            return re.split(pattern, text[text.index(opener):
                                          text.index(closer)])[1:]
    return []


CASES = [
    (ROOT / "README.md", r'\n(?=\*\*v[\d.]+\*\* — )'),
    (ROOT / "modelscope" / "README.md", r'\n(?=- \*\*v[\d.]+\*\*)'),
]


def test_the_readme_keeps_only_the_recent_releases():
    """They were a third of the README, and a new reader met forty-nine of
    them before reaching what the software is for."""
    for path, pat in CASES:
        got = _entries(path, pat)
        assert 0 < len(got) <= MAX_ENTRIES, (
            f"{path.name} carries {len(got)} release entries; move the older "
            f"ones to CHANGELOG.md")


def test_no_entry_opens_with_the_same_bolded_headline_template():
    """One template repeated is the loudest tell. If every entry in a file
    begins the same way, the file was not written, it was filled in."""
    for path, pat in CASES:
        for e in _entries(path, pat):
            body = e.split("**:", 1)[-1].split("— ", 1)[-1].lstrip()
            assert not body.startswith("**"), (
                f"{path.parent.name}/{path.name}: an entry opens with a bolded headline clause — "
                f"{body[:48]!r}")


def test_bold_is_not_being_used_as_structure():
    """`**this**` and `**that**` and `**the other**` inside one paragraph is
    a substitute for the paragraph breaks."""
    for path, pat in CASES:
        for e in _entries(path, pat):
            n = len(re.findall(r'\*\*[^*\n]+\*\*', e))
            assert n <= MAX_BOLD_PER_ENTRY, (
                f"{path.parent.name}/{path.name}: {n} bold runs in one entry — "
                f"{e.strip()[:48]!r}")


def test_the_changelogs_exist_and_hold_the_rest():
    for rel, marker in ((("CHANGELOG.md"), "**v"),
                        (("modelscope/CHANGELOG.md"), "- **v")):
        p = ROOT / rel
        assert p.exists(), f"{rel} missing"
        assert p.read_text(encoding="utf-8").count(marker) > 10


def test_the_style_note_says_what_it_measured():
    """A rule with no evidence behind it is a preference, and preferences
    get argued with."""
    doc = (ROOT / "docs" / "WRITING.md").read_text(encoding="utf-8")
    assert "39 of 49" in doc and "43 of 49" in doc


def test_no_stock_marketing_phrases_in_the_readmes():
    """If a phrase would fit any product, it is not describing this one."""
    banned = ("seamlessly", "effortlessly", "cutting-edge", "game-changing",
              "一杯咖啡的时间", "轻松搞定", "无缝")
    for path, _ in CASES:
        text = path.read_text(encoding="utf-8").lower()
        for phrase in banned:
            assert phrase.lower() not in text, f"{path.parent.name}/{path.name}: {phrase!r}"


# ---------------------------------------------------------------------------
# v3.53 — the section stopped being updated and nobody noticed for 85 releases.
# ---------------------------------------------------------------------------

#: How far behind the newest shipped release the README's newest entry may
#: fall. Some slack, because a release and its note are separate commits.
MAX_RELEASES_BEHIND = 3

#: v3.65 — this used to be `^v(2\.\d+…)`, the series that was current when
#: the gate was written. The moment v3.0 shipped it stopped matching anything
#: and the check went quiet: sixty-four v3 releases went by with **What's
#: new** frozen on v2.99, and every test in this file passed the whole time.
#: The same defect this file exists to catch, caught by nothing, because the
#: guard was pinned to the shape of the data on the day it was written.
#: `test_the_gate_can_see_the_newest_release` below is the part that does not
#: expire.
_VERSION_COMMIT = re.compile(r"^v(\d+\.\d+(?:\.\d+)*)\s*(?:—|:|-)\s")

#: Deliberately independent of the pattern above: any leading `vN.N`, with no
#: opinion about what comes after it. If this finds a newer release than
#: `_VERSION_COMMIT` does, the gate has a blind spot.
_ANY_VERSION_COMMIT = re.compile(r"^v(\d+\.\d+(?:\.\d+)*)\b")


def _released_versions() -> list[tuple[int, ...]]:
    import subprocess
    out = subprocess.run(["git", "log", "--format=%s"], cwd=ROOT,
                         capture_output=True, text=True)
    if out.returncode != 0:
        return []
    seen = set()
    for subject in out.stdout.splitlines():
        m = _VERSION_COMMIT.match(subject.strip())
        if m:
            seen.add(tuple(int(x) for x in m.group(1).split(".")))
    return sorted(seen, reverse=True)


def _entry_versions(path: Path, pattern: str) -> list[tuple[int, ...]]:
    out = []
    for e in _entries(path, pattern):
        m = re.search(r"v(\d+(?:\.\d+)+)", e)
        if m:
            out.append(tuple(int(x) for x in m.group(1).split(".")))
    return sorted(out, reverse=True)


def _newest_entry(path: Path, pattern: str) -> tuple[int, ...] | None:
    vs = _entry_versions(path, pattern)
    return vs[0] if vs else None


def test_the_gate_can_see_the_newest_release():
    """The defect that made the rest of this file useless for sixty-four
    releases: `_VERSION_COMMIT` was written as `^v(2\\.\\d+…)`, so when the
    version numbers moved to 3.x it matched nothing new and reported the
    README as current forever.

    Checking the README against the log is only a check if the thing
    reading the log can still read it. So: scan for release commits a
    second way, with a pattern that has no opinion about the major
    version, and fail if that finds something newer. A regex narrowed
    to today's numbers gets caught the first time a new series ships,
    instead of eleven releases later.
    """
    import subprocess
    out = subprocess.run(["git", "log", "--format=%s"], cwd=ROOT,
                         capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    loose = set()
    for subject in out.stdout.splitlines():
        m = _ANY_VERSION_COMMIT.match(subject.strip())
        if m:
            loose.add(tuple(int(x) for x in m.group(1).split(".")))
    if not loose:
        raise AssertionError("no release commits at all — shallow checkout?")
    strict = _released_versions()
    assert strict, "the release-commit pattern matches nothing in this log"
    assert max(strict) == max(loose), (
        f"the release-commit pattern's newest match is v{max(strict)} but "
        f"the log's newest release-shaped subject is v{max(loose)}. The "
        "pattern has gone blind to the series currently shipping, which is "
        "exactly how What's new froze on v2.99 for sixty-four releases.")


def test_whats_new_has_not_stopped_being_updated():
    """The defect this catches, stated plainly: "What's new" listed v2.45
    while the newest release was v2.99, so the public description of the
    product was eighty-five releases out of date and every gate in this
    file passed the whole time — they check the shape of the section, and
    a stale section is perfectly shaped.
    """
    released = _released_versions()
    if len(released) < 5:
        # A shallow checkout cannot answer this. Say so rather than
        # passing: a gate that cannot see is not a gate that agrees.
        raise AssertionError(
            "only %d release commits visible — this needs full history "
            "(actions/checkout with fetch-depth: 0)" % len(released))
    newest = released[0]
    for path, pattern in CASES:
        top = _newest_entry(path, pattern)
        assert top is not None, f"{path.name}: no version in the section"
        behind = sum(1 for v in released if v > top)
        assert behind <= MAX_RELEASES_BEHIND, (
            f"{path.parent.name}/{path.name}: newest entry is "
            f"v{'.'.join(map(str, top))} and {behind} releases have shipped "
            f"since, up to v{'.'.join(map(str, newest))}. Move the old ones "
            "into the changelog and write the new ones.")


def test_the_changelog_carries_what_the_readme_dropped():
    """The two halves have to add up, or moving an entry down loses it."""
    for readme, pattern, changelog in (
            (ROOT / "README.md", CASES[0][1], ROOT / "CHANGELOG.md"),
            (ROOT / "modelscope" / "README.md", CASES[1][1],
             ROOT / "modelscope" / "CHANGELOG.md")):
        held = _entry_versions(readme, pattern)
        assert held, f"{readme.name}: no versions in the section"
        # Everything OLDER than the oldest entry the README still shows
        # has to be findable in the changelog. The ones it still shows
        # are not missing; they are upstairs.
        oldest_held = held[-1]
        listed = {tuple(int(x) for x in m.split("."))
                  for m in re.findall(r"\*\*v(\d+(?:\.\d+)+)\*\*",
                                      changelog.read_text(encoding="utf-8"))}
        missing = [v for v in _released_versions()
                   if v < oldest_held and v not in listed and v >= (2, 44)]
        assert not missing, (
            f"{changelog.parent.name}/{changelog.name} is missing "
            f"{len(missing)} releases that are no longer in the README: "
            + ", ".join("v" + ".".join(map(str, v)) for v in missing[:6]))
