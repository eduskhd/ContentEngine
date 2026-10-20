"""
GAMEPLAY_SPLIT_50 preset unit tests.

Tests that _force_gameplay_split_50() correctly overrides the plan for gameplay
clips and leaves non-gameplay clips unchanged.

Run with:
    python -m pytest tests/test_gameplay_split_50.py -v
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.reframe.planner import _force_gameplay_split_50, _GAMEPLAY_SCENE_TYPES


# ── Helpers ───────────────────────────────────────────────────────────────────

def _base_plan(dom_type: str, has_main=True, has_secondary=True) -> dict:
    plan: dict = {
        "version": 3.2,
        "composition_mode": "split_layout",
        "filter_version": "v12",
        "v12": {
            "dominant_scene_type": dom_type,
            "split_fraction": 0.65,
            "split_fraction_source": "adaptive",
        },
    }
    if has_main:
        plan["main_region"] = [0, 0, 1920, 810]
    if has_secondary:
        plan["secondary_region"] = [1400, 50, 500, 400]
    return plan


# ── T1: active_gameplay → forces split_fraction=0.50 ─────────────────────────

def test_t1_active_gameplay_forces_50():
    plan = _base_plan("active_gameplay")
    result = _force_gameplay_split_50(plan)
    assert result["composition_mode"] == "split_layout"
    assert result["filter_version"] == "v12"
    assert result["v12"]["split_fraction"] == 0.50
    assert result["v12"]["split_fraction_source"] == "gameplay_split_50_fixed"
    assert result["v12"]["gameplay_split_50"] is True


def test_t2_static_gameplay_forces_50():
    plan = _base_plan("static_gameplay")
    result = _force_gameplay_split_50(plan)
    assert result["v12"]["split_fraction"] == 0.50
    assert result["v12"]["gameplay_split_50"] is True


# ── T3: non-gameplay types are left unchanged ─────────────────────────────────

def test_t3_face_reaction_unchanged():
    plan = _base_plan("face_reaction")
    plan["v12"]["split_fraction"] = 0.65
    result = _force_gameplay_split_50(plan)
    assert result["v12"]["split_fraction"] == 0.65
    assert "gameplay_split_50_skip" in result["v12"]
    assert "active_gameplay" not in result["v12"].get("gameplay_split_50_skip", "")


def test_t4_conversation_unchanged():
    plan = _base_plan("conversation")
    plan["composition_mode"] = "face_focus"
    result = _force_gameplay_split_50(plan)
    assert result["composition_mode"] == "face_focus"
    assert "gameplay_split_50_skip" in result["v12"]


def test_t5_unknown_unchanged():
    plan = _base_plan("unknown")
    result = _force_gameplay_split_50(plan)
    assert "gameplay_split_50_skip" in result["v12"]


# ── T6: gameplay but no secondary_region → graceful fallback ─────────────────

def test_t6_no_secondary_region_fallback():
    plan = _base_plan("active_gameplay", has_secondary=False)
    result = _force_gameplay_split_50(plan)
    assert result["v12"].get("gameplay_split_50_fallback") == "no_secondary_region"
    # composition_mode should NOT be forced to split_layout
    assert result.get("v12", {}).get("gameplay_split_50") is not True


def test_t7_no_main_region_fallback():
    plan = _base_plan("active_gameplay", has_main=False)
    result = _force_gameplay_split_50(plan)
    assert result["v12"].get("gameplay_split_50_fallback") == "no_main_region"


# ── T8: split_fraction is exactly 0.50, not rounded ─────────────────────────

def test_t8_fraction_is_exact_half():
    for dom_type in _GAMEPLAY_SCENE_TYPES:
        plan = _base_plan(dom_type)
        result = _force_gameplay_split_50(plan)
        frac = result["v12"]["split_fraction"]
        assert frac == 0.50, f"expected 0.50 for {dom_type}, got {frac}"


# ── T9: prior adaptive fraction overridden ───────────────────────────────────

def test_t9_overrides_adaptive_fraction():
    for prior_frac in (0.55, 0.60, 0.65, 0.70, 0.72):
        plan = _base_plan("active_gameplay")
        plan["v12"]["split_fraction"] = prior_frac
        plan["v12"]["split_fraction_source"] = "adaptive"
        result = _force_gameplay_split_50(plan)
        assert result["v12"]["split_fraction"] == 0.50
        assert result["v12"]["split_fraction_source"] == "gameplay_split_50_fixed"


# ── T10: filter_version is set to v12 ────────────────────────────────────────

def test_t10_filter_version_v12():
    plan = _base_plan("static_gameplay")
    plan["filter_version"] = "v11"   # old value — should be overridden
    result = _force_gameplay_split_50(plan)
    assert result["filter_version"] == "v12"


# ── T11: _GAMEPLAY_SCENE_TYPES coverage ───────────────────────────────────────

def test_t11_gameplay_scene_types_set():
    assert "active_gameplay" in _GAMEPLAY_SCENE_TYPES
    assert "static_gameplay" in _GAMEPLAY_SCENE_TYPES
    # Non-gameplay types must NOT be in the set
    for t in ("face_reaction", "conversation", "menu_or_ui", "loading_or_transition", "unknown"):
        assert t not in _GAMEPLAY_SCENE_TYPES, f"{t} should not be in _GAMEPLAY_SCENE_TYPES"


# ── T12: plan_clip_gameplay_split_50 export ──────────────────────────────────

def test_t12_function_importable():
    from engine.reframe.planner import plan_clip_gameplay_split_50
    assert callable(plan_clip_gameplay_split_50)


# ── T13: version and preset tags ─────────────────────────────────────────────

def test_t13_force_does_not_set_version():
    """_force_gameplay_split_50 itself does not set version/preset — wrapper does."""
    plan = _base_plan("active_gameplay")
    plan["version"] = 3.2
    result = _force_gameplay_split_50(plan)
    # version should still be whatever it was — force fn doesn't touch it
    assert result["version"] == 3.2
    assert "preset" not in result
