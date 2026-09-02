"""v3.9 — record that the photographer chose A over B, as a pair.

The compare modal already has an explicit preference gesture: "选最佳 +
其余 cull". The charter said it did not, and the charter was wrong — the
button is at results.js:7538 and has been there since v0.7.

What it does with the answer is the problem. It writes N pointwise
annotations: keep for the winner, cull for every sibling. Two things are
lost and one is actively broken.

LOST: the pair. "I preferred this frame to that one, and they were nearly
identical" is a different and much stronger statement than "this one is
good and those are bad". Pairwise preference is the format the
personalised-DPO line of work consumes, and it is the cheapest
high-quality taste signal a culling tool can collect, because the
photographer produces it as a side effect of work they were doing anyway.

BROKEN: a burst sibling rejected in compare is not a bad photograph. It
is a photograph that lost to a near-identical one, so its axis stars are
nearly the same as the winner's. Writing it into `annotations.jsonl` as a
plain human `cull` feeds `personal_learn.aggregate_prefs`, which averages
axis stars for keeps against axis stars for culls and hands the gap to
`axis_weights`. Feeding it near-identical rows on both sides flattens
that gap. Every use of the compare gesture made the personal profile
slightly worse, and nothing anywhere said so.

So the pointwise labels from compare are marked at the source, the
pairwise structure is kept here in its correct form, and
`gather_examples_from_runs` drops the rejected siblings from the taste
profile — the signal is not discarded, it is stored as what it is.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable

FILENAME = "pairwise_prefs.jsonl"
SCHEMA = "pixcull.pairwise_pref/v1"

#: Annotation `source` values the compare gesture writes. Restricted:
#: a client must not be able to invent a provenance string, because
#: `gather_examples_from_runs` makes an inclusion decision from it.
COMPARE_WINNER = "compare_winner"
COMPARE_REJECTED = "compare_rejected"
KNOWN_SOURCES = frozenset({"human", "lr_round_trip",
                           COMPARE_WINNER, COMPARE_REJECTED})


def record(output_dir: Path | str, *, winner: str, losers: Iterable[str],
           cluster: str = "", context: str = "burst") -> dict:
    """Append one preference: ``winner`` was chosen over ``losers``.

    Returns the record written. Appends rather than rewrites for the same
    reason the verdict cache does: a run killed mid-write must not
    corrupt the preferences already collected.
    """
    losers = [str(x) for x in losers if str(x) and str(x) != str(winner)]
    rec = {
        "schema": SCHEMA,
        "winner": str(winner),
        "losers": losers,
        "cluster": str(cluster),
        "context": str(context),
        "timestamp": time.time(),
    }
    path = Path(output_dir) / FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def load(output_dir: Path | str) -> list[dict]:
    """Every preference recorded for this run, oldest first.

    A preference with no losers is dropped on read. It can be written by
    a client that sent a winner and nothing else, and "preferred over
    nothing" is not a preference — keeping it would inflate the count of
    a dataset whose whole value is that each row is a real comparison.
    """
    path = Path(output_dir) / FILENAME
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue        # torn tail from a killed run
            if not isinstance(rec, dict):
                continue
            if rec.get("schema") != SCHEMA:
                continue
            if not rec.get("winner") or not rec.get("losers"):
                continue
            out.append(rec)
    except OSError:
        return []
    return out


def pairs(records: Iterable[dict]) -> list[tuple[str, str]]:
    """Flatten to ``(winner, loser)`` tuples, deduplicated.

    One compare of a seven-frame burst is six pairs, not one. Counting it
    as one would undercount the signal by the size of the burst.
    """
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for rec in records:
        w = str(rec.get("winner") or "")
        for l in rec.get("losers") or []:
            key = (w, str(l))
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out


def summary(output_dir: Path | str) -> dict[str, Any]:
    recs = load(output_dir)
    ps = pairs(recs)
    return {
        "comparisons": len(recs),
        "pairs": len(ps),
        "frames_preferred": len({w for w, _ in ps}),
    }
