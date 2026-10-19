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
_MIN_FACE_AREA_FRAC = 0.01  # minimum face area as fraction of proxy frame (filters background artifacts)


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

        min_face_area = proxy_w * proxy_h * _MIN_FACE_AREA_FRAC
        for i, (ftime, faces, persons) in enumerate(zip(frame_times, face_results, person_results)):
            # Normalise to (x, y, w, h, score)
            dets: list = []
            valid_faces = [(fx, fy, fw, fh) for fx, fy, fw, fh in faces if fw * fh >= min_face_area]
            if valid_faces:
                for fx, fy, fw, fh in valid_faces:
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


# ── v3: Composition Engine — explicit mode selection ──────────────────────────

def plan_clip_v3(
    proxy_path: str,
    clip_start: float,
    clip_end: float,
    src_w: int,
    src_h: int,
    content_hint: str = "auto",
) -> dict:
    """Smart Reframing V1 framing plan using the Composition Engine.

    Extension of plan_clip_v2() that adds:
      - Explicit composition mode (FACE_FOCUS / ACTION_FOCUS / SPLIT_LAYOUT /
        SPEAKER_TRACKING / CENTER)
      - Facecam detection for SPLIT_LAYOUT
      - TemporalSmoother with hysteresis + dwell time + velocity limiting
      - Per-frame keypoints for smooth camera movement (not just per-scene)
      - ContentAnalysis metadata embedded in the returned plan

    Falls back to plan_clip_v2() when newer modules are unavailable.
    """
    from engine.reframe.scene_detector import detect_scenes
    from engine.reframe.mediapipe_detector import (
        face_model_available, pose_model_available,
        detect_faces_mp, detect_persons_mp,
    )
    from engine.reframe.yolox_detector import model_available as yolox_available
    from engine.reframe.yolox_detector import detect_persons as yolox_detect_persons
    from engine.reframe.tracker import ByteTracker
    from engine.reframe.facecam_detector import detect_facecam
    from engine.reframe.smoother import TemporalSmoother
    from engine.reframe import composition as comp

    crop_w = int(src_h * _TARGET_W / _TARGET_H)
    center_offset = (src_w - crop_w) // 2
    half_crop = crop_w / 2.0

    cap = cv2.VideoCapture(proxy_path)
    if not cap.isOpened():
        plan = plan_clip_v2(proxy_path, clip_start, clip_end, src_w, src_h, content_hint)
        plan["composition_mode"] = "center"
        return plan

    proxy_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    proxy_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    proxy_fps = cap.get(cv2.CAP_PROP_FPS) or 2.0
    scale_x = src_w / max(1, proxy_w)
    scale_y = src_h / max(1, proxy_h)

    # ── Read all frames for this clip ─────────────────────────────────────────
    cap.set(cv2.CAP_PROP_POS_MSEC, clip_start * 1000.0)
    all_frames, all_times = [], []
    interval = 1.0 / proxy_fps
    t = clip_start
    while t <= clip_end + interval * 0.5:
        ret, frame = cap.read()
        if not ret:
            break
        all_frames.append(frame)
        all_times.append(t)
        t += interval
    cap.release()

    if not all_frames:
        plan = plan_clip_v2(proxy_path, clip_start, clip_end, src_w, src_h, content_hint)
        plan["composition_mode"] = "center"
        return plan

    # ── Run detectors once over all frames ────────────────────────────────────
    face_results: list[list] = [[] for _ in all_frames]
    person_results: list[list] = [[] for _ in all_frames]
    model_used = "none"

    if face_model_available():
        face_results = detect_faces_mp(all_frames)
        if any(face_results):
            model_used = "mediapipe_face"

    face_hit_rate = sum(1 for f in face_results if f) / max(1, len(all_frames))

    # Try pose/person when face detection is weak
    if face_hit_rate < 0.3 or content_hint in ("action", "gameplay"):
        if pose_model_available():
            person_results = detect_persons_mp(all_frames)
            if any(person_results):
                model_used = model_used + "+mediapipe_pose" if model_used != "none" else "mediapipe_pose"
        if not any(person_results) and yolox_available():
            person_results = yolox_detect_persons(all_frames)
            if any(person_results):
                model_used = model_used + "+yolox" if model_used != "none" else "yolox"

    # YuNet fallback when MediaPipe blocked
    if not any(face_results) and not any(person_results):
        from engine.reframe.detector import model_available as yunet_ok
        from engine.reframe.detector import detect_faces_batch as yunet_detect
        if yunet_ok():
            raw = yunet_detect(all_frames)
            face_results = [[(f[0], f[1], f[2], f[3]) for f in fd] for fd in raw]
            if any(face_results):
                model_used = "yunet"
                face_hit_rate = sum(1 for f in face_results if f) / max(1, len(all_frames))

    # ── Facecam detection ─────────────────────────────────────────────────────
    facecam = detect_facecam(all_frames, face_results, scale_x, scale_y)

    # ── ContentAnalysis ───────────────────────────────────────────────────────
    min_face_area = proxy_w * proxy_h * _MIN_FACE_AREA_FRAC
    face_areas = []
    multi_face_frames = 0
    for faces in face_results:
        valid = [f for f in faces if f[2] * f[3] >= min_face_area]
        if len(valid) >= 2:
            multi_face_frames += 1
        for f in valid:
            face_areas.append((f[2] * f[3]) / max(1, proxy_w * proxy_h))

    person_hit_rate = sum(1 for p in person_results if p) / max(1, len(all_frames))

    analysis = comp.ContentAnalysis(
        face_count_avg=len(face_areas) / max(1, len(all_frames)),
        face_area_ratio=float(statistics.mean(face_areas)) if face_areas else 0.0,
        face_hit_rate=face_hit_rate,
        multi_face_rate=multi_face_frames / max(1, len(all_frames)),
        person_hit_rate=person_hit_rate,
        has_facecam=facecam is not None,
        facecam_confidence=facecam.confidence if facecam else 0.0,
        facecam_corner=facecam.corner if facecam else "",
        facecam_region=(facecam.x, facecam.y, facecam.w, facecam.h) if facecam else None,
        content_hint=content_hint,
        model_used=model_used,
    )

    # ── Composition decision ──────────────────────────────────────────────────
    decision = comp.decide(analysis, center_offset, src_w, src_h)

    # ── Per-frame tracking with TemporalSmoother ──────────────────────────────
    smoother = TemporalSmoother(
        hysteresis_px=40,
        min_dwell_s=0.4,
        max_velocity_pxs=250.0,
        alpha=0.25,
        lost_hold_s=1.5,
    )
    smoother.reset(center_offset)

    tracker = ByteTracker(iou_threshold=0.25, max_age=4)
    scene_changes = detect_scenes(proxy_path, clip_start, clip_end)
    scene_boundaries = {round(s.start_s, 2) for s in scene_changes[1:]}  # all except first

    keypoints: list[list] = []
    last_kp_x: int | None = None

    for i, (frame_t, faces, persons) in enumerate(zip(all_times, face_results, person_results)):
        # Reset tracker at scene cuts
        if round(frame_t, 2) in scene_boundaries:
            tracker.reset()

        # Filter small faces
        valid_faces = [(fx, fy, fw, fh) for fx, fy, fw, fh in faces if fw * fh >= min_face_area]

        proposed_x: float | None = None

        if decision.mode in (comp.CompositionMode.FACE_FOCUS, comp.CompositionMode.SPEAKER_TRACKING):
            if valid_faces:
                if decision.mode == comp.CompositionMode.SPEAKER_TRACKING:
                    # Track largest face (speaker heuristic)
                    primary = max(valid_faces, key=lambda f: f[2] * f[3])
                else:
                    primary = max(valid_faces, key=lambda f: f[2] * f[3])
                fx, fy, fw, fh = primary
                face_cx_src = (fx + fw * 0.5) * scale_x
                # Head-room: shift crop up slightly to give space above head
                face_h_src = fh * scale_y
                head_room = face_h_src * _HEAD_MARGIN
                # We want face centre to appear at 40% from top (not 50%)
                proposed_x = face_cx_src - half_crop

        elif decision.mode == comp.CompositionMode.ACTION_FOCUS:
            dets = []
            for p in persons:
                if len(p) == 5:
                    dets.append(p)
                elif len(p) == 4:
                    dets.append((*p, 0.7))
            if dets:
                active = tracker.update(dets)
                if active:
                    primary = max(active, key=lambda t: t.area)
                    bx, by, bw, bh = primary.bbox
                    proposed_x = (bx + bw * 0.5) * scale_x - half_crop

        # SPLIT_LAYOUT and CENTER: no per-frame tracking
        # (SPLIT_LAYOUT uses fixed regions; CENTER uses center_offset)

        smoothed_x = smoother.update(proposed_x, frame_t - clip_start, src_w, crop_w)

        # Emit keypoint only when position changes meaningfully
        if last_kp_x is None or abs(smoothed_x - last_kp_x) >= _MIN_SHIFT_PX:
            keypoints.append([round(frame_t - clip_start, 3), smoothed_x])
            last_kp_x = smoothed_x

    if not keypoints:
        keypoints = [[0.0, center_offset if decision.fallback else smoother.finalize(src_w, crop_w)]]

    # Deduplicate keypoints with same x (keep only transitions)
    deduped = [keypoints[0]]
    for kp in keypoints[1:]:
        if kp[1] != deduped[-1][1]:
            deduped.append(kp)
    keypoints = deduped

    # Primary offset = first keypoint
    primary_x = keypoints[0][1] if keypoints else center_offset
    if decision.fallback:
        primary_x = center_offset

    # Build per-scene plans for compatibility with v2 consumers
    scene_plans = []
    if scene_changes:
        for s in scene_changes:
            # Find keypoints in this scene window
            in_scene = [x for t, x in keypoints if s.start_s - clip_start <= t < s.end_s - clip_start]
            scene_x = int(statistics.median(in_scene)) if in_scene else primary_x
            scene_plans.append(_make_scene_plan(
                s.start_s, s.end_s, scene_x, decision.confidence,
                None, None, None, model_used=model_used,
            ))

    return {
        "version": 3,
        "strategy": decision.mode.value,
        "composition_mode": decision.mode.value,
        "x_offset": primary_x,
        "confidence": round(decision.confidence, 3),
        "fallback": decision.fallback,
        "model": model_used,
        "scenes": scene_plans,
        "keypoints": keypoints,
        "analysis_resolution": [proxy_w, proxy_h],
        "analysis_fps": proxy_fps,
        "created_at": _now(),
        # Composition Engine metadata
        "composition": comp.describe(decision),
        "content_analysis": {
            "face_hit_rate":     round(analysis.face_hit_rate, 3),
            "face_area_ratio":   round(analysis.face_area_ratio, 4),
            "multi_face_rate":   round(analysis.multi_face_rate, 3),
            "person_hit_rate":   round(analysis.person_hit_rate, 3),
            "has_facecam":       analysis.has_facecam,
            "facecam_confidence": analysis.facecam_confidence,
            "facecam_corner":    analysis.facecam_corner,
            "facecam_region":    list(analysis.facecam_region) if analysis.facecam_region else None,
            "content_hint":      content_hint,
        },
        # SPLIT_LAYOUT regions (null when not applicable)
        "main_region":      list(decision.main_region) if decision.main_region else None,
        "secondary_region": list(decision.secondary_region) if decision.secondary_region else None,
    }


# ── v3.1: Smart Reframing V1.1 — optimal gameplay region + AR-safe scale ──────

def plan_clip_v3_1(
    proxy_path: str,
    clip_start: float,
    clip_end: float,
    src_w: int,
    src_h: int,
    content_hint: str = "auto",
) -> dict:
    """Smart Reframing V1.1 framing plan.

    Extension of plan_clip_v3() that adds:
      - _optimal_gameplay_region() for SPLIT_LAYOUT (selects highest-content
        gameplay crop instead of a simple horizontal strip)
      - filter_version="v11" tag so render_clip uses _compute_split_layout_filter_v11()
        (scale-fill+crop for gameplay, scale-fit+pad for facecam — no distortion)

    Falls back to plan_clip_v3() when composition module is unavailable.
    """
    from engine.reframe import composition as comp

    plan = plan_clip_v3(proxy_path, clip_start, clip_end, src_w, src_h, content_hint)

    plan["version"] = 3.1
    plan["filter_version"] = "v11"

    # Re-run the composition decision with V1.1 logic when SPLIT_LAYOUT is active
    if plan.get("composition_mode") == "split_layout":
        try:
            # Rebuild ContentAnalysis from stored analysis
            ca = plan.get("content_analysis", {})
            analysis = comp.ContentAnalysis(
                face_hit_rate=ca.get("face_hit_rate", 0.0),
                face_area_ratio=ca.get("face_area_ratio", 0.0),
                multi_face_rate=ca.get("multi_face_rate", 0.0),
                person_hit_rate=ca.get("person_hit_rate", 0.0),
                has_facecam=ca.get("has_facecam", False),
                facecam_confidence=ca.get("facecam_confidence", 0.0),
                facecam_corner=ca.get("facecam_corner", ""),
                facecam_region=tuple(ca["facecam_region"]) if ca.get("facecam_region") else None,
                content_hint=content_hint,
            )
            crop_w = int(src_h * _TARGET_W / _TARGET_H)
            center_offset = (src_w - crop_w) // 2
            decision_v11 = comp.decide_v11(analysis, center_offset, src_w, src_h)

            plan["main_region"]      = list(decision_v11.main_region) if decision_v11.main_region else plan.get("main_region")
            plan["secondary_region"] = list(decision_v11.secondary_region) if decision_v11.secondary_region else plan.get("secondary_region")
            plan["composition"] = comp.describe(decision_v11)
            plan["composition"]["filter_version"] = "v11"
        except Exception as e:
            plan["v11_error"] = str(e)

    return plan


# ── v3.2: Smart Reframing V1.2 — Adaptive Composition Engine ─────────────────

def plan_clip_v3_2(
    proxy_path: str,
    clip_start: float,
    clip_end: float,
    src_w: int,
    src_h: int,
    content_hint: str = "auto",
) -> dict:
    """Smart Reframing V1.2 — Adaptive Composition Engine.

    Extends V1.1 with:
      1. Scene Understanding: classifies the clip into temporal scene types
         (ACTIVE_GAMEPLAY, FACE_REACTION, MENU_OR_UI, …) and adapts the
         composition mode accordingly.
      2. Dead Zone: ConfidenceGate (±0.05 around 0.50) prevents oscillation
         between FACE_FOCUS and SPLIT_LAYOUT for borderline clips.
      3. Adaptive Split Ratio: selects the split fraction (0.55–0.72) that
         best matches the aspect ratio of the optimal gameplay region.
      4. HUD Protection: detects persistent corner HUD regions so the
         composition scorer can account for information loss.

    Falls back gracefully to the V1.1 plan on any internal error.
    """
    from engine.reframe import composition as comp
    from engine.reframe.scene_analyzer import analyze_clip_scenes, adaptive_split_fraction
    from engine.reframe.hud_protector import detect_hud_regions

    crop_w = int(src_h * _TARGET_W / _TARGET_H)
    center_offset = (src_w - crop_w) // 2

    # ── Step 1: run V1.1 base plan for all structural analysis ───────────────
    plan = plan_clip_v3_1(proxy_path, clip_start, clip_end, src_w, src_h, content_hint)
    plan["version"] = 3.2
    plan["filter_version"] = "v12"

    # ── Step 2: re-open proxy for scene analysis ──────────────────────────────
    try:
        cap = cv2.VideoCapture(proxy_path)
        if not cap.isOpened():
            raise RuntimeError("proxy not readable")

        proxy_fps = cap.get(cv2.CAP_PROP_FPS) or 2.0

        cap.set(cv2.CAP_PROP_POS_MSEC, clip_start * 1000.0)
        sa_frames, sa_times = [], []
        interval = 1.0 / proxy_fps
        t = clip_start
        while t <= clip_end + interval * 0.5:
            ret, frame = cap.read()
            if not ret:
                break
            sa_frames.append(frame)
            sa_times.append(t)
            t += interval
        cap.release()

        if not sa_frames:
            raise RuntimeError("no frames read")

        # ── Step 3: face detection for scene analysis ─────────────────────────
        from engine.reframe.detector import model_available as yunet_ok
        from engine.reframe.detector import detect_faces_batch as yunet_detect
        if yunet_ok():
            raw_faces = yunet_detect(sa_frames)
            sa_faces = [[(f[0], f[1], f[2], f[3]) for f in fd] for fd in raw_faces]
        else:
            sa_faces = [[] for _ in sa_frames]

        # ── Step 4: classify scene segments ──────────────────────────────────
        scene_segments = analyze_clip_scenes(sa_frames, sa_faces, proxy_fps, sa_times)

        # ── Step 5: HUD detection ─────────────────────────────────────────────
        hud_regions = detect_hud_regions(sa_frames, sa_faces, src_w, src_h)

        # ── Step 6: dominant scene type ───────────────────────────────────────
        from engine.reframe.scene_analyzer import dominant_scene_type
        dom_seg = dominant_scene_type(scene_segments)
        dom_scene_type = dom_seg.scene_type.value if dom_seg else "unknown"

        # ── Step 7: adaptive split fraction ───────────────────────────────────
        current_main = plan.get("main_region")
        gp_tuple = tuple(current_main) if current_main else None
        split_frac = adaptive_split_fraction(
            scene_segments,
            gameplay_region=gp_tuple,
            target_w=_TARGET_W,
            target_h=_TARGET_H,
        )
        split_frac = round(split_frac / 0.05) * 0.05
        split_frac = max(0.55, min(0.72, split_frac))

        # ── Step 8: ConfidenceGate dead zone ──────────────────────────────────
        gate = comp.ConfidenceGate(entry_threshold=0.55, exit_threshold=0.45)
        ca = plan.get("content_analysis", {})
        analysis = comp.ContentAnalysis(
            face_hit_rate=ca.get("face_hit_rate", 0.0),
            face_area_ratio=ca.get("face_area_ratio", 0.0),
            multi_face_rate=ca.get("multi_face_rate", 0.0),
            person_hit_rate=ca.get("person_hit_rate", 0.0),
            has_facecam=ca.get("has_facecam", False),
            facecam_confidence=ca.get("facecam_confidence", 0.0),
            facecam_corner=ca.get("facecam_corner", ""),
            facecam_region=tuple(ca["facecam_region"]) if ca.get("facecam_region") else None,
            content_hint=content_hint,
        )

        # ── Step 9: V1.2 composition decision ─────────────────────────────────
        top_output_h = int(_TARGET_H * split_frac)
        top_output_h = top_output_h - (top_output_h % 2)

        decision_v12 = comp.decide_v12(
            analysis, center_offset, src_w, src_h,
            scene_type=dom_scene_type,
            confidence_gate=gate,
            split_fraction=split_frac,
            top_output_h=top_output_h,
            output_w=_TARGET_W,
            hud_regions=hud_regions,
        )

        # ── Step 10: update plan with V1.2 data ───────────────────────────────
        plan["composition_mode"] = decision_v12.mode.value
        plan["main_region"]      = list(decision_v12.main_region) if decision_v12.main_region else plan.get("main_region")
        plan["secondary_region"] = list(decision_v12.secondary_region) if decision_v12.secondary_region else plan.get("secondary_region")
        plan["composition"]      = comp.describe(decision_v12)
        plan["composition"]["filter_version"] = "v12"
        plan["v12"] = {
            "dominant_scene_type": dom_scene_type,
            "scene_segments": [
                {
                    "start_s": s.start_s,
                    "end_s": s.end_s,
                    "type": s.scene_type.value,
                    "confidence": s.confidence,
                    "fraction": s.recommended_split_fraction,
                    "reasons": s.reason_codes,
                }
                for s in scene_segments
            ],
            "hud_regions": [
                {"x": r.x, "y": r.y, "w": r.w, "h": r.h,
                 "type": r.hud_type.value, "priority": r.priority,
                 "confidence": r.confidence}
                for r in hud_regions
            ],
            "split_fraction": split_frac,
            "confidence_gate": {
                "entry": gate.entry_threshold,
                "exit": gate.exit_threshold,
                "active": gate.is_active,
            },
        }

        # ── Step 10b: per-segment composition decisions (P4 — stored for analysis) ──
        try:
            seg_decisions = []
            for seg in scene_segments:
                seg_frac = getattr(seg, "recommended_split_fraction", None) or split_frac
                seg_frac = max(0.55, min(0.72, seg_frac))
                seg_top_h = int(_TARGET_H * seg_frac)
                seg_top_h = seg_top_h - (seg_top_h % 2)
                seg_gate = comp.ConfidenceGate(entry_threshold=0.55, exit_threshold=0.45)
                seg_dec = comp.decide_v12(
                    analysis, center_offset, src_w, src_h,
                    scene_type=seg.scene_type.value,
                    confidence_gate=seg_gate,
                    split_fraction=seg_frac,
                    top_output_h=seg_top_h,
                    output_w=_TARGET_W,
                    hud_regions=hud_regions,
                )
                seg_decisions.append({
                    "start_s": seg.start_s,
                    "end_s": seg.end_s,
                    "scene_type": seg.scene_type.value,
                    "mode": seg_dec.mode.value,
                    "confidence": round(seg_dec.confidence, 3),
                    "reason": seg_dec.reason,
                    "split_fraction": seg_frac,
                })
            plan["v12"]["segment_decisions"] = seg_decisions
        except Exception as _seg_exc:
            plan["v12"]["segment_decisions_error"] = str(_seg_exc)

    except Exception as e:
        # Graceful fallback: tag error but keep V1.1 plan data
        plan["v12_error"] = str(e)

    return plan
