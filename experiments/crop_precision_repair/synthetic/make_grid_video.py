"""
Generate a 1920x1080 synthetic reference video with a coloured grid.
No drawtext — avoids fontconfig dependency on Windows.
Corner markers: red TL, green TR, blue BL, yellow BR.
Each cell has a distinct colour. Grid lines every 240x216 pixels.

Output: experiments/crop_precision_repair/synthetic/grid_1920x1080.mp4
"""
import subprocess
import sys
from pathlib import Path
import colorsys

W, H = 1920, 1080
COLS, ROWS = 8, 5   # 240x216 cells
FPS = 30
DURATION = 10

OUT_DIR = Path(__file__).parent
OUT_PATH = OUT_DIR / "grid_1920x1080.mp4"
FFMPEG = "ffmpeg"


def _hex(col, row):
    h = ((col * ROWS + row) / (COLS * ROWS)) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.75, 0.85)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def main():
    cell_w = W // COLS  # 240
    cell_h = H // ROWS  # 216

    parts = []

    # Coloured cells
    for row in range(ROWS):
        for col in range(COLS):
            x, y = col * cell_w, row * cell_h
            c = _hex(col, row)
            parts.append(f"drawbox=x={x}:y={y}:w={cell_w}:h={cell_h}:color={c}@0.85:t=fill")

    # Grid lines (vertical)
    for col in range(1, COLS):
        parts.append(f"drawbox=x={col*cell_w}:y=0:w=2:h={H}:color=white@0.5:t=fill")

    # Grid lines (horizontal)
    for row in range(1, ROWS):
        parts.append(f"drawbox=x=0:y={row*cell_h}:w={W}:h=2:color=white@0.5:t=fill")

    # Corner markers 8x8 — red TL, green TR, blue BL, yellow BR
    for cx, cy, color in [(0, 0, "red"), (W-8, 0, "lime"), (0, H-8, "blue"), (W-8, H-8, "yellow")]:
        parts.append(f"drawbox=x={cx}:y={cy}:w=8:h=8:color={color}:t=fill")

    # Centre crosshair
    cx, cy = W // 2, H // 2
    parts.append(f"drawbox=x={cx-1}:y={cy-20}:w=2:h=40:color=white:t=fill")
    parts.append(f"drawbox=x={cx-20}:y={cy-1}:w=40:h=2:color=white:t=fill")

    vf = ",".join(parts)

    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi",
        "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={DURATION}",
        "-vf", vf,
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-pix_fmt", "yuv420p",
        str(OUT_PATH),
    ]

    print("Generating grid video...")
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if r.returncode != 0:
        print("FFMPEG FAILED:")
        print(r.stderr.decode(errors="replace")[-600:])
        sys.exit(1)
    sz = OUT_PATH.stat().st_size // 1024
    print(f"Done: {OUT_PATH} ({sz} KB)")


if __name__ == "__main__":
    main()
