"""YuNet face detector wrapper using cv2.FaceDetectorYN.

The ONNX model is bundled in models/ and does not require a network call
after the first download. The detector is created once per (frame_size)
to avoid the overhead of re-initializing on every frame.
"""
from __future__ import annotations
from pathlib import Path

import cv2
import numpy as np

_MODEL_PATH = Path(__file__).parent.parent.parent / "models" / "face_detection_yunet_2023mar.onnx"
_SCORE_THRESHOLD = 0.6
_NMS_THRESHOLD = 0.3
_TOP_K = 5000


def model_available() -> bool:
    return _MODEL_PATH.exists()


def detect_faces_batch(
    frames: list[np.ndarray],
    score_threshold: float = _SCORE_THRESHOLD,
) -> list[list[tuple[int, int, int, int]]]:
    """
    Detect faces in a batch of same-size BGR frames.
    Returns a list (one entry per frame) of (x, y, w, h) tuples in frame coords.
    Creates the detector once for the shared frame dimensions.
    """
    if not frames:
        return []
    if not _MODEL_PATH.exists():
        return [[] for _ in frames]

    h, w = frames[0].shape[:2]
    detector = cv2.FaceDetectorYN.create(
        str(_MODEL_PATH), "", (w, h),
        score_threshold=score_threshold,
        nms_threshold=_NMS_THRESHOLD,
        top_k=_TOP_K,
    )

    results = []
    for frame in frames:
        _, faces = detector.detect(frame)
        if faces is None:
            results.append([])
            continue
        found = []
        for face in faces:
            fx, fy, fw, fh = int(face[0]), int(face[1]), int(face[2]), int(face[3])
            found.append((fx, fy, fw, fh))
        results.append(found)

    return results
