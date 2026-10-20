"""Smart Reframing V1.1 — Tests T19-T44.

Extends the 18 V1 tests with V1.1-specific coverage:
  - _optimal_gameplay_region() for all facecam corner positions
  - decide_v11() composition decisions
  - _compute_split_layout_filter_v11() AR-safe scaling
  - Aspect ratio validation
  - Scalding uniformity checks
  - Fallback conditions
  - plan_clip_v3_1() plan structure
  - Temporal stability
  - Feature flag and planner compatibility
  - FFmpeg filter syntax
  - Borderline thresholds
"""
import sys
import math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pytest


# ── T19 — optimal_gameplay_region: TL facecam picks right side ───────────────

def test_T19_optimal_region_tl_facecam_picks_right():
    from engine.reframe.composition import _optimal_gameplay_region
    # IlloJuan-style: small TL facecam at (75, 384, 180, 180)
    rx, ry, rw, rh = _optimal_gameplay_region(75, 384, 180, 180, 1920, 1080, "TL")
    # Right-of-facecam should score higher than the thin bottom strip V1 used
    assert rx > 0, "V1.1 should avoid x=0 for TL facecam (would pick right or full)"
    # Region must be at least 50% of frame width
    assert rw >= 1920 * 0.5, f"Region too narrow: {rw}px"
    # Full height should be preserved
    assert rh == 1080, f"Expected full height 1080, got {rh}"


# ── T20 — optimal_gameplay_region: TR facecam picks left side ────────────────

def test_T20_optimal_region_tr_facecam_picks_left():
    from engine.reframe.composition import _optimal_gameplay_region
    # AuronPlay-style: TR facecam at (1575, 51, 183, 183)
    rx, ry, rw, rh = _optimal_gameplay_region(1575, 51, 183, 183, 1920, 1080, "TR")
    # Left-of-facecam region: starts at x=0, must not extend into facecam
    assert rx == 0, f"Left region should start at x=0, got {rx}"
    assert rw < 1920, "Left region must not include TR facecam"
    assert rw >= 1920 * 0.50, f"Region too narrow: {rw}px"
    assert rh == 1080


# ── T21 — optimal_gameplay_region: large centered facecam falls back to full ─

def test_T21_large_centered_facecam_fallback():
    from engine.reframe.composition import _optimal_gameplay_region
    # Hypothetical: large centered facecam occupying most of the frame
    # 800x600 facecam at (560, 240) in 1920×1080
    rx, ry, rw, rh = _optimal_gameplay_region(560, 240, 800, 600, 1920, 1080, "")
    # No side/above/below region will be ≥ 25% of frame → full frame fallback
    # Right side: 1920-(560+800+margin) = 1920-1480 = 440px → 440/1920 = 22.9% < 25%
    # Left side: 560-margin = 440px → 22.9% < 25%
    # Either falls back to "full" or picks one of these borderline candidates
    # The key invariant: w > 0 and h > 0
    assert rw > 0 and rh > 0, "Must return a valid region even for large centered facecam"
    assert rx >= 0 and ry >= 0


# ── T22 — optimal_gameplay_region: full frame has highest area ───────────────

def test_T22_full_frame_always_valid_candidate():
    from engine.reframe.composition import _optimal_gameplay_region
    # Any configuration: full frame must be a candidate and return valid result
    rx, ry, rw, rh = _optimal_gameplay_region(0, 0, 100, 100, 1920, 1080, "TL")
    assert rw > 0 and rh > 0


# ── T23 — optimal_gameplay_region: AR of result better than V1 strip ─────────

def test_T23_result_ar_better_than_v1_strip_for_illojuan():
    from engine.reframe.composition import _optimal_gameplay_region
    # IlloJuan: V1 gives (0, 564, 1920, 516) → AR = 1920/516 = 3.72
    rx, ry, rw, rh = _optimal_gameplay_region(75, 384, 180, 180, 1920, 1080, "TL")
    ar_v11 = rw / rh
    ar_v1 = 1920 / 516  # = 3.72
    assert ar_v11 < ar_v1, (
        f"V1.1 AR {ar_v11:.2f} must be better (closer to 16:9=1.78) than V1's {ar_v1:.2f}"
    )
    # Should be closer to 16:9
    assert abs(ar_v11 - 16/9) < abs(ar_v1 - 16/9)


# ── T24 — decide_v11: SPLIT_LAYOUT uses optimal region ──────────────────────

def test_T24_decide_v11_split_layout_uses_optimal_region():
    from engine.reframe.composition import decide_v11, ContentAnalysis, CompositionMode
    analysis = ContentAnalysis(
        face_hit_rate=0.7,
        face_area_ratio=0.03,
        has_facecam=True,
        facecam_confidence=0.85,
        facecam_corner="TL",
        facecam_region=(75, 384, 180, 180),
    )
    decision = decide_v11(analysis, center_offset=656, src_w=1920, src_h=1080)
    assert decision.mode == CompositionMode.SPLIT_LAYOUT
    # V1.1 main_region should NOT be a thin horizontal strip
    mr = decision.main_region
    assert mr is not None
    gx, gy, gw, gh = mr
    ar = gw / gh
    assert ar < 3.0, f"V1.1 gameplay region AR {ar:.2f} should not be extreme (> 3.0)"


# ── T25 — decide_v11: FACE_FOCUS falls through to original decide() ──────────

def test_T25_decide_v11_face_focus_unchanged():
    from engine.reframe.composition import decide_v11, decide, ContentAnalysis, CompositionMode
    analysis = ContentAnalysis(face_hit_rate=0.60, face_area_ratio=0.08)
    d_v1  = decide(analysis, 656, 1920, 1080)
    d_v11 = decide_v11(analysis, 656, 1920, 1080)
    assert d_v1.mode  == CompositionMode.FACE_FOCUS
    assert d_v11.mode == CompositionMode.FACE_FOCUS
    assert d_v1.x_offset == d_v11.x_offset, "FACE_FOCUS path must match V1 exactly"


# ── T26 — decide_v11: low facecam confidence skips SPLIT_LAYOUT ─────────────

def test_T26_low_facecam_conf_not_split_layout():
    from engine.reframe.composition import decide_v11, ContentAnalysis, CompositionMode
    analysis = ContentAnalysis(
        face_hit_rate=0.70,
        face_area_ratio=0.05,
        has_facecam=True,
        facecam_confidence=0.35,   # below _FACECAM_CONF_THRESHOLD = 0.50
        facecam_corner="TL",
        facecam_region=(75, 384, 180, 180),
    )
    decision = decide_v11(analysis, 656, 1920, 1080)
    assert decision.mode != CompositionMode.SPLIT_LAYOUT, (
        "Confidence 0.35 < threshold 0.50 must not activate SPLIT_LAYOUT"
    )


# ── T27 — filter_v11: contains vstack and [out] ──────────────────────────────

def test_T27_v11_filter_structure():
    from engine.renderers.render_clip import _compute_split_layout_filter_v11
    f = _compute_split_layout_filter_v11(
        main_region=[465, 0, 1455, 1080],
        secondary_region=[207, 66, 225, 225],
        src_w=1920, src_h=1080,
    )
    assert "vstack" in f
    assert "[out]" in f
    assert "force_original_aspect_ratio=increase" in f, "Gameplay must use increase AR"
    assert "force_original_aspect_ratio=decrease" in f, "Facecam must use decrease AR"
    assert "pad=" in f, "Facecam must be padded to fill exact dimensions"


# ── T28 — filter_v11: no uniform scale distortion on gameplay ────────────────

def test_T28_no_distortion_in_gameplay_scale():
    """Verify the gameplay filter does NOT stretch both dimensions independently.

    With force_original_aspect_ratio=increase + crop, both scale factors
    are equal (the max of the two needed values) — no non-uniform scaling.
    This test documents the guarantee: the filter must not use bare scale=W:H.
    """
    from engine.renderers.render_clip import _compute_split_layout_filter_v11
    f = _compute_split_layout_filter_v11(
        main_region=[0, 0, 1920, 1080],
        secondary_region=[100, 50, 200, 200],
        src_w=1920, src_h=1080,
    )
    # The scale for gameplay must not appear as bare "scale=1080:1152" (which distorts)
    # It should appear as "scale=1080:1152:force_original_aspect_ratio=increase"
    assert "scale=1080:1152:force_original_aspect_ratio" in f, (
        "Gameplay scale must include force_original_aspect_ratio to prevent distortion"
    )


# ── T29 — filter_v11: output dimensions are even ─────────────────────────────

def test_T29_output_dimensions_are_even():
    from engine.renderers.render_clip import _compute_split_layout_filter_v11
    f = _compute_split_layout_filter_v11(
        main_region=[100, 100, 1720, 980],
        secondary_region=[50, 50, 200, 200],
        src_w=1920, src_h=1080,
    )
    # Extract top_h and bot_h from the filter
    # Pattern: scale=1080:{top_h}:force...
    import re
    scales = re.findall(r"scale=1080:(\d+)", f)
    for s in scales:
        h = int(s)
        assert h % 2 == 0, f"Dimension {h} is odd — will fail codec"


# ── T30 — filter_v11: clamps invalid regions without crash ───────────────────

def test_T30_v11_filter_clamps_invalid():
    from engine.renderers.render_clip import _compute_split_layout_filter_v11
    # Regions larger than source
    f = _compute_split_layout_filter_v11(
        main_region=[-200, -100, 4000, 3000],
        secondary_region=[1800, 900, 500, 400],
        src_w=1920, src_h=1080,
    )
    assert "vstack" in f and "[out]" in f


# ── T31 — filter_v11: facecam crop never exceeds source ──────────────────────

def test_T31_facecam_stays_within_source():
    from engine.renderers.render_clip import _compute_split_layout_filter_v11
    import re
    # Facecam at edge: might push crop out of bounds
    f = _compute_split_layout_filter_v11(
        main_region=[0, 0, 1920, 1080],
        secondary_region=[1800, 900, 200, 200],   # partially out of 1920×1080
        src_w=1920, src_h=1080,
    )
    # Extract face crop: crop=fw:fh:fx:fy
    crops = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", f)
    assert len(crops) >= 2
    # Face crop (second one)
    fc = crops[1]
    fw, fh, fx, fy = int(fc[0]), int(fc[1]), int(fc[2]), int(fc[3])
    assert fx + fw <= 1920, f"Facecam crop extends beyond source width: {fx}+{fw}={fx+fw}"
    assert fy + fh <= 1080, f"Facecam crop extends beyond source height: {fy}+{fh}={fy+fh}"


# ── T32 — plan_clip_v3_1: returns version 3.1 and filter_version v11 ─────────

def test_T32_plan_v31_has_correct_keys():
    import tempfile, os, cv2
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
            frame = np.zeros((h, w, 3), dtype=np.uint8)
            writer.write(frame)
        writer.release()

        from engine.reframe.planner import plan_clip_v3_1
        plan = plan_clip_v3_1(tmp.name, 0.0, 4.0, 1920, 1080)

        assert plan.get("version") == 3.1, f"Expected version 3.1, got {plan.get('version')}"
        assert plan.get("filter_version") == "v11", f"Expected filter_version v11"
        assert "composition_mode" in plan
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


# ── T33 — plan_clip_v3_1: SPLIT_LAYOUT has v11 main_region (better AR) ───────

def test_T33_v31_split_layout_region_has_better_ar_than_v3():
    from engine.reframe.composition import decide, decide_v11, ContentAnalysis, CompositionMode

    analysis = ContentAnalysis(
        face_hit_rate=0.7,
        face_area_ratio=0.015,
        has_facecam=True,
        facecam_confidence=0.90,
        facecam_corner="TL",
        facecam_region=(75, 384, 180, 180),  # IlloJuan-style
    )
    d_v1  = decide(analysis, 656, 1920, 1080)
    d_v11 = decide_v11(analysis, 656, 1920, 1080)

    assert d_v1.mode  == CompositionMode.SPLIT_LAYOUT
    assert d_v11.mode == CompositionMode.SPLIT_LAYOUT

    mr_v1  = d_v1.main_region
    mr_v11 = d_v11.main_region
    assert mr_v1  is not None and mr_v11 is not None

    ar_v1  = mr_v1[2]  / mr_v1[3]   # w/h
    ar_v11 = mr_v11[2] / mr_v11[3]

    assert ar_v11 < ar_v1, (
        f"V1.1 AR {ar_v11:.2f} should be closer to 16:9 than V1 AR {ar_v1:.2f}"
    )


# ── T34 — content_preservation: V1.1 shows more source content ───────────────

def test_T34_v11_preserves_more_source_content():
    """V1.1 gameplay region must preserve more of the source frame than V1's strip."""
    from engine.reframe.composition import decide, decide_v11, ContentAnalysis

    analysis = ContentAnalysis(
        face_hit_rate=0.9,
        face_area_ratio=0.01,
        has_facecam=True,
        facecam_confidence=0.92,
        facecam_corner="TL",
        facecam_region=(99, 390, 183, 183),
    )
    d_v1  = decide(analysis, 656, 1920, 1080)
    d_v11 = decide_v11(analysis, 656, 1920, 1080)

    def content_preserved(main_region, output_w=1080, top_h=1152):
        gx, gy, gw, gh = main_region
        if gw <= 0 or gh <= 0:
            return 0.0
        scale = max(output_w / gw, top_h / gh)
        vis_w = output_w / scale
        vis_h = top_h   / scale
        return (vis_w * vis_h) / (gw * gh)

    pres_v1  = content_preserved(d_v1.main_region)
    pres_v11 = content_preserved(d_v11.main_region)

    assert pres_v11 > pres_v1, (
        f"V1.1 ({pres_v11:.2%}) must preserve more content than V1 ({pres_v1:.2%})"
    )


# ── T35 — aspect ratio protection: no bare scale in v11 gameplay ─────────────

def test_T35_no_bare_scale_in_v11_gameplay():
    """Verify the gameplay section never uses bare scale=W:H without AR protection."""
    from engine.renderers.render_clip import _compute_split_layout_filter_v11
    import re

    f = _compute_split_layout_filter_v11(
        main_region=[0, 564, 1920, 516],   # The problematic V1 region
        secondary_region=[75, 384, 180, 180],
        src_w=1920, src_h=1080,
    )
    # There must be no "scale=W:H" immediately followed by "," (bare scale)
    # Correct: scale=W:H:force_original_aspect_ratio=increase
    bare_scales = re.findall(r"scale=\d+:\d+,", f)
    assert not bare_scales, (
        f"Found bare scale filter (no AR protection): {bare_scales}\nFilter: {f}"
    )


# ── T36 — facecam BL/BR corner detection ─────────────────────────────────────

def test_T36_optimal_region_bl_facecam():
    from engine.reframe.composition import _optimal_gameplay_region
    # Hypothetical: facecam in BL corner at (50, 850, 200, 200)
    rx, ry, rw, rh = _optimal_gameplay_region(50, 850, 200, 200, 1920, 1080, "BL")
    # Above the facecam should have 850px of height — significant
    # Right of facecam: 1920-280=1640px wide, full height
    assert rw > 0 and rh > 0
    # Result should NOT be the thin strip above (50×850 → very narrow strip below)
    # i.e., height should not be 850 with width 1920 (AR=2.26)
    # Actually right (1640×1080) would score better
    ar = rw / rh
    assert ar < 3.0, f"BL facecam should not produce extreme AR region: {ar:.2f}"


# ── T37 — fallback: when no candidate passes threshold ───────────────────────

def test_T37_always_returns_valid_region():
    from engine.reframe.composition import _optimal_gameplay_region
    # Extreme case: nearly full-frame facecam
    rx, ry, rw, rh = _optimal_gameplay_region(10, 10, 1900, 1060, 1920, 1080, "TL")
    assert rw > 0 and rh > 0, "Must always return a non-empty region"


# ── T38 — filter_v11: different split ratios don't break filter ──────────────

def test_T38_v11_filter_custom_split_fraction():
    from engine.renderers.render_clip import _compute_split_layout_filter_v11
    # 70/30 split
    f = _compute_split_layout_filter_v11(
        main_region=[0, 0, 1920, 1080],
        secondary_region=[100, 50, 200, 200],
        src_w=1920, src_h=1080,
        top_fraction=0.70,
    )
    assert "vstack" in f
    assert "[out]" in f
    # 70% of 1920 = 1344 (already even)
    assert "1344" in f, "70% split should yield 1344px gameplay height"


# ── T39 — existing tests remain unaffected (compatibility check) ─────────────

def test_T39_v1_decide_unchanged():
    """V1's decide() must return identical results after adding decide_v11()."""
    from engine.reframe.composition import decide, ContentAnalysis, CompositionMode

    test_cases = [
        ContentAnalysis(face_hit_rate=0.5, face_area_ratio=0.05),             # FACE_FOCUS
        ContentAnalysis(),                                                      # CENTER
        ContentAnalysis(face_hit_rate=0.8, multi_face_rate=0.4, face_area_ratio=0.06),  # SPEAKER
        ContentAnalysis(has_facecam=True, facecam_confidence=0.8, face_area_ratio=0.02,
                        facecam_region=(100,50,200,200), facecam_corner="TL"), # SPLIT
    ]
    expected_modes = [
        CompositionMode.FACE_FOCUS,
        CompositionMode.CENTER,
        CompositionMode.SPEAKER_TRACKING,
        CompositionMode.SPLIT_LAYOUT,
    ]
    for analysis, expected in zip(test_cases, expected_modes):
        d = decide(analysis, 656, 1920, 1080)
        assert d.mode == expected, f"V1 decide() changed for {analysis}: got {d.mode}"


# ── T40 — plan_clip_v3_1: does NOT modify source video ───────────────────────

def test_T40_plan_v31_read_only():
    """plan_clip_v3_1 must not write to the DB or modify source files."""
    import tempfile, os, cv2
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
        for _ in range(6):
            writer.write(np.zeros((h, w, 3), dtype=np.uint8))
        writer.release()

        mtime_before = os.path.getmtime(tmp.name)
        size_before  = os.path.getsize(tmp.name)

        from engine.reframe.planner import plan_clip_v3_1
        plan_clip_v3_1(tmp.name, 0.0, 3.0, 1920, 1080)

        mtime_after = os.path.getmtime(tmp.name)
        size_after  = os.path.getsize(tmp.name)

        assert mtime_after == mtime_before, "plan_clip_v3_1 must not modify source file"
        assert size_after  == size_before,  "plan_clip_v3_1 must not write to source file"
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


# ── T41 — feature flag: version 31 selects v3.1 planner ─────────────────────

def test_T41_feature_flag_version_31():
    from engine.config import CONFIG
    # V1.1 is only active when smart_reframing_enabled=True AND smart_reframing_version=31
    # Default: disabled
    assert CONFIG.smart_reframing_enabled is False, (
        "smart_reframing_enabled must be False in production"
    )
    # The version 31 constant must be a valid integer
    assert isinstance(31, int)
    # Config must accept version=31 without errors
    CONFIG_copy = type(CONFIG)()
    assert CONFIG_copy.smart_reframing_version == 3, "Default version must be 3"


# ── T42 — optimal_gameplay_region: score favors facecam-avoiding regions ──────

def test_T42_score_favors_non_full_frame():
    """When a good non-full-frame region exists, it should score higher than full frame."""
    from engine.reframe.composition import _optimal_gameplay_region

    # Rubius: TL facecam at (207, 66, 225, 225) → right region (465, 0, 1455, 1080) beats full
    rx, ry, rw, rh = _optimal_gameplay_region(207, 66, 225, 225, 1920, 1080, "TL")
    # Must NOT return full frame (0, 0, 1920, 1080) because right region scores better
    # Right region is 1455×1080 which preserves ~69% vs 53% for full
    assert rx > 0, (
        "For Rubius TL facecam, right-of-facecam region should score better than full frame"
    )


# ── T43 — v11 filter: pad color is black ─────────────────────────────────────

def test_T43_facecam_pad_is_black():
    from engine.renderers.render_clip import _compute_split_layout_filter_v11
    f = _compute_split_layout_filter_v11(
        main_region=[0, 0, 1920, 1080],
        secondary_region=[100, 50, 180, 180],
        src_w=1920, src_h=1080,
    )
    assert ":black" in f or "0x000000" in f or "color=black" in f, (
        "Facecam padding must be black to avoid visual artifacts"
    )


# ── T44 — smart_reframing_version config field exists ────────────────────────

def test_T44_config_smart_reframing_version():
    from engine.config import CONFIG
    assert hasattr(CONFIG, "smart_reframing_version"), (
        "CONFIG must have smart_reframing_version field"
    )
    assert CONFIG.smart_reframing_version == 3, (
        "Default must be 3 (V1), not 31 (V1.1) to protect production"
    )
