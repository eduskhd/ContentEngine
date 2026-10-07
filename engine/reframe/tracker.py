"""Simplified ByteTrack: IoU-based multi-object tracker.

Designed for 2fps proxy frames where Kalman prediction is unnecessary.
Handles:
  - IoU matching via Hungarian assignment (scipy)
  - Track persistence across brief occlusion gaps
  - Track ID stability for subject selection
"""
from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Track:
    track_id: int
    bbox: tuple[int, int, int, int]   # x, y, w, h in frame coords
    score: float
    class_id: int = 0
    hits: int = 1
    time_since_update: int = 0
    history: list[tuple[int, int, int, int]] = field(default_factory=list)

    @property
    def area(self) -> int:
        return self.bbox[2] * self.bbox[3]

    @property
    def center_x(self) -> float:
        return self.bbox[0] + self.bbox[2] / 2

    @property
    def center_y(self) -> float:
        return self.bbox[1] + self.bbox[3] / 2


class ByteTracker:
    """IoU-based multi-object tracker (ByteTrack-lite).

    Not a full ByteTrack implementation — no Kalman filter, no two-stage
    matching.  Sufficient for 2fps proxy analysis where inter-frame motion
    is small relative to bounding-box size.
    """

    def __init__(self, iou_threshold: float = 0.25, max_age: int = 4):
        self._tracks: list[Track] = []
        self._next_id: int = 1
        self.iou_threshold = iou_threshold
        self.max_age = max_age

    def reset(self) -> None:
        """Reset all tracks (call at scene boundaries)."""
        self._tracks.clear()
        self._next_id = 1

    def update(
        self,
        detections: list[tuple[int, int, int, int, float]],
        class_id: int = 0,
    ) -> list[Track]:
        """Process one frame of detections.

        detections: list of (x, y, w, h, score)
        Returns currently active tracks (time_since_update == 0).
        """
        # Age all existing tracks
        for t in self._tracks:
            t.time_since_update += 1

        if not detections:
            self._tracks = [t for t in self._tracks if t.time_since_update < self.max_age]
            return []

        det_arr = np.array([[d[0], d[1], d[2], d[3]] for d in detections], dtype=float)
        det_scores = [d[4] for d in detections]

        if not self._tracks:
            for box, score in zip(det_arr, det_scores):
                t = Track(self._next_id, tuple(int(v) for v in box), score, class_id)
                t.history.append(t.bbox)
                self._tracks.append(t)
                self._next_id += 1
        else:
            track_arr = np.array([t.bbox for t in self._tracks], dtype=float)
            iou_mat = _iou_matrix(track_arr, det_arr)
            matched, unmatched_t, unmatched_d = _match(iou_mat, self.iou_threshold)

            for t_idx, d_idx in matched:
                t = self._tracks[t_idx]
                t.bbox = tuple(int(v) for v in det_arr[d_idx])
                t.score = det_scores[d_idx]
                t.hits += 1
                t.time_since_update = 0
                t.history.append(t.bbox)

            for d_idx in unmatched_d:
                t = Track(
                    self._next_id,
                    tuple(int(v) for v in det_arr[d_idx]),
                    det_scores[d_idx],
                    class_id,
                )
                t.history.append(t.bbox)
                self._tracks.append(t)
                self._next_id += 1

        self._tracks = [t for t in self._tracks if t.time_since_update < self.max_age]
        return [t for t in self._tracks if t.time_since_update == 0]

    @property
    def active_tracks(self) -> list[Track]:
        return [t for t in self._tracks if t.time_since_update == 0]

    def largest_track(self) -> Track | None:
        """Return the active track with the largest bounding-box area."""
        active = self.active_tracks
        return max(active, key=lambda t: t.area) if active else None


# ── Internals ─────────────────────────────────────────────────────────────────

def _iou_matrix(boxes1: np.ndarray, boxes2: np.ndarray) -> np.ndarray:
    """Compute IOU matrix for two sets of (x, y, w, h) boxes."""
    b1 = np.column_stack([boxes1[:, 0], boxes1[:, 1],
                           boxes1[:, 0] + boxes1[:, 2],
                           boxes1[:, 1] + boxes1[:, 3]])
    b2 = np.column_stack([boxes2[:, 0], boxes2[:, 1],
                           boxes2[:, 0] + boxes2[:, 2],
                           boxes2[:, 1] + boxes2[:, 3]])
    iou = np.zeros((len(b1), len(b2)), dtype=float)
    a1 = (b1[:, 2] - b1[:, 0]) * (b1[:, 3] - b1[:, 1])
    a2 = (b2[:, 2] - b2[:, 0]) * (b2[:, 3] - b2[:, 1])
    for i, box in enumerate(b1):
        xx1 = np.maximum(box[0], b2[:, 0])
        yy1 = np.maximum(box[1], b2[:, 1])
        xx2 = np.minimum(box[2], b2[:, 2])
        yy2 = np.minimum(box[3], b2[:, 3])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou[i] = inter / (a1[i] + a2 - inter + 1e-6)
    return iou


def _match(
    iou_mat: np.ndarray,
    threshold: float,
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Hungarian assignment + threshold filtering."""
    from scipy.optimize import linear_sum_assignment

    if iou_mat.size == 0:
        return [], list(range(iou_mat.shape[0])), list(range(iou_mat.shape[1]))

    row_idx, col_idx = linear_sum_assignment(-iou_mat)
    matched, matched_t, matched_d = [], set(), set()

    for r, c in zip(row_idx, col_idx):
        if iou_mat[r, c] >= threshold:
            matched.append((r, c))
            matched_t.add(r)
            matched_d.add(c)

    unmatched_t = [i for i in range(iou_mat.shape[0]) if i not in matched_t]
    unmatched_d = [j for j in range(iou_mat.shape[1]) if j not in matched_d]
    return matched, unmatched_t, unmatched_d
