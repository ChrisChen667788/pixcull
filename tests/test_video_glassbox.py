"""v2.17-P0 — the reel glass box reaches the review surface: template hooks
for the per-window sub-signal bars + why-low line exist and stay wired."""

from pathlib import Path

_TPL = (Path(__file__).resolve().parent.parent
        / "pixcull" / "report" / "templates" / "video_review.html")


def test_review_template_renders_glassbox_hooks():
    t = _TPL.read_text(encoding="utf-8")
    assert "function sigBar(" in t              # mini-bar helper
    assert "c.signals" in t                     # guarded field access
    assert "c.why_low" in t                     # why-low line
    assert 'class="sigbars"' in t               # render container
    assert 'class="whylow"' in t
    # old reel_candidates.json (no fields) must degrade gracefully:
    # both injections are ternary-guarded on the field's presence.
    assert "(c.signals?(" in t
    assert "(c.why_low?(" in t
