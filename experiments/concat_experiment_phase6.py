"""Phase 6: 12-clip Concat experiment.

Renders 4 gaming + 4 reactions + 4 dynamic clips via Concat and saves
results to clip_variants table for comparison with FFmpeg originals.

Usage:
    python experiments/concat_experiment_phase6.py
    python experiments/concat_experiment_phase6.py --dry-run
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.config import CONFIG
from engine.database import create_clip_variant, update_clip_variant, db, get_clip

# ── Clip selection ────────────────────────────────────────────────────────────
EXPERIMENT_CLIPS = {
    "gaming": [
        "e2c937a1-85ef-44d5-9602-2943701356d0",  # xbuyer  start=0s  30s
        "26ad5ece-9948-4a1e-8782-9cdafa1b922c",  # xbuyer  start=0s  30s
        "cfe25b1a-6176-4c81-b69b-f35095102398",  # xbuyer  start=0s  60s
        "697e287d-5807-4b0f-8d65-e6ec1472e245",  # ibai    start=40s 30s
    ],
    "reactions": [
        "8bdcb954-2350-406b-a12c-09f18c5320fa",  # mrbeast start=19s 34s
        "36b553de-cf9e-49d1-9f73-0c857b8bea85",  # rickyedit start=23s 45s
        "c965427f-8ef1-4751-9814-58682b7c55d8",  # mrbeast start=29s 15s
        "cb33b5b8-1188-469b-aa84-7a0e66a91935",  # mrbeast start=19s 34s
    ],
    "dynamic": [
        "cbda7aff-dd77-47b4-970d-1f8b784296f0",  # godeik    start=47s 48s
        "7c4ba4b4-d897-4d26-8a42-2b66e5d96972",  # bycalitos start=76s 38s
        "0b2a24a5-cecd-45c2-a0d4-996176f2d0f1",  # bycalitos start=91s 15s
        "507c2958-fa30-47c4-8681-7742ebe107d6",  # bycalitos start=91s 37s
    ],
}


def _resolve_clip(clip_id: str):
    """Return (clip, src_path, src_w, src_h, start_s, end_s) or None."""
    with db() as conn:
        row = conn.execute(
            """SELECT v.path, v.width, v.height, ca.start_s, ca.end_s
               FROM candidates ca
               JOIN videos v ON ca.video_id = v.id
               JOIN clips cl ON cl.candidate_id = ca.id
               WHERE cl.id = ?""",
            (clip_id,)
        ).fetchone()
    clip = get_clip(clip_id)
    if not row or not clip:
        return None
    src_path, src_w, src_h, start_s, end_s = row
    if not src_path or not Path(src_path).exists():
        return None
    return clip, str(src_path), int(src_w or 1920), int(src_h or 1080), float(start_s), float(end_s)


def _pre_trim(src_path: str, start_s: float, duration_s: float, out_dir: Path) -> str | None:
    """Extract [start_s, start_s+duration_s] from src_path using ffmpeg -c copy."""
    tmp = tempfile.mktemp(suffix=".mp4", dir=str(out_dir))
    try:
        r = subprocess.run(
            [CONFIG.ffmpeg_path, "-y",
             "-ss", str(start_s),
             "-i", src_path,
             "-t", str(duration_s),
             "-c", "copy",
             "-avoid_negative_ts", "1",
             tmp],
            capture_output=True, timeout=120,
        )
        if r.returncode == 0 and Path(tmp).exists() and Path(tmp).stat().st_size > 0:
            return tmp
    except Exception as e:
        print(f"    [pre-trim] FAILED: {e}")
    if Path(tmp).exists():
        Path(tmp).unlink(missing_ok=True)
    return None


def render_one(clip_id: str, category: str, dry_run: bool = False) -> dict:
    info = _resolve_clip(clip_id)
    if not info:
        return {"clip_id": clip_id, "status": "SKIP", "reason": "clip/video not found"}

    clip, src_path, src_w, src_h, start_s, end_s = info
    duration_s = end_s - start_s

    print(f"\n  [{category}] {clip_id[:12]}  {src_w}x{src_h}  {start_s:.0f}s->{end_s:.0f}s  ({duration_s:.0f}s)")

    if dry_run:
        print("    [dry-run] skipping render")
        return {"clip_id": clip_id, "status": "DRY_RUN"}

    out_dir = Path(CONFIG.output_dir) / "concat_variants"
    out_dir.mkdir(parents=True, exist_ok=True)

    import uuid
    variant_id = str(uuid.uuid4())
    variant_path = str(out_dir / f"{variant_id}.mp4")

    create_clip_variant(
        clip_id=clip_id,
        render_engine="concat",
        output_path=variant_path,
        engine_version="0.2.8",
        edit_method="concat-cli-api-phase6",
        duration_s=duration_s,
        width=clip.get("width") or 1080,
        height=clip.get("height") or 1920,
    )

    # Pre-trim with ffmpeg so Concat gets a short file (no long-range seeking)
    t0 = time.monotonic()
    tmp_seg = _pre_trim(src_path, start_s, duration_s, out_dir)
    actual_src = tmp_seg if tmp_seg else src_path
    actual_start = 0.0 if tmp_seg else start_s
    pre_trim_s = time.monotonic() - t0
    print(f"    pre-trim: {pre_trim_s:.1f}s -> {Path(actual_src).name[-20:]}")

    try:
        from integrations.concat import get_adapter
        from integrations.concat.adapter import ConcatRenderRequest
        adapter = get_adapter()
        req = ConcatRenderRequest(
            source_path=actual_src,
            output_path=variant_path,
            start_s=actual_start,
            duration_s=duration_s,
            x_offset=0,
            src_w=src_w,
            src_h=src_h,
            canvas_w=clip.get("width") or 1080,
            canvas_h=clip.get("height") or 1920,
            fps=30,
        )
        result = adapter.render(req)
        update_clip_variant(variant_id, render_status="DONE",
                            file_size_bytes=result.file_size_bytes,
                            duration_s=result.duration_s)
        total = time.monotonic() - t0
        print(f"    OK  {result.file_size_bytes//1024}KB  {total:.1f}s total")
        return {"clip_id": clip_id, "variant_id": variant_id,
                "status": "DONE", "render_s": round(total, 1),
                "size_kb": result.file_size_bytes // 1024}
    except Exception as exc:
        update_clip_variant(variant_id, render_status="FAILED", qa_status="FAIL")
        print(f"    FAILED: {exc}")
        return {"clip_id": clip_id, "variant_id": variant_id, "status": "FAILED", "error": str(exc)[:120]}
    finally:
        if tmp_seg and Path(tmp_seg).exists():
            Path(tmp_seg).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--category", choices=["gaming", "reactions", "dynamic"])
    args = parser.parse_args()

    if not CONFIG.concat_enabled:
        print("ERROR: concat_enabled=False in config. Set to True first.")
        sys.exit(1)

    from integrations.concat import concat_available
    if not concat_available():
        print("ERROR: Concat not available (exe not found or not responding).")
        sys.exit(1)

    print("=== Phase 6: Concat 12-Clip Experiment ===")
    print(f"concat-cli: {CONFIG.concat_exe_path}")

    results = {"gaming": [], "reactions": [], "dynamic": []}
    categories = [args.category] if args.category else ["gaming", "reactions", "dynamic"]

    for cat in categories:
        print(f"\n-- {cat.upper()} ---------------------------")
        for clip_id in EXPERIMENT_CLIPS[cat]:
            r = render_one(clip_id, cat, dry_run=args.dry_run)
            results[cat].append(r)

    # Summary
    print("\n=== Results ===")
    total = done = failed = 0
    for cat in categories:
        for r in results[cat]:
            total += 1
            if r["status"] == "DONE": done += 1
            elif r["status"] == "FAILED": failed += 1
            status = r["status"]
            extra = f"  {r.get('render_s','?')}s  {r.get('size_kb','?')}KB" if status == "DONE" else f"  {r.get('error','')}"
            print(f"  [{r['status']:6s}] {cat:10s}  {r['clip_id'][:12]}{extra}")

    print(f"\nDone: {done}/{total}  Failed: {failed}/{total}")


if __name__ == "__main__":
    main()
