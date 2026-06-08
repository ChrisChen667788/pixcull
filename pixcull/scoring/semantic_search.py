"""P-AI-2 — CLIP-backed semantic search across a run's photos.

The user types "bride looking at groom" or "long-exposure waterfall"
or "拍鸟翅膀展开" — we encode the text via CLIP, cosine-sim against
each photo's cached CLIP image embedding, and return the top-k.

First search on a run lazily builds + caches the per-photo image
embeddings into ``output/embeddings.npz``. Subsequent searches reuse
the cache and complete in single-digit ms even on 5000-photo runs.

Cache shape:
    embeddings.npz: {
      "filenames":  array of str (in order, indexes into embeddings)
      "vectors":    float32 array shape=(N, 512) — L2-normalized
      "model":      str — provenance ("clip-vit-base-patch32")
    }

The CLIP model itself is shared with the SceneDetector (same
@cache-decorated _clip() loader in pixcull.detectors.scene) so we
don't double-load 200 MB of weights.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def _norm(v: np.ndarray) -> np.ndarray:
    """L2-normalize a (..., D) vector array along the last axis."""
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    n = np.where(n == 0, 1.0, n)
    return v / n


def _feature_tensor(feats):
    """Normalise CLIP ``get_image_features`` / ``get_text_features`` output
    to the projected-embedding tensor.

    transformers < 5 returned the projected ``[N, proj_dim]`` tensor
    directly; transformers ≥ 5 wraps it in a ``BaseModelOutputWithPooling``
    whose ``pooler_output`` IS that projected embedding (512-d for CLIP
    ViT-B/32).  Accept either so the search works across the version range
    instead of crashing with ``'…OutputWithPooling' object has no
    attribute 'cpu'``.
    """
    import torch
    if torch.is_tensor(feats):
        return feats
    for attr in ("pooler_output", "image_embeds", "text_embeds"):
        v = getattr(feats, attr, None)
        if torch.is_tensor(v):
            return v
    raise TypeError(
        f"unexpected CLIP feature output: {type(feats).__name__}")


def build_embeddings_cache(
    image_paths: list[Path],
    cache_path: Path,
    *,
    batch_size: int = 16,
    progress_cb: Optional[callable] = None,
) -> dict:
    """Encode each image with CLIP and persist to ``cache_path``.

    Returns the in-memory dict (filenames + vectors + model name).
    The cache file is written atomically: temp → rename.

    Skips paths that fail to load. The cache only contains successfully-
    encoded entries.
    """
    from PIL import Image
    import torch
    from pixcull.detectors.scene import _clip

    proc, model, device = _clip()
    filenames: list[str] = []
    vectors:   list[np.ndarray] = []

    for i in range(0, len(image_paths), batch_size):
        batch = image_paths[i : i + batch_size]
        imgs: list[Image.Image] = []
        names: list[str] = []
        for p in batch:
            try:
                imgs.append(Image.open(p).convert("RGB"))
                names.append(p.name)
            except (OSError, ValueError) as e:
                logger.warning(f"skip {p}: {e}")
                continue
        if not imgs:
            continue
        with torch.no_grad():
            inputs = proc(images=imgs, return_tensors="pt", padding=True).to(device)
            feats = model.get_image_features(pixel_values=inputs["pixel_values"])
            feats = _feature_tensor(feats).cpu().numpy().astype(np.float32)
        for name, vec in zip(names, feats):
            filenames.append(name)
            vectors.append(vec)
        if progress_cb is not None:
            progress_cb(min(i + batch_size, len(image_paths)),
                         len(image_paths))

    if not vectors:
        return {"filenames": np.array([]), "vectors": np.zeros((0, 512), np.float32),
                "model": "clip-vit-base-patch32"}

    arr = np.stack(vectors, axis=0)
    arr = _norm(arr)
    payload = {
        "filenames": np.array(filenames),
        "vectors":   arr,
        "model":     np.array("clip-vit-base-patch32"),
    }
    # Atomic save: write next to cache_path, then rename.
    # NB: np.savez appends ".npz" to a str/Path target that doesn't already
    # end in ".npz" — our ".npz.tmp" temp would then land at
    # ".npz.tmp.npz" and the rename below would FileNotFound.  Writing
    # through an explicit binary file handle makes numpy honour the path
    # exactly, keeping the write truly atomic (same-dir rename).
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "wb") as fh:
        np.savez(fh, **payload)
    tmp.rename(cache_path)
    return {
        "filenames": payload["filenames"],
        "vectors":   payload["vectors"],
        "model":     str(payload["model"]),
    }


def load_embeddings_cache(cache_path: Path) -> Optional[dict]:
    """Load the .npz cache. Returns None if missing or unreadable."""
    if not cache_path.is_file():
        return None
    try:
        z = np.load(cache_path, allow_pickle=False)
        return {
            "filenames": z["filenames"],
            "vectors":   z["vectors"],
            "model":     str(z["model"]) if "model" in z else "",
        }
    except (OSError, ValueError, KeyError) as e:
        logger.warning(f"failed to load {cache_path}: {e}")
        return None


def encode_query(text: str) -> np.ndarray:
    """CLIP-encode a query string. Returns L2-normalized (D,) vector."""
    import torch
    from pixcull.detectors.scene import _clip

    proc, model, device = _clip()
    with torch.no_grad():
        inputs = proc(text=[text], return_tensors="pt", padding=True).to(device)
        feats = model.get_text_features(**inputs)
        v = _feature_tensor(feats).cpu().numpy().astype(np.float32)[0]
    return _norm(v[None])[0]


def search(
    query: str,
    *,
    cache: dict,
    k: int = 10,
) -> list[tuple[str, float]]:
    """Return ``[(filename, similarity), ...]`` top-k by cosine sim.

    Similarity is the dot product of L2-normalized vectors, so it's
    in [-1, 1] but realistic values for image-text alignment are
    typically 0.15..0.35 (CLIP's contrastive head is calibrated low).
    """
    if cache is None or cache["vectors"].shape[0] == 0:
        return []
    q = encode_query(query)
    sims = cache["vectors"] @ q   # (N,)
    k = min(k, sims.shape[0])
    # argpartition for cheap top-k; then sort that small slice
    top_idx = np.argpartition(-sims, k - 1)[:k]
    top_idx = top_idx[np.argsort(-sims[top_idx])]
    return [
        (str(cache["filenames"][i]), float(sims[i]))
        for i in top_idx
    ]
