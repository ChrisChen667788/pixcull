"""v3.7 — the doubt travels to the catalogue with the verdict.

`decision_to_xmp` has always sent keep/maybe/cull to Lightroom as stars
and a colour label. How sure the tool was stayed behind, so a catalogue
could sort by the verdict and could not ask "which of these was the tool
unsure about" — which is the question a photographer actually asks of a
machine's cull.

Capture One's Assisted Review is the design worth copying, and the part
worth copying is not the wording: their "Can't tell" is a TAG, and tags
are Smart Album criteria. A keyword is that same object in Lightroom.
"""
import tempfile
from pathlib import Path

from pixcull.io import xmp as X


def test_a_measured_disagreement_is_tagged_as_measured():
    kw = X._uncertainty_keywords({"measured_agreement": 2 / 3})
    assert kw == [X.UNCERTAIN_KEYWORD, X.UNCERTAIN_MEASURED]


def test_a_measurement_overrules_the_models_opinion_of_itself():
    """Both signals present. The measured one decides and the
    self-reported one does not get a second vote."""
    kw = X._uncertainty_keywords({"measured_agreement": 1.0,
                                  "meta_confidence": 0.1,
                                  "meta_inconsistencies": "焦点与主体冲突"})
    assert kw == []


def test_self_reported_doubt_is_labelled_as_self_reported():
    """The two are not the same claim. Collapsing them into one tag
    launders the weaker signal into the stronger one's authority."""
    assert X._uncertainty_keywords({"meta_confidence": 0.4}) == [
        X.UNCERTAIN_KEYWORD, X.UNCERTAIN_SELF_REPORTED]
    assert X._uncertainty_keywords(
        {"meta_confidence": 0.95, "meta_inconsistencies": "x"}) == [
        X.UNCERTAIN_KEYWORD, X.UNCERTAIN_SELF_REPORTED]


def test_an_unjudged_frame_is_not_tagged_either_way():
    """A frame the meta pass never saw is not certain — it is unexamined.
    Tagging it would put a claim in the catalogue the run never made."""
    assert X._uncertainty_keywords({}) == []
    assert X._uncertainty_keywords({"meta_inconsistencies": ""}) == []


def test_anything_short_of_unanimous_counts_as_doubt():
    assert X._uncertainty_keywords({"measured_agreement": 0.99})
    assert X._uncertainty_keywords({"measured_agreement": 1.0}) == []


def test_booleans_are_not_mistaken_for_scores():
    """Booleans are ints in Python, and a row can carry one — a column
    that was a flag before it was a float, a pandas cast, a CSV "False".

    `False` is the value that separates the two implementations: without
    the guard it compares as 0.0, so it slips under every gate and marks
    a frame uncertain on a signal that was never a score. `True` would
    pass either way, which is why asserting on it protects nothing.
    """
    assert X._uncertainty_keywords({"measured_agreement": False}) == []
    assert X._uncertainty_keywords({"measured_agreement": True}) == []
    assert X._uncertainty_keywords({"meta_confidence": False}) == []


def test_the_keyword_strings_are_a_pinned_public_contract():
    """These end up in a third-party catalogue and in smart collections
    the photographer built by hand. Renaming one is a migration."""
    assert X.UNCERTAIN_KEYWORD == "PixCull:uncertain"
    assert X.UNCERTAIN_MEASURED == "PixCull:uncertain:measured"
    assert X.UNCERTAIN_SELF_REPORTED == "PixCull:uncertain:self-reported"


# -- the reachability half -------------------------------------------

def test_the_row_builder_actually_emits_them():
    row = {"decision": "maybe", "measured_agreement": 0.5}
    fields = X.build_iptc_fields_from_row(row)
    assert X.UNCERTAIN_KEYWORD in fields["keywords"]
    assert X.UNCERTAIN_MEASURED in fields["keywords"]


def test_a_certain_row_carries_no_uncertainty_keyword():
    fields = X.build_iptc_fields_from_row(
        {"decision": "keep", "measured_agreement": 1.0})
    assert not [k for k in fields["keywords"] if "uncertain" in k]


def test_the_keyword_survives_into_the_written_sidecar():
    """A keyword the exporter builds and the writer drops is the same
    defect as never building it."""
    row = {"decision": "maybe", "meta_confidence": 0.3}
    fields = X.build_iptc_fields_from_row(row)
    with tempfile.TemporaryDirectory() as d:
        img = Path(d) / "DSC_0001.NEF"
        out = X.write_xmp(img, 3, "Yellow", keywords=fields["keywords"])
        text = out.read_text(encoding="utf-8")
    assert X.UNCERTAIN_KEYWORD in text
    assert X.UNCERTAIN_SELF_REPORTED in text
