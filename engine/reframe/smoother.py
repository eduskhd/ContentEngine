"""Trajectory smoothing utilities for framing x_offset values."""


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
