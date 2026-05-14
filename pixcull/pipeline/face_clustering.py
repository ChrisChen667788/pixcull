"""V22.0 — face embedding + clustering for "person A / B / C" propagation.

Wedding / event / kids photographers shoot 1000+ frames of the SAME few
people. Today PixCull treats each face as anonymous: a 5-star portrait
of the bride and a 5-star portrait of the groomsman get equal weight,
the photographer has to manually filter "show me bride photos".

V22 adds face clustering so PixCull can answer "which 200 of these
1500 photos contain Person 1 (bride)?". V22.0 is the data layer:
embed each detected face, cluster across the batch, assign a stable
cluster_id per face per photo, and surface it in scores.csv +
/decisions API. V22.1+ adds the labeling UI ("call cluster_3 'Bride'")
and persistent labels across runs.

Architecture
============
* ``_clip_embed_batch`` + ``_crop_face_with_margin`` run INSIDE
  workers (alongside the rest of analyze_one — CLIP is already
  loaded for scene detection, marginal cost is the face crop
  forward pass). Each worker writes ``row['face_embeddings']``
  (list of 512-dim float lists, one per meaningful face).
* ``cluster_faces_across_rows`` runs in the MAIN process after
  the parallel pass joins. Just DBSCAN — no I/O, no model calls.
* The embeddings are dropped from the row before scores.csv write
  (in orchestrator) so we don't bloat the CSV with hundreds of
  floats per face.

Embedding choice: CLIP
----------------------
We already load CLIP ViT-B/32 for scene detection. For each face
bbox, crop a square patch (face + ~30% context margin), feed to
CLIP image encoder, get a 512-dim L2-normalized embedding.

Tradeoff: CLIP wasn't trained for face identity. Cosine similarity
between CLIP face crops is noisier than a dedicated face-recognition
model (InsightFace ArcFace would give ~0.95+ similarity on same-person
crops vs ~0.4 on different-person; CLIP gives ~0.75 vs ~0.5 —
narrower band). But CLIP needs zero new dependencies and runs at
the per-photo cost we're already paying. "Good enough" for wedding
/ kids batches where the same person appears in distinctive lighting
+ pose conditions; if clustering quality is poor in practice we can
drop in face_recognition or insightface as a V22.0.1.

Clustering: DBSCAN cosine, ε=0.30 min_samples=2
-----------------------------------------------
DBSCAN is a good fit:
  * No need to know cluster count in advance (depends on who's at
    the wedding)
  * Natural support for noise points (a guest in 1 photo never
    again → cluster_id=-1, not a useless cluster of size 1)
  * Density-based — handles uneven cluster sizes (bride in 400
    photos vs random guest in 5)

ε=0.30 tuned on a small portrait sample: matched ~95% of same-person
faces, ~3% false-merge. min_samples=2 means ≥2 photos to form a
cluster; "occasional guests" stay as noise.

Output schema (added to each row dict)
======================================
    "face_clusters": [int, ...]   # one per meaningful face;
                                  # -1 = noise / unique-ish
"""

from __future__ import annotations

import sys
from typing import Any

import numpy as np
from PIL import Image


_CLIP_FACE_CROP_PADDING = 0.30   # 30% margin around the bbox for CLIP context
_DBSCAN_EPS = 0.30
_DBSCAN_MIN_SAMPLES = 2


def _crop_face_with_margin(img: Image.Image, bbox: tuple,
                              padding: float = _CLIP_FACE_CROP_PADDING
                              ) -> Image.Image | None:
    """Crop a square-ish region around the face bbox with extra context.

    CLIP was trained on full scenes, not tight face crops — giving it
    some background context (~30% margin on each side) produces more
    semantically discriminative embeddings than the tight bbox alone.
    Returns None if the resulting crop is too small to be useful.
    """
    x1, y1, x2, y2 = bbox[:4]
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    half_w = (x2 - x1) / 2 * (1.0 + padding)
    half_h = (y2 - y1) / 2 * (1.0 + padding)
    w, h = img.size
    cx1 = max(0, int(cx - half_w))
    cy1 = max(0, int(cy - half_h))
    cx2 = min(w, int(cx + half_w))
    cy2 = min(h, int(cy + half_h))
    if cx2 - cx1 < 32 or cy2 - cy1 < 32:
        return None
    return img.crop((cx1, cy1, cx2, cy2))


def _clip_embed_batch(crops: list[Image.Image]) -> np.ndarray:
    """Embed a list of PIL crops via CLIP image encoder. Returns a
    (N, 512) numpy array with L2-normalized rows.

    Reuses ``pixcull.detectors.scene._clip`` so we don't double-load
    the model. Falls through to numpy on the device returned by that
    function (cuda / mps / cpu).

    Implementation note: we explicitly extract ``pixel_values`` and
    call ``get_image_features`` with ONLY that kwarg. The earlier
    version passed ``padding=True`` to the processor, which made it
    also generate empty text inputs (``input_ids`` /
    ``attention_mask``). Some transformers versions then interpret
    ``model.get_image_features(**inputs)`` as a joint forward pass
    and return a ``BaseModelOutputWithPooling`` wrapper instead of
    a plain Tensor — breaking the ``.norm()`` call. Image-only is
    the correct call shape here.
    """
    if not crops:
        return np.zeros((0, 512), dtype=np.float32)
    from pixcull.detectors.scene import _clip
    import torch

    proc, model, device = _clip()
    pixel_values = proc(images=crops, return_tensors="pt")["pixel_values"].to(device)
    with torch.no_grad():
        # On the transformers version we ship,
        # ``CLIPModel.get_image_features(pixel_values=...)`` returns a
        # ``BaseModelOutputWithPooling`` wrapper, not a Tensor. Going
        # through vision_model + visual_projection manually gets us the
        # 512-d shared-space embedding directly, and is also slightly
        # faster (we skip the wrapper construction).
        vision_out = model.vision_model(pixel_values=pixel_values)
        # pooler_output is the CLS-like 768-d representation for ViT-B/32
        pooled = vision_out.pooler_output
        # Project to the 512-d shared text/image space
        feats = model.visual_projection(pooled)
    # L2-normalize so cosine similarity == dot product
    feats = feats / feats.norm(dim=-1, keepdim=True).clamp(min=1e-8)
    return feats.detach().cpu().numpy().astype(np.float32)


def cluster_faces_across_rows(
    rows: list[dict[str, Any]],
    *,
    eps: float = _DBSCAN_EPS,
    min_samples: int = _DBSCAN_MIN_SAMPLES,
    drop_embeddings: bool = True,
) -> list[dict[str, Any]]:
    """Run DBSCAN over the per-row face embeddings, write cluster IDs
    back into each row's ``face_clusters`` field.

    Each row must have ``face_embeddings`` populated by the worker
    (a list of N 512-dim lists, where N = number of meaningful faces
    in that photo). The list may be empty (no faces) — those rows
    get ``face_clusters = []``.

    Side-effect: mutates each row in place. Also returns ``rows`` for
    fluent chaining.

    Cluster IDs are run-scoped integers:
        0, 1, 2, ...  → real clusters (≥ min_samples photos)
        -1             → noise (unique-ish face, not enough overlap)

    When ``drop_embeddings`` (default True), removes the raw 512-dim
    embeddings from each row after clustering — they're huge and the
    CSV / JSON downstream consumers don't need them. Set False for
    debugging or for callers that want to do their own clustering.

    V22.0 stops here — cross-run persistence (so cluster 0 = "bride"
    across multiple weddings) is V22.1+.
    """
    flat_emb: list[list[float]] = []
    flat_index: list[tuple[int, int]] = []
    for ri, row in enumerate(rows):
        embs = row.get("face_embeddings") or []
        # Pre-fill cluster placeholder so the field always exists
        row["face_clusters"] = [-1] * len(embs)
        for fi, e in enumerate(embs):
            flat_emb.append(e)
            flat_index.append((ri, fi))

    if not flat_emb:
        if drop_embeddings:
            for r in rows:
                r.pop("face_embeddings", None)
                r.pop("face_bboxes", None)
        return rows

    X = np.array(flat_emb, dtype=np.float32)
    try:
        from sklearn.cluster import DBSCAN
    except ImportError:
        # sklearn missing somehow — degrade gracefully (every face is
        # its own noise point); don't kill the whole pipeline.
        print("[face_cluster] sklearn unavailable, "
              "skipping cluster assignment", file=sys.stderr)
        if drop_embeddings:
            for r in rows:
                r.pop("face_embeddings", None)
                r.pop("face_bboxes", None)
        return rows

    labels = DBSCAN(eps=eps, min_samples=min_samples,
                    metric="cosine", n_jobs=-1).fit_predict(X)

    for (ri, fi), lab in zip(flat_index, labels):
        rows[ri]["face_clusters"][fi] = int(lab)

    if drop_embeddings:
        for r in rows:
            r.pop("face_embeddings", None)
            r.pop("face_bboxes", None)

    n_clusters = len({int(l) for l in labels if l >= 0})
    n_noise = int(sum(1 for l in labels if l < 0))
    print(f"[face_cluster] {len(flat_emb)} face embeddings → "
          f"{n_clusters} clusters + {n_noise} noise points "
          f"(eps={eps}, min_samples={min_samples})",
          file=sys.stderr)
    return rows


def cluster_summary(rows: list[dict[str, Any]]) -> dict[int, dict]:
    """V22.0 — handy summary for the orchestrator log + future UI:
    {cluster_id: {n_photos, n_faces, sample_filenames[:5]}}.

    Cluster -1 (noise) is included so the user can see how many
    "unique guests" the run produced.
    """
    out: dict[int, dict] = {}
    seen: dict[int, set] = {}
    for r in rows:
        cs = r.get("face_clusters") or []
        for cid in cs:
            d = out.setdefault(cid, {"n_photos": 0, "n_faces": 0,
                                      "sample_filenames": []})
            d["n_faces"] += 1
        # Distinct-photo accounting — count each photo once per cluster
        fn = r.get("filename", "")
        for cid in set(cs):
            d = out.setdefault(cid, {"n_photos": 0, "n_faces": 0,
                                      "sample_filenames": []})
            seen.setdefault(cid, set())
            if fn and fn not in seen[cid]:
                d["n_photos"] += 1
                seen[cid].add(fn)
                if len(d["sample_filenames"]) < 5:
                    d["sample_filenames"].append(fn)
    return out


__all__ = [
    "cluster_faces_across_rows",
    "cluster_summary",
    "_crop_face_with_margin",
    "_clip_embed_batch",
]
