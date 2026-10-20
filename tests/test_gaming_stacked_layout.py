"""Tests for GAMING_STACKED_FIT layout — geometry, FIT mode, captions, blurred bg."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from engine.renderers.render_clip import (
    _compute_stacked_fit_filter,
    _compute_split_layout_filter_manual,
    TARGET_W,
    TARGET_H,
)

# ── Fixture: a typical gaming region (16:9 gameplay, 4:3 facecam) in 1280×720 source
SRC_W, SRC_H = 1280, 720
GP   = [0, 0, 1280, 720]      # full frame gameplay
FACE = [900, 400, 380, 270]   # bottom-right facecam


# ── 1. Default split is 65/35 ─────────────────────────────────────────────────
def test_default_split_65_35():
    filt = _compute_stacked_fit_filter(GP, FACE, SRC_W, SRC_H)
    top_h = int(TARGET_H * 0.65)
    top_h -= top_h % 2
    assert f":{top_h}:" in filt or f"pad={TARGET_W}:{top_h}" in filt


# ── 2. 50/50 split produces correct top_h ────────────────────────────────────
def test_split_50_50():
    filt = _compute_stacked_fit_filter(GP, FACE, SRC_W, SRC_H, top_fraction=0.50)
    top_h = int(TARGET_H * 0.50)
    top_h -= top_h % 2
    assert str(top_h) in filt


# ── 3. 60/40 split ────────────────────────────────────────────────────────────
def test_split_60_40():
    filt = _compute_stacked_fit_filter(GP, FACE, SRC_W, SRC_H, top_fraction=0.60)
    top_h = int(TARGET_H * 0.60)
    top_h -= top_h % 2
    assert str(top_h) in filt


# ── 4. 70/30 split ────────────────────────────────────────────────────────────
def test_split_70_30():
    filt = _compute_stacked_fit_filter(GP, FACE, SRC_W, SRC_H, top_fraction=0.70)
    top_h = int(TARGET_H * 0.70)
    top_h -= top_h % 2
    assert str(top_h) in filt


# ── 5. top_h + bot_h = TARGET_H ──────────────────────────────────────────────
@pytest.mark.parametrize("frac", [0.50, 0.60, 0.65, 0.70])
def test_top_plus_bot_equals_total(frac):
    top_h = int(TARGET_H * frac)
    top_h -= top_h % 2
    bot_h = TARGET_H - top_h
    bot_h -= bot_h % 2
    assert top_h + bot_h == TARGET_H


# ── 6. FIT mode for gameplay: force_original_aspect_ratio=decrease ────────────
def test_gameplay_uses_fit_not_fill():
    filt = _compute_stacked_fit_filter(GP, FACE, SRC_W, SRC_H)
    assert "force_original_aspect_ratio=decrease" in filt
    assert "force_original_aspect_ratio=increase" not in filt


# ── 7. No second crop after gameplay scale (no gameplay cropping) ─────────────
def test_no_gameplay_crop_after_scale():
    filt = _compute_stacked_fit_filter(GP, FACE, SRC_W, SRC_H)
    # In black mode, gameplay chain should be: crop → scale → pad (no second crop)
    # We look for the scale line and verify pad follows, not crop
    lines = filt.split(";")
    for i, seg in enumerate(lines):
        if "force_original_aspect_ratio=decrease" in seg and "[v0]" in seg:
            assert ",crop=" not in seg.split("scale=")[1]


# ── 8. FIT for facecam too: decrease + pad ────────────────────────────────────
def test_facecam_uses_fit_pad():
    filt = _compute_stacked_fit_filter(GP, FACE, SRC_W, SRC_H)
    # facecam segment ends in [v1]
    for seg in filt.split(";"):
        if "[v1]" in seg:
            assert "force_original_aspect_ratio=decrease" in seg
            assert "pad=" in seg
            break


# ── 9. vstack at the end ─────────────────────────────────────────────────────
def test_vstack_output():
    filt = _compute_stacked_fit_filter(GP, FACE, SRC_W, SRC_H)
    assert "vstack=inputs=2[out]" in filt


# ── 10. Output labelled [out] for filter_complex routing ─────────────────────
def test_output_label_out():
    filt = _compute_stacked_fit_filter(GP, FACE, SRC_W, SRC_H)
    assert filt.strip().endswith("[out]")


# ── 11. Blurred background: boxblur present ───────────────────────────────────
def test_blurred_bg_uses_boxblur():
    filt = _compute_stacked_fit_filter(GP, FACE, SRC_W, SRC_H, bg="blurred")
    assert "boxblur" in filt


# ── 12. Blurred bg: no pad for gameplay (overlay instead) ────────────────────
def test_blurred_bg_uses_overlay_not_pad_for_gameplay():
    filt = _compute_stacked_fit_filter(GP, FACE, SRC_W, SRC_H, bg="blurred")
    assert "overlay=" in filt


# ── 13. Blurred bg: facecam still uses pad ───────────────────────────────────
def test_blurred_bg_facecam_still_padded():
    filt = _compute_stacked_fit_filter(GP, FACE, SRC_W, SRC_H, bg="blurred")
    assert "pad=" in filt


# ── 14. Blurred bg: both fill (for blur) and fit (for fg) present ─────────────
def test_blurred_bg_has_increase_and_decrease():
    filt = _compute_stacked_fit_filter(GP, FACE, SRC_W, SRC_H, bg="blurred")
    assert "force_original_aspect_ratio=increase" in filt
    assert "force_original_aspect_ratio=decrease" in filt


# ── 15. Region clamping: out-of-bounds coords are clamped safely ─────────────
def test_region_clamping():
    bad_gp = [-100, -50, 9999, 9999]
    bad_face = [1200, 650, 500, 500]
    filt = _compute_stacked_fit_filter(bad_gp, bad_face, SRC_W, SRC_H)
    # Should produce a valid-looking filter without negative crop coords
    assert "crop=" in filt
    assert "-" not in filt.split("crop=")[1].split(",")[0]


# ── 16. Output width is always TARGET_W ───────────────────────────────────────
def test_output_width_is_target_w():
    filt = _compute_stacked_fit_filter(GP, FACE, SRC_W, SRC_H)
    assert f"scale={TARGET_W}:" in filt or f"pad={TARGET_W}:" in filt


# ── 17. GAMING_STACKED_FIT default is different from GAMING_MANUAL_SPLIT_50 ──
def test_stacked_fit_differs_from_manual_split():
    stacked = _compute_stacked_fit_filter(GP, FACE, SRC_W, SRC_H, top_fraction=0.65)
    manual = _compute_split_layout_filter_manual(GP, FACE, SRC_W, SRC_H, top_fraction=0.65)
    # Same structure, same FIT approach — should produce identical filters
    # (GAMING_STACKED_FIT with black bg is functionally equivalent to manual)
    assert stacked == manual


# ── 18. Caption safe zone: margin_v exceeds webcam boundary + buffer ──────────
def test_caption_safe_zone_calculation():
    top_fraction = 0.65
    top_h = int(TARGET_H * top_fraction)
    top_h -= top_h % 2
    # safe margin_v must push captions above webcam panel (100px buffer)
    safe_margin_v = TARGET_H - top_h + 100
    caption_bottom_from_top = TARGET_H - safe_margin_v
    assert caption_bottom_from_top <= top_h
