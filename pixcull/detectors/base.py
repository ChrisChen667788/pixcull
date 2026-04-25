from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from PIL import Image


@dataclass
class DetectionResult:
    """Unified output of any detector.

    metrics: numeric scores (blur variance, similarity, etc.)
    flags:   string tags (e.g. "closed_eyes", "rear_view")
    extras:  model-specific payload (masks, embeddings, crops)
    """

    metrics: dict[str, float] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)


class Detector(ABC):
    """Base class for all detectors. Keep implementations stateless once initialized."""

    name: str = ""

    @abstractmethod
    def analyze(self, img: Image.Image, **kwargs: Any) -> DetectionResult:
        """Run detection on a single PIL image."""
        ...
