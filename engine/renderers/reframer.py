"""Auto-reframing: crop/scale clips to 9:16 vertical format."""
import subprocess
from pathlib import Path

from engine.config import CONFIG
from engine import database as db


TARGET_W, TARGET_H = CONFIG.target_resolution  # (1080, 1920)


def reframe_clips(job_id: str, clip_ids: list[str]) -> list[str]:
    reframed = []
    for clip_id in clip_ids:
        # Read metadata (short lock)
        with db.db() as conn:
            row = conn.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()

        if not row or not row["output_path"]:
            continue

        # Run ffmpeg with NO DB connection held
        out_path = _reframe(row["output_path"], row["width"], row["height"])

        # Update DB after ffmpeg completes (short lock)
        if out_path:
            with db.db() as conn:
                conn.execute(
                    "UPDATE clips SET output_path=?, width=?, height=? WHERE id=?",
                    (out_path, TARGET_W, TARGET_H, clip_id)
                )
            reframed.append(clip_id)

    return reframed


def _reframe(input_path: str, src_w: int, src_h: int) -> str:
    out_path = input_path.replace(".mp4", "_9x16.mp4")
    src_ratio = (src_w or 1) / (src_h or 1)
    target_ratio = TARGET_W / TARGET_H

    if abs(src_ratio - target_ratio) < 0.01:
        vf = f"scale={TARGET_W}:{TARGET_H}"
    elif src_ratio > target_ratio:
        new_w = int(src_h * target_ratio)
        x_offset = (src_w - new_w) // 2
        vf = f"crop={new_w}:{src_h}:{x_offset}:0,scale={TARGET_W}:{TARGET_H}"
    else:
        new_h = int(src_w / target_ratio)
        y_offset = (src_h - new_h) // 2
        vf = f"crop={src_w}:{new_h}:0:{y_offset},scale={TARGET_W}:{TARGET_H}"

    cmd = [
        CONFIG.ffmpeg_path, "-y", "-i", input_path,
        "-vf", vf,
        "-c:v", "libx264", "-crf", "20", "-preset", "fast",
        "-c:a", "copy", "-movflags", "+faststart",
        out_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    return out_path if result.returncode == 0 else None
