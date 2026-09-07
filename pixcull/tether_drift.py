"""v3.24 — the live path and the finished path diverged, on purpose and not.

`tether.py` and `tether_stream.py` date from P2.2.  Everything the last
forty versions added to the finished pipeline — written advice, client
picks, the viewable-folder export, burst evidence, the rubric axes, the
face and location clusters — went into the finished path and stopped
there.  The live path writes ten columns.  The finished path writes
seventy-three.

It is NOT obvious the live path should carry all of them.  A tether
session is a photographer watching frames land during a shoot; rendering
a four-sentence critique between shutter releases would be worse, not
better.  What is obvious is that nobody decided — the divergence is an
accident that happens to be partly right.

SO THE DELIVERABLE IS THE DECISION, NOT THE PARITY

Every column the finished path produces and the live path does not gets a
disposition here, with a reason.  A column with no disposition fails the
gate.  That turns a silent accumulation of drift into a thing somebody
has to answer for, once, when they add a column — which is the only
moment they know why.

This is the same shape as the fallback ledger: the point is not that
nothing is missing, it is that nothing is missing *unremarked*.
"""
from __future__ import annotations

from pathlib import Path

#: What `tether._append_row` writes. Kept here as the single statement of
#: the live schema; the writer's own list is asserted against it.
TETHER_COLUMNS = (
    "filename", "path", "scene", "decision", "score_final", "flags",
    "reason", "mtime", "sharpness", "is_burst_peak",
    # v3.30 — five of the seventeen gaps v3.24 named, carried. Chosen for
    # what changes the NEXT frame: blown highlights and a tilted horizon
    # are fixable immediately, a blink means reshoot before the subject
    # moves. The other twelve stay decided-and-not-done.
    "highlight_clip_pct", "shadow_clip_pct", "horizon_tilt_deg",
    "face_count", "face_max_blink",
)

#: A snapshot of a real finished run's columns. Refreshed by re-running
#: the pipeline and copying the CSV header; the gate compares against it,
#: so adding a pipeline column without a disposition below is a failure
#: rather than a silent widening of the gap.
FINISHED_COLUMNS_FILE = Path(__file__).resolve().parent / "data" \
    / "finished_run_columns.txt"

#: Why each finished-only column is not in the live path.
#:
#: `deliberate` — it should not be there. A tether view is a photographer
#:   glancing at a screen between frames.
#: `impossible` — it needs the whole shoot, and during a shoot there is
#:   no whole shoot yet.
#: `gap` — it should be there and is not. These are work, and naming them
#:   here is the point of the file.
DISPOSITIONS: dict[str, tuple[str, str]] = {
    # Needs the set, not the frame.
    "cluster_id": ("impossible", "near-duplicate grouping needs the shoot"),
    "peak_rank": ("impossible", "rank within a burst that is still arriving"),
    "burst_peak_reason": ("impossible", "same"),
    "face_clusters": ("impossible", "identity clustering is a whole-shoot pass"),
    "gps_cluster_id": ("impossible", "location clustering is a whole-shoot pass"),
    "score_temporal": ("impossible", "a window needs frames on both sides"),
    # Deliberately absent from a live view.
    "reason": ("deliberate", "already in the live schema"),
    "scene_probs": ("deliberate", "a distribution is not glanceable"),
    "elapsed_s": ("deliberate", "per-frame timing is a diagnostic"),
    "datetime": ("deliberate", "the photographer knows what time it is"),
    # Real gaps, named.
    "score_sharpness": ("gap", "the sub-scores behind the verdict are hidden"),
    "score_composition": ("gap", "same"),
    "score_exposure": ("gap", "same"),
    "score_aesthetic": ("gap", "same"),
    "score_moment": ("gap", "same"),
    "face_count": ("gap", "eyes-open is the live question and it is absent"),
    "face_max_blink": ("gap", "same — this is THE tether-time signal"),
    "face_min_ear": ("gap", "same"),
    "face_max_smile": ("gap", "same"),
    "face_max_brow_down": ("gap", "same"),
    "face_region_lap_var": ("gap",
                            "sharpness INSIDE the face — the tethered "
                            "portrait question, and it is missing"),
    # Exposure. A tethered photographer is watching for blown highlights
    # more than for anything else on this list; the live path reports a
    # verdict and not the one number that would let them fix the next
    # frame.
    "mean_luma": ("gap", "exposure is what a tether session is watching"),
    "highlight_clip_pct": ("gap", "blown highlights are fixable NEXT frame"),
    "shadow_clip_pct": ("gap", "same"),
    "horizon_tilt_deg": ("gap", "a tilt is correctable while still on set"),
    # Present in a different form, or not glanceable.
    "laplacian_global": ("deliberate", "the live schema carries `sharpness`"),
    "laplacian_subject": ("deliberate", "same"),
    "scene_confidence": ("deliberate", "the scene NAME is already live"),
    "moment_score": ("deliberate", "folded into score_final"),
    "subject_fraction": ("deliberate", "a detector diagnostic"),
    "laion_aes": ("deliberate", "an aesthetic model's raw output"),
    "clipiqa": ("deliberate", "same"),
    "rule_of_thirds_offset": ("deliberate", "composition diagnostics"),
    "composition_score": ("deliberate", "same"),
    "gps_lat": ("deliberate", "the photographer knows where they are"),
    "gps_lon": ("deliberate", "same"),
}

#: Prefixes handled as a family rather than one line each.
FAMILY_DISPOSITIONS: tuple[tuple[str, str, str], ...] = (
    ("rubric_", "deliberate",
     "six axes and their pass flags is a table, not a glance"),
    ("model_", "deliberate", "the learned head's per-axis stars, same reason"),
    ("canon_", "deliberate",
     "quantified canon metrics are evidence for a critique nobody reads "
     "during a shoot"),
    ("vlm_", "impossible",
     "a cloud round trip per frame does not fit between shutter releases"),
    ("meta_", "impossible", "the meta-judge runs after the VLM pass"),
    ("wedding_moment", "gap",
     "moment classification is per-frame and would be useful live"),
)


def finished_columns() -> list[str]:
    try:
        return [c.strip() for c in
                FINISHED_COLUMNS_FILE.read_text(encoding="utf-8").splitlines()
                if c.strip()]
    except OSError:
        return []


def disposition_for(column: str) -> tuple[str, str] | None:
    if column in DISPOSITIONS:
        return DISPOSITIONS[column]
    for prefix, kind, why in FAMILY_DISPOSITIONS:
        if column.startswith(prefix):
            return (kind, why)
    return None


def undecided() -> list[str]:
    """Finished-path columns nobody has ruled on. The gate fails on these."""
    live = set(TETHER_COLUMNS)
    return [c for c in finished_columns()
            if c not in live and disposition_for(c) is None]


def gaps() -> list[tuple[str, str]]:
    """Columns someone decided SHOULD be live and are not. Work, not drift."""
    live = set(TETHER_COLUMNS)
    out = []
    for c in finished_columns():
        if c in live:
            continue
        d = disposition_for(c)
        if d and d[0] == "gap":
            out.append((c, d[1]))
    return out


def report() -> dict:
    live = set(TETHER_COLUMNS)
    fin = finished_columns()
    kinds: dict[str, int] = {}
    for c in fin:
        if c in live:
            continue
        d = disposition_for(c)
        kinds[d[0] if d else "undecided"] = kinds.get(
            d[0] if d else "undecided", 0) + 1
    return {"live_columns": len(live), "finished_columns": len(fin),
            "by_disposition": kinds, "undecided": undecided(),
            "gaps": gaps()}
