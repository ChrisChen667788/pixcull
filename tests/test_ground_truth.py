"""v2.88 — the accuracy figure the roadmap planned cannot be computed.

Not because the harness was missing. Because the ground truth does not
exist. Audited on the machine that was supposed to hold the "608-row
correction set":

  pixcull_label_run/*/output/rubric.jsonl   415 records, source="auto"
  runs/*/output/vlm_verdicts.jsonl        1,114 records, carry model_name
  runs/*/output/meta_verdicts.jsonl       1,114 records, carry model_name
  human-produced labels                        0

The 415 rubric records match scores.csv exactly — 369 keep, 29 cull, 17
maybe on both sides — because they ARE scores.csv written back out.
Measured with strict=False, agreement is 100.0%. That number is the
proof, not the result.

Nobody would publish that on purpose. The danger is the arithmetic
running without complaint on a subtly different comparison and producing
something plausible. So the circular measurement now raises.
"""
import json

import pytest

from pixcull.scoring.ground_truth import (
    CircularMeasurement, accuracy, audit_labels, label_provenance,
)


# ------------------------------------------------------------ provenance


@pytest.mark.parametrize("rec", [
    {"source": "human"}, {"source": "owner"}, {"source": "RATER"},
    {"rater": "p1"}, {"annotator": "someone"},
])
def test_attested_human_labels_are_human(rec):
    assert label_provenance(rec) == "human"


@pytest.mark.parametrize("rec", [
    {"source": "auto"}, {"source": "model"}, {"source": "vlm"},
    {"model_name": "minimax:m3"}, {"elapsed_s": 1.2}, {"raw_text": "..."},
])
def test_model_output_is_model_output(rec):
    assert label_provenance(rec) == "model"


def test_a_label_with_no_provenance_is_not_assumed_human():
    """The assumption that would matter. Every model verdict on this
    machine lacks a `source` field; treating unlabelled provenance as
    human turns 2,228 model verdicts into a ground truth."""
    assert label_provenance({"filename": "a.jpg", "overall_label": "keep"}) \
        == "unknown"


def test_a_model_marker_beats_a_missing_source():
    rec = {"filename": "a.jpg", "overall_label": "keep",
           "model_name": "minimax:m3"}
    assert label_provenance(rec) == "model"


# ------------------------------------------------------------- the audit


def test_the_audit_counts_by_provenance(tmp_path):
    p = tmp_path / "labels.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in [
        {"filename": "a", "overall_label": "keep", "source": "auto"},
        {"filename": "b", "overall_label": "cull", "source": "human"},
        {"filename": "c", "overall_label": "keep"},
        {"not_a_label": 1},
    ]), encoding="utf-8")
    inv = audit_labels([p])
    assert inv.counts["model"] == 1
    assert inv.counts["human"] == 1
    assert inv.counts["unknown"] == 1
    assert inv.human == 1 and inv.usable_for_accuracy is True


def test_a_set_of_only_model_labels_is_not_usable(tmp_path):
    p = tmp_path / "auto.jsonl"
    p.write_text("\n".join(json.dumps(
        {"filename": f"f{i}", "overall_label": "keep", "source": "auto"})
        for i in range(50)), encoding="utf-8")
    inv = audit_labels([p])
    assert inv.human == 0
    assert inv.usable_for_accuracy is False


# ---------------------------------------------------------- the refusal


def test_measuring_against_model_output_raises():
    truth = [{"filename": f"f{i}", "overall_label": "keep", "source": "auto"}
             for i in range(20)]
    preds = {f"f{i}": "keep" for i in range(20)}
    with pytest.raises(CircularMeasurement) as e:
        accuracy(preds, truth)
    assert "model" in str(e.value)


def test_the_perfect_score_is_reachable_only_by_asking_for_it():
    """strict=False exists so the circularity can be DEMONSTRATED, and
    it returns 100% on identical inputs. It must never be the default."""
    truth = [{"filename": f"f{i}", "overall_label": "keep", "source": "auto"}
             for i in range(20)]
    preds = {f"f{i}": "keep" for i in range(20)}
    r = accuracy(preds, truth, strict=False)
    assert r["agreement"] == 1.0
    assert r["strict"] is False


def test_human_labels_produce_a_real_figure():
    truth = ([{"filename": f"f{i}", "overall_label": "keep", "source": "human"}
              for i in range(8)]
             + [{"filename": f"g{i}", "overall_label": "cull", "source": "human"}
                for i in range(2)])
    preds = {f"f{i}": "keep" for i in range(8)}
    preds.update({f"g{i}": "keep" for i in range(2)})     # both wrong
    r = accuracy(preds, truth)
    assert r["n"] == 10
    assert r["agreement"] == pytest.approx(0.8)
    assert r["confusion"]["cull->keep"] == 2


def test_model_records_are_excluded_even_when_humans_are_present():
    """A mixed set must be measured on the human half only, or the model
    half quietly inflates the agreement it is being measured against."""
    truth = ([{"filename": "h", "overall_label": "cull", "source": "human"}]
             + [{"filename": f"m{i}", "overall_label": "keep", "source": "auto"}
                for i in range(99)])
    preds = {"h": "keep"}
    preds.update({f"m{i}": "keep" for i in range(99)})
    r = accuracy(preds, truth)
    assert r["n"] == 1
    assert r["agreement"] == 0.0


def test_the_signature_takes_records_not_a_mapping():
    """Passing filename->label would strip the provenance and make the
    check impossible. The shape is the guard."""
    import inspect
    sig = inspect.signature(accuracy)
    p = sig.parameters.get("truth_records")
    assert p is not None
    assert p.default is inspect.Parameter.empty, (
        "truth_records has a default, so a caller can omit the records "
        "entirely and the provenance check has nothing to check")
    assert p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
