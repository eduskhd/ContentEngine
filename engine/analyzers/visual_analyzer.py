"""Visual analysis: motion, faces, composition per candidate window.

Optimizations over original:
- Accepts proxy_path (low-res pre-scaled video) for much faster frame decoding.
- Opens VideoCapture ONCE for all candidates instead of once per candidate.
- Samples at 1 fps from the proxy (usually already 1-2 fps, so near-zero overhead).
"""
import numpy as np
from pathlib import Path

from engine.config import CONFIG
from engine import database as db

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


def analyze_visual(
    job_id: str,
    video_path: str,
    candidates: list[dict],
    proxy_path: str = None,
) -> dict[str, float]:
    """Returns {candidate_id: visual_score}.

    Uses proxy_path for analysis if provided (recommended: 360p, 1-2fps).
    Falls back to full master video if proxy is unavailable.
    """
    if not CV2_AVAILABLE:
        return {c["id"]: 0.5 for c in candidates}

    analyze_path = proxy_path or video_path
    if proxy_path and not Path(proxy_path).exists():
        analyze_path = video_path

    return _analyze_all_candidates(analyze_path, candidates)


def _analyze_all_candidates(video_path: str, candidates: list[dict]) -> dict[str, float]:
    """Open video once and score all candidate windows."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {c["id"]: 0.5 for c in candidates}

    fps = cap.get(cv2.CAP_PROP_FPS) or 1.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    scores = {}
    for cand in candidates:
        try:
            start_frame = int(cand["start_s"] * fps)
            end_frame = min(int(cand["end_s"] * fps), total_frames - 1)
            # Sample 1 frame per second of source video (not proxy fps)
            # proxy is typically 1-2fps already, so sample_every=1 gets them all
            sample_every = max(1, int(fps))

            frames = []
            for fi in range(start_frame, end_frame + 1, sample_every):
                cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
                ret, frame = cap.read()
                if not ret:
                    break
                frames.append(frame)

            if not frames:
                scores[cand["id"]] = 0.5
                continue

            motion = _motion_score(frames)
            face = _face_score(frames)
            brightness = _brightness_score(frames)
            score = min(1.0, motion * 0.4 + face * 0.4 + brightness * 0.2)
            db.update_candidate(cand["id"], visual_score=score)
            scores[cand["id"]] = score

        except Exception:
            scores[cand["id"]] = 0.5
            db.update_candidate(cand["id"], visual_score=0.5)

    cap.release()
    return scores


def _motion_score(frames: list) -> float:
    if len(frames) < 2:
        return 0.5
    diffs = []
    for a, b in zip(frames[:-1], frames[1:]):
        gray_a = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
        gray_b = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
        diff = np.mean(np.abs(gray_a.astype(float) - gray_b.astype(float)))
        diffs.append(diff)
    avg_diff = np.mean(diffs)
    if avg_diff < 2:
        return 0.2
    elif avg_diff < 5:
        return 0.5
    elif avg_diff < 20:
        return 0.8 + (avg_diff - 5) / 75
    else:
        return max(0.3, 1.0 - (avg_diff - 20) / 100)


def _face_score(frames: list) -> float:
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    try:
        detector = cv2.CascadeClassifier(cascade_path)
    except Exception:
        return 0.5
    face_frames = 0
    for frame in frames[:10]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        if len(faces) > 0:
            face_frames += 1
    return min(1.0, face_frames / max(len(frames[:10]), 1))


def _brightness_score(frames: list) -> float:
    brightnesses = []
    for frame in frames:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        brightnesses.append(np.mean(hsv[:, :, 2]))
    avg = np.mean(brightnesses)
    if 80 <= avg <= 180:
        return 1.0
    elif avg < 80:
        return avg / 80.0
    else:
        return max(0.3, 1.0 - (avg - 180) / 75.0)
