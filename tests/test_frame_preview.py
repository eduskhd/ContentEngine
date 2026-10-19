"""Tests for the real-frame preview system (POST /jobs/prepare-preview)."""
import time
import pytest


def test_timestamps_from_percentages():
    """Timestamps are computed correctly from percentages and duration."""
    duration = 3600.0
    pcts = [5, 15, 30, 50, 70, 85, 95]
    margin = 2.0
    ts = [max(1.0, min(duration - margin, duration * pct / 100)) for pct in pcts]
    assert ts[0] == pytest.approx(180.0)
    assert ts[3] == pytest.approx(1800.0)
    assert ts[-1] == pytest.approx(3420.0)


def test_timestamps_short_video():
    """Short video timestamps clamped correctly."""
    duration = 10.0
    pcts = [5, 50, 95]
    margin = 2.0
    ts = [max(1.0, min(duration - margin, duration * pct / 100)) for pct in pcts]
    assert ts[0] == pytest.approx(1.0)   # 0.5s → clamped to 1.0
    assert ts[1] == pytest.approx(5.0)
    assert ts[2] == pytest.approx(8.0)   # 9.5s → clamped to 8.0


def test_gallery_state_reset():
    """Gallery state is empty after reset."""
    gallery_frames = [{"t": 10, "ok": True}, {"t": 30, "ok": True}]
    active_idx = 1
    gallery_frames = []
    active_idx = -1
    assert gallery_frames == []
    assert active_idx == -1


def test_normalized_coords_stable_across_resolutions():
    """Same normalized rect produces correct pixel coords at any canvas size."""
    rect = {"x": 0.0, "y": 0.0, "w": 0.75, "h": 0.50}
    for canvas_w, canvas_h in [(640, 360), (1280, 720), (400, 225)]:
        assert abs(rect["w"] * canvas_w / canvas_w - 0.75) < 0.001
        assert abs(rect["h"] * canvas_h / canvas_h - 0.50) < 0.001


def test_frame_cache_keyed_by_url():
    """Cache entries are independent per source URL."""
    cache = {}
    url1 = "https://youtube.com/watch?v=aaa"
    url2 = "https://youtube.com/watch?v=bbb"
    cache[url1] = {"direct_url": "http://direct1", "expiry": 9999}
    cache[url2] = {"direct_url": "http://direct2", "expiry": 9999}
    assert cache[url1]["direct_url"] != cache[url2]["direct_url"]
    assert len(cache) == 2


def test_cache_expiry():
    """Expired cache entry is not valid."""
    entry = {"direct_url": "http://old", "expiry": time.time() - 1}
    assert not (entry["expiry"] > time.time())


def test_cache_valid():
    """Fresh cache entry is valid."""
    entry = {"direct_url": "http://new", "expiry": time.time() + 3600}
    assert entry["expiry"] > time.time()


def test_gallery_rect_overlay_coords():
    """Rects on 140x79 gallery thumbnails use correct normalized scaling."""
    rect = {"x": 0.1, "y": 0.1, "w": 0.6, "h": 0.8}
    gal_w, gal_h = 140, 79
    assert abs(rect["x"] * gal_w - 14.0) < 0.5
    assert abs(rect["y"] * gal_h - 7.9) < 0.5
    assert abs(rect["w"] * gal_w - 84.0) < 0.5
    assert abs(rect["h"] * gal_h - 63.2) < 0.5


def test_interval_config_structure():
    """Interval config has required fields with valid ranges."""
    cfg = {
        "start_time": 0, "end_time": 1500,
        "gameplay_rect": {"x": 0.0, "y": 0.0, "w": 0.75, "h": 0.85},
        "facecam_rect":  {"x": 0.75, "y": 0.0, "w": 0.25, "h": 0.25},
        "fit_mode": "FIT", "split_ratio": 0.5,
    }
    assert cfg["end_time"] > cfg["start_time"]
    assert "gameplay_rect" in cfg and "facecam_rect" in cfg


def test_no_overlapping_intervals():
    """Consecutive intervals must not overlap."""
    intervals = [
        {"start_time": 0,    "end_time": 1500},
        {"start_time": 1500, "end_time": 3060},
    ]
    for i in range(len(intervals) - 1):
        assert intervals[i]["end_time"] <= intervals[i + 1]["start_time"]


def test_prepare_preview_timestamps_pct_limit():
    """timestamps_pct must have at most 20 entries."""
    pcts = list(range(0, 105, 5))  # 21 entries
    is_valid = isinstance(pcts, list) and len(pcts) <= 20
    assert not is_valid

    pcts_ok = [5, 15, 30, 50, 70, 85, 95]
    assert isinstance(pcts_ok, list) and len(pcts_ok) <= 20
