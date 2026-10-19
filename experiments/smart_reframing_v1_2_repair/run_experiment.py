"""Smart Reframing V1.2 Repair Experiment.

Fixes applied vs. original V1.2 experiment:
  P1/P2: Uses real 16:9 source files (not 9:16 pre-cropped clips from V1.1 experiment).
  P3:    HUD penalty wired into _optimal_gameplay_region() scoring.
  P4:    Per-segment composition decisions stored in plan["v12"]["segment_decisions"].

Renders 6 clips in 3 variants:
  original      : direct 16:9 -> 9:16 center crop (baseline)
  v1_1          : Smart Reframing V1.1 (plan_clip_v3_1)
  v1_2_repair   : Smart Reframing V1.2 with P3+P4 fixes (plan_clip_v3_2)

Source clips: real 16:9 source files queried from DB by candidate_id.
Feature flag safety: smart_reframing_enabled never changed. No DB writes. No publishing.

Usage:
  python experiments/smart_reframing_v1_2_repair/run_experiment.py
  python experiments/smart_reframing_v1_2_repair/run_experiment.py --clip AuronPlay_9e003b08
  python experiments/smart_reframing_v1_2_repair/run_experiment.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.config import CONFIG

# ── Paths ──────────────────────────────────────────────────────────────────────

REPO_ROOT   = Path(__file__).parent.parent.parent
EXP_DIR     = Path(__file__).parent
ORIG_DIR    = EXP_DIR / "clips" / "original"
V11_DIR     = EXP_DIR / "clips" / "v1_1"
V12R_DIR    = EXP_DIR / "clips" / "v1_2_repair"
MANIFEST    = EXP_DIR / "manifest.json"

FFMPEG  = CONFIG.ffmpeg_path
FFPROBE = CONFIG.ffprobe_path
TARGET_W, TARGET_H = 1080, 1920
DB_PATH = REPO_ROOT / "db" / "engine.sqlite"


# ── Clip registry ──────────────────────────────────────────────────────────────

@dataclass
class ClipSpec:
    name: str
    creator: str
    candidate_id: str   # first 8 chars sufficient for LIKE query
    start_s: float
    end_s: float
    src_path: str = ""
    proxy_path: str = ""
    src_w: int = 1920
    src_h: int = 1080


_CLIP_DEFS = [
    ClipSpec("Rubius_4ffe7a7c",    "rubius",    "4ffe7a7c", 166.33,    201.03),
    ClipSpec("AuronPlay_9e003b08", "auronplay", "9e003b08", 972.44,   1007.70),
    ClipSpec("Rickyedit_2a3e3755", "rickyedit", "2a3e3755", 730.49,    766.51),
    ClipSpec("IlloJuan_04b85e28",  "illojuan",  "04b85e28", 10413.83, 10450.20),
    ClipSpec("IlloJuan_41bd5f73",  "illojuan",  "41bd5f73",  8994.85,  9031.05),
    ClipSpec("IlloJuan_d1378815",  "illojuan",  "d1378815",  8978.85,  9014.93),
]


def _load_clips_from_db() -> list[ClipSpec]:
    specs = []
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        for c in _CLIP_DEFS:
            row = conn.execute(
                "SELECT v.path, v.proxy_path, v.width, v.height "
                "FROM candidates ca JOIN videos v ON ca.video_id = v.id "
                "WHERE ca.id LIKE ?",
                (c.candidate_id + "%",),
            ).fetchone()
            if row:
                c.src_path   = row["path"] or ""
                c.proxy_path = row["proxy_path"] or ""
                c.src_w      = row["width"] or 1920
                c.src_h      = row["height"] or 1080
            specs.append(c)
    return specs


# ── Render helpers ──────────────────────────────────────────────────────────────

def _render_original(spec: ClipSpec, out_path: Path) -> dict:
    if out_path.exists():
        return {"status": "cached", "path": str(out_path)}

    crop_w = int(spec.src_h * TARGET_W / TARGET_H)
    x_off  = (spec.src_w - crop_w) // 2
    dur    = spec.end_s - spec.start_s

    cmd = [
        FFMPEG, "-y",
        "-ss", str(spec.start_s), "-t", str(dur),
        "-i", spec.src_path,
        "-vf", f"crop={crop_w}:{spec.src_h}:{x_off}:0,scale={TARGET_W}:{TARGET_H}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        str(out_path),
    ]
    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = round(time.time() - t0, 2)
    if result.returncode == 0:
        return {"status": "ok", "path": str(out_path), "render_s": elapsed}
    return {"status": "error", "error": result.stderr[-500:]}


def _render_v11(spec: ClipSpec, out_path: Path) -> dict:
    if out_path.exists():
        return {"status": "cached", "path": str(out_path)}
    if not spec.proxy_path or not Path(spec.proxy_path).exists():
        return {"status": "error", "error": "proxy not found"}

    from engine.reframe.planner import plan_clip_v3_1
    from engine.renderers.render_clip import _compute_split_layout_filter_v11

    t0 = time.time()
    plan = plan_clip_v3_1(spec.proxy_path, spec.start_s, spec.end_s,
                          spec.src_w, spec.src_h)
    plan_s = round(time.time() - t0, 2)
    dur = spec.end_s - spec.start_s
    mode = plan.get("composition_mode", "center")

    if mode == "split_layout" and plan.get("main_region") and plan.get("secondary_region"):
        vf = _compute_split_layout_filter_v11(
            plan["main_region"], plan["secondary_region"],
            spec.src_w, spec.src_h, top_fraction=0.60,
        )
        cmd = [
            FFMPEG, "-y",
            "-ss", str(spec.start_s), "-t", str(dur),
            "-i", spec.src_path,
            "-filter_complex", vf,
            "-map", "[out]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            str(out_path),
        ]
    else:
        x_off  = plan.get("x_offset", (spec.src_w - int(spec.src_h * TARGET_W / TARGET_H)) // 2)
        crop_w = int(spec.src_h * TARGET_W / TARGET_H)
        cmd = [
            FFMPEG, "-y",
            "-ss", str(spec.start_s), "-t", str(dur),
            "-i", spec.src_path,
            "-vf", f"crop={crop_w}:{spec.src_h}:{x_off}:0,scale={TARGET_W}:{TARGET_H}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            str(out_path),
        ]

    t1 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    render_s = round(time.time() - t1, 2)
    if result.returncode == 0:
        return {"status": "ok", "path": str(out_path),
                "plan_s": plan_s, "render_s": render_s,
                "mode": mode, "filter_version": "v11"}
    return {"status": "error", "error": result.stderr[-500:]}


def _render_v12_repair(spec: ClipSpec, out_path: Path) -> dict:
    if out_path.exists():
        return {"status": "cached", "path": str(out_path)}
    if not spec.proxy_path or not Path(spec.proxy_path).exists():
        return {"status": "error", "error": "proxy not found"}

    from engine.reframe.planner import plan_clip_v3_2
    from engine.renderers.render_clip import _compute_split_layout_filter_v12

    t0 = time.time()
    plan = plan_clip_v3_2(spec.proxy_path, spec.start_s, spec.end_s,
                          spec.src_w, spec.src_h)
    plan_s = round(time.time() - t0, 2)

    if "v12_error" in plan:
        print(f"\n    [WARN] V1.2 scene analysis failed: {plan['v12_error']}")
        print(f"    [INFO] Falling back to V1.1 plan")

    dur    = spec.end_s - spec.start_s
    mode   = plan.get("composition_mode", "center")
    v12    = plan.get("v12", {})
    split_frac = v12.get("split_fraction", 0.60)

    if mode == "split_layout" and plan.get("main_region") and plan.get("secondary_region"):
        vf = _compute_split_layout_filter_v12(
            plan["main_region"], plan["secondary_region"],
            spec.src_w, spec.src_h, top_fraction=split_frac,
        )
        cmd = [
            FFMPEG, "-y",
            "-ss", str(spec.start_s), "-t", str(dur),
            "-i", spec.src_path,
            "-filter_complex", vf,
            "-map", "[out]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            str(out_path),
        ]
    else:
        x_off  = plan.get("x_offset", (spec.src_w - int(spec.src_h * TARGET_W / TARGET_H)) // 2)
        crop_w = int(spec.src_h * TARGET_W / TARGET_H)
        cmd = [
            FFMPEG, "-y",
            "-ss", str(spec.start_s), "-t", str(dur),
            "-i", spec.src_path,
            "-vf", f"crop={crop_w}:{spec.src_h}:{x_off}:0,scale={TARGET_W}:{TARGET_H}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k",
            str(out_path),
        ]

    t1 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True)
    render_s = round(time.time() - t1, 2)

    seg_count = len(v12.get("segment_decisions", []))
    hud_count = len(v12.get("hud_regions", []))

    if result.returncode == 0:
        return {
            "status": "ok", "path": str(out_path),
            "plan_s": plan_s, "render_s": render_s,
            "mode": mode, "filter_version": "v12_repair",
            "split_fraction": split_frac,
            "dominant_scene": v12.get("dominant_scene_type", "unknown"),
            "scene_count": len(v12.get("scene_segments", [])),
            "segment_decisions_count": seg_count,
            "hud_count": hud_count,
        }
    return {"status": "error", "error": result.stderr[-500:]}


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Smart Reframing V1.2 Repair Experiment")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--clip", help="Only process this clip name")
    args = parser.parse_args()

    ORIG_DIR.mkdir(parents=True, exist_ok=True)
    V11_DIR.mkdir(parents=True, exist_ok=True)
    V12R_DIR.mkdir(parents=True, exist_ok=True)

    specs = _load_clips_from_db()

    if args.clip:
        specs = [s for s in specs if args.clip in s.name]
        if not specs:
            print(f"[ERROR] No clip matching '{args.clip}'")
            sys.exit(1)

    # Validate all sources exist
    for s in specs:
        if not s.src_path or not Path(s.src_path).exists():
            print(f"[ERROR] Source file missing for {s.name}: {s.src_path}")
            sys.exit(1)
        if not s.proxy_path or not Path(s.proxy_path).exists():
            print(f"[WARN] Proxy missing for {s.name}: {s.proxy_path}")

    if args.dry_run:
        print("=== DRY RUN — no files will be written ===")
        for s in specs:
            print(f"  {s.name}")
            print(f"    src:   {s.src_path}")
            print(f"    proxy: {s.proxy_path}")
            print(f"    range: {s.start_s:.2f}s – {s.end_s:.2f}s ({s.end_s - s.start_s:.1f}s)")
        return

    manifest_clips = []
    total_t0 = time.time()

    for i, spec in enumerate(specs, 1):
        print(f"\n[{i}/{len(specs)}] {spec.name}")
        entry: dict = {"name": spec.name, "creator": spec.creator,
                       "start_s": spec.start_s, "end_s": spec.end_s,
                       "src": spec.src_path, "proxy": spec.proxy_path}

        # Original
        print(f"  original ... ", end="", flush=True)
        r = _render_original(spec, ORIG_DIR / f"{spec.name}_original.mp4")
        print(r["status"], f"({r.get('render_s', 0):.1f}s)" if r["status"] == "ok" else "")
        entry["original"] = r

        # V1.1
        print(f"  v1_1    ... ", end="", flush=True)
        r = _render_v11(spec, V11_DIR / f"{spec.name}_v1_1.mp4")
        print(r["status"], f"({r.get('render_s', 0):.1f}s, mode={r.get('mode','?')})" if r["status"] == "ok" else "")
        entry["v1_1"] = r

        # V1.2 repair
        print(f"  v1_2r   ... ", end="", flush=True)
        r = _render_v12_repair(spec, V12R_DIR / f"{spec.name}_v1_2_repair.mp4")
        if r["status"] == "ok":
            print(f"ok ({r.get('render_s', 0):.1f}s, mode={r.get('mode','?')}, "
                  f"scene={r.get('dominant_scene','?')}, "
                  f"hud={r.get('hud_count',0)}, "
                  f"segs={r.get('segment_decisions_count',0)})")
        else:
            print(r["status"])
        entry["v1_2_repair"] = r

        manifest_clips.append(entry)

    total_s = round(time.time() - total_t0, 1)
    manifest = {
        "experiment": "smart_reframing_v1_2_repair",
        "description": "V1.2 with P1/P2/P3/P4 fixes — 16:9 source inputs, HUD penalty, per-segment decisions",
        "fixes": ["P1_correct_16x9_input", "P2_correct_scene_analysis", "P3_hud_penalty", "P4_segment_decisions"],
        "total_clips": len(specs),
        "total_s": total_s,
        "clips": manifest_clips,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nDone in {total_s:.1f}s. Manifest: {MANIFEST}")


if __name__ == "__main__":
    main()
