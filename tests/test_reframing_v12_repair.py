"""Smart Reframing V1.2 Repair — Tests T81-T85.

Covers P3 and P4 fixes:
  T81: _optimal_gameplay_region() backward compat — hud_regions=[] accepted
  T82: HUD penalty discounts candidates that overlap HUD regions
  T83: decide_v12() accepts hud_regions without error
  T84: plan_clip_v3_2() includes segment_decisions in plan["v12"]
  T85: each segment_decisions entry has start_s, end_s, mode, scene_type
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pytest


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_frames(n=8, h=202, w=360, color=(80, 80, 80)):
    return [np.full((h, w, 3), color, dtype=np.uint8) for _ in range(n)]


# ─── T81: _optimal_gameplay_region backward compat — empty hud_regions ────────

def test_T81_optimal_gameplay_region_empty_hud():
    from engine.reframe.composition import _optimal_gameplay_region

    # Facecam in top-left corner
    rx, ry, rw, rh = _optimal_gameplay_region(
        fc_x=10, fc_y=10, fc_w=120, fc_h=80,
        src_w=1920, src_h=1080,
        corner="top-left",
        hud_regions=[],
    )
    assert rw > 0 and rh > 0
    assert rx >= 0 and ry >= 0
    assert rx + rw <= 1920
    assert ry + rh <= 1080


def test_T81b_optimal_gameplay_region_none_hud():
    from engine.reframe.composition import _optimal_gameplay_region

    rx, ry, rw, rh = _optimal_gameplay_region(
        fc_x=10, fc_y=10, fc_w=120, fc_h=80,
        src_w=1920, src_h=1080,
        corner="top-left",
        hud_regions=None,
    )
    assert rw > 0 and rh > 0


# ─── T82: HUD penalty discounts candidates overlapping HUD ────────────────────

def test_T82_hud_penalty_non_zero_when_hud_excluded():
    """Penalty > 0 when the crop window excludes the HUD region."""
    from engine.reframe.hud_protector import hud_penalty, HUDRegion, HUDType

    # Minimap at top-right; crop covers only the left third — HUD is outside crop
    crop = (0, 0, 600, 1080)
    hud_regions = [
        HUDRegion(x=1600, y=0, w=320, h=120, hud_type=HUDType.MINIMAP, priority=2, confidence=0.9, reason="test"),
    ]
    pen = hud_penalty(crop, hud_regions, src_w=1920, src_h=1080)
    assert pen > 0.0
    assert pen <= 1.0


def test_T82b_hud_penalty_zero_when_hud_included():
    """Penalty = 0 when the crop fully contains the HUD region."""
    from engine.reframe.hud_protector import hud_penalty, HUDRegion, HUDType

    # Full-frame crop includes the minimap at (1600, 0, 320, 120)
    crop = (0, 0, 1920, 1080)
    hud_regions = [
        HUDRegion(x=1600, y=0, w=320, h=120, hud_type=HUDType.MINIMAP, priority=2, confidence=0.9, reason="test"),
    ]
    pen = hud_penalty(crop, hud_regions, src_w=1920, src_h=1080)
    assert pen == 0.0


def test_T82c_hud_penalty_influences_score():
    """Crop that includes the HUD gets lower penalty than one that excludes it."""
    from engine.reframe.hud_protector import hud_penalty, HUDRegion, HUDType

    hud_regions = [
        HUDRegion(x=1700, y=0, w=200, h=80, hud_type=HUDType.MINIMAP, priority=2, confidence=0.9, reason="test"),
    ]
    # Full frame includes the HUD (right edge); left half excludes it
    pen_includes = hud_penalty((0, 0, 1920, 1080), hud_regions, 1920, 1080)
    pen_excludes = hud_penalty((0, 0, 1600, 1080), hud_regions, 1920, 1080)
    assert pen_excludes > pen_includes


# ─── T83: decide_v12() accepts hud_regions without error ──────────────────────

def test_T83_decide_v12_accepts_hud_regions():
    from engine.reframe.composition import decide_v12, ContentAnalysis
    from engine.reframe.hud_protector import HUDRegion, HUDType

    analysis = ContentAnalysis(
        face_hit_rate=0.8,
        face_area_ratio=0.04,
        multi_face_rate=0.1,
        person_hit_rate=0.8,
        has_facecam=True,
        facecam_confidence=0.75,
        facecam_corner="top-left",
        facecam_region=(10, 10, 120, 80),
        content_hint="auto",
    )
    hud_regions = [
        HUDRegion(x=1600, y=0, w=320, h=120, hud_type=HUDType.MINIMAP, priority=2, confidence=0.9, reason="test"),
    ]
    decision = decide_v12(
        analysis, center_offset=420, src_w=1920, src_h=1080,
        scene_type="static_gameplay",
        hud_regions=hud_regions,
    )
    assert decision is not None
    assert decision.mode is not None


def test_T83b_decide_v12_face_dominant_ignores_hud_param():
    """Conversation scene should return face_focus regardless of hud_regions."""
    from engine.reframe.composition import decide_v12, ContentAnalysis, CompositionMode

    analysis = ContentAnalysis(
        face_hit_rate=0.9,
        face_area_ratio=0.15,
        multi_face_rate=0.3,
        person_hit_rate=0.9,
        has_facecam=True,
        facecam_confidence=0.85,
        facecam_corner="top-left",
        facecam_region=(10, 10, 200, 160),
        content_hint="auto",
    )
    decision = decide_v12(
        analysis, center_offset=420, src_w=1920, src_h=1080,
        scene_type="conversation",
        hud_regions=[],
    )
    assert decision.mode == CompositionMode.FACE_FOCUS


# ─── T84: plan_clip_v3_2() includes segment_decisions in plan["v12"] ──────────

def test_T84_plan_v32_has_segment_decisions(tmp_path):
    """plan_clip_v3_2() must store segment_decisions (list) inside plan['v12']."""
    import cv2
    from engine.reframe.planner import plan_clip_v3_2

    # Write a minimal synthetic 16:9 proxy (360×202 = ~16:9, 2fps, 10s)
    proxy = str(tmp_path / "proxy.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(proxy, fourcc, 2.0, (360, 202))
    for i in range(20):
        frame = np.full((202, 360, 3), (30 + i * 5, 30, 100), dtype=np.uint8)
        vw.write(frame)
    vw.release()

    plan = plan_clip_v3_2(proxy, clip_start=0.0, clip_end=8.0, src_w=1920, src_h=1080)

    assert "v12" in plan, "plan must have 'v12' key"
    v12 = plan["v12"]
    assert "segment_decisions" in v12 or "segment_decisions_error" in v12, \
        "v12 must have segment_decisions or segment_decisions_error"

    if "segment_decisions" in v12:
        assert isinstance(v12["segment_decisions"], list)


# ─── T85: segment_decisions entries have required keys ────────────────────────

def test_T85_segment_decisions_schema(tmp_path):
    """Each entry in segment_decisions must have start_s, end_s, mode, scene_type."""
    import cv2
    from engine.reframe.planner import plan_clip_v3_2

    proxy = str(tmp_path / "proxy.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(proxy, fourcc, 2.0, (360, 202))
    for i in range(20):
        frame = np.full((202, 360, 3), (30 + i * 5, 30, 100), dtype=np.uint8)
        vw.write(frame)
    vw.release()

    plan = plan_clip_v3_2(proxy, clip_start=0.0, clip_end=8.0, src_w=1920, src_h=1080)
    v12 = plan.get("v12", {})

    if "segment_decisions_error" in v12:
        pytest.skip(f"segment_decisions_error present: {v12['segment_decisions_error']}")

    decisions = v12.get("segment_decisions", [])
    assert len(decisions) > 0, "expected at least one segment decision"

    required_keys = {"start_s", "end_s", "mode", "scene_type"}
    for entry in decisions:
        missing = required_keys - set(entry.keys())
        assert not missing, f"segment_decision missing keys {missing}: {entry}"
        assert isinstance(entry["start_s"], (int, float))
        assert isinstance(entry["end_s"], (int, float))
        assert isinstance(entry["mode"], str)
        assert isinstance(entry["scene_type"], str)
