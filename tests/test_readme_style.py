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
    if "What's new" in text:
        start = text.index("What's new")
        end = text.index("Earlier releases are in")
    elif "最近更新" in text:
        start = text.index("最近更新")
        end = text.index("更早的版本记录在")
    else:
        return []
    return re.split(pattern, text[start:end])[1:]


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
