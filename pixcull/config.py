"""Load and validate scene_templates.yaml via pydantic."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


DEFAULT_TEMPLATE_PATH = Path(__file__).parent / "scoring" / "templates" / "scene_templates.yaml"


class SceneTemplate(BaseModel):
    description: str = ""
    detectors: dict[str, bool] = Field(default_factory=dict)
    blur: dict[str, Any] = Field(default_factory=dict)
    duplicate: dict[str, Any] = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=dict)
    bonuses: dict[str, float] = Field(default_factory=dict)
    penalties: dict[str, float] = Field(default_factory=dict)
    use_defaults: bool = False


class RescorerConfig(BaseModel):
    """V1.2 learned-head integration knobs.

    ``mode`` controls how ``decide()`` uses the rescorer:

    * ``off`` — rescorer is not loaded; pipeline runs V1.1 rules only. This
      is the default; flipping on requires an explicit CLI flag or YAML
      override so a fresh clone never surprises the user.
    * ``shadow`` — rescorer loaded and scored for every non-cull row, its
      prediction + P(keep) are attached to each record, but the decision
      itself is still the rule-stack's. Safe to leave on for long periods —
      it's the V1.2 data-collection mode.
    * ``adjudicate`` — rescorer can *override* the rule-stack's maybe verdict.
      If rule says maybe and P(keep) ≥ ``keep_threshold`` → promote to keep.
      If rule says maybe and P(keep) ≤ ``maybe_to_cull_threshold`` → demote
      to cull. Rule keeps/culls are never touched in V1.2; we only re-sort
      the ambiguous middle bucket. This is the ship mode once the V1.2 gates
      in ``scripts/check_v1_2_trigger.py`` all turn green.

    The thresholds are deliberately asymmetric: the cost of a wrong cull is
    much higher than the cost of a wrong keep, so the bar to demote maybe →
    cull is set well below the bar to promote maybe → keep.
    """

    mode: str = "off"  # "off" | "shadow" | "adjudicate"
    model_path: str = "models/rescorer_v1.joblib"
    # P(keep) threshold for promoting a rule-maybe → keep in adjudicate mode
    keep_threshold: float = 0.75
    # P(keep) threshold for demoting a rule-maybe → cull in adjudicate mode.
    # Leave at 0.0 (= never demote) until eval shows false-cull rate is safe.
    maybe_to_cull_threshold: float = 0.0


class PixCullConfig(BaseModel):
    version: str
    defaults: dict[str, Any]
    scenes: dict[str, SceneTemplate]
    fusion: dict[str, Any]
    rescorer: RescorerConfig = Field(default_factory=RescorerConfig)

    @classmethod
    def load(cls, path: Path | None = None) -> "PixCullConfig":
        path = path or DEFAULT_TEMPLATE_PATH
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)

    def template_for(self, scene: str) -> SceneTemplate:
        """Return scene template, falling back to defaults if use_defaults=True or missing."""
        if scene not in self.scenes:
            return SceneTemplate(**self._defaults_as_template())
        tpl = self.scenes[scene]
        if tpl.use_defaults:
            return SceneTemplate(**self._defaults_as_template())
        return tpl

    def _defaults_as_template(self) -> dict:
        return {
            "blur": self.defaults.get("blur", {}),
            "duplicate": self.defaults.get("duplicate", {}),
            "weights": self.defaults.get("weights", {}),
        }
