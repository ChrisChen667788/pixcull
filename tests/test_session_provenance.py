"""v3.22 — the export says how it was produced, and leaks nothing doing it.

XMP sidecars and a ratings CSV left the machine with no record of which
model judged, which prompt version, what strictness, whether
personalisation was active, or what fell back to templates.  The gap is
sharper here than elsewhere: this project refuses to publish an accuracy
number without provenance, and then shipped decisions with none at all.

The second half is the one with teeth.  This file travels with client
deliverables.
"""
import json
import tempfile
from pathlib import Path

from pixcull.export import provenance as P


def _rows():
    return [
        {"decision": "keep", "vlm_model_name": "minimax:MiniMax-M3",
         "vlm_overall_label": "keep"},
        {"decision": "keep", "vlm_model_name": "minimax:MiniMax-M3",
         "vlm_overall_label": "maybe"},
        # Configured for M3, never actually judged: skipped, errored or
        # over budget.
        {"decision": "cull", "vlm_model_name": "minimax:MiniMax-M3"},
    ]


def test_the_model_is_counted_from_what_actually_happened():
    """A run configured for M3 still contains frames the API never saw.
    A record built from the configuration claims a judge that never ran."""
    got = P.build(_rows())
    assert got["judged_by_observed"] == {"minimax:MiniMax-M3": 2}
    assert got["n_frames_judged"] == 2
    assert got["n_photos"] == 3


def test_it_names_the_prompt_version_actually_compiled_in():
    from pixcull.scoring.m3 import PROMPT_VERSION
    assert P.build(_rows())["prompt_version"] == PROMPT_VERSION


def test_decision_counts_come_from_the_rows():
    assert P.build(_rows())["decisions"] == {"keep": 2, "cull": 1}


# -- the part that travels to a client --------------------------------

def test_an_absolute_path_never_reaches_the_file():
    """A provenance record that leaks a volume name is worse than none."""
    out = P.scrub({"folder": "/Volumes/Wedding Drive/Chen 2026",
                   "home": "~/Pictures/shoot",
                   "win": "C:\\\\Users\\\\someone\\\\Photos",
                   "unc": "\\\\\\\\nas\\\\share",
                   "safe": "wedding"})
    assert out["folder"] == "<redacted>"
    assert out["home"] == "<redacted>"
    assert out["win"] == "<redacted>"
    assert out["unc"] == "<redacted>"
    assert out["safe"] == "wedding"


def test_redaction_is_recursive():
    out = P.scrub({"a": [{"b": "/private/x"}], "c": ("~/y", "fine")})
    assert out["a"][0]["b"] == "<redacted>"
    assert out["c"] == ["<redacted>", "fine"]


def test_a_leaked_field_is_marked_not_deleted():
    """A missing field reads as "this run had no model". An explicit
    redaction reads as what it is."""
    assert "folder" in P.scrub({"folder": "/tmp/x"})


def test_the_built_record_carries_no_path_anywhere():
    """The end-to-end version of the guard: whatever build() assembles,
    nothing path-shaped survives it."""
    rows = [{"decision": "keep", "path": "/Volumes/Client/DSC_1.NEF",
             "filename": "DSC_1.NEF", "vlm_model_name": "/opt/models/x",
             "vlm_overall_label": "keep"}]
    blob = json.dumps(P.build(rows), ensure_ascii=False)
    for leak in ("/Volumes", "/opt", "/Users", "\\\\"):
        assert leak not in blob


def test_personalisation_reports_why_it_is_off():
    class _Prof:
        label_provenance = "lr_catalog"
        n_annotations = 900

        def is_active(self):
            return False

        def inactive_reason(self):
            return "labels came from a catalogue import"

    got = P.build([], profile=_Prof())["personalisation"]
    assert got["active"] is False
    assert got["inactive_reason"]
    assert got["label_provenance"] == "lr_catalog"


def test_an_unreadable_profile_does_not_kill_the_record():
    class _Bad:
        def is_active(self):
            raise RuntimeError("boom")

    assert P.build([], profile=_Bad())["personalisation"]["active"] is False


def test_the_ledger_travels_with_it():
    got = P.build([], ledger={"passes": {"m3_advice": {"fell_back": 4}}})
    assert got["fallbacks"]["m3_advice"]["fell_back"] == 4


def test_write_round_trips():
    with tempfile.TemporaryDirectory() as d:
        p = P.write(d, P.build(_rows()))
        assert p.name == P.FILENAME
        assert json.loads(p.read_text(encoding="utf-8"))["schema"] == P.SCHEMA


# -- reachability -----------------------------------------------------

def test_both_export_formats_write_it():
    import inspect

    from pixcull import cli
    src = inspect.getsource(cli)
    assert src.count("_write_session_provenance(") >= 3   # def + 2 calls


def test_a_failure_to_write_it_does_not_fail_the_export():
    """It is an addition to a delivery that has already been made.

    Called for real against a directory with no scores.csv, rather than
    grepped for an `except` — the function has several, and a source
    search was satisfied by the wrong one.
    """
    from pixcull.cli import _write_session_provenance
    with tempfile.TemporaryDirectory() as d:
        empty = Path(d) / "no-such-run"
        empty.mkdir()
        assert _write_session_provenance(empty, empty) is None


def test_it_writes_beside_a_real_export():
    import csv as _csv

    from pixcull.cli import _write_session_provenance
    with tempfile.TemporaryDirectory() as d:
        run = Path(d) / "run"
        run.mkdir()
        with (run / "scores.csv").open("w", newline="", encoding="utf-8") as fh:
            w = _csv.DictWriter(fh, fieldnames=["filename", "decision"])
            w.writeheader()
            w.writerow({"filename": "a.jpg", "decision": "keep"})
        got = _write_session_provenance(run, run)
        assert got is not None and got.exists()
        assert json.loads(got.read_text(encoding="utf-8"))["n_photos"] == 1
