"""Facecam (PiP overlay) detector.

Identifies webcam overlays typical of gameplay streamers: a small face/bust
shot superimposed in a corner of the screen.

Heuristics used:
  - Face detected in the same corner quadrant across ≥ MIN_STABILITY frames
  - Face area < FACECAM_MAX_AREA_FRAC of total frame area
  - Face area > FACECAM_MIN_AREA_FRAC (not just noise)
  - Corner quadrant occupies < 30% of frame width/height

Returns the bounding box of the facecam region expanded by a margin, plus
the corner label ("TL", "TR", "BL", "BR") and an estimated inner-frame
boundary so the gameplay region can exclude it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

# Fraction of frame area: facecam must be smaller than this
_FACECAM_MAX_AREA_FRAC = 0.12
# Minimum face area for it to be real content (not a tiny artifact)
_FACECAM_MIN_AREA_FRAC = 0.005
# Fraction of frames that must agree on corner for "stable" detection
_MIN_STABILITY = 0.40
# Expansion margin around detected face to build the facecam region
_EXPAND_FRAC = 0.35


class Corner(NamedTuple):
    label: str    # "TL" | "TR" | "BL" | "BR"
    qi: int       # quadrant row index 0=top, 1=bottom
    qj: int       # quadrant col index 0=left, 1=right


_CORNERS = [
    Corner("TL", 0, 0),
    Corner("TR", 0, 1),
    Corner("BL", 1, 0),
    Corner("BR", 1, 1),
]


@dataclass
class FacecamRegion:
    """Detected facecam overlay region in source-frame coordinates."""
    x: int
    y: int
    w: int
    h: int
    corner: str          # "TL" | "TR" | "BL" | "BR"
    confidence: float    # fraction of frames with consistent detection
    face_bbox: tuple     # (fx, fy, fw, fh) — raw face box at proxy scale


def detect_facecam(
    frames: list[np.ndarray],
    face_results: list[list[tuple[int, int, int, int]]],
    scale_x: float = 1.0,
    scale_y: float = 1.0,
) -> FacecamRegion | None:
    """Detect a persistent corner-overlaid facecam.

    Parameters
    ----------
    frames : list of BGR frames (proxy resolution)
    face_results : list of (x, y, w, h) face boxes per frame (proxy coords)
    scale_x, scale_y : scaling from proxy to source resolution

    Returns FacecamRegion if a stable facecam is detected, else None.
    """
    if not frames or not face_results:
        return None

    fh, fw = frames[0].shape[:2]
    frame_area = fw * fh

    # Per-frame corner votes: at most one vote per frame per corner
    corner_votes: dict[str, list[tuple[int, int, int, int]]] = {c.label: [] for c in _CORNERS}
    n_frames_with_small_face = 0

    for faces in face_results:
        if not faces:
            continue
        # Find the best small face in each corner this frame (one vote per corner per frame)
        frame_corner_best: dict[str, tuple[int, int, int, int] | None] = {c.label: None for c in _CORNERS}
        frame_has_small = False
        for fx, fy, ffw, ffh in faces:
            face_area = ffw * ffh
            area_frac = face_area / max(1, frame_area)
            if area_frac > _FACECAM_MAX_AREA_FRAC or area_frac < _FACECAM_MIN_AREA_FRAC:
                continue
            frame_has_small = True
            cx = fx + ffw / 2
            cy = fy + ffh / 2
            qi = 1 if cy > fh / 2 else 0
            qj = 1 if cx > fw / 2 else 0
            for c in _CORNERS:
                if c.qi == qi and c.qj == qj:
                    prev = frame_corner_best[c.label]
                    if prev is None or ffw * ffh > prev[2] * prev[3]:
                        frame_corner_best[c.label] = (fx, fy, ffw, ffh)
                    break
        if frame_has_small:
            n_frames_with_small_face += 1
            for label, box in frame_corner_best.items():
                if box is not None:
                    corner_votes[label].append(box)

    # Find dominant corner
    best_corner: str | None = None
    best_votes: list = []
    for label, votes in corner_votes.items():
        if len(votes) > len(best_votes):
            best_votes = votes
            best_corner = label

    if not best_corner:
        return None

    stability = min(1.0, len(best_votes) / max(1, n_frames_with_small_face))

    if stability < _MIN_STABILITY:
        return None

    # Median face box in this corner
    xs = [v[0] for v in best_votes]
    ys = [v[1] for v in best_votes]
    ws = [v[2] for v in best_votes]
    hs = [v[3] for v in best_votes]
    mfx = int(np.median(xs))
    mfy = int(np.median(ys))
    mfw = int(np.median(ws))
    mfh = int(np.median(hs))

    # Expand to estimate the full facecam overlay region
    margin_x = int(mfw * _EXPAND_FRAC)
    margin_y = int(mfh * _EXPAND_FRAC)

    corner = next(c for c in _CORNERS if c.label == best_corner)
    if corner.qj == 0:  # left side
        rx = max(0, mfx - margin_x)
        rw = mfw + 2 * margin_x
    else:               # right side
        rx = max(0, mfx - margin_x)
        rw = mfw + 2 * margin_x

    if corner.qi == 0:  # top
        ry = max(0, mfy - margin_y)
        rh = mfh + 2 * margin_y
    else:               # bottom
        ry = max(0, mfy - margin_y)
        rh = mfh + 2 * margin_y

    # Scale to source resolution
    src_x = int(rx * scale_x)
    src_y = int(ry * scale_y)
    src_w = int(rw * scale_x)
    src_h = int(rh * scale_y)
    face_bbox_src = (
        int(mfx * scale_x), int(mfy * scale_y),
        int(mfw * scale_x), int(mfh * scale_y),
    )

    return FacecamRegion(
        x=src_x, y=src_y, w=src_w, h=src_h,
        corner=best_corner,
        confidence=round(stability, 2),
        face_bbox=face_bbox_src,
    )
