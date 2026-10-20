"""
Phase 2: Generate BEFORE/AFTER comparison renders for 3 gaming jobs.

BEFORE: denormalize using crop_config.src_width (1280) — the old bug
AFTER:  denormalize using actual video dims (1920)    — the fix

For each job, renders a 10-second clip at a representative timestamp.
Outputs: contact_sheets/ with side-by-side frames, renders/ with MP4s.
"""
import subprocess, sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.renderers.render_clip import (
    _compute_stacked_fit_filter,
    TARGET_W, TARGET_H,
)

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

OUT = Path(__file__).parent
RENDERS = OUT / "renders"
SHEETS  = OUT / "contact_sheets"
RENDERS.mkdir(exist_ok=True)
SHEETS.mkdir(exist_ok=True)

JOBS = [
    {
        "label": "illojuan_unban",
        "source": r"C:\Users\edupo\Desktop\ContentEngine\output\downloads\illowanillo_dk86z8_vhhs.mp4",
        "src_w": 1920, "src_h": 1080,
        "gp_norm": [0.166, 0.009, 0.771, 0.950],
        "fc_norm": [0.006, 0.009, 0.154, 0.251],
        "preview_w": 1280, "preview_h": 720,
        "split_fraction": 0.65,
        "t_start": 270.0, "duration": 10.0,
    },
    {
        "label": "illojuan_velada",
        "source": r"C:\Users\edupo\Desktop\ContentEngine\output\downloads\illowanillo_8zup_jkbdwa.mp4",
        "src_w": 1920, "src_h": 1080,
        "gp_norm": [0.198, 0.003, 0.807, 0.997],
        "fc_norm": [0.002, 0.405, 0.193, 0.305],
        "preview_w": 1280, "preview_h": 720,
        "split_fraction": 0.65,
        "t_start": 175.0, "duration": 10.0,
    },
    {
        "label": "illojuan_gta6",
        "source": r"C:\Users\edupo\Desktop\ContentEngine\output\downloads\illojuan_y7jtmhipine.mp4",
        "src_w": 1920, "src_h": 1080,
        "gp_norm": [0.197, 0.049, 0.802, 0.866],
        "fc_norm": [0.006, 0.404, 0.188, 0.300],
        "preview_w": 1280, "preview_h": 720,
        "split_fraction": 0.65,
        "t_start": 145.0, "duration": 10.0,
    },
]


def norm_to_px(norm, w, h):
    x, y, nw, nh = norm
    return [x*w, y*h, nw*w, nh*h]


def build_filter(gp_px, fc_px, src_w, src_h, split_fraction):
    return _compute_stacked_fit_filter(gp_px, fc_px, src_w, src_h,
                                       top_fraction=split_fraction, bg="black")


def render_clip(label, source, t_start, duration, filt, out_path):
    is_complex = "[out]" in filt
    if is_complex:
        fg = filt.replace("[out]", "[out]")
        cmd = [FFMPEG, "-y", "-ss", str(t_start), "-t", str(duration),
               "-i", source,
               "-filter_complex", fg,
               "-map", "[out]",
               "-c:v", "libx264", "-crf", "22", "-preset", "fast",
               "-pix_fmt", "yuv420p", "-an",
               str(out_path)]
    else:
        cmd = [FFMPEG, "-y", "-ss", str(t_start), "-t", str(duration),
               "-i", source,
               "-vf", filt,
               "-c:v", "libx264", "-crf", "22", "-preset", "fast",
               "-pix_fmt", "yuv420p", "-an",
               str(out_path)]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if r.returncode != 0:
        print(f"  FFMPEG ERROR for {label}:")
        print(r.stderr.decode(errors="replace")[-300:])
        return False
    return True


def extract_frame(video_path, t, out_jpg):
    cmd = [FFMPEG, "-y", "-ss", str(t), "-i", str(video_path),
           "-frames:v", "1", "-q:v", "2", str(out_jpg)]
    r = subprocess.run(cmd, capture_output=True, timeout=30)
    return r.returncode == 0 and out_jpg.exists()


def side_by_side(frame_before, frame_after, label, out_jpg):
    """Stack two frames horizontally with a 4px white separator."""
    cmd = [FFMPEG, "-y",
           "-i", str(frame_before),
           "-i", str(frame_after),
           "-filter_complex",
           "[0:v]pad=iw+4:ih:0:0:white[p];[p][1:v]hstack=inputs=2[out]",
           "-map", "[out]",
           "-frames:v", "1", "-q:v", "2", str(out_jpg)]
    r = subprocess.run(cmd, capture_output=True, timeout=30)
    return r.returncode == 0


def main():
    results = []

    for job in JOBS:
        label     = job["label"]
        source    = job["source"]
        src_w     = job["src_w"]
        src_h     = job["src_h"]
        prev_w    = job["preview_w"]
        prev_h    = job["preview_h"]
        gp_norm   = job["gp_norm"]
        fc_norm   = job["fc_norm"]
        sf        = job["split_fraction"]
        t_start   = job["t_start"]
        dur       = job["duration"]

        print(f"\n=== {label} ===")
        print(f"  Source: {Path(source).name}")
        print(f"  Actual video: {src_w}x{src_h} | Preview frame: {prev_w}x{prev_h}")

        # BEFORE: denormalize against preview dims (bug)
        gp_before = norm_to_px(gp_norm, prev_w, prev_h)
        fc_before = norm_to_px(fc_norm, prev_w, prev_h)
        filt_before = build_filter(gp_before, fc_before, prev_w, prev_h, sf)
        print(f"  BEFORE gp_px: x={gp_before[0]:.0f} y={gp_before[1]:.0f} w={gp_before[2]:.0f} h={gp_before[3]:.0f} (on {prev_w}x{prev_h} frame!)")

        # AFTER: denormalize against actual dims (fix)
        gp_after  = norm_to_px(gp_norm, src_w, src_h)
        fc_after  = norm_to_px(fc_norm, src_w, src_h)
        filt_after  = build_filter(gp_after, fc_after, src_w, src_h, sf)
        print(f"  AFTER  gp_px: x={gp_after[0]:.0f} y={gp_after[1]:.0f} w={gp_after[2]:.0f} h={gp_after[3]:.0f} (on {src_w}x{src_h} frame)")
        print(f"  Shift: dx={gp_after[0]-gp_before[0]:.0f}px  dw={gp_after[2]-gp_before[2]:.0f}px")

        # Render BEFORE
        out_before = RENDERS / f"{label}_BEFORE.mp4"
        ok_before = render_clip(f"{label}_BEFORE", source, t_start, dur, filt_before, out_before)
        print(f"  BEFORE render: {'OK' if ok_before else 'FAIL'}")

        # Render AFTER
        out_after = RENDERS / f"{label}_AFTER.mp4"
        ok_after = render_clip(f"{label}_AFTER", source, t_start, dur, filt_after, out_after)
        print(f"  AFTER  render: {'OK' if ok_after else 'FAIL'}")

        # Extract frames at t=5s into the clip
        frame_t = 5.0
        jpg_before = SHEETS / f"{label}_BEFORE_frame.jpg"
        jpg_after  = SHEETS / f"{label}_AFTER_frame.jpg"
        sbs_jpg    = SHEETS / f"{label}_SBS.jpg"

        fb_ok = extract_frame(out_before, frame_t, jpg_before) if ok_before else False
        fa_ok = extract_frame(out_after, frame_t, jpg_after) if ok_after else False

        sbs_ok = False
        if fb_ok and fa_ok:
            sbs_ok = side_by_side(jpg_before, jpg_after, label, sbs_jpg)
            print(f"  Side-by-side: {'OK' if sbs_ok else 'FAIL'} -> {sbs_jpg.name}")

        results.append({
            "label": label,
            "gp_shift_x": round(gp_after[0] - gp_before[0], 1),
            "gp_shift_w": round(gp_after[2] - gp_before[2], 1),
            "before_ok": ok_before, "after_ok": ok_after, "sbs_ok": sbs_ok,
        })

    print("\n\n=== SUMMARY ===")
    for r in results:
        status = "OK" if (r["before_ok"] and r["after_ok"] and r["sbs_ok"]) else "PARTIAL"
        print(f"  {status} {r['label']}: x_shift={r['gp_shift_x']}px  w_shift={r['gp_shift_w']}px")

    # Write manifest
    (OUT / "LAYOUT_COMPARISON.md").write_text(
        _make_comparison_md(results), encoding="utf-8"
    )
    print("\nWrote LAYOUT_COMPARISON.md")


def _make_comparison_md(results):
    lines = [
        "# Layout Comparison — BEFORE vs AFTER RC1 Fix",
        f"**Date:** 2026-10-20\n",
        "## What changed",
        "BEFORE: denormalize using `crop_config.src_width = 1280` (720p preview) on a 1920×1080 video.",
        "AFTER:  denormalize using `src_w = 1920` (actual video dimensions from pipeline).\n",
        "## Per-job crop shift\n",
        "| Job | GP x shift | GP w shift | Status |",
        "|---|---|---|---|",
    ]
    for r in results:
        status = "✓" if (r["before_ok"] and r["after_ok"]) else "partial"
        lines.append(f"| {r['label']} | +{r['gp_shift_x']}px | +{r['gp_shift_w']}px | {status} |")

    lines += [
        "",
        "## Contact sheets",
        "Side-by-side frames in `contact_sheets/`:",
    ]
    for r in results:
        if r["sbs_ok"]:
            lines.append(f"- `{r['label']}_SBS.jpg` — left=BEFORE, right=AFTER")

    lines += [
        "",
        "## Interpretation",
        "- BEFORE: gameplay crop starts too far left, too narrow — wrong region shown",
        "- AFTER: correct proportional region — what the user drew in New Job",
        "- For 1920×1080 source with 720p preview: shift = norm_x × (1920-1280) pixels",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
