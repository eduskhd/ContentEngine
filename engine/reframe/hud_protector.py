"""HUD & UI Region Protector — Smart Reframing V1.2.

Detects regions of the frame that likely contain HUD (Heads-Up Display)
elements — minimap, health bars, score, mission text, etc. — and marks
them as protected so the composition engine avoids cropping them out.

Approach:
  - Scan corner and edge regions for persistent high-edge-density patches
  - Use frame-to-frame consistency: HUD elements persist across frames
  - Return HUDRegion objects with (x, y, w, h) in SOURCE frame coordinates

Designed to be fast: all computation uses numpy, sampled frames only.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class HUDType(Enum):
    MINIMAP         = "minimap"
    HEALTH_BAR      = "health_bar"
    SCORE           = "score"
    SUBTITLE        = "subtitle"
    MISSION_TEXT    = "mission_text"
    GENERIC_UI      = "generic_ui"
    CORNER_OVERLAY  = "corner_overlay"


@dataclass
class HUDRegion:
    """A detected region of the frame likely to contain HUD content."""
    x: int
    y: int
    w: int
    h: int
    hud_type: HUDType
    priority: float        # 0–1: how important it is to preserve this region
    confidence: float      # 0–1: detection confidence
    reason: str


# ── HUD zone definitions (relative to frame size) ───────────────────────────

# Standard HUD zones for typical gaming content (position, size as fraction of frame)
# Each zone is (x_frac, y_frac, w_frac, h_frac)
_HUD_ZONES = {
    "top_left":    (0.00, 0.00, 0.20, 0.12, HUDType.HEALTH_BAR,   0.8),
    "top_right":   (0.80, 0.00, 0.20, 0.12, HUDType.SCORE,         0.7),
    "bottom_left": (0.00, 0.85, 0.25, 0.15, HUDType.MINIMAP,       0.9),
    "bottom_right":(0.75, 0.85, 0.25, 0.15, HUDType.MINIMAP,       0.9),
    "bottom_bar":  (0.00, 0.90, 1.00, 0.10, HUDType.SUBTITLE,      0.6),
    "top_bar":     (0.00, 0.00, 1.00, 0.10, HUDType.MISSION_TEXT,  0.6),
}

_EDGE_HUD_THRESHOLD = 8.0    # edge density fraction (%) for HUD detection
_PERSISTENCE_THRESHOLD = 0.5  # must be present in >50% of sampled frames


def detect_hud_regions(
    frames: list[np.ndarray],
    face_results: list[list[tuple[int, int, int, int]]],
    src_w: int,
    src_h: int,
    sample_every: int = 3,
    min_edge_density: float = _EDGE_HUD_THRESHOLD,
) -> list[HUDRegion]:
    """Detect likely HUD regions in source frame coordinates.

    Parameters
    ----------
    frames : proxy BGR frames (at proxy resolution)
    face_results : face boxes per frame (to exclude facial regions from HUD search)
    src_w, src_h : source video resolution (for scaling output coordinates)
    sample_every : analyse every Nth frame (performance optimization)
    min_edge_density : minimum edge pixel fraction in a zone to flag as HUD

    Returns
    -------
    List of HUDRegion objects in source frame coordinates.
    """
    if not frames:
        return []

    try:
        import cv2
    except ImportError:
        return _fallback_corner_regions(src_w, src_h)

    fh, fw = frames[0].shape[:2]
    scale_x = src_w / max(1, fw)
    scale_y = src_h / max(1, fh)

    sampled = frames[::sample_every] if len(frames) > sample_every else frames

    # Per-zone edge density across sampled frames
    zone_edge_densities: dict[str, list[float]] = {z: [] for z in _HUD_ZONES}

    for frame in sampled:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)

        for zone_name, (xf, yf, wf, hf, htype, prio) in _HUD_ZONES.items():
            x1 = int(xf * fw)
            y1 = int(yf * fh)
            x2 = min(fw, int((xf + wf) * fw))
            y2 = min(fh, int((yf + hf) * fh))

            if x2 <= x1 or y2 <= y1:
                continue

            zone_patch = edges[y1:y2, x1:x2]
            edge_frac = float(np.mean(zone_patch > 0) * 100)
            zone_edge_densities[zone_name].append(edge_frac)

    # Identify persistent high-edge zones (likely HUD)
    hud_regions: list[HUDRegion] = []
    for zone_name, densities in zone_edge_densities.items():
        if not densities:
            continue

        mean_density = float(np.mean(densities))
        persistence = float(np.mean([d > min_edge_density for d in densities]))

        if persistence < _PERSISTENCE_THRESHOLD or mean_density < min_edge_density:
            continue

        xf, yf, wf, hf, hud_type, base_priority = _HUD_ZONES[zone_name]

        # Scale to source coordinates
        src_x = int(xf * src_w)
        src_y = int(yf * src_h)
        src_rw = int(wf * src_w)
        src_rh = int(hf * src_h)

        # Skip if this zone overlaps heavily with the primary facecam
        # (facecam itself is a "protected region" handled separately)

        confidence = min(1.0, persistence * (mean_density / (min_edge_density * 2)))

        hud_regions.append(HUDRegion(
            x=src_x, y=src_y, w=src_rw, h=src_rh,
            hud_type=hud_type,
            priority=base_priority,
            confidence=round(confidence, 2),
            reason=f"edge_density={mean_density:.1f}% persistence={persistence:.2f}",
        ))

    return hud_regions


def hud_penalty(
    gameplay_region: tuple[int, int, int, int],
    hud_regions: list[HUDRegion],
    src_w: int,
    src_h: int,
) -> float:
    """Compute a [0,1] penalty for how much HUD content is excluded by the gameplay crop.

    A penalty of 1.0 means a high-priority HUD region is fully outside the crop.
    A penalty of 0.0 means all HUD regions are fully inside the crop.
    """
    if not hud_regions:
        return 0.0

    gx, gy, gw, gh = gameplay_region
    total_weight = sum(r.priority * r.confidence for r in hud_regions)
    if total_weight <= 0:
        return 0.0

    penalty = 0.0
    for r in hud_regions:
        # Compute overlap between HUD region and gameplay crop
        ox1 = max(gx, r.x)
        oy1 = max(gy, r.y)
        ox2 = min(gx + gw, r.x + r.w)
        oy2 = min(gy + gh, r.y + r.h)

        if ox2 <= ox1 or oy2 <= oy1:
            # No overlap: HUD region fully outside gameplay crop
            weight = r.priority * r.confidence
            penalty += weight

    return min(1.0, penalty / total_weight)


def _fallback_corner_regions(src_w: int, src_h: int) -> list[HUDRegion]:
    """Return standard corner HUD regions when edge detection is unavailable."""
    regions = []
    # Bottom-left minimap (common in GTA, FPS games)
    regions.append(HUDRegion(
        x=0, y=int(src_h * 0.80), w=int(src_w * 0.22), h=int(src_h * 0.20),
        hud_type=HUDType.MINIMAP, priority=0.7, confidence=0.3,
        reason="fallback_corner_heuristic",
    ))
    # Top-left health (very common)
    regions.append(HUDRegion(
        x=0, y=0, w=int(src_w * 0.20), h=int(src_h * 0.10),
        hud_type=HUDType.HEALTH_BAR, priority=0.6, confidence=0.3,
        reason="fallback_corner_heuristic",
    ))
    return regions
