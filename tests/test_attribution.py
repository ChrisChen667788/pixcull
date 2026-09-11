"""v3.78 — the axis explanation may not come from a model that sees pixels.

`pixcull/scoring/attribution.py` used to produce Integrated Gradients
saliency maps "per rubric axis" over a timm CNN. It was never served,
and measuring it before wiring it up found three faults, the third
fatal:

* every axis produced a byte-identical PNG, because the per-axis heads
  it looked for moved into the package in v3.44 and the lookup was never
  updated, so all six silently took an identity fallback;
* with the path fixed it would still fall back, because it wants a
  `.coef.npy` surrogate nothing has ever exported;
* and the axis rescorers are sklearn pipelines over **29 tabular
  metrics** — `horizon_tilt_deg`, `rule_of_thirds_offset`, `face_count`
  — that never see pixels at all. A CNN saliency map cannot explain
  them. It would point at image regions the scorer never examined.

The module's previous ten tests all passed throughout: axis list, sha
determinism, cache paths, colour-ramp monotonicity. None compared two
axes' output. This file holds the claim instead of the plumbing.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "pixcull" / "scoring" / "attribution.py"
PACKAGED_MODELS = ROOT / "pixcull" / "models"

#: Any of these in a shipped module means something is computing a
#: pixel-space explanation again. Matched as substrings of a function or
#: call name: the first cut compared names exactly and let
#: `_serve_saliency` straight through, which is precisely the name such
#: a handler would have.
PIXEL_ATTRIBUTION = ("integrated_gradients", "build_heatmap",
                     "build_all_heatmaps", "saliency")

#: Code that computes a saliency map as an INPUT, with the reason.
#:
#: The distinction this gate is about is not the technique, it is where
#: the output goes. Deriving a feature from a saliency map is ordinary
#: image processing; presenting one to a photographer as the reason an
#: axis scored what it did is the defect, because the axis model never
#: saw the pixels.
#:
#: The first cut of this gate had no such list and went red on the
#: composition classifier, which is the honest case.
FEATURE_COMPUTATION = {
    "pixcull/scoring/composition_classifier.py::_saliency_map":
        "A coarse 32x32 map of brightness, local contrast and a centre "
        "prior, used to decide which compositional rule a frame follows. "
        "It produces `composition_score` and `rule_of_thirds_offset` — "
        "two of the 29 columns the axis model consumes. An input, not an "
        "explanation.",
}


def test_the_heatmap_machinery_is_gone():
    src = MODULE.read_text(encoding="utf-8")
    names = {n.name for n in ast.walk(ast.parse(src))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for gone in ("build_heatmap", "build_all_heatmaps", "_get_axis_head",
                 "_get_backbone", "_colorize_warm"):
        assert gone not in names, (
            f"{gone} is back. Read the module docstring before restoring "
            "it: the axis models do not consume pixels.")


def test_the_module_says_why_rather_than_just_being_short():
    """A deletion with no reason attached gets undone by whoever finds
    the gap. The reason is the durable part."""
    doc = ast.get_docstring(ast.parse(MODULE.read_text(encoding="utf-8")))
    assert doc, "the module lost its explanation"
    for must in ("tabular", "29", "v3.44"):
        assert must in doc, f"the docstring no longer explains {must!r}"


def test_nothing_serves_a_pixel_attribution_for_an_axis():
    """The gate with teeth. If a route or a handler starts producing one
    of these, the product is back to explaining a model it does not
    use."""
    offenders = []
    for path in sorted(ROOT.joinpath("pixcull").rglob("*.py")):
        if path == MODULE:
            continue
        src = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        # Structure, not text: a call or def by that name, never a
        # mention of one in a comment.
        for node in ast.walk(tree):
            name = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
            elif isinstance(node, ast.Call):
                f = node.func
                name = getattr(f, "attr", None) or getattr(f, "id", None)
            if name and any(k in name.lower() for k in PIXEL_ATTRIBUTION):
                offenders.append(f"{path.relative_to(ROOT)}::{name}")
    offenders = [o for o in offenders if o not in FEATURE_COMPUTATION]
    assert not offenders, (
        f"these compute or call a pixel-space attribution: {offenders}. "
        "The axis models are trees over tabular metrics; a saliency map "
        "over a CNN explains a different model.")


def test_a_feature_computation_exemption_carries_its_reason():
    """An exemption with no reason is how a list like this turns into a
    place things go to stop failing."""
    for key, why in FEATURE_COMPUTATION.items():
        assert len(why) > 60, f"{key} is exempt without a real reason"
        path, _, fn = key.partition("::")
        assert (ROOT / path).is_file(), f"{key} names a file that is gone"
        names = {n.name for n in ast.walk(
            ast.parse((ROOT / path).read_text(encoding="utf-8")))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert fn in names, f"{key} names a function that is gone"


def test_the_axis_models_really_are_tabular():
    """The premise of all of the above, asserted rather than assumed —
    if the axis models ever become image models, this reasoning changes
    and the test should fail so somebody re-reads it."""
    joblib = pytest.importorskip("joblib")
    path = PACKAGED_MODELS / "rescorer_axis_composition.joblib"
    if not path.is_file():
        pytest.skip("packaged axis model not present in this checkout")
    payload = joblib.load(path)
    cols = payload.get("feature_cols")
    assert cols, "the axis model no longer declares its feature columns"
    assert len(cols) > 10, f"only {len(cols)} features; re-read the premise"
    assert any(c in cols for c in ("horizon_tilt_deg", "face_count",
                                   "laplacian_global")), (
        f"the axis model's features are no longer named metrics: {cols[:8]}")
    assert not any(c.startswith("emb_") or c.startswith("feat_")
                   for c in cols), (
        "the axis model now takes embedding columns; a pixel-space "
        "explanation may be defensible again — re-read attribution.py")


def test_the_packaged_axis_models_are_where_the_resolver_looks():
    """The first of the three faults: the models moved in v3.44 and one
    consumer kept looking at the old path. Asserted so the next consumer
    cannot repeat it quietly."""
    from pixcull.model_assets import resolve
    found = [a for a in ("composition", "light", "subject", "technical",
                         "moment", "aesthetic")
             if resolve(Path("models") / f"rescorer_axis_{a}.joblib")]
    assert len(found) == 6, (
        f"only {len(found)}/6 axis models resolve: {found}. "
        "pixcull.model_assets.resolve is how a packaged model is found; "
        "a bare repo-root path misses every one of them.")


def test_the_upright_loader_survives_and_is_square():
    from pixcull.scoring.attribution import load_upright
    Image = pytest.importorskip("PIL.Image")
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.jpg"
        Image.new("RGB", (120, 60), (10, 20, 30)).save(p)
        assert load_upright(p, size=48).size == (48, 48)
