"""v3.0 — what the CLIENT chose, kept apart from what the photographer judged.

Two people, two questions. The photographer's `overall_label` answers
"is this frame good enough to deliver". The client's pick answers "do I
want this one". They disagree constantly and that is normal — a slightly
soft frame where the grandmother is laughing gets picked every time.

WHY A SEPARATE FILE, not a field on the annotation record.

`_read_human_by_fn_cached` builds its index with `out[fn] = rec` —
LATER WINS, replacing the whole record. Appending a client pick to
`annotations.jsonl` with an empty `overall_label` would therefore erase
the photographer's own verdict from every reader of that index. One
line of someone else's opinion, and the label you spent an evening on is
gone from the UI.

The separation is also the guard the rest of the project needs. A client
pick must never reach:

  the personalisation profile   — it would learn the client's taste as
                                  the photographer's, and v2.83 already
                                  cannot demonstrate that loop works
  ground truth                  — v2.88 refuses to measure accuracy
                                  against anything but an independent
                                  human judgement of the SAME question
  the cull decision             — the client did not see the frames you
                                  culled

Living in its own file with its own schema makes each of those a
non-event rather than a discipline anyone has to remember.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

FILENAME = "client_picks.jsonl"
SCHEMA = "pixcull.client_pick/v1"


@dataclass(frozen=True)
class Pick:
    filename: str
    picked: bool
    source: str          # "wechat-reply" | "on-site" | ...
    at: float
    note: str = ""

    def as_record(self) -> dict:
        return {"schema": SCHEMA, "filename": self.filename,
                "picked": bool(self.picked), "source": self.source,
                "note": self.note, "timestamp": self.at}


def path_for(output_dir) -> Path:
    return Path(output_dir) / FILENAME


def record(output_dir, filenames, *, source: str, picked: bool = True,
           note: str = "") -> int:
    """Append picks. Append-only; the newest line for a filename wins.

    Returns how many lines were written. Recording the same photograph
    twice is not an error — a client changes their mind, and the history
    is worth more than the tidiness.
    """
    p = path_for(output_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    n = 0
    with p.open("a", encoding="utf-8") as fh:
        for fn in filenames:
            fn = str(fn or "").strip()
            if not fn:
                continue
            fh.write(json.dumps(
                Pick(fn, picked, source, now, note).as_record(),
                ensure_ascii=False) + "\n")
            n += 1
    return n


def load(output_dir) -> dict[str, dict]:
    """filename -> the newest pick record. Missing file is empty, not an
    error: most runs never have one."""
    p = path_for(output_dir)
    if not p.is_file():
        return {}
    out: dict[str, dict] = {}
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        fn = rec.get("filename")
        if fn:
            out[str(fn)] = rec        # later wins
    return out


def picked_filenames(output_dir) -> set[str]:
    """Only the ones currently picked — an un-pick is a later line with
    picked=false, and must actually un-pick."""
    return {fn for fn, rec in load(output_dir).items() if rec.get("picked")}


def summary(output_dir) -> dict:
    recs = load(output_dir)
    picked = [r for r in recs.values() if r.get("picked")]
    sources: dict[str, int] = {}
    for r in picked:
        s = str(r.get("source") or "?")
        sources[s] = sources.get(s, 0) + 1
    return {"n_seen": len(recs), "n_picked": len(picked), "sources": sources}
