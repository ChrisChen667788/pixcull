"""v2.94 — the only tool that makes real labels, in the one shape the guard rejects.

v2.88 built a provenance guard so an accuracy figure cannot be computed
against the model's own output. `pixcull m3 label` writes a genuinely
blind pass — no verdict, no rationale, no score on the card. The two
could not talk to each other:

  the sheet wrote      {"selection": "blind", "verdicts": {...}}
  the guard needed     a `source` field, and one record per photograph

So a real blind pass came back as `unknown` and was refused, and the
labelling that unblocks three versions produced a file nothing would
accept. Advertised, and unreachable.

The third button is separate and opt-in. Two buttons force a decision;
a shrug is the easiest thing to click and a set full of them measures
nothing. But v2.89 cannot see the keep/maybe boundary because no label
set contains a single `maybe` truth, and only that question needs a
middle button.
"""
import json
from pathlib import Path

import pytest

from pixcull.report.review_sheet import write
from pixcull.scoring.ground_truth import (
    CircularMeasurement, accuracy, label_provenance, load_blind_sheet,
)

SHEET = Path(__file__).resolve().parents[1] / "pixcull" / "report" / "review_sheet.py"


@pytest.fixture()
def photos(tmp_path):
    from PIL import Image
    out = []
    for i in range(3):
        p = tmp_path / f"p{i}.jpg"
        Image.new("RGB", (400, 300), (60 + i * 40, 100, 140)).save(p, "JPEG")
        out.append(p)
    return out


# ---------------------------------------------------------- the handshake


def test_a_saved_blind_pass_is_readable_as_labels(tmp_path):
    f = tmp_path / "pass.json"
    f.write_text(json.dumps({
        "reviewed_at": "2026-09-01", "source": "human",
        "tool": "pixcull m3 label", "blind": True, "selection": "blind",
        "verdicts": {"a.jpg": "keep", "b.jpg": "cull"}}), encoding="utf-8")
    recs = load_blind_sheet(f)
    assert len(recs) == 2
    assert all(label_provenance(r) == "human" for r in recs)


def test_a_blind_pass_can_actually_be_measured_against(tmp_path):
    """The end of the chain. Before v2.94 this raised."""
    f = tmp_path / "pass.json"
    f.write_text(json.dumps({
        "source": "human", "selection": "blind",
        "verdicts": {"a.jpg": "keep", "b.jpg": "cull"}}), encoding="utf-8")
    r = accuracy({"a.jpg": "keep", "b.jpg": "keep"}, load_blind_sheet(f))
    assert r["n"] == 2
    assert r["agreement"] == 0.5
    assert r["confusion"]["cull->keep"] == 1


def test_a_sheet_saved_before_v2_94_is_still_refused(tmp_path):
    """Nothing in that file says a person made it. Backfilling the field
    on read would be this module assuming exactly what it exists to stop
    anyone assuming."""
    f = tmp_path / "old.json"
    f.write_text(json.dumps({
        "selection": "blind", "verdicts": {"a.jpg": "keep"}}), encoding="utf-8")
    recs = load_blind_sheet(f)
    assert [label_provenance(r) for r in recs] == ["unknown"]
    with pytest.raises(CircularMeasurement):
        accuracy({"a.jpg": "keep"}, recs)


@pytest.mark.parametrize("doc", [
    "[]", "{}", '{"verdicts": []}', "not json at all",
    # A NON-EMPTY wrong type. The empty list above passes even without
    # the type check, because `[] or {}` is `{}` — it looked like
    # coverage and was not.
    '{"verdicts": ["a.jpg", "b.jpg"]}',
    '{"verdicts": "keep"}',
    '{"verdicts": 7}',
])
def test_a_malformed_file_yields_nothing_rather_than_raising(tmp_path, doc):
    f = tmp_path / "bad.json"
    f.write_text(doc, encoding="utf-8")
    assert load_blind_sheet(f) == []


def test_a_missing_file_yields_nothing(tmp_path):
    assert load_blind_sheet(tmp_path / "nope.json") == []


# ------------------------------------------------------------- the sheet


def _html(items, tmp_path):
    dest = write(items, tmp_path / "s.html", blind=True, slug="blind",
                 selection="blind", title="t", lede="l")
    return Path(str(dest)).read_text(encoding="utf-8")


def test_the_sheet_stamps_its_own_provenance(photos, tmp_path):
    body = _html([{"fn": p.name, "path": str(p)} for p in photos], tmp_path)
    assert 'source:"human"' in body.replace(" ", "")
    assert "pixcull m3 label" in body


def test_two_buttons_by_default(photos, tmp_path):
    body = _html([{"fn": p.name, "path": str(p)} for p in photos], tmp_path)
    assert 'class="mid"' not in body
    assert "mark(0,2)" not in body


def test_the_middle_button_is_opt_in(photos, tmp_path):
    items = [{"fn": p.name, "path": str(p), "mid_value": "maybe"}
             for p in photos]
    body = _html(items, tmp_path)
    assert body.count('class="mid"') == len(photos)
    assert 'data-mid="maybe"' in body


def test_the_three_values_map_through_one_function_only():
    """R[i] was a boolean and is now 1, 0 or 2. Every reader has to agree
    what that means, so the mapping lives in one place — a second copy is
    how a `maybe` gets recorded as a `cull`."""
    src = SHEET.read_text(encoding="utf-8")
    assert src.count("function _label(") == 1
    assert "R[i]?c.dataset.yes:c.dataset.no" not in src.replace(" ", ""), \
        "payload still reads R as a boolean, so a middle verdict saves as cull"
