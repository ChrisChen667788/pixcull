from functools import cache

import torch
from PIL import Image

from pixcull.detectors.base import DetectionResult, Detector


# P-CORE-2 — per-class posterior priors. These multiply the raw
# CLIP softmax output to correct for known over-firing classes
# before argmax.  Values come from a confusion audit on the
# 4508-image scan + the goldenset:
#
#   stilllife   : 35% of frames tagged stilllife on the user's
#                 scan, but golden-truth says it's only ~10% of
#                 their portfolio. CLIP confuses "indoor portrait
#                 with uniform background" + "any close-up under
#                 tungsten light" as stilllife. Shrink to 0.75.
#   documentary : was already tightened in V18.2, but it still
#                 over-fires on event/sports edge cases. 0.85.
#   abstract    : tends to absorb out-of-focus or pattern-heavy
#                 frames that are really landscape/macro. 0.85.
#   landscape   : slight under-fires when there's a small subject
#                 in a wide scenic frame. Boost to 1.10.
#   portrait    : neutral.  Already gets a face-presence rerank
#                 from V20 in worker.py, no prior needed.
#
# Priors apply BEFORE the margin abstain check, so they shape
# both the picked class AND the abstain decision.  Renormalized
# to sum to 1 after the multiplicative step so downstream
# consumers still see proper probability semantics.
SCENE_PRIORS: dict[str, float] = {
    "stilllife":   0.75,
    "documentary": 0.85,
    "abstract":    0.85,
    "landscape":   1.10,
    # all other classes are at 1.0 by default (see _scene_prior_for)
}

# If after prior-correction the gap between top-1 and top-2 is
# tighter than this, mark the scene "unknown" instead of forcing
# a confident pick.  Downstream (get_strategy in genre_strategies)
# already falls back to identity for unknown.  Threshold of 0.04
# = 4 percentage points was picked so that *clear* picks (top-1
# typically > 0.30, runner-up < 0.15) always succeed while
# genuinely tied cases (top-1 ~0.18, runner-up ~0.16) abstain
# cleanly.  Audit on the 4508-scan suggests this affects ~5% of
# frames — exactly the ambiguous-content tail we want to handle
# with downstream face/EXIF heuristics rather than CLIP guessing.
SCENE_ABSTAIN_MARGIN: float = 0.04
SCENE_UNKNOWN_LABEL: str = "unknown"


def _scene_prior_for(name: str) -> float:
    return SCENE_PRIORS.get(name, 1.0)


def _apply_priors_and_renormalize(
    names: list[str], probs: list[float]
) -> list[float]:
    """Multiply each prob by its class prior and renormalize to 1.

    Pure-Python so it's testable without torch + works when this
    module is imported by a script that doesn't have CLIP loaded.
    """
    weighted = [p * _scene_prior_for(n) for n, p in zip(names, probs)]
    total = sum(weighted)
    if total <= 0:
        return list(probs)  # degenerate; fall back to raw
    return [w / total for w in weighted]


def _resolve_scene_with_abstain(
    names: list[str], probs: list[float]
) -> tuple[str, float, bool]:
    """Run argmax with margin-based abstain.

    Returns (chosen_name, chosen_prob, abstained).  When the
    margin between top-1 and top-2 is below
    SCENE_ABSTAIN_MARGIN, chosen_name is set to
    SCENE_UNKNOWN_LABEL and abstained = True; chosen_prob is
    still the top-1 prob so callers retain a confidence number
    for telemetry.
    """
    pairs = sorted(zip(names, probs), key=lambda kv: kv[1], reverse=True)
    if not pairs:
        return SCENE_UNKNOWN_LABEL, 0.0, True
    top_name, top_p = pairs[0]
    runner_p = pairs[1][1] if len(pairs) > 1 else 0.0
    if (top_p - runner_p) < SCENE_ABSTAIN_MARGIN:
        return SCENE_UNKNOWN_LABEL, float(top_p), True
    return str(top_name), float(top_p), False


SCENE_PROMPTS: dict[str, str] = {
    # V0.x core genres
    "portrait":     "a portrait photo of people, wedding or event portrait",
    "wildlife":     "a wildlife photo of a bird or animal in nature",
    "event":        "a sports or event photo with people in action",
    "stilllife":    "a product or still life photo, indoor studio setup",
    "landscape":    "a landscape or scenery photo, outdoors",
    "street":       "a street photography photo, candid urban scene",
    # V8.2 expanded genres — broader coverage of classic + modern
    # photographic practice. Prompt strings tuned via cross-validation
    # against the goldenset; each entry is sufficiently distinct from
    # all others that CLIP softmax assigns confident probability.
    "architecture": "an architectural photo of a building's exterior or interior",
    # V18.2: tightened — original prompt "a documentary or
    # photojournalism photo with strong narrative content" was a
    # catch-all that CLIP would argmax onto ANY casual family/event
    # photo. Audit on the user's 4508-image scan: 1616 / 4508 (35.8%)
    # were tagged documentary, often by a margin of < 0.05 over the
    # runner-up (portrait/event/fashion). New prompt is anchored on
    # news-content semantics specifically; 50-sample A/B showed
    # 41/50 relabel to more appropriate categories
    # (16 portrait, 8 event, 7 fashion, 6 abstract, 3 street, 1 wildlife)
    # with 9 remaining genuinely news-like (photojournalism).
    "documentary":  "photojournalism of newsworthy events, protests, war zones, or social issues",
    "fashion":      "a fashion or editorial photo with stylized clothing and posing",
    "macro":        "a close-up macro photo of a tiny subject like an insect or flower detail",
    "food":         "a food photography shot with arranged dishes",
    "sports":       "a sports action photo capturing athletic movement",
    "astro":        "an astrophotography photo of the night sky, stars, or milky way",
    "abstract":     "an abstract photograph emphasizing pattern, texture, or form over subject",
}


@cache
def _clip():
    from transformers import CLIPModel, CLIPProcessor

    device = (
        "cuda" if torch.cuda.is_available()
        else "mps" if torch.backends.mps.is_available()
        else "cpu"
    )
    proc = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(device).eval()
    return proc, model, device


class SceneDetector(Detector):
    """CLIP zero-shot scene classifier. No training needed."""

    name = "scene"

    @torch.no_grad()
    def analyze(self, img: Image.Image, **_: object) -> DetectionResult:
        proc, model, device = _clip()
        inputs = proc(
            text=list(SCENE_PROMPTS.values()),
            images=img,
            return_tensors="pt",
            padding=True,
        ).to(device)
        out = model(**inputs)
        raw_probs = out.logits_per_image.softmax(dim=-1).cpu().numpy()[0]
        names = list(SCENE_PROMPTS.keys())
        raw_probs_list = [float(p) for p in raw_probs]

        # P-CORE-2 — apply class priors + margin-based abstain.
        # Raw softmax probs are kept under "scene_probs_raw" so the
        # admin debug panel and confusion audit can see what CLIP
        # said without the correction.
        calibrated = _apply_priors_and_renormalize(names, raw_probs_list)
        scene, top_p, abstained = _resolve_scene_with_abstain(names, calibrated)

        result = DetectionResult()
        result.metrics["scene_confidence"] = float(top_p)
        result.extras["scene"] = scene
        # ``scene_probs`` reflects the calibrated, post-prior
        # posteriors so downstream re-rankers (the V20 face-aware
        # stilllife demoter in worker.py) operate on the corrected
        # distribution.  ``scene_probs_raw`` is the pre-prior CLIP
        # softmax — kept for audit + telemetry only.
        result.extras["scene_probs"] = dict(zip(names, calibrated))
        result.extras["scene_probs_raw"] = dict(zip(names, raw_probs_list))
        if abstained:
            # Flagging "scene_uncertain" lets the rescorer ignore
            # the genre adjustment for this frame (treat as generic)
            # and surfaces the abstain on the admin debug page.
            result.flags.append("scene_uncertain")
        return result
