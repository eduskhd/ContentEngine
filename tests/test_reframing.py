"""Tests for Smart Reframing Engine V1 — 18 tests (T01–T18)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pytest


# ── T01 — smooth_ema bounds ───────────────────────────────────────────────────

def test_T01_smooth_ema_bounded():
    from engine.reframe.smoother import smooth_ema
    values = [100.0, 400.0, 200.0, 350.0]
    result = smooth_ema(values, alpha=0.3)
    assert len(result) == len(values)
    assert result[0] == values[0]
    # EMA is a convex combination so must stay within [min, max] of inputs
    lo, hi = min(values), max(values)
    assert all(lo <= v <= hi for v in result)


# ── T02 — clamp_offset bounds ─────────────────────────────────────────────────

def test_T02_clamp_offset_stays_in_range():
    from engine.reframe.smoother import clamp_offset
    src_w, crop_w = 1920, 607
    assert clamp_offset(-100, src_w, crop_w) == 0
    assert clamp_offset(9999, src_w, crop_w) == src_w - crop_w
    mid = 660
    assert clamp_offset(mid, src_w, crop_w) == mid


# ── T03 — TemporalSmoother hysteresis suppresses small moves ─────────────────

def test_T03_hysteresis_suppresses_small_move():
    from engine.reframe.smoother import TemporalSmoother
    sm = TemporalSmoother(hysteresis_px=50, min_dwell_s=0.0, max_velocity_pxs=9999, alpha=1.0)
    sm.reset(center_offset=400)
    x0 = sm.update(400.0, 0.0, 1920, 607)
    # Move of 20px — below hysteresis threshold of 50px
    x1 = sm.update(420.0, 0.5, 1920, 607)
    assert x1 == x0, "Small move within hysteresis zone must not change committed position"


# ── T04 — TemporalSmoother commits move exceeding hysteresis ─────────────────

def test_T04_hysteresis_allows_large_move():
    from engine.reframe.smoother import TemporalSmoother
    sm = TemporalSmoother(hysteresis_px=30, min_dwell_s=0.0, max_velocity_pxs=9999, alpha=1.0)
    sm.reset(center_offset=400)
    sm.update(400.0, 0.0, 1920, 607)
    # Move of 200px — far exceeds hysteresis of 30px
    x1 = sm.update(600.0, 1.0, 1920, 607)
    assert x1 > 400, "Large move must be committed and reflected in output"


# ── T05 — TemporalSmoother None holds last position ──────────────────────────

def test_T05_lost_target_hold():
    from engine.reframe.smoother import TemporalSmoother
    sm = TemporalSmoother(hysteresis_px=0, min_dwell_s=0.0, max_velocity_pxs=9999,
                          alpha=1.0, lost_hold_s=10.0)
    sm.reset(center_offset=400)
    x0 = sm.update(700.0, 0.0, 1920, 607)
    # No detection — within lost_hold_s window
    x1 = sm.update(None, 0.5, 1920, 607)
    assert x1 == x0, "Within lost_hold_s, None detection must hold last valid position"


# ── T06 — TemporalSmoother drifts toward center after lost_hold_s ────────────

def test_T06_lost_target_drift_to_center():
    from engine.reframe.smoother import TemporalSmoother
    sm = TemporalSmoother(hysteresis_px=0, min_dwell_s=0.0, max_velocity_pxs=9999,
                          alpha=0.5, lost_hold_s=0.1)
    sm.reset(center_offset=656)
    sm.update(1200.0, 0.0, 1920, 607)   # initialise far from center
    # After lost_hold_s passes, repeated None updates should move toward center
    for step in range(10):
        sm.update(None, 1.0 + step * 0.5, 1920, 607)
    final = sm.update(None, 10.0, 1920, 607)
    assert final < 1200, "After lost_hold_s, position must drift toward center, not stay at 1200"


# ── T07 — FACE_FOCUS when face_hit_rate >= 0.30 ──────────────────────────────

def test_T07_face_focus_selected():
    from engine.reframe import composition as comp
    analysis = comp.ContentAnalysis(face_hit_rate=0.55, face_area_ratio=0.08)
    decision = comp.decide(analysis, center_offset=656, src_w=1920, src_h=1080)
    assert decision.mode == comp.CompositionMode.FACE_FOCUS


# ── T08 — CENTER fallback when all detections are zero ───────────────────────

def test_T08_center_fallback():
    from engine.reframe import composition as comp
    analysis = comp.ContentAnalysis()  # all zeros / False
    decision = comp.decide(analysis, center_offset=656, src_w=1920, src_h=1080)
    assert decision.mode == comp.CompositionMode.CENTER
    assert decision.fallback is True


# ── T09 — SPEAKER_TRACKING when multi_face_rate >= 0.35 ─────────────────────

def test_T09_speaker_tracking():
    from engine.reframe import composition as comp
    analysis = comp.ContentAnalysis(face_hit_rate=0.8, multi_face_rate=0.50, face_area_ratio=0.06)
    decision = comp.decide(analysis, center_offset=656, src_w=1920, src_h=1080)
    assert decision.mode == comp.CompositionMode.SPEAKER_TRACKING


# ── T10 — SPLIT_LAYOUT when facecam present ──────────────────────────────────

def test_T10_split_layout_selected():
    from engine.reframe import composition as comp
    analysis = comp.ContentAnalysis(
        face_hit_rate=0.6,
        face_area_ratio=0.05,    # < _FACE_AREA_MAX_SPLIT (0.20)
        has_facecam=True,
        facecam_confidence=0.80,  # >= _FACECAM_CONF_THRESHOLD (0.50)
        facecam_corner="BR",
        facecam_region=(1500, 800, 300, 200),
    )
    decision = comp.decide(analysis, center_offset=656, src_w=1920, src_h=1080)
    assert decision.mode == comp.CompositionMode.SPLIT_LAYOUT
    assert decision.secondary_region == (1500, 800, 300, 200)


# ── T11 — detect_facecam returns None with no small faces ────────────────────

def test_T11_facecam_none_when_no_small_faces():
    from engine.reframe.facecam_detector import detect_facecam
    # Faces that are all large (> FACECAM_MAX_AREA_FRAC of 640*480 frame)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frames = [frame] * 5
    # Large face occupying 30% of frame area
    face_results = [[(10, 10, 300, 200)]] * 5   # area 60000 / 307200 ≈ 19.5% > 12%
    result = detect_facecam(frames, face_results)
    assert result is None


# ── T12 — detect_facecam finds BR facecam ────────────────────────────────────

def test_T12_facecam_detected_br_corner():
    from engine.reframe.facecam_detector import detect_facecam
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frames = [frame] * 8
    # Small face consistently in bottom-right corner: x>320, y>240, area small
    # 60x40 face at (540, 400): area 2400 / 307200 ≈ 0.78% — within [0.5%, 12%]
    face_results = [[(540, 400, 60, 40)]] * 8
    result = detect_facecam(frames, face_results)
    assert result is not None
    assert result.corner == "BR"
    assert result.confidence <= 1.0


# ── T13 — _compute_crop_filter: center crop when x_offset=None ───────────────

def test_T13_crop_filter_center():
    from engine.renderers.render_clip import _compute_crop_filter
    f = _compute_crop_filter(src_w=1920, src_h=1080, x_offset=None)
    # For 1920x1080 source, crop_w = int(1080 * 1080/1920) = 607
    # center_offset = (1920 - 607) // 2 = 656
    assert "crop=607:1080:656:0" in f or "scale=1080:1920" in f


# ── T14 — _compute_crop_filter: custom x_offset respected ───────────────────

def test_T14_crop_filter_custom_offset():
    from engine.renderers.render_clip import _compute_crop_filter
    f = _compute_crop_filter(src_w=1920, src_h=1080, x_offset=200)
    assert ":200:0" in f, f"Expected x_offset 200 in filter: {f}"


# ── T15 — _compute_split_layout_filter: contains vstack and crop ─────────────

def test_T15_split_layout_filter_structure():
    from engine.renderers.render_clip import _compute_split_layout_filter
    f = _compute_split_layout_filter(
        main_region=[0, 0, 1920, 720],
        secondary_region=[1540, 800, 380, 280],
        src_w=1920, src_h=1080,
    )
    assert "vstack" in f
    assert "crop" in f
    assert "[out]" in f


# ── T16 — _compute_split_layout_filter: clamps invalid regions ───────────────

def test_T16_split_layout_filter_clamps():
    from engine.renderers.render_clip import _compute_split_layout_filter
    # Regions larger than source — should not raise
    f = _compute_split_layout_filter(
        main_region=[-100, -50, 3000, 2000],
        secondary_region=[1900, 1000, 500, 300],
        src_w=1920, src_h=1080,
    )
    assert "vstack" in f   # filter built without error


# ── T17 — smart_reframing_enabled is False by default ────────────────────────

def test_T17_smart_reframing_disabled_by_default():
    from engine.config import CONFIG
    assert CONFIG.smart_reframing_enabled is False, (
        "smart_reframing_enabled must default to False to protect production renders"
    )


# ── T18 — plan_clip_v3 returns valid plan dict on synthetic proxy ─────────────

def test_T18_plan_clip_v3_synthetic_proxy():
    import tempfile, os
    try:
        import cv2
    except ImportError:
        pytest.skip("cv2 not available")

    # Write a tiny 8-frame synthetic proxy (320x180, 2fps)
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.close()
    try:
        w, h = 320, 180
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(tmp.name, fourcc, 2.0, (w, h))
        if not writer.isOpened():
            pytest.skip("cv2.VideoWriter could not open temp file")
        for i in range(8):
            frame = np.zeros((h, w, 3), dtype=np.uint8)
            # Draw a small "face" rectangle in a consistent corner
            cv2.rectangle(frame, (260, 130), (310, 170), (200, 180, 160), -1)
            writer.write(frame)
        writer.release()

        from engine.reframe.planner import plan_clip_v3
        plan = plan_clip_v3(tmp.name, 0.0, 4.0, src_w=1920, src_h=1080)

        assert isinstance(plan, dict)
        assert plan.get("version") == 3
        assert "composition_mode" in plan
        assert plan["composition_mode"] in (
            "face_focus", "action_focus", "split_layout", "speaker_tracking", "center"
        )
        assert "keypoints" in plan
        assert isinstance(plan["keypoints"], list)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
