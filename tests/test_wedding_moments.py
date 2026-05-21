"""P-PRO-4 — tests for the wedding moment-list classifier helpers.

The classifier itself runs CLIP; these tests cover the pure-Python
infrastructure (moment vocabulary, margin abstain, coverage audit)
so they're fast + deterministic + don't need GPU.
"""
from __future__ import annotations

import pytest

from pixcull.scoring.wedding_moments import (
    MANDATORY_CHINESE,
    MANDATORY_PRESETS,
    MANDATORY_WESTERN,
    MOMENT_ABSTAIN_MARGIN,
    MOMENT_UNKNOWN_LABEL,
    WEDDING_MOMENTS,
    coverage_audit,
    known_moment_keys,
    mandatory_moment_keys,
    moment_label_zh,
    moment_prompts,
    resolve_moment_with_abstain,
)


def test_known_moments_nonempty_and_unique():
    keys = known_moment_keys()
    assert len(keys) >= 10, "should cover the main wedding sequence"
    assert len(set(keys)) == len(keys), "no duplicate moment keys"


def test_every_moment_has_a_prompt_and_label():
    for m in WEDDING_MOMENTS:
        assert m.prompt.strip(), f"moment {m.key} missing prompt"
        assert m.label_zh.strip(), f"moment {m.key} missing zh label"
        # ASCII snake_case key — survives CSV/JSON
        assert all(c.isalnum() or c == "_" for c in m.key), \
            f"key {m.key!r} should be ASCII snake_case"


def test_mandatory_moments_subset_of_all():
    mand = set(mandatory_moment_keys())
    all_keys = set(known_moment_keys())
    assert mand.issubset(all_keys)
    # At least the no-album-survives-without-them moments are mandatory
    for must_have in ("ring_exchange", "first_kiss", "first_dance"):
        assert must_have in mand, \
            f"{must_have} should be flagged mandatory — it's contract-grade"


def test_label_zh_falls_back_to_key_for_unknown():
    assert moment_label_zh("first_kiss")  # known
    assert moment_label_zh("not_a_real_moment") == "not_a_real_moment"


def test_moment_prompts_returns_full_map():
    prompts = moment_prompts()
    assert len(prompts) == len(WEDDING_MOMENTS)
    assert "first_kiss" in prompts


def test_resolve_clear_winner_returns_pick():
    probs = {
        "first_kiss":  0.50,
        "vows":        0.20,
        "candid":      0.30,
    }
    pick, p, abst = resolve_moment_with_abstain(probs)
    assert pick == "first_kiss"
    assert p == pytest.approx(0.50)
    assert abst is False


def test_resolve_tight_margin_abstains():
    """Top-1 and top-2 within MOMENT_ABSTAIN_MARGIN → unknown."""
    probs = {
        "first_kiss":  0.31,
        "vows":        0.30,
        "candid":      0.39,
    }
    # candid wins clearly (0.39 vs 0.31 = 0.08 > 0.05) → not abstain
    pick, _, abst = resolve_moment_with_abstain(probs)
    assert pick == "candid"
    assert abst is False


def test_resolve_actually_tight_pair_abstains():
    probs = {
        "cake_cutting": 0.34,
        "first_dance":  0.32,   # margin 0.02 < 0.05
        "candid":       0.34,
    }
    pick, p, abst = resolve_moment_with_abstain(probs)
    assert pick == MOMENT_UNKNOWN_LABEL
    assert abst is True
    # still reports the top-1 probability for telemetry
    assert p > 0.30


def test_resolve_empty_returns_unknown():
    pick, p, abst = resolve_moment_with_abstain({})
    assert pick == MOMENT_UNKNOWN_LABEL
    assert p == 0.0
    assert abst is True


def test_coverage_audit_counts_moments():
    rows = [
        {"wedding_moment": "first_kiss"},
        {"wedding_moment": "first_kiss"},
        {"wedding_moment": "vows"},
        {"wedding_moment": "candid"},
    ]
    rpt = coverage_audit(rows)
    assert rpt.n_rows == 4
    assert rpt.moment_counts["first_kiss"] == 2
    assert rpt.moment_counts["vows"] == 1
    assert rpt.moment_counts["candid"] == 1


def test_coverage_audit_flags_missing_mandatory():
    """A wedding with no ring_exchange shots should surface as missing."""
    rows = [
        {"wedding_moment": "first_kiss"},
        {"wedding_moment": "first_dance"},
    ]
    rpt = coverage_audit(rows)
    assert "ring_exchange" in rpt.missing_mandatory
    # The two mandatory ones we DID capture should NOT be in missing
    assert "first_kiss" not in rpt.missing_mandatory
    assert "first_dance" not in rpt.missing_mandatory


def test_coverage_audit_unknown_counted_separately():
    rows = [
        {"wedding_moment": "first_kiss"},
        {"wedding_moment": "unknown"},   # abstained
        {"wedding_moment": None},        # no moment
        {},                              # no field at all
    ]
    rpt = coverage_audit(rows)
    assert rpt.n_unknown == 3
    assert rpt.moment_counts["first_kiss"] == 1


def test_coverage_pct_calculation():
    """coverage_pct = % of mandatory moments with ≥1 photo."""
    rows_capturing_all = [
        {"wedding_moment": k} for k in mandatory_moment_keys()
    ]
    rpt = coverage_audit(rows_capturing_all)
    assert rpt.coverage_pct == 100.0
    assert rpt.missing_mandatory == []

    rpt2 = coverage_audit([])  # no shots at all
    assert rpt2.coverage_pct == 0.0
    assert set(rpt2.missing_mandatory) == set(mandatory_moment_keys())


def test_alternative_moment_field_name():
    """Caller can pass a custom moment_field — used by experimental
    eval pipelines that store the moment under a different column."""
    rows = [{"experimental_moment": "vows"}]
    rpt = coverage_audit(rows, moment_field="experimental_moment")
    assert rpt.moment_counts["vows"] == 1


# -----------------------------------------------------------------
# P-PRO-4.3 — MANDATORY_OVERRIDES + Chinese wedding moments
# -----------------------------------------------------------------

def test_chinese_moments_present_in_vocab():
    """All 6 Chinese moments should be in the vocabulary with prompts
    + Chinese labels."""
    keys = known_moment_keys()
    for must_have in ("door_block", "hair_combing", "tea_ceremony",
                      "kneeling_bow", "red_dress", "firecrackers"):
        assert must_have in keys, f"{must_have} missing from vocab"
        assert moment_label_zh(must_have) != must_have, \
            f"{must_have} missing Chinese label"


def test_mandatory_presets_have_expected_shape():
    """Both western and chinese mandatory presets are non-empty lists."""
    assert isinstance(MANDATORY_WESTERN, list)
    assert isinstance(MANDATORY_CHINESE, list)
    assert len(MANDATORY_WESTERN) >= 4
    assert len(MANDATORY_CHINESE) >= 4
    # Both presets must reference only known moment keys
    all_keys = set(known_moment_keys())
    for k in MANDATORY_WESTERN + MANDATORY_CHINESE:
        assert k in all_keys, f"unknown key in mandatory list: {k}"
    # Presets lookup dict is wired up
    assert "western" in MANDATORY_PRESETS
    assert "chinese" in MANDATORY_PRESETS
    assert MANDATORY_PRESETS["chinese"] == MANDATORY_CHINESE


def test_coverage_audit_with_chinese_mandatory_overrides_western():
    """A Chinese wedding shouldn't be docked for missing first_dance —
    that's not in their mandatory list."""
    rows = [
        {"wedding_moment": "tea_ceremony"},
        {"wedding_moment": "kneeling_bow"},
        {"wedding_moment": "hair_combing"},
    ]
    rpt = coverage_audit(rows, mandatory_keys=MANDATORY_CHINESE)
    # first_dance / cake_cutting are NOT in the Chinese mandatory list,
    # so a wedding without them should not be docked for missing them.
    assert "first_dance" not in rpt.missing_mandatory
    assert "cake_cutting" not in rpt.missing_mandatory
    # But things ARE in the Chinese list — ring_exchange / first_kiss /
    # door_block — should appear as missing.
    assert "door_block" in rpt.missing_mandatory
    assert "first_kiss" in rpt.missing_mandatory
    assert "ring_exchange" in rpt.missing_mandatory


def test_coverage_audit_records_used_mandatory_list():
    """The CoverageReport carries the mandatory_keys it was scored
    against, so downstream renders ("Western mandatory" vs
    "Chinese mandatory" label) know which preset was used."""
    rpt = coverage_audit([], mandatory_keys=MANDATORY_CHINESE)
    assert rpt.mandatory_keys == MANDATORY_CHINESE


def test_coverage_audit_custom_mandatory_list():
    """A user can pass any custom list — not just a preset."""
    rows = [{"wedding_moment": "vows"}]
    custom = ["vows", "first_kiss"]   # niche civil ceremony
    rpt = coverage_audit(rows, mandatory_keys=custom)
    assert rpt.coverage_pct == 50.0   # 1 of 2 hit
    assert "first_kiss" in rpt.missing_mandatory
    assert "vows" not in rpt.missing_mandatory


def test_coverage_audit_default_still_works_pre_p_pro_43():
    """Backwards-compat: callers from before P-PRO-4.3 (no
    mandatory_keys arg) must still get the western mandatory list."""
    rpt = coverage_audit([])
    assert "ring_exchange" in rpt.missing_mandatory
    assert "first_dance" in rpt.missing_mandatory
    assert "cake_cutting" in rpt.missing_mandatory
    # Should NOT include Chinese-specific moments
    assert "tea_ceremony" not in rpt.missing_mandatory
    assert "door_block" not in rpt.missing_mandatory
