"""XMP sidecar read/write for Lightroom / Capture One interop. (V0.5)"""

from pathlib import Path


def write_xmp(image_path: Path, rating: int, color_label: str = "") -> Path:
    """Write Lightroom-compatible XMP sidecar next to the image.

    Args:
        image_path: source image (.jpg or .cr3), XMP path derived as same stem + .xmp
        rating: 0-5 (0 = unrated)
        color_label: "" | "Red" | "Yellow" | "Green" | "Blue" | "Purple"

    Returns:
        Path to written .xmp file.
    """
    raise NotImplementedError("V0.5: write_xmp")


def read_xmp(image_path: Path) -> dict:
    """Read existing XMP sidecar → dict with rating, color_label, keywords."""
    raise NotImplementedError("V0.5: read_xmp")
