"""v3.27 — the return leg: what the client chose against what you decided.

v3.0 kept client picks in their own file and never merged them into the
photographer's record, which was the right call — the two are different
statements and `annotations.jsonl` is latest-wins on the whole row.

But the loop was left open. Picks come back and the photographer
reconciles by hand: the client wants frames that were culled, and ignored
frames that were starred. On a 400-frame delivery that is 400 comparisons
to find maybe fifteen that matter.

ONLY THE ROWS THAT NEED A HUMAN

Agreement needs nobody. A frame the photographer kept and the client
picked is done; a frame nobody wanted is done. What is left is the
disagreement, and it is short.

THE FRAMING IS PART OF THE DESIGN, NOT DECORATION

The client is the client. A tool that presents their choices as errors —
"client picked a reject", a conflict count, anything scored — is worse
than no tool, because the photographer cannot show it to anyone and will
stop opening it. So the categories are named by WHAT TO DO, not by who
was wrong, and nothing here computes an agreement rate. There is no
number in this module that could be read as a score on the client.
"""
from __future__ import annotations

from typing import Any, Iterable

#: The two kinds of row that need the photographer's attention, named as
#: actions rather than as verdicts on anybody.
CLIENT_WANTS_ONE_YOU_SET_ASIDE = "client_wants_one_you_set_aside"
YOUR_PICK_WENT_UNCHOSEN = "your_pick_went_unchosen"

#: Deliberately not exported: an "agreement rate", a "conflict count", or
#: anything else that reads as a score. See the module docstring.


def reconcile(rows: Iterable[dict[str, Any]],
              picked: Iterable[str]) -> dict[str, Any]:
    """Split a delivery into the rows a person still has to look at.

    ``rows`` are the run's scored rows; ``picked`` the filenames the
    client chose. Everything both sides agree on is dropped — that is the
    point, not an optimisation.
    """
    picked_set = {str(p) for p in picked if str(p).strip()}
    wants: list[dict] = []
    unchosen: list[dict] = []
    n_agreed = 0
    for r in rows:
        fn = str(r.get("filename") or "")
        if not fn:
            continue
        decision = str(r.get("decision") or "")
        was_picked = fn in picked_set
        entry = {"filename": fn, "decision": decision,
                 "score_final": r.get("score_final"),
                 "picked": was_picked}
        if was_picked and decision == "cull":
            wants.append(entry)
        elif not was_picked and decision == "keep":
            unchosen.append(entry)
        else:
            # keep+picked, cull+unpicked, and every maybe the client did
            # not touch. Nothing to decide.
            n_agreed += 1
    return {
        CLIENT_WANTS_ONE_YOU_SET_ASIDE: wants,
        YOUR_PICK_WENT_UNCHOSEN: unchosen,
        "n_needs_your_call": len(wants) + len(unchosen),
        # Reported so the photographer can see the view is not empty
        # because something broke. Not a rate, and not per-side.
        "n_settled": n_agreed,
    }


def needs_your_call(rows: Iterable[dict[str, Any]],
                    picked: Iterable[str]) -> list[str]:
    """Just the filenames, for a filter."""
    got = reconcile(rows, picked)
    return ([e["filename"] for e in got[CLIENT_WANTS_ONE_YOU_SET_ASIDE]]
            + [e["filename"] for e in got[YOUR_PICK_WENT_UNCHOSEN]])


#: Wording the report uses. Kept beside the logic because the wording IS
#: the design here: these strings are the whole reason this is usable in
#: front of a client rather than only behind their back.
LABELS_ZH = {
    CLIENT_WANTS_ONE_YOU_SET_ASIDE: "客户挑了你之前放一边的",
    YOUR_PICK_WENT_UNCHOSEN: "你选的这几张客户没挑",
    "heading": "需要你定的",
    "empty": "客户的选择和你的判断没有出入 —— 没有需要你定的。",
}
