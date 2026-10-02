"""v3.93 — the client's PDF reported the machine's verdicts.

`--pdf --executive` builds the document a photographer hands to a client:
a cover with "N keep of M", a wall of the five best frames, and the audit
behind them. Its numbers came straight from `scores.csv`. A correction
made in the review page is written to `annotations.jsonl` and the CSV
keeps the machine's answer (v3.76), so a frame the photographer had
culled could lead that wall as a BEST pick, and a frame they had rescued
was not counted.

v3.76 swept the package for readers like this and fixed fourteen. This
one was in `scripts/`, which that sweep and its gate do not look at. It
was found the day the file moved into the package for an unrelated
reason, by the gate, on its first run.

One section is left on the machine's verdict deliberately, and the last
test here holds that too: the "watch" cards exist to show where the
model's call deserves a second look, and say "模型决定" on them.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from pixcull.report import cli_audit as C
from pixcull.report import executive_pdf as E

ROWS = [
    # filename, decision, score_final, rubric_human_labeled
    ("a.jpg", "keep", 0.95, ""),      # the machine's best; photographer culls it
    ("b.jpg", "keep", 0.80, ""),
    ("c.jpg", "cull", 0.30, ""),      # the machine culls; photographer rescues
    ("d.jpg", "maybe", 0.66, ""),     # borderline: a "watch" card either way
    ("e.jpg", "cull", 0.20, ""),
]


def _run(tmp_path: Path, corrections: list[dict] | None) -> Path:
    out = tmp_path / "output"
    out.mkdir()
    with (out / "scores.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["filename", "decision", "score_final",
                    "rubric_human_labeled", "scene"])
        for fn, d, s, h in ROWS:
            w.writerow([fn, d, s, h, "portrait"])
    if corrections is not None:
        (out / "annotations.jsonl").write_text(
            "".join(json.dumps(c) + "\n" for c in corrections), "utf-8")
    return out


@pytest.fixture
def built(monkeypatch):
    """What the builder hands the renderer, instead of the HTML it makes."""
    seen: dict = {}

    def _capture(**kw):
        seen.update(kw)
        return "<html></html>"

    monkeypatch.setattr(E, "build_executive_html", _capture)
    monkeypatch.setattr(E, "inline_thumb", lambda path: "")

    def build(out: Path) -> dict:
        seen.clear()
        C._build_executive_html_for_print(
            out / "scores.csv", out, None, "run", "# audit")
        return dict(seen)

    return build


def _best(got: dict) -> list[str]:
    return [c["fn"] for c in got["best_cards"]]


def test_with_no_corrections_the_pdf_is_the_machines(tmp_path, built):
    """The other side first: nothing corrected, nothing changes."""
    for corrections in (None, []):
        d = tmp_path / ("none" if corrections is None else "empty")
        d.mkdir()
        got = built(_run(d, corrections))
        assert (got["dashboard"]["n_keep"], got["dashboard"]["n_maybe"],
                got["dashboard"]["n_cull"]) == (2, 1, 2)
        assert _best(got) == ["a.jpg", "b.jpg"]


def test_a_frame_the_photographer_culled_is_not_a_best_pick(tmp_path, built):
    got = built(_run(tmp_path, [{"filename": "a.jpg",
                                 "overall_label": "cull"}]))
    assert "a.jpg" not in _best(got), (
        "the client's BEST wall leads with a frame the photographer culled")
    assert _best(got) == ["b.jpg"]


def test_a_frame_the_photographer_rescued_is_counted_and_shown(tmp_path,
                                                               built):
    got = built(_run(tmp_path, [{"filename": "c.jpg",
                                 "overall_label": "keep"}]))
    assert _best(got) == ["a.jpg", "b.jpg", "c.jpg"]
    assert got["dashboard"]["n_keep"] == 3 and got["dashboard"]["n_cull"] == 1


def test_the_cover_counts_are_the_photographers(tmp_path, built):
    got = built(_run(tmp_path, [
        {"filename": "a.jpg", "overall_label": "cull"},
        {"filename": "c.jpg", "overall_label": "keep"},
        {"filename": "d.jpg", "overall_label": "keep"},
    ]))
    dash = got["dashboard"]
    assert (dash["n_keep"], dash["n_maybe"], dash["n_cull"]) == (3, 0, 2)
    assert dash["keep_ratio"] == pytest.approx(3 / 5)


def test_the_last_word_on_a_frame_wins(tmp_path, built):
    """The corrections file is append-only: changing your mind leaves two
    lines and means the second."""
    got = built(_run(tmp_path, [
        {"filename": "a.jpg", "overall_label": "cull"},
        {"filename": "a.jpg", "overall_label": "keep"},
    ]))
    assert _best(got) == ["a.jpg", "b.jpg"]


def test_the_watch_cards_still_show_the_models_own_call(tmp_path, built):
    """Deliberately not corrected. ``d.jpg`` is borderline for the model
    whatever the photographer decided, and its card says what the model
    decided — which is the disagreement the section is there to show."""
    got = built(_run(tmp_path, [{"filename": "d.jpg",
                                 "overall_label": "cull"}]))
    watch = {c["fn"]: c["note"] for c in got["inconsistency_cards"]}
    assert "d.jpg" in watch, f"the borderline frame is not on watch: {watch}"
    assert "模型决定 MAYBE" in watch["d.jpg"], watch["d.jpg"]
