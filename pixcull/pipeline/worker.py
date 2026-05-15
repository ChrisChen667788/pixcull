import time
from functools import cache
from pathlib import Path
from typing import Optional

from pixcull.detectors.blur import BlurDetector
from pixcull.detectors.canon import CanonDetector
from pixcull.detectors.composition import CompositionDetector
from pixcull.detectors.duplicate import DuplicateDetector
from pixcull.detectors.exposure import ExposureDetector
from pixcull.detectors.face import FaceDetector
from pixcull.detectors.scene import SceneDetector
from pixcull.detectors.subject import SubjectDetector
from pixcull.io.exif import read_exif_gps, read_exif_time
from pixcull.io.loader import load_image
from pixcull.scoring.aesthetic import AestheticScorer


@cache
def _detectors():
    return {
        "subject":     SubjectDetector(),
        "blur":        BlurDetector(),
        "exposure":    ExposureDetector(),
        "scene":       SceneDetector(),
        "duplicate":   DuplicateDetector(),
        "aesthetic":   AestheticScorer(),
        "face":        FaceDetector(),
        "composition": CompositionDetector(),
        "canon":       CanonDetector(),
    }


def analyze_one(path: Path) -> Optional[dict]:
    """Run all single-image detectors. Clustering happens later in the orchestrator."""
    img = load_image(path)
    if img is None:
        return None

    t0 = time.time()
    d = _detectors()
    subj = d["subject"].analyze(img)
    mask = subj.extras.get("mask")
    blur = d["blur"].analyze(img, mask=mask)
    expo = d["exposure"].analyze(img)
    scene = d["scene"].analyze(img)
    scene_name = scene.extras["scene"]
    dup = d["duplicate"].analyze(img)
    aes = d["aesthetic"].analyze(img)
    face = d["face"].analyze(img)
    # V20 — scene correction with face evidence.
    #
    # CLIP's stilllife prompt ("a product or still life photo, indoor
    # studio setup") softmaxes onto a non-trivial fraction of indoor
    # portrait / event photos — anything with a centered subject, a
    # uniform indoor background, and warm tungsten light reads as
    # "studio product shot" to CLIP. The user's recent kid-on-highchair
    # shot is the canonical example: 1+ face but scene=stilllife.
    #
    # Fix: when the face detector found ≥ 1 face AND the scene came back
    # stilllife, walk scene_probs in descending order and pick the
    # highest-ranked NON-stilllife class. We only re-rank stilllife
    # because it's the consistent CLIP failure mode; other categories
    # behave fine when face_count >= 1.
    face_count = int(face.metrics.get("face_count") or 0)
    if face_count >= 1 and scene_name == "stilllife":
        ranked = sorted(
            scene.extras["scene_probs"].items(),
            key=lambda kv: kv[1], reverse=True,
        )
        for name, _p in ranked:
            if name != "stilllife":
                scene_name = name
                scene.extras["scene"] = name
                # Also bump scene_confidence to the chosen class's prob
                # so downstream consumers (rescorer, advice picker) see
                # the corrected number, not the original stilllife max.
                scene.metrics["scene_confidence"] = float(_p)
                break
    comp = d["composition"].analyze(img, mask=mask, scene=scene_name)
    canon = d["canon"].analyze(img, mask=mask)

    metrics: dict = {}
    flags: list[str] = []
    for r in (subj, blur, expo, scene, dup, aes, face, comp, canon):
        metrics.update(r.metrics)
        flags.extend(r.flags)

    # V22 — face embedding for cross-photo clustering. V22.0.1 prefers
    # InsightFace ArcFace (much stronger face-identity signal than
    # CLIP), falling back to CLIP if InsightFace isn't installed.
    # The embedder takes the FULL image + bboxes (so ArcFace can do
    # its own detect+align on the original instead of failing on a
    # tight crop), plus pre-made crops as the CLIP fallback input.
    face_bboxes = face.extras.get("face_bboxes") or []
    face_embeddings: list[list[float]] = []
    if face_bboxes:
        from pixcull.pipeline.face_clustering import (
            _crop_face_with_margin, embed_face_crops_for_image,
        )
        crops = [_crop_face_with_margin(img, bb) for bb in face_bboxes]
        crops = [c for c in crops if c is not None]
        embs = embed_face_crops_for_image(img, face_bboxes, crops)
        # Convert to plain Python lists so the row pickles cleanly
        # across the multiprocess boundary (numpy arrays pickle fine
        # but lists are cheaper + safer for the spawn wire).
        face_embeddings = [e.tolist() for e in embs]

    # V23 — EXIF GPS for the location-cluster post-pass. Returns
    # ``None`` cleanly when the camera had no GPS or the photo is
    # indoor / lock failed.
    gps = read_exif_gps(path)
    gps_lat = gps[0] if gps else None
    gps_lon = gps[1] if gps else None

    return {
        "path": str(path),
        "filename": path.name,
        "datetime": read_exif_time(path),
        "scene": scene_name,
        "scene_probs": scene.extras["scene_probs"],
        "embedding": dup.extras["embedding"],
        # V22 — face data for downstream clustering. ``face_bboxes`` is
        # the per-face (x1,y1,x2,y2,conf) tuples from FaceDetector;
        # ``face_embeddings`` is the matching CLIP image features.
        # ``face_clusters`` gets populated by the post-pass.
        "face_bboxes": face_bboxes,
        "face_embeddings": face_embeddings,
        # V23 — raw GPS in decimal degrees (positive N/E, negative S/W).
        # ``gps_cluster_id`` gets filled by ``cluster_locations_across_rows``
        # in the main process post-pass; None means "no GPS / unknown".
        "gps_lat": gps_lat,
        "gps_lon": gps_lon,
        "flags": flags,
        "elapsed_s": time.time() - t0,
        **metrics,
    }
