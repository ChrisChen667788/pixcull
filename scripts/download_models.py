"""Pre-fetch all model weights used by V0.1 so first `pixcull run` is fast.

Downloads:
    - DINOv2 base (facebook/dinov2-base via transformers)
    - CLIP ViT-B/32 (openai/clip-vit-base-patch32)
    - U²-Net (via rembg first-use trigger)
    - LAION Aesthetic + CLIP-IQA (via pyiqa.create_metric trigger)
"""

from __future__ import annotations


def main() -> None:
    print("Downloading DINOv2…")
    from transformers import AutoImageProcessor, AutoModel
    AutoImageProcessor.from_pretrained("facebook/dinov2-base")
    AutoModel.from_pretrained("facebook/dinov2-base")

    print("Downloading CLIP…")
    from transformers import CLIPModel, CLIPProcessor
    CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    CLIPModel.from_pretrained("openai/clip-vit-base-patch32")

    print("Warming U²-Net (rembg)…")
    from rembg import new_session
    new_session(model_name="u2net")

    print("Warming pyiqa metrics…")
    import pyiqa
    for name in ("laion_aes", "clipiqa"):
        pyiqa.create_metric(name, device="cpu")

    print("All models cached. ✓")


if __name__ == "__main__":
    main()
