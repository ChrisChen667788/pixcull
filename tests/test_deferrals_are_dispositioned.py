"""v3.39 — a comment that postpones work has to say what happened to it.

Eight comments were carried into this version as "deferrals to review".
Reviewing them found that the census itself was wrong — two of the eight
were not deferrals at all, one had been satisfied two versions earlier,
one described the code incorrectly ("treat as passing" over a line that
returns `None`), and one had deferred a feature on a premise that was
simply false (a `.lrcat` called a "reverse-engineered binary"; it is
SQLite, and v3.10 opens it with the standard library).

The lesson is not about those eight. It is that nothing made the next
reader notice, so the same audit has to be redone by hand every time
somebody wonders. `pixcull/data/deferrals.tsv` holds the answers, and
this file keeps it honest: a promise-shaped comment that is not in the
inventory fails, and so does an entry whose comment has since been
edited — the hash covers the comment text, so editing a deferral is
the moment you re-state what it is waiting for.
"""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "pixcull" / "data" / "deferrals.tsv"

PROMISE = re.compile(
    r"\b(will add|will ship|deferred to|coming in|future work|for now|"
    r"not yet implemented|V\d+(?:\.\d+)*\+? will|TODO|FIXME)\b", re.I)

DISPOSITIONS = {"done", "wrong", "undecided", "open", "not-a-promise"}


def comment_blocks(path: Path):
    """Contiguous runs of ``#`` lines, joined. A deferral is a paragraph,
    not a line, and splitting it would let a promise hide on line 2."""
    cur: list[str] = []
    start = 0
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            if not cur:
                start = i
            cur.append(stripped.lstrip("#").strip())
        elif cur:
            yield start, " ".join(cur)
            cur = []
    if cur:
        yield start, " ".join(cur)


def digest(text: str) -> str:
    return hashlib.sha1(" ".join(text.split()).encode()).hexdigest()[:8]


def found_in_code() -> dict[tuple[str, str], str]:
    out = {}
    for p in sorted(ROOT.glob("pixcull/**/*.py")):
        rel = p.relative_to(ROOT).as_posix()
        for line, text in comment_blocks(p):
            m = PROMISE.search(text)
            if m:
                out[(rel, digest(text))] = f"{rel}:{line} — {text[:90]}"
    return out


def inventory() -> dict[tuple[str, str], list[str]]:
    out = {}
    for raw in INVENTORY.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        parts = raw.split("\t")
        assert len(parts) == 5, f"malformed row: {raw[:60]}"
        out[(parts[0], parts[1])] = parts
    return out


def test_every_promise_in_the_code_has_an_answer():
    code, inv = found_in_code(), inventory()
    missing = [code[k] for k in code if k not in inv]
    assert not missing, (
        "these comments promise or postpone work and are not in "
        f"{INVENTORY.name} — add a row saying what happened: {missing}")


def test_the_inventory_has_no_rows_for_comments_that_are_gone():
    """Otherwise it accumulates answers to questions nobody is asking,
    and stops being worth reading."""
    code, inv = found_in_code(), inventory()
    stale = [f"{f} {h}" for (f, h) in inv if (f, h) not in code]
    assert not stale, (
        f"{INVENTORY.name} names comments that no longer exist (or have "
        f"been edited — re-state the disposition and update the hash): {stale}")


def test_dispositions_come_from_the_short_list():
    for parts in inventory().values():
        assert parts[3] in DISPOSITIONS, parts[3]


def test_each_answer_actually_says_something():
    """A row reading "done" with no explanation is the deferral again,
    wearing the inventory's clothes."""
    for parts in inventory().values():
        assert len(parts[4].split()) >= 8, f"too thin to be an answer: {parts}"


def test_an_open_deferral_is_allowed_but_must_still_be_waiting_on_something():
    for parts in inventory().values():
        if parts[3] == "open":
            assert re.search(r"\b(until|waiting|needs|no detector|blocked)\b",
                             parts[4], re.I), (
                "an open deferral has to name what it is waiting for: "
                f"{parts}")


def test_the_matcher_would_notice_a_new_one(tmp_path):
    """A census that matches nothing passes for the wrong reason."""
    f = tmp_path / "x.py"
    f.write_text("# We will add the thing in V99.\nx = 1\n", encoding="utf-8")
    blocks = list(comment_blocks(f))
    assert len(blocks) == 1
    assert PROMISE.search(blocks[0][1])
    # and the hash moves when the comment is edited
    assert digest("a b") != digest("a c")
    # a promise on the second line of a block is still caught
    f.write_text("# Context line.\n# For now we skip.\ny = 2\n", encoding="utf-8")
    assert PROMISE.search(list(comment_blocks(f))[0][1])
