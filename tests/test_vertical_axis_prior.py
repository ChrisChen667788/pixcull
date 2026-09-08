"""v3.37 — the axis weighting the README promised and the scorer never did.

`verticals.primary_axes` has been hand-authored for all ten verticals
since V17 — a curated statement of which axes each kind of shoot cares
about — and was read by exactly two callers: a serialiser and a phrase
generator.  Ten judgements in the data model feeding nothing, while the
README said each vertical "adjusts the keep/maybe thresholds AND WEIGHTS
THE AXES to taste".

`decision.py` does apply a per-vertical policy.  It shifts thresholds and
tolerates flags.  It does not weight the axes.

Both halves are fixed here: the data reaches scoring as a cold-start
prior, and the claim is rewritten to describe what actually happens.
"""
import inspect
import re
from pathlib import Path

import pytest

from pixcull import verticals as V

ROOT = Path(__file__).resolve().parent.parent
AXES = ("technical", "subject", "composition", "light", "moment", "aesthetic")


def test_every_vertical_still_carries_its_curated_axes():
    """Ten hand-made judgements. If one is ever emptied, the prior for
    that vertical silently becomes "no opinion"."""
    items = list(V.VERTICALS.values()) if hasattr(V.VERTICALS, "values") \
        else list(V.VERTICALS)
    assert len(items) >= 10
    for v in items:
        assert v.primary_axes, f"{v} has no primary_axes"


def test_the_prior_weights_every_axis_and_sums_to_one():
    w = V.axis_weight_prior("wildlife")
    assert set(w) == set(AXES)
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_the_prior_follows_the_curated_order():
    """`primary_axes` is a RANK statement — subject before moment before
    technical for wildlife — and the weights have to keep that order or
    the curation is being ignored while appearing to be used."""
    w = V.axis_weight_prior("wildlife")
    listed = V.get_vertical("wildlife").primary_axes
    ranked = [a for a in sorted(w, key=lambda a: -w[a]) if a in listed]
    assert ranked == list(listed)


def test_an_unmentioned_axis_is_not_switched_off():
    """Unlisted is unmentioned, not worthless. No vertical's author asked
    for an axis to stop counting.

    Threshold stated as a fraction of equal weight, not as an absolute.
    The first version of this used 0.05, which a zeroed unlisted axis
    clears anyway (it lands at half of equal), so the assertion did not
    guard the thing it was written for.
    """
    equal = 1 / len(AXES)
    w = V.axis_weight_prior("wildlife")
    for a in AXES:
        assert w[a] > 0.6 * equal, (
            f"{a} at {w[a]:.3f} is below 60% of an equal split — an "
            f"unmentioned axis has been switched off, not de-emphasised")


def test_an_unknown_vertical_says_no_opinion_rather_than_equal_weights():
    """None and "everything matters equally" are different answers, and a
    caller has to be able to tell them apart."""
    assert V.axis_weight_prior("no-such-vertical") is None
    assert V.axis_weight_prior(None) is None
    assert V.axis_weight_prior("") is None


def test_strength_zero_is_the_pre_v3_37_behaviour():
    w = V.axis_weight_prior("wildlife", strength=0.0)
    assert all(abs(x - 1 / 6) < 1e-9 for x in w.values())


def test_the_prior_is_a_nudge_not_a_rewrite():
    """A hand-made guess that reorders a cull as hard as a measured
    profile would is a guess wearing a measurement's clothes."""
    assert 0.0 < V.PRIOR_STRENGTH <= 0.5
    w = V.axis_weight_prior("wildlife")
    assert max(w.values()) < 2.0 / 6, "the top axis moves more than 2x equal"


def test_it_is_off_until_measured(monkeypatch):
    monkeypatch.delenv(V.ENV_FLAG, raising=False)
    assert V.axis_prior_enabled() is False
    monkeypatch.setenv(V.ENV_FLAG, "1")
    assert V.axis_prior_enabled() is True


# -- precedence, decided here rather than discovered later ------------

def test_corrections_beat_the_prior():
    """A hand-made guess overriding a measured profile is a downgrade the
    moment the profile exists."""
    from pixcull.pipeline import orchestrator
    src = inspect.getsource(orchestrator.run_pipeline)
    learned = src.index("_axis_pref = axis_weights(_pp)")
    prior = src.index("if _axis_pref is None:")
    assert learned < prior
    block = src[prior:prior + 900]
    assert "axis_weight_prior(vertical)" in block


# -- the claim and the code agree ------------------------------------

def test_the_readme_no_longer_says_the_genre_weights_the_axes():
    """The sentence this version exists because of."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r'Per-genre verticals\.\*\*(.{0,700})', text, re.S)
    assert m, "the feature entry moved"
    para = m.group(1)
    assert "weights the axes\n   to taste" not in para
    assert "comes from your own\n   corrections" in para


def test_the_readme_names_the_flag_rather_than_implying_a_default():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert V.ENV_FLAG in text
