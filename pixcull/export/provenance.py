"""v3.22 — the export says what it is, not only what it decided.

XMP sidecars and a ratings CSV leave the machine with no record of how
they were produced: which model judged, which prompt version, what
strictness, whether personalisation was active, what fell back to
templates. The photographer hands a client a set of selects and neither
of them can answer "how was this decided" three months later.

That gap is sharper here than in most tools, because this project refuses
to publish an accuracy number without provenance and then shipped
decisions with none at all.

WHAT IS READ FROM THE ROWS, NOT FROM THE CONFIG

The model name comes from what the rows say actually happened, the way
the `PixCull:judged-by` keyword does. A run configured for M3 can still
contain frames the API never saw — skipped, errored, over budget — and a
record built from the configuration would claim a judge that never ran.

WHAT MUST NOT BE IN IT

This file travels with client deliverables. No absolute paths, no home
directory, no volume names, no photo filenames. A provenance record that
leaks `/Volumes/<client name> wedding/` is worse than no provenance
record, and the repo's hygiene rules apply to generated artifacts and not
only to the source tree. :func:`scrub` enforces it and a test proves the
enforcement rather than trusting the writer.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

FILENAME = "pixcull-session.json"
SCHEMA = "pixcull.session_provenance/v1"

#: Anything that looks like a filesystem location. Deliberately broad:
#: the cost of dropping a field that was safe is nil, and the cost of
#: shipping one that was not is a client's name in a file they were sent.
_PATHLIKE = re.compile(r"(^|[\s\"'=])(/|~/|[A-Za-z]:\\\\|\\\\\\\\)")


def scrub(value: Any) -> Any:
    """Drop anything path-shaped, recursively.

    Returns the value with offending strings replaced by "<redacted>"
    rather than removing the key: a missing field reads as "this run had
    no model", while an explicit redaction reads as what it is.
    """
    if isinstance(value, str):
        return "<redacted>" if _PATHLIKE.search(value) else value
    if isinstance(value, dict):
        # KEYS too. `judged_by_observed` is keyed by model name, and a
        # locally-hosted model's name is a path — so a record built from
        # a self-hosted run would have shipped the operator's directory
        # layout in a file handed to a client. Found by the end-to-end
        # guard, not by the per-field one, which is why that test exists
        # alongside the unit ones.
        return {scrub(k): scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    return value


def build(rows: list[dict[str, Any]], *, strictness: str = "",
          vertical: str = "", ledger: dict | None = None,
          profile: Any = None) -> dict[str, Any]:
    """The session record for one run, from what the rows actually say."""
    from pixcull import __version__

    models = Counter()
    judged = 0
    for r in rows:
        name = str(r.get("vlm_model_name") or "").strip()
        if str(r.get("vlm_overall_label") or "").strip():
            judged += 1
            if name:
                models[name] += 1
    decisions = Counter(str(r.get("decision") or "") for r in rows)

    prompt_version = ""
    try:
        from pixcull.scoring.m3 import PROMPT_VERSION
        prompt_version = str(PROMPT_VERSION)
    except Exception:  # noqa: BLE001
        pass

    personal: dict[str, Any] = {"active": False}
    if profile is not None:
        try:
            personal = {
                "active": bool(profile.is_active()),
                "label_provenance": str(
                    getattr(profile, "label_provenance", "") or ""),
                "n_annotations": int(
                    getattr(profile, "n_annotations", 0) or 0),
            }
            if not personal["active"]:
                personal["inactive_reason"] = str(profile.inactive_reason())
        except Exception:  # noqa: BLE001
            personal = {"active": False, "error": "profile unreadable"}

    record: dict[str, Any] = {
        "schema": SCHEMA,
        "pixcull_version": str(__version__),
        "n_photos": len(rows),
        "decisions": dict(decisions),
        # Named `judged_by_observed` rather than `model`: it is a count of
        # what happened, not a statement of what was configured.
        "judged_by_observed": dict(models),
        "n_frames_judged": judged,
        "prompt_version": prompt_version,
        "strictness": str(strictness or ""),
        "vertical": str(vertical or ""),
        "personalisation": personal,
        # The ledger is the honest half: it says which passes used a
        # fallback and which never ran at all.
        "fallbacks": (ledger or {}).get("passes", {}),
    }
    return scrub(record)


def write(out_dir: Path | str, record: dict[str, Any]) -> Path:
    p = Path(out_dir) / FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    return p
