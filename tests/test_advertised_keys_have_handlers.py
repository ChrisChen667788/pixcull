"""v3.75 — the report page promised a key that does nothing.

`A` was listed in the keyboard shortcut sheet as "v0.13 · 6 轴 AI
attribution heatmap", described again in the feature-discovery tour, and
pushed at every first-time user in a lightbox toast that opened "三个
PixCull 专属键位" — three PixCull keys, one of which had no keydown
handler anywhere in `results.js` or any of its 35 modules.

The backend is not the missing part. `pixcull/scoring/attribution.py`
computes the integrated-gradients saliency map, has tests, and caches a
PNG. Nothing serves it: there is no route for it among the registered
HTTP handlers, and nothing in the page ever asks. Advertised since
v0.13, reachable in no version since.

This gate is the general form: every key the page advertises has to be
a key the page handles. It reads the advertisements out of the rendered
shortcut sheet and tour, reads the handled keys out of the comparisons
the JS actually makes, and compares the two sets — structure on both
sides, because a page that mentions a key in prose is not a page that
listens for it.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "pixcull" / "report" / "templates" / "results.html"

#: Modifier chords are a different mechanism (they are checked with
#: metaKey/ctrlKey alongside the letter) and are out of scope here.
_CHORD = re.compile(r"<kbd>(?:⌘|Ctrl|Shift|Alt|⌥|⇧)</kbd>\s*\+")

#: What a key is CALLED on a keycap versus what `KeyboardEvent.key`
#: reports. Not exemptions — translations. A shortcut sheet that printed
#: `ArrowLeft` on a keycap would be unreadable, and one that printed `←`
#: while the handler compares `ArrowLeft` is still a kept promise.
ALIASES = {
    "Esc": {"Escape"},
    "Space": {" ", "Spacebar"},
    "←": {"ArrowLeft"},
    "→": {"ArrowRight"},
    "↑": {"ArrowUp"},
    "↓": {"ArrowDown"},
    "−": {"-"},          # U+2212 on the keycap, hyphen-minus in the DOM
    "＋": {"+", "="},
    "Enter": {"Enter", "Return"},
    "Tab": {"Tab"},
}

#: Keys whose handler is registered somewhere this scan cannot see, with
#: the reason. Empty on purpose — add an entry only with a note.
EXEMPT: dict = {}


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _advertised(text: str) -> set:
    """Every single key promised by a shortcut row or the tour."""
    out = set()
    for row in re.finditer(r'<div class="shortcut-row">(.*?)</div>\s*</div>|'
                           r'<div class="shortcut-row">(.*?)</div>', text):
        frag = row.group(0)
        if _CHORD.search(frag):
            continue
        for k in re.findall(r"<kbd>([^<]{1,12})</kbd>", frag):
            k = k.strip()
            # Presentational glyphs, not keys you press by name.
            if k and k not in ("⌘", "Ctrl", "Shift", "Alt", "⌥", "⇧"):
                out.add(k)
    return out


def _handled(text: str) -> set:
    """Every key the page compares against.

    Read from the comparisons themselves rather than from a list some
    human keeps up to date, which would be one more thing that can go
    stale the way the shortcut sheet did.
    """
    out = set()
    # Both polarities. The first cut looked only for `===` and reported
    # `\\` as unhandled; the burst-compare handler is written
    # `if (ev.key !== "\\\\") return;`, an early-return guard, which is
    # the same promise kept in the opposite direction. Exempting it
    # would have hidden a working feature behind a note.
    for pat in (r"\.key\s*!==?\s*['\"]([^'\"]{1,12})['\"]",
                r"\.key\s*===\s*['\"]([^'\"]{1,12})['\"]",
                r"\bk\s*===\s*['\"]([^'\"]{1,12})['\"]",
                r"\.key\s*==\s*['\"]([^'\"]{1,12})['\"]",
                r"\.code\s*===\s*['\"]Key([A-Z])['\"]",
                r"\.key\.toLowerCase\(\)\s*===\s*['\"]([^'\"]{1,12})['\"]"):
        for mt in re.finditer(pat, text):
            # A comparison guarded by a modifier is a CHORD handler, and
            # a chord does not keep a bare key's promise. Cmd+A exists
            # (select-all, Lightroom parity) and for one revision of this
            # file it made bare `A` look handled — so the gate passed on
            # the exact page state it was written to reject. Look at the
            # condition the comparison sits in, not just the comparison.
            around = text[max(0, mt.start() - 200):mt.end() + 40]
            if re.search(r"\b(metaKey|ctrlKey|altKey|shiftKey)\b", around):
                continue
            k = mt.group(1)
            # The page is JavaScript inside HTML, so a backslash key is
            # written "\\\\" and comes back as two characters while the
            # keycap advertises one. Undo the JS escape before comparing.
            out.add(k.replace("\\\\", "\\"))
    # A handler that lowercases before comparing handles both cases.
    for k in list(out):
        out.add(k.lower())
        out.add(k.upper())
    return out


def test_the_page_advertises_a_plausible_number_of_keys():
    """A scan that finds nothing to check passes, and reads exactly like
    a scan that found nothing wrong. This repo has shipped that mistake
    five times; state the data source is alive before trusting it."""
    ads = _advertised(_page())
    assert len(ads) >= 8, (
        f"only {len(ads)} advertised keys found ({sorted(ads)}) — the "
        "shortcut sheet parser is broken, not the page")
    handled = _handled(_page())
    assert len(handled) >= 15, (
        f"only {len(handled)} handled keys found — the handler scan is "
        "broken, not the page")


def test_every_advertised_key_has_a_handler():
    """The defect, stated as a rule: a key in the shortcut sheet is a
    promise the page keeps or does not make."""
    text = _page()
    handled = _handled(text)
    missing = sorted(
        k for k in _advertised(text)
        if k not in handled
        and not (ALIASES.get(k, set()) & handled)
        and k not in EXEMPT)
    assert not missing, (
        f"these keys are advertised in the shortcut sheet or the tour and "
        f"no handler compares against them: {missing}. Either wire the key "
        "or stop promising it.")


def test_the_first_run_toast_counts_the_keys_it_lists():
    """It said 三个 and listed three, one of them dead. The count and the
    list have to agree, so removing a key cannot leave the sentence
    claiming the old number."""
    text = _page()
    m = re.search(r"([一二三四五六七八九两])个 PixCull 专属键位", text)
    assert m, "the first-run lightbox toast no longer names a count"
    words = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9}
    claimed = words[m.group(1)]
    tail = text[m.end():m.end() + 2000]
    listed = len(re.findall(r"<kbd style=", tail))
    assert claimed == listed, (
        f"the first-run toast says {claimed} keys and lists {listed}")
