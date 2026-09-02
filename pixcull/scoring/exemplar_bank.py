"""v3.11 — ground the judge in photographs this photographer actually judged.

v3.4 put worked critiques into the prompt as text. This is the other half
of AtelierJudge's System 1: reference *images*. The canon tells the model
what good composition is in words; an exemplar shows it one this
photographer kept, and one they threw away.

THE CIRCULARITY THIS MUST NOT HAVE

The obvious design is a per-axis bank: for each rubric axis, the
photographer's highest and lowest scoring frames on that axis. It cannot
be built honestly. `annotations.jsonl` stores the photographer's
keep/maybe/cull and nothing per-axis; the axis stars live in scores.csv
and carry `source="auto"` — they are `rubric_decompose`'s own detector
output. A bank selected on them would calibrate the model against the
system's own opinion while presenting itself as the photographer's
judgement, which is the exact circularity this repository has a whole
blind-labelling protocol to prevent.

So exemplars are selected on the DECISION the human actually made, and
`select()` never reads an axis column. There is a test that asserts that
about the source code, because a future edit adding "just one" axis-based
tie-break would reintroduce the circularity silently.

WHICH DECISIONS COUNT

Only `source == "human"`. Not `compare_rejected` — a burst sibling that
lost to a near-identical frame is not an example of a bad photograph
(v3.9). Not `lr_catalog` — an imported flag may mean "delivered" rather
than "best" (v3.10). Not the pipeline's own decisions, for the reason
above.

WHAT AN EXEMPLAR CANNOT DO

It cannot make the model right. It can make it consistent with this
photographer, which is a different and smaller claim, and the measure has
to be per-axis agreement against corrections rather than anything that
sounds like accuracy.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: The only annotation provenance an exemplar may be selected on.
HUMAN = "human"

#: How many of each side reach a prompt. One and one: two extra images
#: already triples the payload of a single-image call, and a bank large
#: enough to average over is a training set, not a prompt.
PER_SIDE = 1


@dataclass(frozen=True)
class Exemplar:
    path: Path
    decision: str          # keep | cull
    filename: str


def _human_decisions(ann_path: Path) -> dict[str, str]:
    """Latest human keep/cull per filename from one annotations file."""
    out: dict[str, str] = {}
    try:
        lines = ann_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        # Provenance gate. A record with no source predates v3.9 and is
        # a hand annotation, so it counts; anything that names a
        # different provenance does not.
        src = rec.get("source", HUMAN)
        if src != HUMAN:
            out.pop(rec.get("filename"), None)
            continue
        fn = rec.get("filename")
        dec = rec.get("overall_label") or rec.get("decision")
        if fn and dec in ("keep", "cull"):
            out[fn] = dec
        elif fn:
            out.pop(fn, None)      # relabelled to maybe: no longer an example
    return out


def select(runs_root: Path | str, *, per_side: int = PER_SIDE) -> list[Exemplar]:
    """Reference frames, chosen on what the photographer decided.

    Deliberately reads no axis column. See the module docstring: the axis
    stars are the system's own output and selecting on them would make
    the model's grounding a mirror.

    Newest run first, so the exemplars reflect what this photographer is
    doing now rather than what they did on their first shoot.
    """
    root = Path(runs_root)
    if not root.exists():
        return []
    anns = sorted(root.rglob("annotations.jsonl"),
                  key=lambda p: p.stat().st_mtime if p.exists() else 0,
                  reverse=True)
    keeps: list[Exemplar] = []
    culls: list[Exemplar] = []
    for ann in anns:
        run_dir = ann.parent
        for fn, dec in _human_decisions(ann).items():
            bucket = keeps if dec == "keep" else culls
            if len(bucket) >= per_side:
                continue
            img = _find_image(run_dir, fn)
            if img is None:
                continue
            bucket.append(Exemplar(path=img, decision=dec, filename=fn))
        if len(keeps) >= per_side and len(culls) >= per_side:
            break
    return keeps[:per_side] + culls[:per_side]


def _find_image(run_dir: Path, filename: str) -> Path | None:
    """Locate the frame an annotation refers to, or None.

    None rather than a guess: an exemplar pointing at the wrong photograph
    is worse than no exemplar, because the label travels with it into the
    prompt.
    """
    for cand in (run_dir / filename,
                 run_dir.parent / filename,
                 run_dir.parent / "input" / filename):
        if cand.exists() and cand.is_file():
            return cand
    return None


def prompt_note(exemplars: list[Exemplar]) -> str:
    """The sentence that says what the extra images are.

    Without it the model sees three photographs and no reason to treat
    two of them differently from the one it is being asked about — which
    is a good way to have it critique the wrong frame.
    """
    if not exemplars:
        return ""
    keeps = [e for e in exemplars if e.decision == "keep"]
    culls = [e for e in exemplars if e.decision == "cull"]
    bits = ["随后附上的是**参考图**,不是要你评的照片。"
            "它们是这位摄影师自己判过的片子,用来告诉你他的取舍在哪里。"]
    if keeps:
        bits.append(f"接下来 {len(keeps)} 张是他**留下**的。")
    if culls:
        bits.append(f"再接下来 {len(culls)} 张是他**剔掉**的。")
    bits.append("只评第一张。参考图只用来校准标准,不要描述它们。")
    return "".join(bits)
