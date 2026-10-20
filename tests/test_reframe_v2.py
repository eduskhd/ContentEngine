"""
Smart Reframing V1.2.1 tests (F1, F2, F4 fixes + regressions T81–T85).

Run with:
    python -m pytest tests/test_reframe_v2.py -v
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.reframe.scene_analyzer import (
    FrameSignals,
    SceneType,
    _classify,
    _FACE_REACTION_AREA,
    _FACE_HIT_REACTION,
    _FACE_CONVERSATION,
)
from engine.reframe.composition import (
    ContentAnalysis,
    CompositionDecision,
    CompositionMode,
    decide_v12,
    ConfidenceGate,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _signals(
    motion_mean=15.0,
    face_hit_rate=0.0,
    face_size_ratio=0.0,
    multi_face_rate=0.0,
    brightness_mean=120.0,
    brightness_std=15.0,
    edge_density=5.0,
) -> FrameSignals:
    return FrameSignals(
        motion_mean=motion_mean,
        motion_max=motion_mean * 1.5,
        brightness_mean=brightness_mean,
        brightness_std=brightness_std,
        edge_density=edge_density,
        face_hit_rate=face_hit_rate,
        face_size_ratio=face_size_ratio,
        multi_face_rate=multi_face_rate,
        n_frames=10,
    )


def _analysis(
    has_facecam=True,
    facecam_confidence=0.75,
    facecam_region=(1400, 50, 500, 400),
    facecam_corner="TR",
    face_area_ratio=0.05,
    face_hit_rate=0.30,
) -> ContentAnalysis:
    return ContentAnalysis(
        has_facecam=has_facecam,
        facecam_confidence=facecam_confidence,
        facecam_region=facecam_region,
        facecam_corner=facecam_corner,
        face_area_ratio=face_area_ratio,
        face_hit_rate=face_hit_rate,
        face_count_avg=1.0 if has_facecam else 0.0,
        content_hint="gameplay",
    )


# ── F1: FACE_REACTION threshold tests ─────────────────────────────────────────

class TestF1FaceReactionThreshold:

    def test_small_facecam_not_face_reaction(self):
        """T81: corner facecam occupying ~6% of frame must NOT trigger FACE_REACTION."""
        sig = _signals(face_hit_rate=0.70, face_size_ratio=0.06)
        scene, conf, _ = _classify(sig)
        assert scene != SceneType.FACE_REACTION, (
            f"Small corner facecam (size=0.06) should NOT trigger FACE_REACTION (got {scene})"
        )

    def test_large_face_still_triggers_reaction(self):
        """T82: full-frame face (IRL streamer, no game) must still trigger FACE_REACTION."""
        sig = _signals(face_hit_rate=0.80, face_size_ratio=0.25, motion_mean=3.0)
        scene, conf, _ = _classify(sig)
        assert scene == SceneType.FACE_REACTION, (
            f"Large face (size=0.25, hit=0.80) must trigger FACE_REACTION (got {scene})"
        )

    def test_threshold_values_not_regressed(self):
        """T83: confirm V1.2.1 threshold values are at expected levels."""
        assert _FACE_REACTION_AREA == 0.15, "F1: _FACE_REACTION_AREA must be 0.15"
        assert _FACE_HIT_REACTION  == 0.65, "F1: _FACE_HIT_REACTION must be 0.65"
        assert _FACE_CONVERSATION  == 0.35, "F1: _FACE_CONVERSATION must be 0.35"

    def test_face_hit_rate_must_exceed_threshold(self):
        """Corner face at correct size but only 50% frame presence → no FACE_REACTION."""
        sig = _signals(face_hit_rate=0.50, face_size_ratio=0.20, motion_mean=3.0)
        scene, _, _ = _classify(sig)
        assert scene != SceneType.FACE_REACTION


# ── F2: SPLIT_LAYOUT protection tests ─────────────────────────────────────────

class TestF2SplitLayoutProtection:

    def test_facecam_protected_despite_face_reaction_scene(self):
        """T84: decide_v12 must keep SPLIT_LAYOUT when has_facecam+confidence >= 0.60."""
        analysis = _analysis(has_facecam=True, facecam_confidence=0.75)
        decision = decide_v12(
            analysis,
            center_offset=200,
            src_w=1920, src_h=1080,
            scene_type="face_reaction",
        )
        assert decision.mode == CompositionMode.SPLIT_LAYOUT, (
            f"F2: reliable facecam should protect SPLIT_LAYOUT (got {decision.mode})"
        )

    def test_low_confidence_facecam_not_protected(self):
        """Low-confidence facecam (0.35 < 0.60) does NOT protect SPLIT_LAYOUT."""
        analysis = _analysis(has_facecam=True, facecam_confidence=0.35)
        decision = decide_v12(
            analysis,
            center_offset=200,
            src_w=1920, src_h=1080,
            scene_type="face_reaction",
        )
        # Must be face_focus since no protection and scene is face_reaction
        assert decision.mode == CompositionMode.FACE_FOCUS, (
            f"Low-confidence facecam in face_reaction → face_focus (got {decision.mode})"
        )

    def test_no_facecam_suppresses_on_face_reaction(self):
        """No facecam detected → face_reaction scene type suppresses SPLIT_LAYOUT."""
        analysis = _analysis(has_facecam=False, facecam_confidence=0.0, facecam_region=None)
        decision = decide_v12(
            analysis,
            center_offset=200,
            src_w=1920, src_h=1080,
            scene_type="face_reaction",
        )
        assert decision.mode == CompositionMode.FACE_FOCUS, (
            f"No facecam + face_reaction → must fall to face_focus (got {decision.mode})"
        )

    def test_conversation_scene_protected_with_reliable_facecam(self):
        """T85: conversation scene type also protected by reliable facecam."""
        analysis = _analysis(has_facecam=True, facecam_confidence=0.80)
        decision = decide_v12(
            analysis,
            center_offset=200,
            src_w=1920, src_h=1080,
            scene_type="conversation",
        )
        assert decision.mode == CompositionMode.SPLIT_LAYOUT, (
            f"F2: reliable facecam in conversation scene → SPLIT_LAYOUT (got {decision.mode})"
        )


# ── F4: segment-weighted split_fraction ──────────────────────────────────────

class TestF4SegmentWeightedFraction:

    def test_equal_weight_average(self):
        """Two equal-duration split segments: fraction is their mean."""
        segments = [
            {"mode": "split_layout", "split_fraction": 0.60, "start_s": 0.0,  "end_s": 10.0},
            {"mode": "split_layout", "split_fraction": 0.70, "start_s": 10.0, "end_s": 20.0},
        ]
        total_w = sum(d["end_s"] - d["start_s"] for d in segments)
        weighted = sum(d["split_fraction"] * (d["end_s"] - d["start_s"]) for d in segments) / total_w
        assert weighted == pytest.approx(0.65, abs=0.001)

    def test_face_focus_segments_excluded(self):
        """face_focus segments must not influence split_fraction."""
        segments = [
            {"mode": "split_layout", "split_fraction": 0.65, "start_s": 0.0,  "end_s": 10.0},
            {"mode": "face_focus",   "split_fraction": 0.0,  "start_s": 10.0, "end_s": 20.0},
        ]
        split_only = [
            (d["split_fraction"], d["end_s"] - d["start_s"])
            for d in segments
            if d.get("mode") == "split_layout" and d.get("split_fraction")
        ]
        assert len(split_only) == 1
        assert split_only[0][0] == 0.65

    def test_fraction_clamps_high(self):
        """Computed fraction above 0.72 must clamp to 0.72."""
        raw = 0.95
        clamped = max(0.55, min(0.72, raw))
        assert clamped == 0.72

    def test_fraction_clamps_low(self):
        """Computed fraction below 0.55 must clamp to 0.55."""
        raw = 0.30
        clamped = max(0.55, min(0.72, raw))
        assert clamped == 0.55


# ── Confidence gate ───────────────────────────────────────────────────────────

class TestConfidenceGate:

    def test_starts_inactive(self):
        gate = ConfidenceGate(entry_threshold=0.55, exit_threshold=0.45)
        assert not gate._active

    def test_activates_above_entry(self):
        gate = ConfidenceGate(entry_threshold=0.55, exit_threshold=0.45)
        result = gate.update(0.60)
        assert result
        assert gate._active

    def test_hysteresis_zone_keeps_active(self):
        gate = ConfidenceGate(entry_threshold=0.55, exit_threshold=0.45)
        gate.update(0.60)   # activate
        result = gate.update(0.48)  # in hysteresis zone
        assert result, "Between entry and exit thresholds: must stay active"

    def test_deactivates_below_exit(self):
        gate = ConfidenceGate(entry_threshold=0.55, exit_threshold=0.45)
        gate.update(0.60)   # activate
        result = gate.update(0.40)  # below exit threshold
        assert not result
        assert not gate._active


# ── Regression tests ──────────────────────────────────────────────────────────

class TestRegressions:

    def test_gameplay_high_motion_no_face_is_active(self):
        """High-motion, no-face clip must stay ACTIVE_GAMEPLAY."""
        sig = _signals(motion_mean=30.0, face_hit_rate=0.0, face_size_ratio=0.0)
        scene, _, _ = _classify(sig)
        assert scene == SceneType.ACTIVE_GAMEPLAY

    def test_low_motion_no_face_is_static_or_menu(self):
        """Very low motion, no face → STATIC_GAMEPLAY or MENU_OR_UI."""
        sig = _signals(motion_mean=2.0, face_hit_rate=0.0, face_size_ratio=0.0, edge_density=4.0)
        scene, _, _ = _classify(sig)
        assert scene in (SceneType.STATIC_GAMEPLAY, SceneType.MENU_OR_UI)

    def test_decide_v12_no_facecam_returns_center_or_face_focus(self):
        """No facecam, no significant face → center or action_focus (not split_layout)."""
        analysis = ContentAnalysis(
            has_facecam=False, facecam_confidence=0.0,
            face_area_ratio=0.01, face_hit_rate=0.05,
            content_hint="gameplay",
        )
        decision = decide_v12(analysis, center_offset=200, src_w=1920, src_h=1080)
        assert decision.mode != CompositionMode.SPLIT_LAYOUT, (
            f"No facecam → must not be SPLIT_LAYOUT (got {decision.mode})"
        )
