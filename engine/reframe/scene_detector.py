"""Scene-cut detection using PySceneDetect 0.7+.

Detects hard and adaptive cuts within a clip window of a proxy or source
video.  Results feed the planner so tracking resets at every scene boundary.
"""
from __future__ import annotations
from typing import NamedTuple


class SceneBoundary(NamedTuple):
    start_s: float
    end_s: float


def detect_scenes(
    video_path: str,
    clip_start: float,
    clip_end: float,
    threshold: float = 27.0,
    adaptive: bool = False,
) -> list[SceneBoundary]:
    """Return scene intervals within [clip_start, clip_end].

    Uses ContentDetector by default (good for hard cuts) or AdaptiveDetector
    when adaptive=True (better for gradual transitions / dissolves).

    Falls back to a single full-span interval on any error.
    """
    try:
        from scenedetect import open_video, SceneManager
        from scenedetect import ContentDetector, AdaptiveDetector

        video = open_video(video_path, start_time=clip_start, end_time=clip_end)
        mgr = SceneManager()
        if adaptive:
            mgr.add_detector(AdaptiveDetector(adaptive_threshold=3.0))
        else:
            mgr.add_detector(ContentDetector(threshold=threshold))

        mgr.detect_scenes(video, show_progress=False)
        raw = mgr.get_scene_list()

        if not raw:
            return [SceneBoundary(clip_start, clip_end)]

        scenes: list[SceneBoundary] = []
        for start_tc, end_tc in raw:
            scenes.append(SceneBoundary(
                start_s=round(start_tc.get_seconds(), 3),
                end_s=round(end_tc.get_seconds(), 3),
            ))
        return scenes

    except Exception:
        return [SceneBoundary(clip_start, clip_end)]


def scene_count(
    video_path: str,
    clip_start: float,
    clip_end: float,
    threshold: float = 27.0,
) -> int:
    """Return number of detected scenes (fast, no frame data)."""
    return len(detect_scenes(video_path, clip_start, clip_end, threshold))
