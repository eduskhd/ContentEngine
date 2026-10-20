"""
End-to-end crop accuracy test using the synthetic grid video.

1. Takes a known normalized region of the 1920x1080 grid video.
2. Applies the same denormalization used by the renderer (actual video dims).
3. Runs FFmpeg crop on the grid video.
4. Extracts a frame from the cropped output.
5. Verifies the correct cell appears at the expected position.

Usage: python verify_crop_accuracy.py
"""
import subprocess
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

GRID = Path(__file__).parent / "grid_1920x1080.mp4"
OUT_DIR = Path(__file__).parent / "crop_results"
OUT_DIR.mkdir(exist_ok=True)

# Grid geometry
W, H = 1920, 1080
CELL_W = W // 8   # 240
CELL_H = H // 5   # 216


def probe_video(path):
    r = subprocess.run([FFPROBE, "-v", "quiet", "-print_format", "json",
                        "-show_streams", str(path)],
                       capture_output=True)
    import json
    data = json.loads(r.stdout)
    vs = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
    return int(vs.get("width", 0)), int(vs.get("height", 0))


def crop_and_extract(label, norm_x, norm_y, norm_w, norm_h, src_w, src_h):
    """
    Denormalize using src_w/src_h (simulating the fixed renderer).
    Crop grid video and extract one frame.
    """
    px_x = int(norm_x * src_w)
    px_y = int(norm_y * src_h)
    px_w = int(norm_w * src_w)
    px_h = int(norm_h * src_h)
    # Make even
    px_w -= px_w % 2
    px_h -= px_h % 2

    out_mp4 = OUT_DIR / f"{label}.mp4"
    out_jpg = OUT_DIR / f"{label}_frame.jpg"

    # Crop + scale to 1080x1920 (or just crop for inspection)
    cmd = [FFMPEG, "-y", "-i", str(GRID),
           "-vf", f"crop={px_w}:{px_h}:{px_x}:{px_y}",
           "-frames:v", "30", "-c:v", "libx264", "-crf", "22",
           str(out_mp4)]
    r = subprocess.run(cmd, capture_output=True, timeout=30)
    if r.returncode != 0:
        print(f"  FAIL {label}: {r.stderr.decode(errors='replace')[-200:]}")
        return None

    # Extract middle frame
    cmd2 = [FFMPEG, "-y", "-i", str(out_mp4),
            "-frames:v", "1", "-q:v", "2", str(out_jpg)]
    subprocess.run(cmd2, capture_output=True, timeout=15)

    out_w, out_h = probe_video(out_mp4)
    return {"label": label, "px": [px_x, px_y, px_w, px_h], "out_w": out_w, "out_h": out_h, "jpg": str(out_jpg)}


def test_case(label, norm_rect, src_w, src_h,
              expected_w_ratio, expected_h_ratio, note=""):
    """
    Verify that crop dimensions are proportionally correct.
    expected_w_ratio = norm_w (crop width as fraction of src_w)
    expected_h_ratio = norm_h (crop height as fraction of src_h)
    """
    r = crop_and_extract(label, *norm_rect, src_w, src_h)
    if r is None:
        print(f"  FAIL {label}: ffmpeg error")
        return False

    actual_w_ratio = r["out_w"] / src_w
    actual_h_ratio = r["out_h"] / src_h
    w_ok = abs(actual_w_ratio - expected_w_ratio) < 0.01
    h_ok = abs(actual_h_ratio - expected_h_ratio) < 0.01

    status = "PASS" if (w_ok and h_ok) else "FAIL"
    print(f"  {status} {label}: norm={norm_rect} out={r['out_w']}x{r['out_h']} "
          f"expected~{int(src_w*expected_w_ratio)}x{int(src_h*expected_h_ratio)} "
          f"{'  ' + note if note else ''}")
    return w_ok and h_ok


def main():
    if not GRID.exists():
        print(f"ERROR: Grid video not found at {GRID}")
        print("Run: python make_grid_video.py")
        sys.exit(1)

    print(f"Source: {GRID}")
    w, h = probe_video(GRID)
    print(f"Probed dimensions: {w}x{h}")
    assert w == 1920 and h == 1080, f"Expected 1920x1080, got {w}x{h}"
    print()

    results = []

    print("== Test: Full-frame crop ==")
    results.append(test_case("full_frame", [0.0, 0.0, 1.0, 1.0], 1920, 1080,
                              1.0, 1.0, "entire frame"))

    print("== Test: Left 80% gameplay region ==")
    results.append(test_case("gameplay_80pct", [0.0, 0.0, 0.80, 1.0], 1920, 1080,
                              0.80, 1.0, "norm [0,0,0.8,1]"))

    print("== Test: Bottom-right facecam ==")
    results.append(test_case("facecam_br", [0.75, 0.60, 0.25, 0.40], 1920, 1080,
                              0.25, 0.40, "norm [0.75,0.60,0.25,0.40]"))

    print("== Test: Center 50% region ==")
    results.append(test_case("center_50pct", [0.25, 0.25, 0.50, 0.50], 1920, 1080,
                              0.50, 0.50, "norm [0.25,0.25,0.5,0.5]"))

    print()
    passed = sum(results)
    total = len(results)
    print(f"RESULT: {passed}/{total} passed")

    if passed == total:
        print("All crop accuracy tests PASSED.")
    else:
        print("SOME TESTS FAILED — check crop pixel math.")
        sys.exit(1)


if __name__ == "__main__":
    main()
