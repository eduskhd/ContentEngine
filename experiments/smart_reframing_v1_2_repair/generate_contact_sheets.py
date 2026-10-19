"""Generate contact sheets — 3 columns × 5 rows PNG per clip.

Columns: Original  |  V1.1  |  V1.2 Repair
Rows:    5 evenly-spaced frames sampled from the clip.

Output: experiments/smart_reframing_v1_2_repair/contact_sheets/{clip_name}_contact.png

Dependencies: opencv-python, numpy (already required by the main project)

Usage:
  python experiments/smart_reframing_v1_2_repair/generate_contact_sheets.py
  python experiments/smart_reframing_v1_2_repair/generate_contact_sheets.py --clip AuronPlay_9e003b08
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

# ── Config ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent.parent
EXP_DIR   = Path(__file__).parent

VARIANTS = [
    ("Original",    EXP_DIR / "clips" / "original"),
    ("V1.1",        EXP_DIR / "clips" / "v1_1"),
    ("V1.2 Repair", EXP_DIR / "clips" / "v1_2_repair"),
]

OUT_DIR   = EXP_DIR / "contact_sheets"
THUMB_W   = 360
THUMB_H   = 640   # 9:16
N_ROWS    = 5
LABEL_H   = 40
HEADER_H  = 60
PAD       = 8
BG_COLOR  = (20, 20, 20)
TEXT_COLOR = (220, 220, 220)
LABEL_COLORS = {
    "Original":    (60, 80, 140),
    "V1.1":        (60, 120, 60),
    "V1.2 Repair": (120, 80, 160),
}

_SUFFIXES = {
    "Original":    "_original",
    "V1.1":        "_v1_1",
    "V1.2 Repair": "_v1_2_repair",
}


# ── Frame extraction ───────────────────────────────────────────────────────────

def _extract_frames(path: str, n: int = N_ROWS) -> list[np.ndarray]:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return []
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total <= 0:
        cap.release()
        return []

    indices = [int(i * (total - 1) / (n - 1)) for i in range(n)]
    frames = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret:
            frames.append(frame)
        else:
            frames.append(np.zeros((THUMB_H, THUMB_W, 3), dtype=np.uint8))
    cap.release()
    return frames


def _resize_to_thumb(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= 0 or h <= 0:
        return np.zeros((THUMB_H, THUMB_W, 3), dtype=np.uint8)
    scale = THUMB_W / w
    nw, nh = THUMB_W, int(h * scale)
    if nh < THUMB_H:
        scale = THUMB_H / h
        nw, nh = int(w * scale), THUMB_H
    resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
    y0 = (nh - THUMB_H) // 2
    x0 = (nw - THUMB_W) // 2
    return resized[y0:y0 + THUMB_H, x0:x0 + THUMB_W]


def _placeholder(label: str = "NOT FOUND") -> np.ndarray:
    thumb = np.full((THUMB_H, THUMB_W, 3), 40, dtype=np.uint8)
    cv2.putText(thumb, label, (10, THUMB_H // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 100), 1)
    return thumb


# ── Sheet builder ──────────────────────────────────────────────────────────────

def _make_label_bar(label: str, w: int = THUMB_W, h: int = LABEL_H) -> np.ndarray:
    bar = np.full((h, w, 3), LABEL_COLORS.get(label, (50, 50, 50)), dtype=np.uint8)
    (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, 0.7, 1)
    x = (w - text_w) // 2
    y = (h + text_h) // 2
    cv2.putText(bar, label, (x, y), cv2.FONT_HERSHEY_DUPLEX, 0.7, TEXT_COLOR, 1, cv2.LINE_AA)
    return bar


def _make_header(clip_name: str, total_w: int) -> np.ndarray:
    bar = np.full((HEADER_H, total_w, 3), (35, 35, 35), dtype=np.uint8)
    title = f"Smart Reframing V1.2 Repair — {clip_name}"
    (tw, th), _ = cv2.getTextSize(title, cv2.FONT_HERSHEY_DUPLEX, 0.60, 1)
    x = max(0, (total_w - tw) // 2)
    y = (HEADER_H + th) // 2
    cv2.putText(bar, title, (x, y), cv2.FONT_HERSHEY_DUPLEX, 0.60, (255, 200, 80), 1, cv2.LINE_AA)
    return bar


def _add_frame_number(thumb: np.ndarray, row: int, n: int) -> np.ndarray:
    out = thumb.copy()
    label = f"frame {row}/{n}"
    cv2.putText(out, label, (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3)
    cv2.putText(out, label, (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    return out


def build_contact_sheet(clip_name: str, variant_paths: dict[str, str | None]) -> np.ndarray:
    n_cols = len(VARIANTS)
    col_w = THUMB_W + PAD
    total_w = col_w * n_cols - PAD

    all_frames: dict[str, list[np.ndarray]] = {}
    for label, _ in VARIANTS:
        path = variant_paths.get(label)
        if path and Path(path).exists():
            frames = _extract_frames(path)
            while len(frames) < N_ROWS:
                frames.append(_placeholder())
        else:
            frames = [_placeholder(f"{label} NOT FOUND") for _ in range(N_ROWS)]
        all_frames[label] = frames

    header    = _make_header(clip_name, total_w)
    lbars     = [_make_label_bar(lbl) for lbl, _ in VARIANTS]
    pad_strip = np.full((LABEL_H, PAD, 3), BG_COLOR, dtype=np.uint8)
    label_row = lbars[0]
    for lb in lbars[1:]:
        label_row = np.hstack([label_row, pad_strip, lb])

    rows = [header, label_row]
    for row_i in range(N_ROWS):
        row_parts = [_resize_to_thumb(all_frames[lbl][row_i]) for lbl, _ in VARIANTS]
        row_parts[0] = _add_frame_number(row_parts[0], row_i + 1, N_ROWS)
        combined = row_parts[0]
        for t in row_parts[1:]:
            combined = np.hstack([combined, np.full((THUMB_H, PAD, 3), BG_COLOR, dtype=np.uint8), t])
        rows.append(combined)
        if row_i < N_ROWS - 1:
            rows.append(np.full((PAD, total_w, 3), BG_COLOR, dtype=np.uint8))

    return np.vstack(rows)


# ── Clip discovery ─────────────────────────────────────────────────────────────

def _discover_clip_names() -> list[str]:
    names = set()
    for label, d in VARIANTS:
        suf = _SUFFIXES[label]
        if d.exists():
            for p in d.glob("*.mp4"):
                if p.stem.endswith(suf):
                    names.add(p.stem[: -len(suf)])
    return sorted(names)


def _find_variant_path(name: str, label: str, d: Path) -> str | None:
    suf = _SUFFIXES[label]
    path = d / f"{name}{suf}.mp4"
    return str(path) if path.exists() else None


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="V1.2 Repair contact sheet generator")
    parser.add_argument("--clip", help="Only this clip name prefix")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    names = _discover_clip_names()

    if not names:
        print(f"[ERROR] No clips found in {EXP_DIR / 'clips'}")
        sys.exit(1)

    if args.clip:
        names = [n for n in names if args.clip in n]

    print(f"Generating contact sheets for {len(names)} clips")
    for name in names:
        print(f"  {name} ... ", end="", flush=True)
        variant_paths = {label: _find_variant_path(name, label, d) for label, d in VARIANTS}
        sheet = build_contact_sheet(name, variant_paths)
        out_path = OUT_DIR / f"{name}_contact.png"
        cv2.imwrite(str(out_path), sheet)
        size_kb = out_path.stat().st_size // 1024
        print(f"OK  {out_path.name} ({size_kb} KB)")

    print("Done.")


if __name__ == "__main__":
    main()
