"""P-PRO-4.1 — wedding moment detector (CLIP zero-shot).

Wraps the moment vocabulary from ``pixcull.scoring.wedding_moments``
in a Detector-compatible class.  Only meant to run when the photo's
scene / vertical is "wedding" — orchestrator's pipeline decides
when to call this, the detector itself just classifies whatever
image it's given.

Reuses the same CLIP model + processor that ``detectors.scene``
loads (cached at module level), so adding this pass to the worker
adds zero extra model weight in memory.
"""
from __future__ import annotations

from typing import Optional

import torch
from PIL import Image

from pixcull.detectors.base import DetectionResult, Detector
from pixcull.detectors.scene import _clip
from pixcull.scoring.wedding_moments import (
    MOMENT_UNKNOWN_LABEL,
    WEDDING_MOMENTS,
    moment_prompts,
    resolve_moment_with_abstain,
)


class WeddingMomentDetector(Detector):
    """CLIP zero-shot classifier over the 16-moment wedding
    vocabulary.

    Behaviour mirrors ``SceneDetector``: builds the prompts once,
    softmaxes per image, applies the margin-abstain helper to
    produce a clean label.  Uncertain frames get
    ``wedding_moment = "unknown"`` and a ``moment_uncertain`` flag.
    """

    name = "wedding_moment"

    def __init__(self) -> None:
        # Pre-cache the prompt list so each per-image call doesn't
        # have to walk WEDDING_MOMENTS again.  Order matches the
        # vocabulary's iteration order, which is intentional + stable
        # in ``WEDDING_MOMENTS`` (list, not dict).
        self._keys = [m.key for m in WEDDING_MOMENTS]
        self._prompts = [moment_prompts()[k] for k in self._keys]

    @torch.no_grad()
    def analyze(self, img: Image.Image, **_: object) -> DetectionResult:
        proc, model, device = _clip()
        inputs = proc(
            text=self._prompts,
            images=img,
            return_tensors="pt",
            padding=True,
        ).to(device)
        out = model(**inputs)
        probs = out.logits_per_image.softmax(dim=-1).cpu().numpy()[0]
        prob_map = {k: float(p) for k, p in zip(self._keys, probs)}

        chosen, top_p, abstained = resolve_moment_with_abstain(prob_map)

        result = DetectionResult()
        result.metrics["wedding_moment_confidence"] = float(top_p)
        result.extras["wedding_moment"] = chosen
        result.extras["wedding_moment_probs"] = prob_map
        if abstained:
            result.flags.append("moment_uncertain")
        return result
