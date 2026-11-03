"""Gaming Crop V3 — A/B render comparison.

A = old behavior: full source frame [0,0,src_w,src_h] for BOTH panels (broken)
B = fixed behavior: actual gameplay/facecam regions from crop_config

Usage: python audits/gaming_crop_v3/_render_ab.py
"""
from __future__ import annotations
import sys, time, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from engine.config import CONFIG
from engine.database import db, get_crop_config
from integrations.concat.adapter import ConcatAdapter, ConcatRenderRequest
from integrations.concat.edit_plan import EditPlan

OUT_DIR = Path(__file__).parent / "renders"
OUT_DIR.mkdir(exist_ok=True)

# Benchmark clips: one per gaming job, diverse region configs
BENCHMARK = [
    "519cb869-6e44-4dd4-ba08-67e0f9e97a07",  # job=efb141e5 gameplay=[0,11,352,328]
    "24bb4817-a5ef-4ca8-9c0c-e0e05b38a851",  # job=76b44f42 gameplay=[0,11,427,356]
    "0a4b9fab-6ed2-4d46-b7d8-75e8ccfaa0e8",  # job=36499131 gameplay=[36,441,290,312]
]

def get_full_clip_id(prefix: str) -> str:
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM clips WHERE id LIKE ?", (prefix + "%",)
        ).fetchone()
    if not row:
        raise ValueError(f"Clip not found with prefix: {prefix}")
    return row[0]


def render_a_broken(plan: EditPlan, out_path: str) -> dict:
    """Render with full-frame regions (old broken behavior)."""
    adapter = ConcatAdapter(
        cli_path=CONFIG.concat_exe_path,
        projects_dir=CONFIG.concat_projects_dir,
    )
    req = plan.to_concat_request()
    req.output_path = out_path
    # Overwrite regions with full frame (simulate old broken behavior)
    req.main_region = None
    req.secondary_region = None
    t0 = time.monotonic()
    result = adapter.render(req)
    elapsed = time.monotonic() - t0
    size_kb = Path(out_path).stat().st_size // 1024
    return {
        "variant": "A_broken",
        "output_path": out_path,
        "main_region": "full_frame",
        "secondary_region": "full_frame",
        "render_s": round(elapsed, 1),
        "size_kb": size_kb,
        "engine_version": result.engine_version,
        "width": result.width,
        "height": result.height,
    }


def render_b_fixed(plan: EditPlan, out_path: str) -> dict:
    """Render with actual regions from crop_config (fixed behavior)."""
    adapter = ConcatAdapter(
        cli_path=CONFIG.concat_exe_path,
        projects_dir=CONFIG.concat_projects_dir,
    )
    req = plan.to_concat_request()
    req.output_path = out_path
    t0 = time.monotonic()
    result = adapter.render(req)
    elapsed = time.monotonic() - t0
    size_kb = Path(out_path).stat().st_size // 1024
    return {
        "variant": "B_fixed",
        "output_path": out_path,
        "main_region": plan.main_region,
        "secondary_region": plan.secondary_region,
        "gaming_top_ratio": plan.gaming_top_ratio,
        "render_s": round(elapsed, 1),
        "size_kb": size_kb,
        "engine_version": result.engine_version,
        "width": result.width,
        "height": result.height,
    }


def main():
    results = []
    for i, clip_prefix in enumerate(BENCHMARK):
        clip_id = clip_prefix  # already full UUIDs
        print(f"\n[{i+1}/{len(BENCHMARK)}] clip={clip_id[:8]}")

        try:
            plan = EditPlan.from_clip(clip_id, render_engine="concat", edit_method="experimental")
        except ValueError as e:
            # Try as prefix
            try:
                full_id = get_full_clip_id(clip_id[:8])
                plan = EditPlan.from_clip(full_id, render_engine="concat", edit_method="experimental")
                clip_id = full_id
            except Exception as e2:
                print(f"  SKIP: {e2}")
                continue

        print(f"  duration={plan.duration_s:.1f}s crop_preset={plan.crop_preset}")
        print(f"  main_region={plan.main_region}")
        print(f"  secondary_region={plan.secondary_region}")

        out_a = str(OUT_DIR / f"clip_{i+1:02d}_A_broken.mp4")
        out_b = str(OUT_DIR / f"clip_{i+1:02d}_B_fixed.mp4")

        print(f"  Rendering A (broken, full-frame)...")
        try:
            info_a = render_a_broken(plan, out_a)
            print(f"    OK {info_a['size_kb']}KB in {info_a['render_s']}s")
        except Exception as e:
            print(f"    FAIL: {e}")
            info_a = {"variant": "A_broken", "error": str(e)}

        print(f"  Rendering B (fixed, actual regions)...")
        try:
            info_b = render_b_fixed(plan, out_b)
            print(f"    OK {info_b['size_kb']}KB in {info_b['render_s']}s")
        except Exception as e:
            print(f"    FAIL: {e}")
            info_b = {"variant": "B_fixed", "error": str(e)}

        results.append({
            "clip_id": clip_id,
            "clip_idx": i + 1,
            "A": info_a,
            "B": info_b,
        })

    # Save results
    report_path = OUT_DIR / "ab_results.json"
    with open(report_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved: {report_path}")
    print(f"Renders: {OUT_DIR}")


if __name__ == "__main__":
    main()
