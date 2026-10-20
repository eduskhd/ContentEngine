"""Scene Understanding Engine — Smart Reframing V1.2.

Classifies temporal segments of a clip into semantic scene types using
lightweight visual signals from proxy frames. No external ML models.

Scene types (SceneType enum):
    ACTIVE_GAMEPLAY         — high motion, minimal face, dynamic action
    STATIC_GAMEPLAY         — low-to-medium motion, minimal face
    MENU_OR_UI              — very low motion, high edge density (text/UI)
    FACE_REACTION           — dominant large face, low motion
    CONVERSATION            — multiple faces or persistent medium face
    LOADING_OR_TRANSITION   — extreme brightness or rapid scene change
    UNKNOWN                 — insufficient signal

Each SceneSegment carries:
    scene_type, start_s, end_s, confidence,
    recommended_split_fraction, reason_codes
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np


class SceneType(Enum):
    ACTIVE_GAMEPLAY       = "active_gameplay"
    STATIC_GAMEPLAY       = "static_gameplay"
    MENU_OR_UI            = "menu_or_ui"
    FACE_REACTION         = "face_reaction"
    CONVERSATION          = "conversation"
    LOADING_OR_TRANSITION = "loading_or_transition"
    UNKNOWN               = "unknown"


# Recommended split fractions per scene type
_SCENE_SPLIT_FRACTION: dict[SceneType, float] = {
    SceneType.ACTIVE_GAMEPLAY:       0.65,   # gameplay priority, but AR-based optimal wins
    SceneType.STATIC_GAMEPLAY:       0.60,
    SceneType.MENU_OR_UI:            0.65,   # slightly more room to read menu
    SceneType.FACE_REACTION:         0.0,    # special: switch to FACE_FOCUS
    SceneType.CONVERSATION:          0.0,    # special: switch to FACE_FOCUS
    SceneType.LOADING_OR_TRANSITION: -1.0,  # special: keep previous
    SceneType.UNKNOWN:               0.60,
}


@dataclass
class FrameSignals:
    """Aggregated visual signals for a group of frames."""
    motion_mean: float = 0.0          # mean inter-frame absolute diff
    motion_max: float = 0.0           # peak motion (scene cut detector)
    brightness_mean: float = 127.0    # mean pixel intensity
    brightness_std: float = 0.0       # std across frames (stability)
    edge_density: float = 0.0         # mean Canny edge fraction
    face_hit_rate: float = 0.0        # fraction of frames with ≥1 face
    face_size_ratio: float = 0.0      # mean (face_area / frame_area) when present
    multi_face_rate: float = 0.0      # fraction of frames with ≥2 faces
    n_frames: int = 0


@dataclass
class SceneSegment:
    """One scene segment with its type classification and composition hint."""
    start_s: float
    end_s: float
    scene_type: SceneType
    confidence: float                   # 0–1 classification confidence
    recommended_split_fraction: float   # 0 = face_focus, -1 = keep prev
    reason_codes: list[str] = field(default_factory=list)
    signals: Optional[FrameSignals] = None

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)


# ── Thresholds ────────────────────────────────────────────────────────────────

_MOTION_HIGH  = 22.0   # px diff/frame → ACTIVE_GAMEPLAY
_MOTION_LOW   = 4.0    # px diff/frame → MENU or STATIC
_BRIGHT_DARK  = 18.0   # very dark → loading/transition
_BRIGHT_WHITE = 235.0  # very bright → loading/transition
_BRIGHT_STD   = 40.0   # unstable brightness → transition
_EDGE_MENU    = 12.0   # high edges → menu/UI
# V1.2 thresholds (kept for reference):
# _FACE_REACTION_AREA = 0.07
# _FACE_HIT_REACTION  = 0.50
# V1.2.1 fix F1: raised thresholds so facecam overlay (small corner face) does
# not trigger FACE_REACTION and suppress SPLIT_LAYOUT. A facecam at 640x360 in
# a 1920x1080 frame occupies ≈6% → below the new 0.15 threshold. A streamer
# filling the whole frame (IRL, no game) occupies >20% and still triggers it.
_FACE_REACTION_AREA = 0.15   # face occupying >15% of frame (was 0.07)
_FACE_HIT_REACTION  = 0.65   # face present in >65% of frames (was 0.50)
_FACE_CONVERSATION  = 0.35   # ≥35% multi-face rate (was 0.30)


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_clip_scenes(
    frames: list[np.ndarray],
    face_results: list[list[tuple[int, int, int, int]]],
    proxy_fps: float,
    frame_times: list[float],
    window_s: float = 2.0,
) -> list[SceneSegment]:
    """Classify the clip into temporal SceneSegments.

    Parameters
    ----------
    frames : proxy-resolution BGR frames (typically 360×202 or similar)
    face_results : face boxes (x,y,w,h) per frame at proxy resolution
    proxy_fps : frame rate of the proxy (usually 2.0)
    frame_times : absolute timestamps (seconds) for each frame
    window_s : analysis window duration (seconds); default 2s = 4 frames at 2fps

    Returns
    -------
    List of SceneSegment covering the full clip duration.
    """
    if not frames or not frame_times:
        return []

    clip_start = frame_times[0]
    clip_end   = frame_times[-1]
    n = len(frames)

    fh, fw = frames[0].shape[:2]
    frame_area = fw * fh

    # ── Compute inter-frame motion ─────────────────────────────────────────────
    motion_per_frame = [0.0] * n
    for i in range(1, n):
        diff = np.mean(np.abs(frames[i].astype(np.int16) - frames[i - 1].astype(np.int16)))
        motion_per_frame[i] = float(diff)

    # ── Group into windows ─────────────────────────────────────────────────────
    frames_per_window = max(1, int(window_s * proxy_fps))
    segments: list[SceneSegment] = []

    i = 0
    while i < n:
        j = min(i + frames_per_window, n)
        window_frames = frames[i:j]
        window_times  = frame_times[i:j]
        window_faces  = face_results[i:j]
        window_motion = motion_per_frame[i:j]

        sig = _compute_signals(window_frames, window_faces, window_motion, frame_area)

        seg_start = window_times[0]
        seg_end   = window_times[-1] + (1.0 / max(proxy_fps, 1.0))

        scene_type, confidence, reasons = _classify(sig)
        fraction = _scene_to_fraction(scene_type)

        segments.append(SceneSegment(
            start_s=round(seg_start, 3),
            end_s=round(seg_end, 3),
            scene_type=scene_type,
            confidence=confidence,
            recommended_split_fraction=fraction,
            reason_codes=reasons,
            signals=sig,
        ))
        i = j

    return _merge_similar_segments(segments)


def dominant_scene_type(
    segments: list[SceneSegment],
) -> SceneSegment | None:
    """Return the SceneSegment type that covers the most total duration."""
    if not segments:
        return None

    duration_by_type: dict[SceneType, float] = {}
    for seg in segments:
        duration_by_type[seg.scene_type] = (
            duration_by_type.get(seg.scene_type, 0.0) + seg.duration_s
        )

    best_type = max(duration_by_type, key=duration_by_type.__getitem__)
    # Return the highest-confidence segment of the dominant type
    candidates = [s for s in segments if s.scene_type == best_type]
    return max(candidates, key=lambda s: s.confidence)


def adaptive_split_fraction(
    segments: list[SceneSegment],
    gameplay_region: tuple[int, int, int, int] | None,
    target_w: int = 1080,
    target_h: int = 1920,
    min_fraction: float = 0.55,
    max_fraction: float = 0.72,
) -> float:
    """Compute the best split fraction for this clip.

    Uses AR-aware computation when gameplay region is available,
    then clips to the range recommended by scene type.
    """
    # AR-optimal fraction (minimises scale factor → maximises content)
    if gameplay_region is not None:
        _, _, gw, gh = gameplay_region
        if gw > 0 and gh > 0:
            # Fraction where aspect ratios match: TARGET_W/gw == (frac*TARGET_H)/gh
            ar_optimal = (target_w * gh) / (gw * target_h)
            # For typical 16:9 gameplay (gw >> gh), ar_optimal < 0.5 → clamped up
            # For near-square gameplay, ar_optimal ≈ 0.56
            ar_fraction = max(min_fraction, min(max_fraction, ar_optimal))
        else:
            ar_fraction = 0.60
    else:
        ar_fraction = 0.60

    # Scene-type range: clip to what the dominant scene recommends
    ds = dominant_scene_type(segments)
    if ds is not None and ds.recommended_split_fraction > 0:
        scene_frac = ds.recommended_split_fraction
        # Use scene fraction as upper bound (don't go above what scene needs)
        combined = min(scene_frac, max_fraction)
        # Round to nearest standard split (0.60, 0.65, 0.70)
        combined = round(combined / 0.05) * 0.05
        combined = max(min_fraction, min(max_fraction, combined))
    else:
        combined = 0.60

    # Final: combine AR-optimal with scene recommendation
    # Weight AR-optimal higher (it directly maximises content preservation)
    final = 0.6 * ar_fraction + 0.4 * combined
    # Round to nearest 0.05
    final = round(final / 0.05) * 0.05
    return max(min_fraction, min(max_fraction, final))


# ── Internal helpers ──────────────────────────────────────────────────────────

def _compute_signals(
    frames: list[np.ndarray],
    face_results: list[list[tuple[int, int, int, int]]],
    motion_values: list[float],
    frame_area: int,
) -> FrameSignals:
    """Aggregate visual signals for a group of frames."""
    if not frames:
        return FrameSignals()

    fh, fw = frames[0].shape[:2]

    # Brightness
    brightnesses = [float(np.mean(f)) for f in frames]
    brightness_mean = float(np.mean(brightnesses))
    brightness_std  = float(np.std(brightnesses))

    # Edge density (Canny on every other frame — fast enough)
    try:
        import cv2 as _cv2
        edge_densities = []
        for i, f in enumerate(frames[::2]):  # sample every 2nd frame
            gray = _cv2.cvtColor(f, _cv2.COLOR_BGR2GRAY)
            edges = _cv2.Canny(gray, 50, 150)
            edge_densities.append(float(np.mean(edges > 0) * 100))
        edge_density = float(np.mean(edge_densities)) if edge_densities else 0.0
    except Exception:
        edge_density = 0.0

    # Motion
    motion_arr = [m for m in motion_values if m > 0]
    motion_mean = float(np.mean(motion_arr)) if motion_arr else 0.0
    motion_max  = float(max(motion_arr, default=0.0))

    # Face signals
    n = len(frames)
    face_hit_frames = 0
    multi_face_frames = 0
    face_size_sum = 0.0
    face_size_count = 0

    for faces in face_results:
        if faces:
            face_hit_frames += 1
            if len(faces) >= 2:
                multi_face_frames += 1
            largest = max(faces, key=lambda f: f[2] * f[3])
            face_size_sum += (largest[2] * largest[3]) / max(1, frame_area)
            face_size_count += 1

    face_hit_rate   = face_hit_frames / max(1, n)
    multi_face_rate = multi_face_frames / max(1, n)
    face_size_ratio = face_size_sum / max(1, face_size_count)

    return FrameSignals(
        motion_mean=motion_mean,
        motion_max=motion_max,
        brightness_mean=brightness_mean,
        brightness_std=brightness_std,
        edge_density=edge_density,
        face_hit_rate=face_hit_rate,
        face_size_ratio=face_size_ratio,
        multi_face_rate=multi_face_rate,
        n_frames=n,
    )


def _classify(sig: FrameSignals) -> tuple[SceneType, float, list[str]]:
    """Apply classification rules. Returns (type, confidence, reason_codes)."""
    reasons: list[str] = []

    # 1. Loading/Transition: extreme brightness or unstable brightness
    if (sig.brightness_mean < _BRIGHT_DARK
            or sig.brightness_mean > _BRIGHT_WHITE
            or sig.brightness_std > _BRIGHT_STD):
        conf = 0.7 + min(0.3, (abs(sig.brightness_std - _BRIGHT_STD) / 100.0))
        reasons.append(f"brightness:{sig.brightness_mean:.0f} std:{sig.brightness_std:.0f}")
        return SceneType.LOADING_OR_TRANSITION, round(min(1.0, conf), 2), reasons

    # 2. Face Reaction: large face present most of the time
    if (sig.face_hit_rate >= _FACE_HIT_REACTION
            and sig.face_size_ratio >= _FACE_REACTION_AREA):
        conf = min(1.0, sig.face_hit_rate * (sig.face_size_ratio / _FACE_REACTION_AREA))
        reasons.append(f"face_hit:{sig.face_hit_rate:.2f} face_size:{sig.face_size_ratio:.3f}")
        return SceneType.FACE_REACTION, round(conf, 2), reasons

    # 3. Conversation: multi-face or persistent medium face
    if sig.multi_face_rate >= _FACE_CONVERSATION:
        conf = min(1.0, sig.multi_face_rate * 2)
        reasons.append(f"multi_face:{sig.multi_face_rate:.2f}")
        return SceneType.CONVERSATION, round(conf, 2), reasons

    # 4. Active Gameplay: high motion, no dominant face
    if sig.motion_mean >= _MOTION_HIGH and sig.face_size_ratio < _FACE_REACTION_AREA:
        conf = min(1.0, (sig.motion_mean - _MOTION_HIGH) / _MOTION_HIGH + 0.6)
        reasons.append(f"motion:{sig.motion_mean:.1f}")
        return SceneType.ACTIVE_GAMEPLAY, round(conf, 2), reasons

    # 5. Low motion → Menu or Static
    if sig.motion_mean < _MOTION_LOW and sig.face_size_ratio < _FACE_REACTION_AREA:
        if sig.edge_density >= _EDGE_MENU:
            conf = min(1.0, (sig.edge_density / _EDGE_MENU) * 0.6)
            reasons.append(f"edge:{sig.edge_density:.1f} motion:{sig.motion_mean:.1f}")
            return SceneType.MENU_OR_UI, round(conf, 2), reasons
        conf = 0.55
        reasons.append(f"low_motion:{sig.motion_mean:.1f}")
        return SceneType.STATIC_GAMEPLAY, round(conf, 2), reasons

    # 6. Medium motion → Static Gameplay
    if sig.motion_mean < _MOTION_HIGH:
        conf = 0.50
        reasons.append(f"medium_motion:{sig.motion_mean:.1f}")
        return SceneType.STATIC_GAMEPLAY, round(conf, 2), reasons

    # 7. Unknown
    reasons.append(f"no_match: motion={sig.motion_mean:.1f} face={sig.face_hit_rate:.2f}")
    return SceneType.UNKNOWN, 0.30, reasons


def _scene_to_fraction(scene_type: SceneType) -> float:
    return _SCENE_SPLIT_FRACTION.get(scene_type, 0.60)


def _merge_similar_segments(
    segments: list[SceneSegment],
    min_duration_s: float = 1.5,
) -> list[SceneSegment]:
    """Merge consecutive same-type segments shorter than min_duration_s."""
    if len(segments) <= 1:
        return segments

    merged: list[SceneSegment] = [segments[0]]
    for seg in segments[1:]:
        prev = merged[-1]
        if (seg.scene_type == prev.scene_type
                or seg.duration_s < min_duration_s
                or prev.duration_s < min_duration_s):
            # Extend previous
            merged[-1] = SceneSegment(
                start_s=prev.start_s,
                end_s=seg.end_s,
                scene_type=prev.scene_type,
                confidence=round((prev.confidence + seg.confidence) / 2, 2),
                recommended_split_fraction=prev.recommended_split_fraction,
                reason_codes=prev.reason_codes,
                signals=prev.signals,
            )
        else:
            merged.append(seg)

    return merged
