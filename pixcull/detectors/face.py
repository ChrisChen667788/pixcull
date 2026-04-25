"""Face / eye / expression detection.

V0.5 pipeline: MediaPipe FaceDetector (liberal, finds 25-40% more faces than
Landmarker alone on distance-portrait photos) → crop each face → FaceLandmarker
on the crop for 468-point landmarks + blendshapes.

Emits:
    metrics:
        face_count           – total detected faces
        face_max_blink       – max eyeBlink blendshape across all faces (0-1)
        face_min_ear         – min Eye Aspect Ratio across all faces
        face_region_lap_var  – Laplacian variance on the largest face crop
    flags:
        closed_eyes          – any detected face has strong blink signal
        motion_blur_on_face  – largest face's Laplacian is below a hard floor
        face_occluded        – landmarker failed on a confidently-detected face

Requires `pip install pixcull[face]` (MediaPipe). When the .task model files
are missing, analyze() returns an empty DetectionResult silently so the pipeline
still runs without the optional weights.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from pixcull.detectors.base import DetectionResult, Detector


# MediaPipe 468-landmark EAR indices (community standard; see
# https://developers.google.com/mediapipe/solutions/vision/face_landmarker).
# Each 6-tuple is (outer_corner, upper_1, upper_2, inner_corner, lower_2, lower_1).
_LEFT_EYE_EAR = (33, 160, 158, 133, 153, 144)
_RIGHT_EYE_EAR = (362, 385, 387, 263, 373, 380)

# Thresholds (tuned against golden set; see tests/fixtures/eval_findings.md).
#
# Blink calibration: MediaPipe's eyeBlink* blendshape fires at ~0.5 for squints,
# side-glances, and artistic mid-blink moments that the photographer rates as
# "keep". On our golden set, keep portraits with blink > 0.55 were intentional
# peak-pose expressions, so 0.55 is too hot. Use 0.80 (confidently closed).
#
# Detection confidence: FaceDetector at conf 0.3 catches lots of fabric-pattern
# false positives. Those fail Landmarker and we used to misread the failure as
# "face_occluded" (24 false positives, 0 real culls). Only "meaningful" faces
# (≥ MIN_DETECTION_CONF AND ≥ MEANINGFUL_FACE_AREA_FRAC of the frame) feed the
# cull-flag path; low-conf detections still count toward face_count metric.
BLINK_CLOSED_THRESHOLD = 0.80        # blendshape >= this → confidently closed
EAR_CLOSED_FALLBACK = 0.15           # stricter than 0.18; tiny eyes are noisy
MEANINGFUL_FACE_AREA_FRAC = 0.02     # face bbox ≥ 2% of image counts for flags
MEANINGFUL_FACE_MIN_CONF = 0.6       # FaceDetector confidence for flag-worthy faces
FACE_BLUR_LAP_FLOOR = 40.0           # below this on face crop → motion_blur_on_face

# Model files — kept next to the detector so the pipeline is self-contained.
_MODEL_DIR = Path(__file__).parent / "_models"
FACE_DETECTOR_MODEL = _MODEL_DIR / "blaze_face_short_range.tflite"
FACE_LANDMARKER_MODEL = _MODEL_DIR / "face_landmarker.task"


def _ear(pts: np.ndarray) -> float:
    """Eye Aspect Ratio for a 6-point eye contour."""
    v1 = np.linalg.norm(pts[1] - pts[5])
    v2 = np.linalg.norm(pts[2] - pts[4])
    h = np.linalg.norm(pts[0] - pts[3])
    return float((v1 + v2) / (2.0 * h + 1e-6))


class FaceDetector(Detector):
    """Face presence + blink detection via MediaPipe.

    Lazy-loads MediaPipe on first call so `import pixcull` stays cheap.
    """

    name = "face"

    def __init__(self) -> None:
        self._detector: Any = None       # mediapipe FaceDetector
        self._landmarker: Any = None     # mediapipe FaceLandmarker
        self._init_failed: bool = False  # stop retrying once we know MP isn't available

    def _lazy_init(self) -> bool:
        if self._detector is not None and self._landmarker is not None:
            return True
        if self._init_failed:
            return False
        if not FACE_DETECTOR_MODEL.exists() or not FACE_LANDMARKER_MODEL.exists():
            self._init_failed = True
            return False
        try:
            import mediapipe as mp  # noqa: F401
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision
        except ImportError:
            self._init_failed = True
            return False

        det_opts = vision.FaceDetectorOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(FACE_DETECTOR_MODEL)),
            running_mode=vision.RunningMode.IMAGE,
            min_detection_confidence=0.3,
            min_suppression_threshold=0.3,
        )
        lm_opts = vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(FACE_LANDMARKER_MODEL)),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=1,  # we pass one face crop at a time
            min_face_detection_confidence=0.3,
            min_face_presence_confidence=0.3,
            min_tracking_confidence=0.3,
            output_face_blendshapes=True,
        )
        self._detector = vision.FaceDetector.create_from_options(det_opts)
        self._landmarker = vision.FaceLandmarker.create_from_options(lm_opts)
        return True

    def analyze(self, img: Image.Image, **_: object) -> DetectionResult:
        result = DetectionResult()
        if not self._lazy_init():
            return result  # silently no-op when MediaPipe / weights are unavailable

        import mediapipe as mp  # cheap after lazy init

        arr = np.array(img.convert("RGB"))
        h, w = arr.shape[:2]
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=arr)

        det_res = self._detector.detect(mp_img)
        detections = det_res.detections or []
        result.metrics["face_count"] = float(len(detections))

        if not detections:
            return result

        # Run landmarker on each face crop (typically 1-5 faces). Only faces that
        # occupy ≥ MEANINGFUL_FACE_AREA_FRAC of the frame contribute to cull flags —
        # a blurry / closed-eye bystander shouldn't cull an otherwise-good shot.
        image_area = float(w * h)
        min_meaningful_area = image_area * MEANINGFUL_FACE_AREA_FRAC

        meaningful_max_blink = 0.0
        meaningful_min_ear = 1.0
        meaningful_saw_landmarks = False
        meaningful_saw_face = False      # any face passed the area gate at detect time

        # Landmark coverage on any face — used for face_occluded fallback.
        all_max_blink = 0.0
        all_min_ear = 1.0
        landmarker_hits = 0

        largest_meaningful_area = 0.0
        largest_meaningful_lap = None

        for det in detections:
            bb = det.bounding_box
            x1, y1 = max(0, bb.origin_x), max(0, bb.origin_y)
            x2 = min(w, bb.origin_x + bb.width)
            y2 = min(h, bb.origin_y + bb.height)
            if x2 - x1 < 16 or y2 - y1 < 16:
                continue
            bbox_area = float((x2 - x1) * (y2 - y1))
            # Confidence — MediaPipe packs it in categories[0].score.
            det_conf = float(det.categories[0].score) if det.categories else 0.0
            is_meaningful = (
                bbox_area >= min_meaningful_area
                and det_conf >= MEANINGFUL_FACE_MIN_CONF
            )
            if is_meaningful:
                meaningful_saw_face = True

            # Pad the crop to 1.5× because landmarker wants some context around the face.
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            half_w = (x2 - x1) * 0.75
            half_h = (y2 - y1) * 0.75
            cx1 = max(0, int(cx - half_w))
            cy1 = max(0, int(cy - half_h))
            cx2 = min(w, int(cx + half_w))
            cy2 = min(h, int(cy + half_h))
            face_arr = arr[cy1:cy2, cx1:cx2]
            if face_arr.size == 0:
                continue

            face_mp = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(face_arr))
            lm_res = self._landmarker.detect(face_mp)
            if not lm_res.face_landmarks:
                continue
            landmarker_hits += 1

            # Blendshape blink — Google's trained signal, more reliable than EAR.
            blink = 0.0
            if lm_res.face_blendshapes:
                bs = {s.category_name: s.score for s in lm_res.face_blendshapes[0]}
                blink = max(bs.get("eyeBlinkLeft", 0.0), bs.get("eyeBlinkRight", 0.0))
            all_max_blink = max(all_max_blink, blink)

            # Geometric EAR as fallback / cross-check.
            fh, fw = face_arr.shape[:2]
            lm = np.array([[p.x * fw, p.y * fh] for p in lm_res.face_landmarks[0]])
            ear_avg = 0.5 * (_ear(lm[list(_LEFT_EYE_EAR)]) + _ear(lm[list(_RIGHT_EYE_EAR)]))
            all_min_ear = min(all_min_ear, ear_avg)

            if is_meaningful:
                meaningful_saw_landmarks = True
                meaningful_max_blink = max(meaningful_max_blink, blink)
                meaningful_min_ear = min(meaningful_min_ear, ear_avg)
                # Face-region sharpness (largest meaningful face only).
                if bbox_area > largest_meaningful_area:
                    largest_meaningful_area = bbox_area
                    gray = cv2.cvtColor(face_arr, cv2.COLOR_RGB2GRAY)
                    largest_meaningful_lap = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # Record metrics (use "all faces" numbers so downstream has full info).
        result.metrics["face_max_blink"] = all_max_blink
        result.metrics["face_min_ear"] = all_min_ear if landmarker_hits else 1.0
        if largest_meaningful_lap is not None:
            result.metrics["face_region_lap_var"] = largest_meaningful_lap

        # Flags — gated on a meaningful face being present (≥2% of frame).
        if meaningful_saw_landmarks and meaningful_max_blink >= BLINK_CLOSED_THRESHOLD:
            result.flags.append("closed_eyes")
        elif (
            meaningful_saw_landmarks
            and meaningful_max_blink == 0.0
            and meaningful_min_ear < EAR_CLOSED_FALLBACK
        ):
            # Blendshape missing but eyes geometrically closed — rare path.
            result.flags.append("closed_eyes")
        elif meaningful_saw_face and not meaningful_saw_landmarks:
            # Confident face bbox, but Landmarker couldn't land → heavy occlusion /
            # side profile / extreme lighting on the main subject.
            result.flags.append("face_occluded")

        if largest_meaningful_lap is not None and largest_meaningful_lap < FACE_BLUR_LAP_FLOOR:
            result.flags.append("motion_blur_on_face")

        # Extras for downstream consumers (blur detector can weight face-region
        # Laplacian; fusion can use face_count to strengthen portrait scene
        # classification).
        result.extras["face_count"] = len(detections)

        return result
