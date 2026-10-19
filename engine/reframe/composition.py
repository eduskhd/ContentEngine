"""Auto Composition Decision Engine for Smart Reframing V1.

Given a ContentAnalysis (computed from detector outputs), selects one of four
composition modes and returns a CompositionDecision with full reasoning.

Modes
-----
FACE_FOCUS
    Primary subject is a face that dominates the frame.  Virtual camera
    follows the face with headroom margin.  Best for "just chatting", IRL,
    reactions.

ACTION_FOCUS
    No dominant face (or subject is a body/person, not face).  Camera targets
    the detected person or defaults to center.  Best for gameplay with a
    full-body shot, sports, action.

SPLIT_LAYOUT
    Source has a distinguishable facecam overlay AND a gameplay/main region.
    Output: top 60% = gameplay, bottom 40% = facecam.  Only activated when
    facecam confidence is high enough.

SPEAKER_TRACKING
    Multiple faces detected; no single dominant face.  Camera tracks the
    current speaker using hysteresis to prevent rapid switching.

CENTER
    Fallback: no reliable detection. Use geometric center crop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CompositionMode(Enum):
    FACE_FOCUS       = "face_focus"
    ACTION_FOCUS     = "action_focus"
    SPLIT_LAYOUT     = "split_layout"
    SPEAKER_TRACKING = "speaker_tracking"
    CENTER           = "center"


@dataclass
class ContentAnalysis:
    """Aggregated analysis from detector + tracker outputs for one clip/scene."""
    # Face detection
    face_count_avg: float = 0.0        # average faces per frame
    face_area_ratio: float = 0.0       # avg face area / frame area
    face_hit_rate: float = 0.0         # fraction of frames with ≥1 face
    multi_face_rate: float = 0.0       # fraction of frames with ≥2 faces

    # Person detection
    person_hit_rate: float = 0.0       # fraction of frames with ≥1 person

    # Facecam
    has_facecam: bool = False
    facecam_confidence: float = 0.0
    facecam_corner: str = ""           # "TL"|"TR"|"BL"|"BR"
    facecam_region: Optional[tuple] = None   # (x, y, w, h) in source coords

    # Motion / dynamics
    motion_level: float = 0.0          # 0=static, 1=highly dynamic
    scene_count: int = 1               # number of detected scene cuts

    # Content hint from upstream
    content_hint: str = "auto"         # "talking_head"|"conversation"|"action"|"gameplay"|"auto"

    # Detection model
    model_used: str = "none"


@dataclass
class CompositionDecision:
    """Output of the decision engine for one clip/scene."""
    mode: CompositionMode
    x_offset: int                  # primary crop x_offset in source pixels
    confidence: float              # 0–1
    reason: str                    # human-readable explanation
    fallback: bool = False

    # SPLIT_LAYOUT regions (source pixels)
    main_region: Optional[tuple] = None       # (x, y, w, h) gameplay
    secondary_region: Optional[tuple] = None  # (x, y, w, h) facecam

    # SPEAKER_TRACKING
    speaker_offsets: list = field(default_factory=list)  # [(time_s, x_offset)]


# ── Thresholds (tunable) ──────────────────────────────────────────────────────

_FACE_HIT_THRESHOLD     = 0.30   # need face in ≥30% of frames for FACE_FOCUS
_MULTI_FACE_THRESHOLD   = 0.35   # ≥35% multi-face frames → SPEAKER_TRACKING
_PERSON_HIT_THRESHOLD   = 0.25   # need person in ≥25% of frames for ACTION_FOCUS
_FACECAM_CONF_THRESHOLD = 0.50   # facecam confidence needed for SPLIT_LAYOUT
_FACE_AREA_MAX_SPLIT    = 0.20   # face area < 20% → subject not filling frame (has gameplay)


def decide(
    analysis: ContentAnalysis,
    center_offset: int,
    src_w: int,
    src_h: int,
) -> CompositionDecision:
    """Select composition mode and return a CompositionDecision.

    Decision priority:
      1. SPLIT_LAYOUT  — when reliable facecam + gameplay coexist
      2. SPEAKER_TRACKING — when multiple speakers are frequently visible
      3. FACE_FOCUS    — single dominant face
      4. ACTION_FOCUS  — body/person without dominant face
      5. CENTER        — no reliable detections
    """

    # ── 1. SPLIT_LAYOUT ───────────────────────────────────────────────────────
    if (analysis.has_facecam
            and analysis.facecam_confidence >= _FACECAM_CONF_THRESHOLD
            and analysis.face_area_ratio < _FACE_AREA_MAX_SPLIT  # not a full-face shot
            and analysis.content_hint not in ("talking_head",)):

        fc = analysis.facecam_region
        if fc is not None:
            fx, fy, fw, fh = fc
            # Gameplay region: full frame minus facecam quadrant row/column
            # Compute gameplay crop to exclude facecam corner
            gp_region = _gameplay_region(fx, fy, fw, fh, src_w, src_h, analysis.facecam_corner)
            return CompositionDecision(
                mode=CompositionMode.SPLIT_LAYOUT,
                x_offset=center_offset,
                confidence=analysis.facecam_confidence,
                reason=(
                    f"Facecam detected at {analysis.facecam_corner} corner "
                    f"(conf={analysis.facecam_confidence:.2f}). "
                    "SPLIT_LAYOUT: gameplay top 60%, facecam bottom 40%."
                ),
                main_region=gp_region,
                secondary_region=(fx, fy, fw, fh),
            )

    # ── 2. SPEAKER_TRACKING ───────────────────────────────────────────────────
    if (analysis.multi_face_rate >= _MULTI_FACE_THRESHOLD
            or analysis.content_hint == "conversation"):
        return CompositionDecision(
            mode=CompositionMode.SPEAKER_TRACKING,
            x_offset=center_offset,
            confidence=analysis.face_hit_rate,
            reason=(
                f"Multiple faces in {analysis.multi_face_rate:.0%} of frames. "
                "SPEAKER_TRACKING: follows dominant speaker with hysteresis."
            ),
        )

    # ── 3. FACE_FOCUS ─────────────────────────────────────────────────────────
    if (analysis.face_hit_rate >= _FACE_HIT_THRESHOLD
            or analysis.content_hint in ("talking_head", "webcam")):
        return CompositionDecision(
            mode=CompositionMode.FACE_FOCUS,
            x_offset=center_offset,
            confidence=analysis.face_hit_rate,
            reason=(
                f"Face detected in {analysis.face_hit_rate:.0%} of frames "
                f"(area ratio {analysis.face_area_ratio:.2%}). "
                "FACE_FOCUS: centered on face with head-room margin."
            ),
        )

    # ── 4. ACTION_FOCUS ───────────────────────────────────────────────────────
    if (analysis.person_hit_rate >= _PERSON_HIT_THRESHOLD
            or analysis.content_hint in ("action", "gameplay")
            or analysis.motion_level > 0.5):
        return CompositionDecision(
            mode=CompositionMode.ACTION_FOCUS,
            x_offset=center_offset,
            confidence=analysis.person_hit_rate,
            reason=(
                f"Person detected in {analysis.person_hit_rate:.0%} of frames. "
                f"Motion level {analysis.motion_level:.2f}. "
                "ACTION_FOCUS: centers on detected person or action region."
            ),
        )

    # ── 5. CENTER fallback ────────────────────────────────────────────────────
    return CompositionDecision(
        mode=CompositionMode.CENTER,
        x_offset=center_offset,
        confidence=0.0,
        reason=(
            "No reliable face or person detection. "
            f"face_hit_rate={analysis.face_hit_rate:.2f}, "
            f"person_hit_rate={analysis.person_hit_rate:.2f}. "
            "CENTER: geometric center crop fallback."
        ),
        fallback=True,
    )


def _gameplay_region(
    fc_x: int, fc_y: int, fc_w: int, fc_h: int,
    src_w: int, src_h: int,
    corner: str,
) -> tuple[int, int, int, int]:
    """Compute gameplay crop region that excludes the facecam corner.

    Returns (x, y, w, h) of the gameplay area.
    Typically this is the full-width frame minus the horizontal strip
    occupied by the facecam — the layout engine will then scale this
    to the top portion of the 9:16 output.
    """
    # Simple approach: exclude the row/column occupied by the facecam
    if corner in ("BL", "BR"):
        # Facecam is at bottom: gameplay = top strip
        return (0, 0, src_w, fc_y)
    else:
        # Facecam is at top: gameplay = bottom strip
        return (0, fc_y + fc_h, src_w, src_h - fc_y - fc_h)


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


# ── V1.1: Optimal gameplay region ─────────────────────────────────────────────

def _optimal_gameplay_region(
    fc_x: int, fc_y: int, fc_w: int, fc_h: int,
    src_w: int, src_h: int,
    corner: str,
    top_output_h: int = 1152,
    output_w: int = 1080,
    safety_margin_frac: float = 0.15,
    hud_regions=None,
) -> tuple[int, int, int, int]:
    """Select the gameplay region that maximises source content preserved in SPLIT_LAYOUT.

    Uses a scale-fill+crop model: we score each candidate by the fraction of the
    original source frame that will be visible after scaling to fill the target
    gameplay area and then center-cropping to exact dimensions.

    Returns (x, y, w, h) in source pixels.
    """
    margin = int(max(fc_w, fc_h) * safety_margin_frac)

    # Expanded facecam exclusion zone
    exc_x1 = max(0, fc_x - margin)
    exc_y1 = max(0, fc_y - margin)
    exc_x2 = min(src_w, fc_x + fc_w + margin)
    exc_y2 = min(src_h, fc_y + fc_h + margin)

    # Candidate regions: (name, x, y, w, h)
    candidates: list[tuple[str, int, int, int, int]] = [
        ("full", 0, 0, src_w, src_h),
    ]

    rw_right = src_w - exc_x2
    if rw_right >= src_w * 0.25:
        candidates.append(("right", exc_x2, 0, rw_right, src_h))

    rw_left = exc_x1
    if rw_left >= src_w * 0.25:
        candidates.append(("left", 0, 0, rw_left, src_h))

    rh_below = src_h - exc_y2
    if rh_below >= src_h * 0.25:
        candidates.append(("below", 0, exc_y2, src_w, rh_below))

    rh_above = exc_y1
    if rh_above >= src_h * 0.25:
        candidates.append(("above", 0, 0, src_w, rh_above))

    best: tuple[int, int, int, int] | None = None
    best_score = -1.0

    for name, rx, ry, rw, rh in candidates:
        if rw <= 0 or rh <= 0:
            continue

        # Scale needed to fill the target box (increase approach)
        scale = max(output_w / rw, top_output_h / rh)
        # Source pixels visible through the target viewport
        visible_src_w = output_w / scale
        visible_src_h = top_output_h / scale
        content_frac = (visible_src_w * visible_src_h) / (rw * rh)

        # Fraction of full source frame covered by this region
        area_frac = (rw * rh) / (src_w * src_h)

        # Mild bonus for regions that exclude the facecam
        facecam_bonus = 0.0 if name == "full" else 0.05

        # HUD penalty: discount candidates that crop out important HUD elements
        hud_pen = 0.0
        if hud_regions:
            from engine.reframe.hud_protector import hud_penalty
            hud_pen = hud_penalty((rx, ry, rw, rh), hud_regions, src_w, src_h)

        score = content_frac * 0.6 + area_frac * 0.3 + facecam_bonus * 0.1 - hud_pen * 0.25

        if score > best_score:
            best_score = score
            best = (rx, ry, rw, rh)

    return best if best is not None else (0, 0, src_w, src_h)


def decide_v11(
    analysis: ContentAnalysis,
    center_offset: int,
    src_w: int,
    src_h: int,
    top_output_h: int = 1152,
    output_w: int = 1080,
) -> CompositionDecision:
    """V1.1 decision engine — uses optimal gameplay region for SPLIT_LAYOUT.

    All modes except SPLIT_LAYOUT fall through to the original decide().
    SPLIT_LAYOUT now uses _optimal_gameplay_region() which selects the
    candidate that maximises source content in the output, avoiding the
    vertical-stretch distortion of the V1 horizontal-strip approach.
    """
    if (analysis.has_facecam
            and analysis.facecam_confidence >= _FACECAM_CONF_THRESHOLD
            and analysis.face_area_ratio < _FACE_AREA_MAX_SPLIT
            and analysis.content_hint not in ("talking_head",)):

        fc = analysis.facecam_region
        if fc is not None:
            fx, fy, fw, fh = fc

            gp_region = _optimal_gameplay_region(
                fx, fy, fw, fh, src_w, src_h, analysis.facecam_corner,
                top_output_h=top_output_h, output_w=output_w,
            )
            gx, gy, gw, gh = gp_region

            if gw > 0 and gh > 0:
                scale = max(output_w / gw, top_output_h / gh)
                visible_src_w = output_w / scale
                visible_src_h = top_output_h / scale
                content_pct = visible_src_w * visible_src_h / (gw * gh) * 100.0

                return CompositionDecision(
                    mode=CompositionMode.SPLIT_LAYOUT,
                    x_offset=center_offset,
                    confidence=analysis.facecam_confidence,
                    reason=(
                        f"Facecam in {analysis.facecam_corner} corner "
                        f"(conf={analysis.facecam_confidence:.2f}). "
                        f"V1.1 SPLIT_LAYOUT: gameplay region ({gw}x{gh} at {gx},{gy}), "
                        f"scale-fill+crop preserving {content_pct:.0f}% of region content."
                    ),
                    main_region=gp_region,
                    secondary_region=(fx, fy, fw, fh),
                )

    # All other modes: delegate to V1 decide()
    return decide(analysis, center_offset, src_w, src_h)


def describe(decision: CompositionDecision) -> dict:
    """Return a JSON-serialisable summary of the decision."""
    return {
        "mode":             decision.mode.value,
        "x_offset":         decision.x_offset,
        "confidence":       round(_clamp01(decision.confidence), 3),
        "reason":           decision.reason,
        "fallback":         decision.fallback,
        "main_region":      decision.main_region,
        "secondary_region": decision.secondary_region,
    }


# ── V1.2: ConfidenceGate (dead zone for mode stability) ───────────────────────

class ConfidenceGate:
    """Hysteresis gate that prevents mode oscillation near the confidence threshold.

    Two thresholds:
      - entry_threshold : confidence needed to ACTIVATE SPLIT_LAYOUT
      - exit_threshold  : confidence below which SPLIT_LAYOUT is deactivated

    Entry > Exit creates a dead zone that prevents the Rickyedit-style
    oscillation where confidence hovers at ≈0.48–0.52.

    Default: entry=0.55, exit=0.45 (±0.05 around the base threshold 0.50).
    """

    def __init__(
        self,
        entry_threshold: float = 0.55,
        exit_threshold: float = 0.45,
    ) -> None:
        if entry_threshold <= exit_threshold:
            raise ValueError("entry_threshold must be > exit_threshold")
        self.entry_threshold = entry_threshold
        self.exit_threshold  = exit_threshold
        self._active = False

    def reset(self) -> None:
        """Reset to inactive state (start of a new clip)."""
        self._active = False

    def update(self, confidence: float) -> bool:
        """Return True if SPLIT_LAYOUT should be active given the new confidence.

        Uses hysteresis: once active, stays active until confidence drops
        below exit_threshold; once inactive, needs entry_threshold to activate.
        """
        if self._active:
            if confidence < self.exit_threshold:
                self._active = False
        else:
            if confidence >= self.entry_threshold:
                self._active = True
        return self._active

    @property
    def is_active(self) -> bool:
        return self._active


# ── V1.2: Scene-aware composition decision ────────────────────────────────────

def decide_v12(
    analysis: ContentAnalysis,
    center_offset: int,
    src_w: int,
    src_h: int,
    scene_type: str = "unknown",
    confidence_gate: "ConfidenceGate | None" = None,
    split_fraction: float = 0.60,
    top_output_h: int | None = None,
    output_w: int = 1080,
    hud_regions=None,
) -> CompositionDecision:
    """V1.2 decision engine — scene-aware composition with dead zone stability.

    Improvements over V1.1:
      1. Scene-type override: FACE_REACTION / CONVERSATION scenes skip SPLIT_LAYOUT
         and use FACE_FOCUS even when facecam confidence is high.
      2. Dead zone (ConfidenceGate): prevents oscillation near the confidence threshold.
      3. Adaptive split fraction: passed in from scene_analyzer.adaptive_split_fraction().
      4. HUD-aware: the optimal gameplay region respects the split_fraction.

    Falls back to decide_v11() for all non-overridden paths.
    """
    from engine.reframe.scene_analyzer import SceneType

    # Compute target top_h from split_fraction
    target_h = 1920
    if top_output_h is None:
        top_output_h = int(target_h * split_fraction)
        top_output_h = top_output_h - (top_output_h % 2)   # ensure even

    # ── Scene-type overrides ─────────────────────────────────────────────────
    scene_lower = scene_type.lower()
    is_face_dominant = scene_lower in ("face_reaction", "conversation")

    if is_face_dominant:
        # Face-dominated scenes: suppress facecam so SPLIT_LAYOUT is never chosen
        override = ContentAnalysis(
            face_count_avg=analysis.face_count_avg,
            face_area_ratio=analysis.face_area_ratio,
            face_hit_rate=analysis.face_hit_rate,
            multi_face_rate=analysis.multi_face_rate,
            person_hit_rate=analysis.person_hit_rate,
            has_facecam=False,        # prevent SPLIT_LAYOUT from activating
            facecam_confidence=0.0,
            content_hint=analysis.content_hint,
            motion_level=analysis.motion_level,
        )
        return decide(override, center_offset, src_w, src_h)

    # ── Confidence gate (dead zone) ──────────────────────────────────────────
    gate = confidence_gate
    facecam_conf = analysis.facecam_confidence if analysis.has_facecam else 0.0

    if gate is not None:
        split_layout_allowed = gate.update(facecam_conf)
    else:
        split_layout_allowed = facecam_conf >= _FACECAM_CONF_THRESHOLD

    if (split_layout_allowed
            and analysis.has_facecam
            and analysis.face_area_ratio < _FACE_AREA_MAX_SPLIT
            and analysis.content_hint not in ("talking_head",)):

        fc = analysis.facecam_region
        if fc is not None:
            fx, fy, fw, fh = fc
            gp_region = _optimal_gameplay_region(
                fx, fy, fw, fh, src_w, src_h, analysis.facecam_corner,
                top_output_h=top_output_h, output_w=output_w,
                hud_regions=hud_regions,
            )
            gx, gy, gw, gh = gp_region
            if gw > 0 and gh > 0:
                scale = max(output_w / gw, top_output_h / gh)
                visible_src_w = output_w / scale
                visible_src_h = top_output_h / scale
                content_pct = visible_src_w * visible_src_h / (gw * gh) * 100.0
                hud_note = f", hud_regions={len(hud_regions)}" if hud_regions else ""

                return CompositionDecision(
                    mode=CompositionMode.SPLIT_LAYOUT,
                    x_offset=center_offset,
                    confidence=min(1.0, facecam_conf),
                    reason=(
                        f"V1.2 SPLIT_LAYOUT [scene={scene_type}]: "
                        f"gameplay region ({gw}x{gh} at {gx},{gy}), "
                        f"split={split_fraction:.0%}, "
                        f"scale-fill+crop preserving {content_pct:.0f}% content"
                        f"{hud_note}."
                    ),
                    main_region=gp_region,
                    secondary_region=(fx, fy, fw, fh),
                )

    # Fall through: use V1.1 decide (which falls to V1 decide for non-split modes)
    return decide_v11(analysis, center_offset, src_w, src_h,
                      top_output_h=top_output_h, output_w=output_w)
