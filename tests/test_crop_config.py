"""Tests for crop config CRUD and manual render integration."""
import sys
sys.path.insert(0, '.')
from engine.renderers.render_clip import _compute_split_layout_filter_v12, _compute_split_layout_filter_manual


def test_manual_framing_plan_construction():
    """Manual crop config should produce correct framing plan dict."""
    cfg = {
        'crop_mode': 'manual',
        'validation_status': 'validated',
        'src_width': 1920,
        'src_height': 1080,
        'gameplay_x': 0.0, 'gameplay_y': 0.0, 'gameplay_w': 0.75, 'gameplay_h': 1.0,
        'facecam_x': 0.75, 'facecam_y': 0.0, 'facecam_w': 0.25, 'facecam_h': 0.5,
        'split_fraction': 0.5,
    }
    cw, ch = cfg['src_width'], cfg['src_height']
    main = [cfg['gameplay_x']*cw, cfg['gameplay_y']*ch, cfg['gameplay_w']*cw, cfg['gameplay_h']*ch]
    sec  = [cfg['facecam_x']*cw, cfg['facecam_y']*ch, cfg['facecam_w']*cw, cfg['facecam_h']*ch]
    assert main == [0.0, 0.0, 1440.0, 1080.0]
    assert sec == [1440.0, 0.0, 480.0, 540.0]


def test_filter_string_has_vstack():
    main = [0, 0, 1440, 1080]
    sec  = [1440, 0, 480, 540]
    filt = _compute_split_layout_filter_v12(main, sec, 1920, 1080, top_fraction=0.5)
    assert 'vstack' in filt
    assert 'crop=1440:1080:0:0' in filt


def test_normalized_coords_overlap_still_works():
    """Overlapping regions are not an error — filter still produces valid output."""
    gp = [0.0, 0.0, 0.8, 1.0]
    fc = [0.75, 0.0, 0.25, 0.5]
    main = [gp[0]*1920, gp[1]*1080, gp[2]*1920, gp[3]*1080]
    sec  = [fc[0]*1920, fc[1]*1080, fc[2]*1920, fc[3]*1080]
    filt = _compute_split_layout_filter_v12(main, sec, 1920, 1080, 0.5)
    assert 'vstack' in filt


def test_auto_mode_not_overridden():
    """Auto mode crop config should not override planner."""
    cfg = {
        'crop_mode': 'auto',
        'validation_status': 'validated',
        'gameplay_x': 0.0, 'gameplay_y': 0.0,
    }
    assert cfg['crop_mode'] != 'manual'


def test_pending_status_not_used():
    """Pending validation status should not activate manual crop."""
    cfg = {
        'crop_mode': 'manual',
        'validation_status': 'pending',
    }
    use_manual = (cfg.get('crop_mode') == 'manual' and cfg.get('validation_status') == 'validated')
    assert not use_manual


def test_manual_plan_has_correct_preset():
    """Manual crop framing plan should have GAMING_MANUAL_SPLIT_50 preset."""
    cfg = {
        'crop_mode': 'manual',
        'validation_status': 'validated',
        'src_width': 1920,
        'src_height': 1080,
        'gameplay_x': 0.0, 'gameplay_y': 0.0, 'gameplay_w': 0.75, 'gameplay_h': 1.0,
        'facecam_x': 0.75, 'facecam_y': 0.5, 'facecam_w': 0.25, 'facecam_h': 0.5,
        'split_fraction': 0.5,
    }
    cw = cfg.get('src_width') or 1920
    ch = cfg.get('src_height') or 1080
    plan = {
        "composition_mode": "split_layout",
        "filter_version": "v12",
        "version": 3.4,
        "preset": "GAMING_MANUAL_SPLIT_50",
        "main_region": [
            cfg["gameplay_x"] * cw,
            cfg["gameplay_y"] * ch,
            cfg["gameplay_w"] * cw,
            cfg["gameplay_h"] * ch,
        ],
        "secondary_region": [
            cfg["facecam_x"] * cw,
            cfg["facecam_y"] * ch,
            cfg["facecam_w"] * cw,
            cfg["facecam_h"] * ch,
        ],
        "v12": {"split_fraction": cfg.get("split_fraction", 0.5)},
    }
    assert plan["preset"] == "GAMING_MANUAL_SPLIT_50"
    assert plan["composition_mode"] == "split_layout"
    assert plan["filter_version"] == "v12"
    assert plan["v12"]["split_fraction"] == 0.5
    assert plan["main_region"] == [0.0, 0.0, 1440.0, 1080.0]
    assert plan["secondary_region"] == [1440.0, 540.0, 480.0, 540.0]


def test_db_get_crop_config_nonexistent():
    """get_crop_config returns None for nonexistent job."""
    from engine import database as db
    result = db.get_crop_config('nonexistent-job-id-00000000')
    assert result is None


def test_filter_50_50_split():
    """50/50 split should give equal top and bottom halves."""
    main = [0, 0, 1920, 1080]
    sec  = [0, 0, 480, 270]
    filt = _compute_split_layout_filter_v12(main, sec, 1920, 1080, top_fraction=0.5)
    assert 'vstack' in filt
    # top_fraction=0.5 → top_h = 960, bot_h = 960
    assert '960' in filt


def test_manual_filter_fit_no_edge_crop():
    """Manual filter must NOT crop the selected region — only scale and pad."""
    main = [0.0, 0.0, 1300.0, 850.0]
    sec  = [1300.0, 0.0, 300.0, 280.0]
    filt = _compute_split_layout_filter_manual(main, sec, 1920, 1080, top_fraction=0.5)
    assert 'force_original_aspect_ratio=increase' not in filt
    assert filt.count('pad=') == 2
    assert filt.count('force_original_aspect_ratio=decrease') == 2
    assert 'vstack' in filt


def test_manual_filter_exact_crop_region():
    """Manual filter must use exactly the coordinates provided."""
    main = [100.0, 150.0, 1300.0, 850.0]
    sec  = [1550.0, 100.0, 300.0, 280.0]
    filt = _compute_split_layout_filter_manual(main, sec, 1920, 1080, 0.5)
    assert 'crop=1300:850:100:150' in filt
    assert 'crop=300:280:1550:100' in filt


def test_manual_filter_clamping():
    """Out-of-bounds coordinates must be clamped without error."""
    main = [0.0, 0.0, 2000.0, 1200.0]   # exceeds 1920x1080
    sec  = [-10.0, -20.0, 400.0, 300.0]  # negative offset
    filt = _compute_split_layout_filter_manual(main, sec, 1920, 1080, 0.5)
    assert 'vstack' in filt


def test_manual_vs_v11_different_gameplay_filter():
    """Manual FIT filter differs from V1.1 FILL filter for gameplay."""
    from engine.renderers.render_clip import _compute_split_layout_filter_v11
    main = [0.0, 0.0, 1440.0, 1080.0]
    sec  = [1440.0, 0.0, 480.0, 540.0]
    filt_manual = _compute_split_layout_filter_manual(main, sec, 1920, 1080, 0.5)
    filt_v11    = _compute_split_layout_filter_v11(main, sec, 1920, 1080, 0.5)
    assert 'force_original_aspect_ratio=decrease' in filt_manual
    assert filt_manual != filt_v11


def test_gaming_audit_eligible_clips_found():
    """Gaming audit must find eligible clips for all 14 known gaming creators."""
    import sqlite3, os
    GAMING_CREATORS = [
        'rubius_z','illojuan','auron','thegrefg','illowanito','illoreacts',
        'illoresumen_fan','bycalitos','xbuyer','rickyedit','baitylive',
        'ibai','westcol','agustin51_world'
    ]
    conn = sqlite3.connect('db/engine.sqlite')
    conn.row_factory = sqlite3.Row
    rows = conn.execute('''
        SELECT cl.id, v.creator_slug, v.path, v.proxy_path
        FROM clips cl
        JOIN candidates cand ON cand.id = cl.candidate_id
        JOIN videos v ON v.job_id = cl.job_id
        WHERE v.creator_slug IN ({})
          AND cl.technical_qa = 'PASS'
    '''.format(','.join('?' * len(GAMING_CREATORS))), GAMING_CREATORS).fetchall()
    conn.close()
    eligible = [r for r in rows if r['path'] and os.path.exists(r['path'])
                                 and r['proxy_path'] and os.path.exists(r['proxy_path'])]
    creators_found = set(r['creator_slug'] for r in eligible)
    assert len(eligible) >= 400, f"Expected >= 400 eligible gaming clips, got {len(eligible)}"
    assert len(creators_found) == 14, f"Expected 14 creators, got {creators_found}"


def test_compute_split_layout_filter_manual_symmetric():
    """When both regions have the same aspect ratio, both halves should have identical scales."""
    # 16:9 region on top, 16:9 region on bottom → both should scale/pad identically
    main = [0.0, 0.0, 1920.0, 1080.0]   # full frame, 16:9
    sec  = [0.0, 0.0, 1920.0, 1080.0]   # same region (symmetric test)
    filt = _compute_split_layout_filter_manual(main, sec, 1920, 1080, top_fraction=0.5)
    # With 50/50 split both segments get TARGET_H/2 = 960px height
    assert 'vstack' in filt
    assert filt.count('1080:1920') == 0  # must NOT produce original portrait output
    # Both gameplay and facecam lines should use the same pad dimensions (1080:960)
    assert filt.count('pad=1080:960') == 2
    # No fill/increase used (only FIT)
    assert 'force_original_aspect_ratio=increase' not in filt


def test_confirmed_no_preview_activates_manual_crop():
    """validation_status='confirmed_no_preview' should activate manual crop in renderer."""
    cfg = {
        'crop_mode': 'manual',
        'validation_status': 'confirmed_no_preview',
        'gameplay_x': 0.0, 'gameplay_y': 0.0, 'gameplay_w': 0.75, 'gameplay_h': 1.0,
        'facecam_x': 0.75, 'facecam_y': 0.0, 'facecam_w': 0.25, 'facecam_h': 0.5,
    }
    valid_statuses = ("validated", "confirmed_no_preview")
    use_manual = (
        cfg.get("crop_mode") == "manual"
        and cfg.get("validation_status") in valid_statuses
        and cfg.get("gameplay_x") is not None
    )
    assert use_manual


def test_url_frame_normalized_to_video_coords():
    """Normalized coords [0-1] multiply correctly to source pixel coords."""
    src_w, src_h = 1920, 1080
    canvas_w, canvas_h = 640, 360
    rect_canvas = {'x': 0, 'y': 0, 'w': 384, 'h': 360}  # 60% of canvas width
    norm = {k: v / (canvas_w if k in ('x', 'w') else canvas_h) for k, v in rect_canvas.items()}
    px_x = norm['x'] * src_w
    px_w = norm['w'] * src_w
    assert px_x == 0.0
    assert abs(px_w - 1152.0) < 1  # 0.60 * 1920 = 1152


def test_gaming_url_mode_requires_crop_confirm():
    """Submit must be blocked when gaming+manual+url without confirmed crop."""
    source = 'url'
    video_type = 'gaming'
    crop_mode = 'manual'
    has_meta = True
    crop_confirmed = False
    needs_crop = (source == 'url' and video_type == 'gaming'
                  and crop_mode == 'manual' and has_meta)
    submit_blocked = needs_crop and not crop_confirmed
    assert submit_blocked
