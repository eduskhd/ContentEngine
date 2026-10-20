"""Trajectory smoothing utilities for framing x_offset values.

Provides two levels of smoothing:
  - `smooth_ema()` / `clamp_offset()`: simple helpers used by plan_clip() v1/v2
  - `TemporalSmoother`: stateful class used by plan_clip_v3() with:
      * EMA dampening
      * Hysteresis dead-zone (suppress micro-jitter)
      * Min dwell time (hold position before committing to a new crop)
      * Max velocity (cap pixels-per-second camera movement)
      * Lost-target hold (maintain last valid position when tracking lost)
"""
from __future__ import annotations


# ── Simple helpers (backward-compatible) ─────────────────────────────────────

def smooth_ema(values: list[float], alpha: float = 0.3) -> list[float]:
    """Exponential moving average smoothing."""
    if not values:
        return []
    result = [values[0]]
    for v in values[1:]:
        result.append(alpha * v + (1.0 - alpha) * result[-1])
    return result


def clamp_offset(x_offset: float, src_w: int, crop_w: int) -> int:
    """Clamp crop x_offset so the crop window stays within the frame."""
    return int(max(0, min(x_offset, src_w - crop_w)))


# ── TemporalSmoother ──────────────────────────────────────────────────────────

class TemporalSmoother:
    """Stateful per-clip smoother for x_offset trajectories.

    Designed for 2fps proxy analysis but scales to any frame rate.

    Parameters
    ----------
    hysteresis_px : int
        Dead zone around current position.  Proposed moves smaller than this
        are ignored (suppresses micro-jitter from detection noise).
    min_dwell_s : float
        Minimum seconds to stay at a position before committing to a move.
        Prevents rapid scene-level flips when the subject briefly leaves frame.
    max_velocity_pxs : float
        Maximum pixels per second the virtual camera is allowed to move.
        Caps abrupt jumps; the camera catches up smoothly over multiple frames.
    alpha : float
        EMA smoothing factor (0 = no update, 1 = instant update).
    lost_hold_s : float
        Seconds to hold the last valid crop when no subject is detected.
        After this duration, fall back to center.
    """

    def __init__(
        self,
        hysteresis_px: int = 30,
        min_dwell_s: float = 0.5,
        max_velocity_pxs: float = 300.0,
        alpha: float = 0.25,
        lost_hold_s: float = 1.5,
    ) -> None:
        self.hysteresis_px = hysteresis_px
        self.min_dwell_s = min_dwell_s
        self.max_velocity_pxs = max_velocity_pxs
        self.alpha = alpha
        self.lost_hold_s = lost_hold_s

        # Internal state
        self._current: float | None = None      # current smoothed position
        self._committed: float | None = None    # last committed (post-hysteresis) position
        self._committed_at: float = 0.0         # timestamp when current position was committed
        self._last_detection_t: float = -999.0  # timestamp of last successful detection
        self._center: int = 0                   # fallback center offset

    def reset(self, center_offset: int = 0) -> None:
        """Reset state for a new clip or scene boundary."""
        self._current = None
        self._committed = None
        self._committed_at = 0.0
        self._last_detection_t = -999.0
        self._center = center_offset

    def update(
        self,
        proposed_x: float | None,
        timestamp: float,
        src_w: int,
        crop_w: int,
    ) -> int:
        """
        Process one frame's proposed offset.

        Parameters
        ----------
        proposed_x : float | None
            Raw x_offset from detector (None = no detection this frame).
        timestamp : float
            Absolute timestamp in seconds from clip start.
        src_w, crop_w : int
            Source/crop widths for clamping.

        Returns
        -------
        int
            Smoothed, hysteresis-filtered, velocity-limited x_offset.
        """
        center = (src_w - crop_w) // 2
        self._center = center

        if self._current is None:
            # Initialise to first valid detection or center
            init = proposed_x if proposed_x is not None else float(center)
            self._current = init
            self._committed = init
            self._committed_at = timestamp
            if proposed_x is not None:
                self._last_detection_t = timestamp
            return clamp_offset(init, src_w, crop_w)

        if proposed_x is not None:
            self._last_detection_t = timestamp
            # Apply EMA
            ema = self.alpha * proposed_x + (1.0 - self.alpha) * self._current
        else:
            # No detection: hold or gradually return to center after lost_hold_s
            time_since_detection = timestamp - self._last_detection_t
            if time_since_detection > self.lost_hold_s:
                # Slowly drift back to center
                ema = self.alpha * float(center) + (1.0 - self.alpha) * self._current
            else:
                # Hold current position
                ema = self._current

        # Velocity limit: cap how fast the offset can change per frame
        dt = timestamp - self._committed_at
        if dt > 0:
            max_move = self.max_velocity_pxs * dt
            delta = ema - self._current
            if abs(delta) > max_move:
                ema = self._current + max_move * (1 if delta > 0 else -1)

        self._current = ema

        # Hysteresis: only commit if move exceeds dead zone
        committed = self._committed if self._committed is not None else ema
        if abs(ema - committed) < self.hysteresis_px:
            return clamp_offset(committed, src_w, crop_w)

        # Min dwell time: don't commit too frequently
        if (timestamp - self._committed_at) < self.min_dwell_s:
            return clamp_offset(committed, src_w, crop_w)

        # Commit new position
        self._committed = ema
        self._committed_at = timestamp
        return clamp_offset(ema, src_w, crop_w)

    def finalize(self, src_w: int, crop_w: int) -> int:
        """Return final committed offset (call after processing all frames)."""
        if self._committed is not None:
            return clamp_offset(self._committed, src_w, crop_w)
        return (src_w - crop_w) // 2
