"""MediaPipe face and pose detection for reframing.

Uses the MediaPipe Tasks API (1.0+).  Model files are NOT bundled — run
  python scripts/download_models.py
to fetch them.  All public functions fail gracefully when models are absent.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np

# On Windows, suppress the modal "Bad Image" / "Imagen incorrecta" dialog that
# the OS shows when Application Control blocks a native DLL load.  Without this
# the dialog freezes the server process until manually dismissed.  The OSError
# is still raised and caught by the callers below — behaviour is unchanged.
if sys.platform == "win32":
    try:
        import ctypes
        _SEM_FAILCRITICALERRORS = 0x0001
        _SEM_NOOPENFILEERRORBOX = 0x8000
        ctypes.windll.kernel32.SetErrorMode(_SEM_FAILCRITICALERRORS | _SEM_NOOPENFILEERRORBOX)
    except Exception:
        pass

_MODEL_DIR = Path(__file__).parent.parent.parent / "models"
_FACE_MODEL = _MODEL_DIR / "blaze_face_full_range.tflite"
_POSE_MODEL = _MODEL_DIR / "pose_landmarker_lite.task"

# Probe once at import time whether the MediaPipe Tasks native DLL is loadable.
# On Windows, Windows Application Control can block the DLL with a modal dialog
# before Python gets the OSError; SetErrorMode above suppresses the dialog, and
# this ctypes probe checks loadability once so callers never attempt it per-frame.
_TASKS_AVAILABLE: bool = False
try:
    import mediapipe as _mp_probe
    if sys.platform == "win32":
        import ctypes as _ctypes
        _dll_path = str(Path(_mp_probe.__file__).parent / "tasks" / "c" / "libmediapipe.dll")
        _ctypes.CDLL(_dll_path)
    _TASKS_AVAILABLE = True
except Exception:
    pass


# ── Availability checks ───────────────────────────────────────────────────────

def face_model_available() -> bool:
    return _TASKS_AVAILABLE and _FACE_MODEL.exists()


def pose_model_available() -> bool:
    return _TASKS_AVAILABLE and _POSE_MODEL.exists()


# ── Face detection ─────────────────────────────────────────────────────────────

def detect_faces_mp(
    frames: list[np.ndarray],
    min_confidence: float = 0.4,
) -> list[list[tuple[int, int, int, int]]]:
    """Detect faces with MediaPipe BlazeFace.

    Returns one list per frame; each entry is (x, y, w, h) in frame pixels.
    """
    if not face_model_available() or not frames:
        return [[] for _ in frames]

    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision
        import cv2
    except (ImportError, OSError):
        return [[] for _ in frames]

    try:
        base_options = mp_python.BaseOptions(model_asset_path=str(_FACE_MODEL))
        options = mp_vision.FaceDetectorOptions(
            base_options=base_options,
            min_detection_confidence=min_confidence,
            min_suppression_threshold=0.3,
        )
        detector = mp_vision.FaceDetector.create_from_options(options)
    except OSError:
        # Windows Application Control may block the MediaPipe native library
        return [[] for _ in frames]

    results: list[list[tuple[int, int, int, int]]] = []
    for frame in frames:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        detection_result = detector.detect(mp_img)
        faces: list[tuple[int, int, int, int]] = []
        for det in detection_result.detections:
            bb = det.bounding_box
            faces.append((bb.origin_x, bb.origin_y, bb.width, bb.height))
        results.append(faces)

    detector.close()
    return results


# ── Pose / person detection ───────────────────────────────────────────────────

def detect_persons_mp(
    frames: list[np.ndarray],
    min_confidence: float = 0.4,
) -> list[list[tuple[int, int, int, int]]]:
    """Detect persons via MediaPipe PoseLandmarker; return body bounding boxes.

    Each box is (x, y, w, h) derived from the convex hull of visible landmarks
    plus a 15% margin to include head clearance.
    """
    if not pose_model_available() or not frames:
        return [[] for _ in frames]

    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision
        import cv2
    except (ImportError, OSError):
        return [[] for _ in frames]

    try:
        base_options = mp_python.BaseOptions(model_asset_path=str(_POSE_MODEL))
        options = mp_vision.PoseLandmarkerOptions(
            base_options=base_options,
            min_pose_detection_confidence=min_confidence,
            min_pose_presence_confidence=min_confidence,
            min_tracking_confidence=0.3,
            num_poses=4,
        )
        landmarker = mp_vision.PoseLandmarker.create_from_options(options)
    except OSError:
        return [[] for _ in frames]

    results: list[list[tuple[int, int, int, int]]] = []
    for frame in frames:
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = landmarker.detect(mp_img)
        bboxes: list[tuple[int, int, int, int]] = []
        for pose_landmarks in result.pose_landmarks:
            xs = [lm.x * w for lm in pose_landmarks]
            ys = [lm.y * h for lm in pose_landmarks]
            if not xs:
                continue
            x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
            pw, ph = x2 - x1, y2 - y1
            margin_x, margin_y = pw * 0.10, ph * 0.15
            x1 = max(0.0, x1 - margin_x)
            y1 = max(0.0, y1 - margin_y)
            x2 = min(float(w), x2 + margin_x)
            y2 = min(float(h), y2 + margin_y)
            bboxes.append((int(x1), int(y1), int(x2 - x1), int(y2 - y1)))
        results.append(bboxes)

    landmarker.close()
    return results
