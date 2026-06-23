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
from pixcull.detectors.wedding_moment import WeddingMomentDetector
from pixcull.io.exif import (
    is_drone_camera,
    read_exif_gps,
    read_exif_make_model,
    read_exif_time,
)
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
        # P-PRO-4.1 — wedding moment classifier.  Cached at module
        # level like the others; only called from analyze_one()
        # when scene/vertical is "wedding" so non-wedding runs pay
        # zero CLIP cost beyond the existing SceneDetector pass.
        "wedding_moment": WeddingMomentDetector(),
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

    # v2.14-P2 — aerial scene. DJI / drone shots are "aerial" regardless of
    # what CLIP guessed: an aerial landscape reads as "landscape" to CLIP, so a
    # visual classifier can't separate them. Detect deterministically from the
    # drone camera's EXIF make/model (DJI modules report FC####; the Mavic
    # 2 Pro / Mavic 3 report Hasselblad "L1D-20c"/"L2D-20c") or a DJI_ filename,
    # and override. Non-drone frames are untouched.
    try:
        _mk, _md = read_exif_make_model(path)
        if is_drone_camera(_mk, _md, path.name):
            scene_name = "aerial"
            scene.extras["scene"] = "aerial"
            # keep scene_probs indexable by the chosen scene for downstream
            # consumers that look up scene_probs[scene_name].
            sp = scene.extras.setdefault("scene_probs", {})
            sp["aerial"] = float(scene.metrics.get("scene_confidence") or 1.0)
    except Exception:
        pass

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

    # P-PRO-4.1 — wedding moment classifier.  Only fires when the
    # scene resolves to "wedding" — wastes no CLIP cycles on
    # landscape / wildlife / stilllife runs.  The vertical-override
    # path (vertical=wedding even when scene came back something
    # else) will be wired in P-PRO-4.2 once the worker has access
    # to the per-run vertical hint (currently a pipeline-level
    # arg, not per-image).
    wedding_moment: Optional[str] = None
    wedding_moment_confidence: Optional[float] = None
    moment_uncertain: bool = False
    if scene_name == "wedding":
        try:
            wm = d["wedding_moment"].analyze(img)
            wedding_moment            = wm.extras.get("wedding_moment")
            wedding_moment_confidence = wm.metrics.get(
                "wedding_moment_confidence")
            moment_uncertain = "moment_uncertain" in (wm.flags or [])
            if moment_uncertain:
                flags.append("moment_uncertain")
        except Exception:
            # Never let the moment classifier crash the per-frame
            # pipeline.  Skip the moment annotation; the rest of
            # the row still lands cleanly.
            pass

    # v2.14 — moment_score: de-stub the "moment" fusion axis.  Until now it was
    # a constant 0.5 placeholder for EVERY frame (moment is 1/6 of the weighted
    # fusion), so it carried zero discriminative signal AND could never be
    # learned (a constant feature is useless to the rescorer).  Derive a real
    # value where one honestly exists; leave it None otherwise so fusion keeps
    # its deliberate neutral-0.5 default (landscape / no-face frames unchanged).
    # There is no general expression / peak-action detector, so we use only
    # signals that genuinely exist: the wedding-moment classifier's confidence,
    # and (weakly) whether a detected face is mid-blink.  action_at_peak stays
    # unmodelled — see rubric_decompose.
    moment_score: Optional[float] = None
    if wedding_moment_confidence is not None:
        moment_score = float(wedding_moment_confidence)
    elif face_count >= 1:
        if "closed_eyes" in flags:
            moment_score = 0.40
        else:
            # v2.14-P1.1 — a smiling, open-eyed face is a stronger moment than
            # a neutral one. face_max_smile is the MediaPipe smile blendshape
            # (0..1). Neutral (smile 0) stays at the prior 0.60 baseline; a full
            # smile lifts it to 0.85. Real expression signal, bounded.
            _smile = float(face.metrics.get("face_max_smile") or 0.0)
            moment_score = round(min(0.85, 0.60 + 0.25 * _smile), 4)

    return {
        "path": str(path),
        "filename": path.name,
        "datetime": read_exif_time(path),
        "scene": scene_name,
        "scene_probs": scene.extras["scene_probs"],
        "embedding": dup.extras["embedding"],
        # P-PRO-4.1 — wedding moment annotation. None on non-wedding
        # frames; the column still exists so CSV round-trips don't
        # have to None-check.
        "wedding_moment":            wedding_moment,
        "wedding_moment_confidence": wedding_moment_confidence,
        # v2.14 — real "moment" fusion signal (None = no signal → fusion
        # falls back to its neutral 0.5 placeholder).
        "moment_score":              moment_score,
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
