"""Framing planner — v1 (YuNet static) + v2 (scene-aware, multi-model).

v1  plan_clip()       — original, used by the live pipeline
v2  plan_clip_v2()    — new: scene cuts + MediaPipe / YOLOX + tracker

Both return a FramingPlan dict (JSON-serialisable):
  {
    "version":    1 | 2,
    "strategy":   str,          # e.g. "mediapipe_face", "yolox_person", "center"
    "x_offset":   int,          # primary static crop offset (source pixels)
    "confidence": float,        # 0–1  fraction of frames with a detection
    "fallback":   bool,
    "model":      str,          # which detector produced the plan
    "scenes": [                 # v2 only
      {
        "start_s":     float,
        "end_s":       float,
        "x_offset":    int,
        "confidence":  float,
        "subject_bbox": [x, y, w, h] | null,
        "subject_class": str | null,
        "track_id":    int | null,
      },
      …
    ],
    "keypoints":  [[time_s, x_offset], …],  # used for dynamic FFmpeg crop
    "analysis_resolution": [w, h],          # proxy frame size
    "analysis_fps":        float,
    "created_at":          str,             # ISO-8601
  }
"""
from __future__ import annotations
import statistics
import datetime

import cv2

from engine.reframe.detector import model_available as yunet_available
from engine.reframe.detector import detect_faces_batch as yunet_detect
from engine.reframe.smoother import smooth_ema, clamp_offset

# ── Constants ─────────────────────────────────────────────────────────────────
_TARGET_W = 1080
_TARGET_H = 1920
_MIN_SHIFT_PX = 60          # suppress micro-jitter between keypoints
_HEAD_MARGIN = 0.20         # fraction of face height added above for head-room
_BODY_MARGIN = 0.08         # lateral margin when centering on a body box


# ── v1: original static plan (YuNet) ─────────────────────────────────────────

def plan_clip(
    proxy_path: str,
    clip_start: float,
    clip_end: float,
    src_w: int,
    src_h: int,
) -> dict:
    """Analyse [clip_start, clip_end] in the proxy and return a v1 FramingPlan.

    Falls back to centre crop when YuNet model is absent or no faces found.
    """
    crop_w = int(src_h * _TARGET_W / _TARGET_H)
    center_offset = (src_w - crop_w) // 2

    def _center_plan() -> dict:
        return {
            "version": 1,
            "strategy": "center",
            "x_offset": center_offset,
            "confidence": 0.0,
            "fallback": True,
            "model": "none",
            "scenes": [],
            "keypoints": [[round(clip_start, 2), center_offset]],
            "analysis_resolution": [0, 0],
            "analysis_fps": 0.0,
            "created_at": _now(),
        }

    if not yunet_available():
        return _center_plan()

    cap = cv2.VideoCapture(proxy_path)
    if not cap.isOpened():
        return _center_plan()

    proxy_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    proxy_fps = cap.get(cv2.CAP_PROP_FPS) or 2.0
    scale_x = src_w / max(1, proxy_w)

    cap.set(cv2.CAP_PROP_POS_MSEC, clip_start * 1000.0)
    frames, frame_times = [], []
    interval = 1.0 / proxy_fps
    t = clip_start
    while t <= clip_end + interval * 0.5:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
        frame_times.append(t)
        t += interval
    cap.release()

    if not frames:
        return _center_plan()

    detections = yunet_detect(frames)
    face_centers: list[tuple[float, float]] = []
    for time_s, faces in zip(frame_times, detections):
        if not faces:
            continue
        largest = max(faces, key=lambda f: f[2] * f[3])
        fx, _, fw, _ = largest
        face_centers.append((time_s, (fx + fw * 0.5) * scale_x))

    if not face_centers:
        return _center_plan()

    times = [c[0] for c in face_centers]
    centers = [c[1] for c in face_centers]
    smoothed = smooth_ema(centers, alpha=0.3)
    half_crop = crop_w / 2.0
    raw_offsets = [clamp_offset(cx - half_crop, src_w, crop_w) for cx in smoothed]

    if len(raw_offsets) >= 3 and statistics.variance(raw_offsets) < _MIN_SHIFT_PX ** 2:
        static_off = clamp_offset(statistics.median(raw_offsets), src_w, crop_w)
        keypoints = [[round(times[0], 2), static_off]]
        strategy = "face_center_static"
    else:
        keypoints, last_off = [], None
        for ts, off in zip(times, raw_offsets):
            if last_off is None or abs(off - last_off) >= _MIN_SHIFT_PX:
                keypoints.append([round(ts, 2), int(off)])
                last_off = off
        if not keypoints:
            keypoints = [[round(times[0], 2), int(raw_offsets[0])]]
        strategy = "face_center_dynamic"

    confidence = round(len(face_centers) / max(1, len(frames)), 2)
    return {
        "version": 1,
        "strategy": strategy,
        "x_offset": keypoints[0][1],
        "confidence": confidence,
        "fallback": False,
        "model": "yunet",
        "scenes": [],
        "keypoints": keypoints,
        "analysis_resolution": [proxy_w, int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if proxy_w else 0],
        "analysis_fps": proxy_fps,
        "created_at": _now(),
    }


# ── v2: scene-aware, multi-model plan ────────────────────────────────────────

def plan_clip_v2(
    proxy_path: str,
    clip_start: float,
    clip_end: float,
    src_w: int,
    src_h: int,
    content_hint: str = "auto",  # "talking_head"|"conversation"|"action"|"webcam"|"auto"
) -> dict:
    """Scene-aware framing plan using MediaPipe + YOLOX + ByteTrack.

    content_hint steers which detector is tried first:
      "talking_head" / "conversation"  → face detection first
      "action"                          → YOLOX person detection first
      "webcam"                          → face detection + full-frame fallback
      "auto"                            → try face; if low confidence, try YOLOX

    Falls back to plan_clip() (YuNet) when newer models are absent, and to
    center crop when all detectors fail.
    """
    from engine.reframe.scene_detector import detect_scenes
    from engine.reframe.mediapipe_detector import (
        face_model_available, pose_model_available,
        detect_faces_mp, detect_persons_mp,
    )
    from engine.reframe.yolox_detector import model_available as yolox_available
    from engine.reframe.yolox_detector import detect_persons as yolox_detect_persons
    from engine.reframe.tracker import ByteTracker

    crop_w = int(src_h * _TARGET_W / _TARGET_H)
    center_offset = (src_w - crop_w) // 2
    half_crop = crop_w / 2.0

    # ── Open proxy ────────────────────────────────────────────────────────────
    cap = cv2.VideoCapture(proxy_path)
    if not cap.isOpened():
        return plan_clip(proxy_path, clip_start, clip_end, src_w, src_h)

    proxy_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    proxy_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    proxy_fps = cap.get(cv2.CAP_PROP_FPS) or 2.0
    scale_x = src_w / max(1, proxy_w)

    # ── Scene detection ───────────────────────────────────────────────────────
    scenes_raw = detect_scenes(proxy_path, clip_start, clip_end)

    # ── Per-scene analysis ────────────────────────────────────────────────────
    scene_plans: list[dict] = []
    all_keypoints: list[list] = []
    total_frames = 0
    total_detections = 0

    for scene in scenes_raw:
        s_start, s_end = scene.start_s, scene.end_s

        # Read frames for this scene
        cap.set(cv2.CAP_PROP_POS_MSEC, s_start * 1000.0)
        frames, frame_times = [], []
        interval = 1.0 / proxy_fps
        t = s_start
        while t <= s_end + interval * 0.5:
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(frame)
            frame_times.append(t)
            t += interval

        if not frames:
            scene_plans.append(_make_scene_plan(s_start, s_end, center_offset, 0.0, None, None, None))
            continue

        total_frames += len(frames)

        # ── Detector selection ────────────────────────────────────────────────
        use_face = content_hint in ("talking_head", "conversation", "webcam", "auto")
        use_action = content_hint in ("action",)

        face_results: list[list] = [[] for _ in frames]
        person_results: list[list] = [[] for _ in frames]
        model_used = "none"

        # 1) MediaPipe face detection
        if use_face and face_model_available():
            face_results = detect_faces_mp(frames)
            if any(face_results):
                model_used = "mediapipe_face"

        # 2) MediaPipe pose (if face gave poor results or action content)
        face_hit_rate = sum(1 for f in face_results if f) / max(1, len(frames))
        if (use_action or (content_hint == "auto" and face_hit_rate < 0.3)) and pose_model_available():
            person_results = detect_persons_mp(frames)
            if any(person_results):
                model_used = "mediapipe_pose"

        # 3) YOLOX (action scenes or when face detection is weak)
        if (use_action or (content_hint == "auto" and face_hit_rate < 0.3)) and yolox_available():
            if not any(person_results):
                person_results = yolox_detect_persons(frames)
                if any(person_results):
                    model_used = "yolox_person"

        # 4) YuNet fallback — use when no other model produced results
        if model_used == "none" and yunet_available():
            yunet_raw = yunet_detect(frames)
            face_results = [[(f[0], f[1], f[2], f[3]) for f in fd] for fd in yunet_raw]
            if any(face_results):
                model_used = "yunet"

        # 5) YuNet second try — MediaPipe detected 0 faces (may be blocked by OS)
        if not any(face_results) and not any(person_results) and yunet_available():
            yunet_raw = yunet_detect(frames)
            face_results = [[(f[0], f[1], f[2], f[3]) for f in fd] for fd in yunet_raw]
            if any(face_results):
                model_used = "yunet"

        # ── Merge detections: face preferred, then person ─────────────────────
        tracker = ByteTracker(iou_threshold=0.25, max_age=3)
        scene_offsets: list[tuple[float, int]] = []  # (time_s, x_offset)
        scene_subject_bbox = None
        scene_track_id = None
        scene_subject_class = None

        for i, (ftime, faces, persons) in enumerate(zip(frame_times, face_results, person_results)):
            # Normalise to (x, y, w, h, score)
            dets: list = []
            if faces:
                for fx, fy, fw, fh in faces:
                    dets.append((fx, fy, fw, fh, 0.85))
                subject_class = "face"
            elif persons:
                for p in persons:
                    if len(p) == 5:
                        dets.append(p)
                    else:
                        dets.append((*p[:4], 0.7))
                subject_class = "person"
            else:
                subject_class = None

            active = tracker.update(dets)
            if not active:
                continue

            # Pick largest active track as primary subject
            primary = max(active, key=lambda t: t.area)
            if scene_subject_bbox is None:
                scene_subject_bbox = list(primary.bbox)
                scene_track_id = primary.track_id
                scene_subject_class = subject_class

            # Compute x_offset that centres the subject's horizontal midpoint
            bx, by, bw, bh = primary.bbox
            subject_cx_src = (bx + bw * 0.5) * scale_x

            # Add head-room when framing a face
            if subject_class == "face":
                face_h_src = bh * scale_x
                subject_cx_src = clamp_offset(
                    subject_cx_src - half_crop, src_w, crop_w
                ) + half_crop  # recalculate after potential shift

            x_off = clamp_offset(subject_cx_src - half_crop, src_w, crop_w)
            scene_offsets.append((ftime, x_off))
            total_detections += 1

        # ── Build per-scene offset from smoothed trajectory ───────────────────
        if not scene_offsets:
            x_off_final = center_offset
            confidence = 0.0
        else:
            raw_ts = [o[0] for o in scene_offsets]
            raw_xs = [o[1] for o in scene_offsets]
            smoothed = smooth_ema(raw_xs, alpha=0.25)
            offsets_clamped = [clamp_offset(x, src_w, crop_w) for x in smoothed]
            confidence = round(len(scene_offsets) / max(1, len(frames)), 2)

            # Primary offset = median of smoothed positions (stable, not jittery)
            x_off_final = clamp_offset(int(statistics.median(offsets_clamped)), src_w, crop_w)
            # One keypoint per scene at its start time (scene-boundary-aligned crop)
            all_keypoints.append([round(s_start - clip_start, 3), x_off_final])

        scene_plans.append(_make_scene_plan(
            s_start, s_end, x_off_final, confidence,
            scene_subject_bbox, scene_subject_class, scene_track_id,
            model_used=model_used,
        ))

    cap.release()

    # ── Build global plan ─────────────────────────────────────────────────────
    if not scene_plans:
        return plan_clip(proxy_path, clip_start, clip_end, src_w, src_h)

    global_confidence = round(total_detections / max(1, total_frames), 2)
    fallback = global_confidence < 0.1

    # Primary x_offset: first scene (most of the time the whole clip)
    primary_offset = scene_plans[0]["x_offset"]
    if fallback:
        primary_offset = center_offset

    # KI-016 guard: low-confidence detection at an extreme edge is unreliable.
    # If confidence < 0.80 and the offset is within 80px of either edge, fall
    # back to center crop rather than risk a worse framing than the original.
    max_offset = src_w - crop_w
    _EDGE_GUARD_PX = 80
    if (not fallback and global_confidence < 0.80
            and (primary_offset < _EDGE_GUARD_PX or primary_offset > max_offset - _EDGE_GUARD_PX)):
        primary_offset = center_offset
        fallback = True

    # Subject class: majority vote across scenes with detections
    subject_classes = [sp["subject_class"] for sp in scene_plans if sp.get("subject_class")]
    dominant_class = max(set(subject_classes), key=subject_classes.count) if subject_classes else None

    # Determine dominant strategy
    if fallback:
        strategy = "center"
    elif not all_keypoints or len(all_keypoints) == 1:
        strategy = "face_center_static" if dominant_class == "face" else "person_static"
    else:
        strategy = "face_center_dynamic" if dominant_class == "face" else "person_dynamic"

    # Collect model names used across scenes
    scene_models = {sp.get("model", "none") for sp in scene_plans}
    model_str = "+".join(sorted(scene_models - {"none"})) or "none"

    if not all_keypoints:
        all_keypoints = [[0.0, primary_offset]]

    return {
        "version": 2,
        "strategy": strategy,
        "x_offset": primary_offset,
        "confidence": global_confidence,
        "fallback": fallback,
        "model": model_str,
        "scenes": scene_plans,
        "keypoints": all_keypoints,
        "analysis_resolution": [proxy_w, proxy_h],
        "analysis_fps": proxy_fps,
        "created_at": _now(),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_scene_plan(
    start_s: float,
    end_s: float,
    x_offset: int,
    confidence: float,
    subject_bbox: list | None,
    subject_class: str | None,
    track_id: int | None,
    model_used: str = "none",
) -> dict:
    return {
        "start_s": round(start_s, 3),
        "end_s": round(end_s, 3),
        "x_offset": x_offset,
        "confidence": round(confidence, 2),
        "subject_bbox": subject_bbox,
        "subject_class": subject_class,
        "track_id": track_id,
        "model": model_used,
    }


def _now() -> str:
    return datetime.datetime.utcnow().isoformat()
