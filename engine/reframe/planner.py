"""Framing planner: analyze a proxy video clip window and produce a FramingPlan.

A FramingPlan is a JSON-serializable dict:
  {
    "strategy":  "face_center_static" | "face_center_dynamic" | "center",
    "x_offset":  int,          # primary (static) crop offset in source pixels
    "confidence": float,       # 0.0–1.0 (fraction of frames with a detected face)
    "fallback":  bool,         # True = no model or no faces found
    "keypoints": [[time_s, x_offset], ...],  # per-segment offsets (future use)
  }

v1 always uses the static x_offset regardless of keypoints. Dynamic per-frame
crop (zoompan) is left for v2 once keypoints are battle-tested.
"""
from __future__ import annotations
import statistics

import cv2

from engine.reframe.detector import model_available, detect_faces_batch
from engine.reframe.smoother import smooth_ema, clamp_offset

# Target output is 1080×1920 (9:16)
_TARGET_W = 1080
_TARGET_H = 1920
# Minimum x_offset shift to emit a new keypoint (suppress micro-jitter)
_MIN_SHIFT_PX = 60


def plan_clip(
    proxy_path: str,
    clip_start: float,
    clip_end: float,
    src_w: int,
    src_h: int,
) -> dict:
    """
    Analyze [clip_start, clip_end] in the proxy video and return a FramingPlan.
    Falls back to center crop if the model is unavailable or no faces are found.
    """
    crop_w = int(src_h * _TARGET_W / _TARGET_H)
    center_offset = (src_w - crop_w) // 2

    def _center_plan() -> dict:
        return {
            "strategy": "center",
            "x_offset": center_offset,
            "confidence": 0.0,
            "fallback": True,
            "keypoints": [[round(clip_start, 2), center_offset]],
        }

    if not model_available():
        return _center_plan()

    # ── Read proxy frames for the clip window ─────────────────────────────────
    cap = cv2.VideoCapture(proxy_path)
    if not cap.isOpened():
        return _center_plan()

    proxy_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    proxy_fps = cap.get(cv2.CAP_PROP_FPS) or 2.0
    scale_x = src_w / max(1, proxy_w)  # proxy_x * scale_x → source_x

    cap.set(cv2.CAP_PROP_POS_MSEC, clip_start * 1000.0)

    frames: list = []
    frame_times: list[float] = []
    frame_interval = 1.0 / proxy_fps

    t = clip_start
    while t <= clip_end + frame_interval * 0.5:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
        frame_times.append(t)
        t += frame_interval

    cap.release()

    if not frames:
        return _center_plan()

    # ── Face detection (single detector instance for the whole batch) ─────────
    detections = detect_faces_batch(frames)

    face_centers_src: list[tuple[float, float]] = []  # (time_s, center_x_in_source)
    for time_s, faces in zip(frame_times, detections):
        if not faces:
            continue
        # Pick the largest face (proxy for "closest to camera")
        largest = max(faces, key=lambda f: f[2] * f[3])
        fx, _, fw, _ = largest
        center_src_x = (fx + fw * 0.5) * scale_x
        face_centers_src.append((time_s, center_src_x))

    if not face_centers_src:
        return _center_plan()

    # ── Smooth trajectory ─────────────────────────────────────────────────────
    times   = [d[0] for d in face_centers_src]
    centers = [d[1] for d in face_centers_src]
    smoothed_centers = smooth_ema(centers, alpha=0.3)

    # Convert face center → crop x_offset (keep face horizontally centered in crop)
    half_crop = crop_w / 2.0
    raw_offsets = [clamp_offset(cx - half_crop, src_w, crop_w) for cx in smoothed_centers]

    # ── Decide strategy ───────────────────────────────────────────────────────
    if len(raw_offsets) >= 3:
        variance = statistics.variance(raw_offsets)
        if variance < _MIN_SHIFT_PX ** 2:
            # Stable scene — single static offset (median of all smoothed positions)
            static_off = clamp_offset(statistics.median(raw_offsets), src_w, crop_w)
            keypoints = [[round(times[0], 2), static_off]]
            strategy = "face_center_static"
        else:
            # Moving scene — emit one keypoint per significant shift
            keypoints = []
            last_off = None
            for ts, off in zip(times, raw_offsets):
                if last_off is None or abs(off - last_off) >= _MIN_SHIFT_PX:
                    keypoints.append([round(ts, 2), int(off)])
                    last_off = off
            if not keypoints:
                keypoints = [[round(times[0], 2), int(raw_offsets[0])]]
            strategy = "face_center_dynamic"
    else:
        keypoints = [[round(times[0], 2), int(raw_offsets[0])]]
        strategy = "face_center_static"

    primary_offset = keypoints[0][1]
    confidence = round(len(face_centers_src) / max(1, len(frames)), 2)

    return {
        "strategy": strategy,
        "x_offset": primary_offset,
        "confidence": confidence,
        "fallback": False,
        "keypoints": keypoints,
    }
