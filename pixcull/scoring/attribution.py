"""What used to be per-axis attribution heatmaps, and why they are gone.

v0.13-P0-1 shipped `build_heatmap(image_path, axis)`: Integrated
Gradients over a timm `mobilenetv3_small_100` backbone, producing a
256×256 saliency map per (photo, axis) pair for alpha-blended overlay on
the lightbox. It was advertised in the shortcut sheet, the feature tour,
a first-run toast and, step by step, in both READMEs, beside a
screenshot captioned as showing it.

Nothing ever served it. v3.75 removed the advertisements, v3.76 recorded
it as an unfinished feature, and v3.78 measured it before wiring it up.

**It was not unfinished. It was the wrong shape.**

Three things, each enough on its own:

1. **Every axis produced a byte-identical PNG.** `_get_axis_head` looked
   for `models/rescorer_axis_<axis>.joblib`; the models moved into the
   package in v3.44 and live at `pixcull/models/`, so the lookup always
   missed and every axis silently took an identity fallback —
   `feats.mean(dim=1)` — which ignores the axis entirely. Measured: the
   same sha256 for composition, light, subject and technical.

2. **Even with the path fixed it would still fall back.** On finding the
   joblib it loads the estimator, discards it, looks for a
   `rescorer_axis_<axis>.coef.npy` that was never exported by anything,
   and returns the identity again.

3. **And a correct implementation would still be wrong.** The axis
   rescorers are sklearn pipelines over **29 named tabular metrics** —
   `horizon_tilt_deg`, `rule_of_thirds_offset`, `face_count`,
   `laplacian_global`, `subject_fraction` and so on. They never see
   pixels. An Integrated Gradients map over a CNN cannot explain a model
   that does not consume the CNN: it would attribute the decision to
   image regions the scorer never examined.

That last one is why this is deleted rather than repaired. A saliency
map is persuasive — it is a picture, drawn over the photograph, pointing
at things. In a product whose distinguishing claim is that it tells you
*why*, shipping a confident explanation of a model it does not use is a
worse defect than having no explanation at all.

Ten tests covered this module and all of them passed: the canonical axis
list, sha determinism, cache directory layout, the colour ramp's shape
and monotonicity. Not one compared two axes' output. The plumbing was
tested and the claim was not.

**The honest explanation already ships.** Those 29 metrics are readable
on their own — `horizon_tilt_deg` is a number in degrees — and the
product already surfaces them as the cull-reason taxonomy and the
per-axis driver line ("构图 4.8★ 撑分,光线 2.5★ 拖后腿"). Attributing
an axis score to the features it actually consumes is the shape a real
version of this would take, and `docs/OPEN-ITEMS.md` describes it.

What remains here is the one piece that had a consumer: opening a
photograph the way a viewer sees it.
"""
from __future__ import annotations


def load_upright(image_path, size: int = 224):
    """Open one photo square and the right way up.

    Kept from the removed heatmap path because the EXIF-orientation gate
    uses it, and because the ordering it pins is easy to get wrong:
    transpose BEFORE the square resize. Transposing after would hand a
    model a frame whose aspect ratio never existed.
    """
    from PIL import Image, ImageOps
    return (ImageOps.exif_transpose(Image.open(image_path))
            .convert("RGB").resize((size, size)))

