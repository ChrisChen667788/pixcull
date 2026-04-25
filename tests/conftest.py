from pathlib import Path

import pytest
from PIL import Image


@pytest.fixture
def sample_image():
    """Synthetic 512x512 RGB image — no network / disk dependency."""
    import numpy as np
    arr = (np.random.rand(512, 512, 3) * 255).astype("uint8")
    return Image.fromarray(arr)


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
