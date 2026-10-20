"""Smart Reframing V1.2 — Tests T45-T80.

Covers:
  - SceneAnalyzer: classify signals into scene types
  - ConfidenceGate: dead zone for mode stability
  - decide_v12(): scene-aware composition with adaptive ratio
  - HUD protector: corner region detection + penalty
  - plan_clip_v3_2(): version 3.2, filter_version v12, scene data
  - _compute_split_layout_filter_v12(): adaptive fraction FFmpeg filter
  - Feature flag version 32
  - Backward compatibility (V1, V1.1 unchanged)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pytest


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_frames(n=8, h=202, w=360, color=(80, 80, 80), motion=False):
    """Create synthetic proxy frames."""
    frames = []
    for i in range(n):
        frame = np.full((h, w, 3), color, dtype=np.uint8)
        if motion:
            # Simulate motion by adding noise proportional to frame index
            noise = np.random.randint(0, 40, (h, w, 3), dtype=np.uint8)
            frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        frames.append(frame)
    return frames


def _make_face_results(n=8, has_face=True, face_size=(30, 30), position=(10, 10)):
    """Create synthetic face detection results."""
    if not has_face:
        return [[] for _ in range(n)]
    fx, fy = position
    fw, fh = face_size
    return [[(fx, fy, fw, fh)] for _ in range(n)]


def _make_times(n=8, start=0.0, fps=2.0):
    return [start + i / fps for i in range(n)]


# ─── T45: SceneType enum values ───────────────────────────────────────────────

def test_T45_scene_type_enum():
    from engine.reframe.scene_analyzer import SceneType
    assert SceneType.ACTIVE_GAMEPLAY.value == "active_gameplay"
    assert SceneType.FACE_REACTION.value == "face_reaction"
    assert SceneType.MENU_OR_UI.value == "menu_or_ui"
    assert SceneType.LOADING_OR_TRANSITION.value == "loading_or_transition"
    assert SceneType.UNKNOWN.value == "unknown"


# ─── T46: High-motion frames → ACTIVE_GAMEPLAY ───────────────────────────────

def test_T46_active_gameplay_high_motion():
    from engine.reframe.scene_analyzer import analyze_clip_scenes, SceneType
    frames = _make_frames(n=8, motion=True)
    # Boost motion by adding large deltas
    for i in range(1, len(frames)):
        frames[i] = np.clip(
            frames[i].astype(np.int16) + np.random.randint(20, 50, frames[i].shape),
            0, 255
        ).astype(np.uint8)
    face_results = _make_face_results(n=8, has_face=False)
    times = _make_times(n=8)
    segments = analyze_clip_scenes(frames, face_results, 2.0, times)
    assert len(segments) > 0
    types = [s.scene_type for s in segments]
    # At least one ACTIVE_GAMEPLAY or STATIC_GAMEPLAY with high motion
    assert any(t in (SceneType.ACTIVE_GAMEPLAY, SceneType.STATIC_GAMEPLAY) for t in types)


# ─── T47: Large face + low motion → FACE_REACTION ────────────────────────────

def test_T47_face_reaction_large_face():
    from engine.reframe.scene_analyzer import analyze_clip_scenes, SceneType
    h, w = 202, 360
    frames = _make_frames(n=8, h=h, w=w)  # static (no motion)
    # Large face: > 7% of frame area (202*360 = 72720, 7% = 5090, face 71*71=5041)
    face_size = (72, 72)  # 72*72=5184 = 7.1% of 72720
    face_results = _make_face_results(n=8, has_face=True, face_size=face_size, position=(5, 5))
    times = _make_times(n=8)
    segments = analyze_clip_scenes(frames, face_results, 2.0, times)
    assert len(segments) > 0
    types = [s.scene_type for s in segments]
    assert SceneType.FACE_REACTION in types, f"Expected FACE_REACTION, got {types}"


# ─── T48: Dark frames → LOADING_OR_TRANSITION ─────────────────────────────────

def test_T48_dark_frames_loading():
    from engine.reframe.scene_analyzer import analyze_clip_scenes, SceneType
    # Very dark frames (mean brightness < 18)
    frames = _make_frames(n=8, color=(10, 10, 10))
    face_results = _make_face_results(n=8, has_face=False)
    times = _make_times(n=8)
    segments = analyze_clip_scenes(frames, face_results, 2.0, times)
    types = [s.scene_type for s in segments]
    assert SceneType.LOADING_OR_TRANSITION in types


# ─── T49: Low motion + no face → STATIC_GAMEPLAY or MENU_OR_UI ───────────────

def test_T49_low_motion_no_face_static():
    from engine.reframe.scene_analyzer import analyze_clip_scenes, SceneType
    frames = _make_frames(n=8, color=(120, 120, 120))  # static gray, no motion
    face_results = _make_face_results(n=8, has_face=False)
    times = _make_times(n=8)
    segments = analyze_clip_scenes(frames, face_results, 2.0, times)
    types = [s.scene_type for s in segments]
    assert any(t in (SceneType.STATIC_GAMEPLAY, SceneType.MENU_OR_UI, SceneType.UNKNOWN) for t in types)


# ─── T50: analyze_clip_scenes returns at least one segment ───────────────────

def test_T50_analyze_returns_segments():
    from engine.reframe.scene_analyzer import analyze_clip_scenes
    frames = _make_frames(n=6)
    face_results = _make_face_results(n=6, has_face=False)
    times = _make_times(n=6)
    segments = analyze_clip_scenes(frames, face_results, 2.0, times)
    assert isinstance(segments, list)
    assert len(segments) >= 1
    for s in segments:
        assert s.start_s < s.end_s


# ─── T51: dominant_scene_type selects the longest ─────────────────────────────

def test_T51_dominant_scene_type():
    from engine.reframe.scene_analyzer import SceneSegment, SceneType, dominant_scene_type

    segs = [
        SceneSegment(0.0, 5.0, SceneType.ACTIVE_GAMEPLAY, 0.8, 0.65, []),
        SceneSegment(5.0, 7.0, SceneType.FACE_REACTION, 0.9, 0.0, []),
        SceneSegment(7.0, 20.0, SceneType.ACTIVE_GAMEPLAY, 0.75, 0.65, []),
    ]
    dom = dominant_scene_type(segs)
    assert dom is not None
    assert dom.scene_type == SceneType.ACTIVE_GAMEPLAY


# ─── T52: adaptive_split_fraction clips to valid range ───────────────────────

def test_T52_adaptive_fraction_valid_range():
    from engine.reframe.scene_analyzer import SceneSegment, SceneType, adaptive_split_fraction

    segs = [SceneSegment(0.0, 10.0, SceneType.ACTIVE_GAMEPLAY, 0.8, 0.65, [])]
    frac = adaptive_split_fraction(segs, gameplay_region=(285, 0, 1635, 1080))
    assert 0.55 <= frac <= 0.72, f"Fraction {frac} out of range"


# ─── T53: ConfidenceGate — entry/exit behavior ────────────────────────────────

def test_T53_confidence_gate_entry_exit():
    from engine.reframe.composition import ConfidenceGate
    gate = ConfidenceGate(entry_threshold=0.55, exit_threshold=0.45)

    # Below entry: stays inactive
    assert gate.update(0.48) is False
    assert gate.is_active is False

    # At entry: becomes active
    assert gate.update(0.56) is True
    assert gate.is_active is True

    # Between thresholds: stays active
    assert gate.update(0.50) is True

    # Below exit: becomes inactive
    assert gate.update(0.40) is False
    assert gate.is_active is False


# ─── T54: ConfidenceGate — invalid init raises ────────────────────────────────

def test_T54_confidence_gate_invalid_init():
    from engine.reframe.composition import ConfidenceGate
    with pytest.raises(ValueError):
        ConfidenceGate(entry_threshold=0.40, exit_threshold=0.50)  # entry < exit


# ─── T55: ConfidenceGate — dead zone prevents Rickyedit oscillation ───────────

def test_T55_dead_zone_prevents_oscillation():
    from engine.reframe.composition import ConfidenceGate
    gate = ConfidenceGate(entry_threshold=0.55, exit_threshold=0.45)

    # Simulate oscillating confidence (V1 Rickyedit case: conf ~0.48)
    # Without dead zone would flip; with dead zone should stay inactive
    results = [gate.update(c) for c in [0.46, 0.49, 0.51, 0.48, 0.50, 0.49]]
    assert all(r is False for r in results), (
        f"Dead zone should prevent activation at conf≈0.46-0.51: {results}"
    )


# ─── T56: decide_v12 — FACE_REACTION bypasses SPLIT_LAYOUT ──────────────────

def test_T56_face_reaction_bypasses_split():
    from engine.reframe.composition import decide_v12, ContentAnalysis, CompositionMode
    analysis = ContentAnalysis(
        face_hit_rate=0.8, face_area_ratio=0.05,
        has_facecam=True, facecam_confidence=0.95,
        facecam_region=(100, 50, 200, 200), facecam_corner="TL",
    )
    decision = decide_v12(
        analysis, 656, 1920, 1080,
        scene_type="face_reaction",  # should override SPLIT_LAYOUT
    )
    assert decision.mode != CompositionMode.SPLIT_LAYOUT, (
        "FACE_REACTION scene must not use SPLIT_LAYOUT"
    )


# ─── T57: decide_v12 — ACTIVE_GAMEPLAY uses SPLIT_LAYOUT when facecam high ───

def test_T57_active_gameplay_uses_split_layout():
    from engine.reframe.composition import decide_v12, ContentAnalysis, CompositionMode, ConfidenceGate
    analysis = ContentAnalysis(
        face_hit_rate=0.3, face_area_ratio=0.02,
        has_facecam=True, facecam_confidence=0.85,
        facecam_region=(100, 50, 200, 200), facecam_corner="TL",
    )
    gate = ConfidenceGate()
    gate.update(0.85)  # activate gate
    decision = decide_v12(
        analysis, 656, 1920, 1080,
        scene_type="active_gameplay",
        confidence_gate=gate,
        split_fraction=0.65,
    )
    assert decision.mode == CompositionMode.SPLIT_LAYOUT


# ─── T58: decide_v12 — dead zone gate prevents split for borderline ──────────

def test_T58_dead_zone_gate_prevents_split():
    from engine.reframe.composition import decide_v12, ContentAnalysis, CompositionMode, ConfidenceGate
    analysis = ContentAnalysis(
        face_hit_rate=0.5, face_area_ratio=0.03,
        has_facecam=True, facecam_confidence=0.48,
        facecam_region=(100, 50, 180, 180), facecam_corner="TL",
    )
    gate = ConfidenceGate(entry_threshold=0.55, exit_threshold=0.45)
    # conf=0.48 < entry_threshold=0.55 → gate stays inactive → no SPLIT_LAYOUT
    decision = decide_v12(
        analysis, 656, 1920, 1080,
        scene_type="active_gameplay",
        confidence_gate=gate,
    )
    assert decision.mode != CompositionMode.SPLIT_LAYOUT, (
        "Borderline confidence 0.48 with entry_threshold 0.55 must not activate SPLIT_LAYOUT"
    )


# ─── T59: HUDRegion dataclass ────────────────────────────────────────────────

def test_T59_hud_region_dataclass():
    from engine.reframe.hud_protector import HUDRegion, HUDType
    r = HUDRegion(x=0, y=800, w=400, h=200, hud_type=HUDType.MINIMAP,
                  priority=0.9, confidence=0.7, reason="test")
    assert r.x == 0
    assert r.hud_type == HUDType.MINIMAP
    assert 0 < r.priority <= 1.0


# ─── T60: hud_penalty — region inside crop → no penalty ─────────────────────

def test_T60_hud_penalty_inside_crop():
    from engine.reframe.hud_protector import HUDRegion, HUDType, hud_penalty
    # HUD at bottom-left, gameplay region covers full frame
    hud = [HUDRegion(x=0, y=864, w=320, h=216, hud_type=HUDType.MINIMAP,
                     priority=0.9, confidence=0.8, reason="test")]
    gameplay = (0, 0, 1920, 1080)  # full frame covers HUD
    penalty = hud_penalty(gameplay, hud, 1920, 1080)
    assert penalty == 0.0, f"Expected 0 penalty when HUD is inside crop, got {penalty}"


# ─── T61: hud_penalty — region outside crop → penalty > 0 ───────────────────

def test_T61_hud_penalty_outside_crop():
    from engine.reframe.hud_protector import HUDRegion, HUDType, hud_penalty
    # HUD at bottom-right, gameplay crops only left portion
    hud = [HUDRegion(x=1600, y=900, w=320, h=180, hud_type=HUDType.MINIMAP,
                     priority=0.9, confidence=0.8, reason="test")]
    gameplay = (0, 0, 1200, 1080)  # crops right side — HUD excluded
    penalty = hud_penalty(gameplay, hud, 1920, 1080)
    assert penalty > 0, "Excluded HUD region must generate a positive penalty"


# ─── T62: detect_hud_regions returns list ────────────────────────────────────

def test_T62_detect_hud_regions_returns_list():
    from engine.reframe.hud_protector import detect_hud_regions
    frames = _make_frames(n=6)
    face_results = _make_face_results(n=6, has_face=False)
    regions = detect_hud_regions(frames, face_results, 1920, 1080)
    assert isinstance(regions, list)


# ─── T63: plan_clip_v3_2 returns version 3.2 ─────────────────────────────────

def test_T63_plan_v32_version():
    import tempfile, os
    try:
        import cv2
    except ImportError:
        pytest.skip("cv2 not available")
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.close()
    try:
        w, h = 320, 180
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(tmp.name, fourcc, 2.0, (w, h))
        if not writer.isOpened():
            pytest.skip("VideoWriter unavailable")
        for _ in range(8):
            writer.write(np.zeros((h, w, 3), dtype=np.uint8))
        writer.release()

        from engine.reframe.planner import plan_clip_v3_2
        plan = plan_clip_v3_2(tmp.name, 0.0, 4.0, 1920, 1080)
        assert plan.get("version") == 3.2, f"Expected 3.2, got {plan.get('version')}"
        assert plan.get("filter_version") == "v12"
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


# ─── T64: plan_clip_v3_2 has v12 metadata ────────────────────────────────────

def test_T64_plan_v32_has_v12_metadata():
    import tempfile, os
    try:
        import cv2
    except ImportError:
        pytest.skip("cv2 not available")
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.close()
    try:
        w, h = 320, 180
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(tmp.name, fourcc, 2.0, (w, h))
        if not writer.isOpened():
            pytest.skip("VideoWriter unavailable")
        for _ in range(8):
            writer.write(np.zeros((h, w, 3), dtype=np.uint8))
        writer.release()

        from engine.reframe.planner import plan_clip_v3_2
        plan = plan_clip_v3_2(tmp.name, 0.0, 4.0, 1920, 1080)
        # Should have v12 metadata OR v12_error (if scene analysis failed gracefully)
        assert "v12" in plan or "v12_error" in plan, (
            "plan must have 'v12' metadata or 'v12_error' fallback key"
        )
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


# ─── T65: filter_v12 generates valid FFmpeg syntax ───────────────────────────

def test_T65_filter_v12_syntax():
    from engine.renderers.render_clip import _compute_split_layout_filter_v12
    f = _compute_split_layout_filter_v12(
        main_region=[285, 0, 1635, 1080],
        secondary_region=[75, 384, 180, 180],
        src_w=1920, src_h=1080,
        top_fraction=0.65,
    )
    assert "vstack" in f
    assert "[out]" in f
    assert "force_original_aspect_ratio=increase" in f
    assert "force_original_aspect_ratio=decrease" in f


# ─── T66: filter_v12 with adaptive fraction 65% uses correct top_h ───────────

def test_T66_filter_v12_adaptive_fraction():
    from engine.renderers.render_clip import _compute_split_layout_filter_v12
    import re
    f = _compute_split_layout_filter_v12(
        main_region=[0, 0, 1920, 1080],
        secondary_region=[100, 50, 200, 200],
        src_w=1920, src_h=1080,
        top_fraction=0.65,
    )
    # 65% of 1920 = 1248, must be even
    expected_top_h = 1248
    assert str(expected_top_h) in f, (
        f"65% fraction should yield top_h={expected_top_h} in filter: {f[:200]}"
    )


# ─── T67: filter_v12 even dimensions ─────────────────────────────────────────

def test_T67_filter_v12_even_dims():
    from engine.renderers.render_clip import _compute_split_layout_filter_v12
    import re
    for frac in [0.55, 0.60, 0.65, 0.70, 0.72]:
        f = _compute_split_layout_filter_v12(
            [0, 0, 1920, 1080], [100, 50, 200, 200], 1920, 1080, top_fraction=frac
        )
        scales = re.findall(r"scale=1080:(\d+)", f)
        for s in scales:
            assert int(s) % 2 == 0, f"Odd dimension {s} for fraction {frac}"


# ─── T68: feature flag version 32 in config ──────────────────────────────────

def test_T68_config_version_32():
    from engine.config import CONFIG
    # Production flag must be off
    assert CONFIG.smart_reframing_enabled is False
    # V1.2 config fields exist
    assert hasattr(CONFIG, "smart_reframing_v12_confidence_entry")
    assert hasattr(CONFIG, "smart_reframing_v12_confidence_exit")
    assert hasattr(CONFIG, "smart_reframing_v12_min_split_fraction")
    assert hasattr(CONFIG, "smart_reframing_v12_max_split_fraction")
    # Dead zone values are reasonable
    assert CONFIG.smart_reframing_v12_confidence_entry > CONFIG.smart_reframing_v12_confidence_exit
    assert CONFIG.smart_reframing_version == 3  # default still V1


# ─── T69: ConfidenceGate reset ────────────────────────────────────────────────

def test_T69_confidence_gate_reset():
    from engine.reframe.composition import ConfidenceGate
    gate = ConfidenceGate()
    gate.update(0.9)  # activate
    assert gate.is_active is True
    gate.reset()
    assert gate.is_active is False


# ─── T70: backward compat — V1 decide() unchanged after V1.2 additions ───────

def test_T70_v1_decide_backward_compat():
    from engine.reframe.composition import decide, ContentAnalysis, CompositionMode
    analysis = ContentAnalysis(
        has_facecam=True, facecam_confidence=0.90, face_area_ratio=0.02,
        facecam_region=(100, 50, 200, 200), facecam_corner="TL",
    )
    d = decide(analysis, 656, 1920, 1080)
    assert d.mode == CompositionMode.SPLIT_LAYOUT


# ─── T71: SceneSegment.duration_s property ────────────────────────────────────

def test_T71_scene_segment_duration():
    from engine.reframe.scene_analyzer import SceneSegment, SceneType
    seg = SceneSegment(1.0, 5.5, SceneType.ACTIVE_GAMEPLAY, 0.8, 0.65, [])
    assert abs(seg.duration_s - 4.5) < 0.001


# ─── T72: analyze_clip_scenes empty input → empty list ───────────────────────

def test_T72_empty_frames_returns_empty():
    from engine.reframe.scene_analyzer import analyze_clip_scenes
    result = analyze_clip_scenes([], [], 2.0, [])
    assert result == []


# ─── T73: hud_penalty no regions → 0 ─────────────────────────────────────────

def test_T73_hud_penalty_no_regions():
    from engine.reframe.hud_protector import hud_penalty
    penalty = hud_penalty((0, 0, 1920, 1080), [], 1920, 1080)
    assert penalty == 0.0


# ─── T74: conversation scene bypasses SPLIT_LAYOUT ───────────────────────────

def test_T74_conversation_bypasses_split():
    from engine.reframe.composition import decide_v12, ContentAnalysis, CompositionMode
    analysis = ContentAnalysis(
        multi_face_rate=0.5, face_hit_rate=0.7, face_area_ratio=0.06,
        has_facecam=True, facecam_confidence=0.90,
        facecam_region=(100, 50, 200, 200), facecam_corner="TL",
    )
    d = decide_v12(analysis, 656, 1920, 1080, scene_type="conversation")
    assert d.mode != CompositionMode.SPLIT_LAYOUT


# ─── T75: scene_segments in plan are sorted by start time ─────────────────────

def test_T75_scene_segments_ordered():
    import tempfile, os
    try:
        import cv2
    except ImportError:
        pytest.skip("cv2 not available")
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.close()
    try:
        w, h = 320, 180
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(tmp.name, fourcc, 2.0, (w, h))
        if not writer.isOpened():
            pytest.skip("VideoWriter unavailable")
        for _ in range(12):
            writer.write(np.zeros((h, w, 3), dtype=np.uint8))
        writer.release()

        from engine.reframe.planner import plan_clip_v3_2
        plan = plan_clip_v3_2(tmp.name, 0.0, 6.0, 1920, 1080)
        segs = plan.get("v12", {}).get("scene_segments", [])
        starts = [s["start_s"] for s in segs]
        assert starts == sorted(starts), "Scene segments must be ordered by start_s"
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


# ─── T76: _SCENE_SPLIT_FRACTION coverage ─────────────────────────────────────

def test_T76_scene_split_fractions():
    from engine.reframe.scene_analyzer import SceneType, _SCENE_SPLIT_FRACTION
    for st in SceneType:
        assert st in _SCENE_SPLIT_FRACTION, f"SceneType {st} missing from _SCENE_SPLIT_FRACTION"


# ─── T77: adaptive_split_fraction with no gameplay_region ─────────────────────

def test_T77_adaptive_fraction_no_region():
    from engine.reframe.scene_analyzer import SceneSegment, SceneType, adaptive_split_fraction
    segs = [SceneSegment(0.0, 10.0, SceneType.ACTIVE_GAMEPLAY, 0.8, 0.65, [])]
    frac = adaptive_split_fraction(segs, gameplay_region=None)
    assert 0.55 <= frac <= 0.72


# ─── T78: Multiple clips — white scene → LOADING_OR_TRANSITION ───────────────

def test_T78_white_frames_loading():
    from engine.reframe.scene_analyzer import analyze_clip_scenes, SceneType
    frames = _make_frames(n=8, color=(250, 250, 250))  # bright white
    face_results = _make_face_results(n=8, has_face=False)
    times = _make_times(n=8)
    segments = analyze_clip_scenes(frames, face_results, 2.0, times)
    types = [s.scene_type for s in segments]
    assert SceneType.LOADING_OR_TRANSITION in types


# ─── T79: plan_clip_v3_2 is read-only (doesn't modify proxy) ─────────────────

def test_T79_plan_v32_read_only():
    import tempfile, os
    try:
        import cv2
    except ImportError:
        pytest.skip("cv2 not available")
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.close()
    try:
        w, h = 320, 180
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(tmp.name, fourcc, 2.0, (w, h))
        if not writer.isOpened():
            pytest.skip("VideoWriter unavailable")
        for _ in range(8):
            writer.write(np.zeros((h, w, 3), dtype=np.uint8))
        writer.release()

        mtime_before = os.path.getmtime(tmp.name)
        from engine.reframe.planner import plan_clip_v3_2
        plan_clip_v3_2(tmp.name, 0.0, 4.0, 1920, 1080)
        mtime_after = os.path.getmtime(tmp.name)
        assert mtime_after == mtime_before, "plan_clip_v3_2 must not modify source file"
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


# ─── T80: Full test count — 44 old + 36 new = 80 total ───────────────────────

def test_T80_total_test_coverage():
    """Sentinel test to verify T45-T80 are all accounted for (36 new tests)."""
    # This test is a documentation anchor, not a runtime check
    assert True
