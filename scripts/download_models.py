"""Download required model files for the smart reframe feature.

Models downloaded:
  models/blaze_face_full_range.tflite  — MediaPipe BlazeFace (full-range)
  models/pose_landmarker_lite.task     — MediaPipe PoseLandmarker (lite)
  models/yolox_nano.onnx               — YOLOX-nano person detector

Licenses:
  MediaPipe models  — Apache-2.0 (Google LLC)
  YOLOX-nano ONNX   — Apache-2.0 (Megvii, https://github.com/Megvii-BaseDetection/YOLOX)

Run:
  python scripts/download_models.py

Already-present files are skipped unless --force is passed.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
from urllib.request import urlretrieve
from urllib.error import URLError

MODELS_DIR = Path(__file__).parent.parent / "models"

MODELS = [
    {
        "name": "blaze_face_full_range.tflite",
        "url": (
            "https://storage.googleapis.com/mediapipe-models/"
            "face_detector/blaze_face_full_range/float16/1/"
            "blaze_face_full_range.tflite"
        ),
        "license": "Apache-2.0",
        "owner": "Google LLC (MediaPipe)",
        "size_hint": "~1 MB",
    },
    {
        "name": "pose_landmarker_lite.task",
        "url": (
            "https://storage.googleapis.com/mediapipe-models/"
            "pose_landmarker/pose_landmarker_lite/float16/1/"
            "pose_landmarker_lite.task"
        ),
        "license": "Apache-2.0",
        "owner": "Google LLC (MediaPipe)",
        "size_hint": "~5 MB",
    },
    {
        "name": "yolox_nano.onnx",
        "url": (
            "https://github.com/Megvii-BaseDetection/YOLOX/"
            "releases/download/0.1.1rc0/yolox_nano.onnx"
        ),
        "license": "Apache-2.0",
        "owner": "Megvii BaseDetection (YOLOX)",
        "size_hint": "~3 MB",
    },
]


def _progress(block_count: int, block_size: int, total: int) -> None:
    downloaded = block_count * block_size
    if total > 0:
        pct = min(100, downloaded * 100 // total)
        bar = "#" * (pct // 5) + "." * (20 - pct // 5)
        print(f"\r  [{bar}] {pct:3d}%", end="", flush=True)


def download_all(force: bool = False) -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Model directory: {MODELS_DIR}\n")

    any_failed = False
    for spec in MODELS:
        dest = MODELS_DIR / spec["name"]
        if dest.exists() and not force:
            size_kb = dest.stat().st_size // 1024
            print(f"  [skip]  {spec['name']}  ({size_kb} KB already present)")
            continue

        print(f"  [fetch] {spec['name']}  {spec['size_hint']}")
        print(f"          license: {spec['license']}  /  {spec['owner']}")
        print(f"          from:    {spec['url']}")
        try:
            urlretrieve(spec["url"], dest, reporthook=_progress)
            print(f"\n  [ok]    {spec['name']}")
        except (URLError, OSError) as exc:
            print(f"\n  [FAIL]  {spec['name']}: {exc}")
            dest.unlink(missing_ok=True)
            any_failed = True

    print()
    if any_failed:
        print("Some downloads failed.  Check your internet connection and retry.")
        sys.exit(1)
    else:
        print("All models ready.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download smart reframe model files")
    parser.add_argument("--force", action="store_true", help="Re-download even if file exists")
    args = parser.parse_args()
    download_all(force=args.force)
