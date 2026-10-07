"""One-pass clip renderer: trim + reframe + caption burn in a single FFmpeg call.

Replaces the three-step pipeline (clip_generator → reframer → caption_burner)
with a single FFmpeg filter graph, eliminating two intermediate re-encodes.

Pipeline per clip:
  source master
    -ss {start} -t {duration}
    -vf "{crop_scale_filter},ass='{ass}'"
    -c:v {hw_encoder} {hw_opts}
    -c:a aac -b:a 192k
    → final_clip.mp4

Uses hardware encoding (QSV/NVENC) when available; falls back to libx264 veryfast.
Renders clips in parallel (max_parallel_renders from hw_accel.detect_encoder).
"""
import json
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from engine.config import CONFIG
from engine import database as db
from engine.hw_accel import detect_encoder
from engine.captions.extractor import extract_clip_words
from engine.captions.presets import default_settings
from engine.captions.renderer import build_ass
from engine.reframe.planner import plan_clip, plan_clip_v2

TARGET_W, TARGET_H = CONFIG.target_resolution  # (1080, 1920)


# ── Public entry point ────────────────────────────────────────────────────────

_MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB minimum free space before starting renders


def render_clips_onepass(
    job_id: str,
    source: str,
    finalists: list[dict],
    words: list[dict],
    src_w: int,
    src_h: int,
    output_subdir: str = "clips",
    proxy_path: str | None = None,
) -> list[str]:
    """
    Render all finalist clips in a single FFmpeg pass per clip (trim+crop+caption).

    When proxy_path is provided, each clip gets a face-detected framing plan
    that replaces the static center crop with a face-centered x_offset.

    Clips are rendered in parallel up to max_parallel_renders.
    Returns list of clip_ids (DB) for successfully rendered clips,
    ordered by virality_score descending (highest first → user sees best clips first).
    """
    import shutil as _shutil
    out_dir = Path(CONFIG.output_dir) / output_subdir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Fail fast if disk space is critically low — avoids mid-render failures
    try:
        free = _shutil.disk_usage(CONFIG.output_dir).free
        if free < _MIN_FREE_BYTES:
            raise RuntimeError(
                f"STORAGE_INSUFFICIENT: only {free // (1024**3)} GB free on output disk "
                f"(minimum {_MIN_FREE_BYTES // (1024**3)} GB required)"
            )
    except RuntimeError:
        raise
    except Exception:
        pass  # disk_usage failure is non-fatal — proceed and let FFmpeg report errors

    encoder, enc_opts, max_par = detect_encoder()
    caption_settings = dict(default_settings())

    # Build render tasks; sort by virality so highest-score clips render first
    tasks = []
    for i, cand in enumerate(finalists):
        out_path = str(out_dir / f"clip{i+1:02d}_final.mp4")
        tasks.append((i, cand, out_path))

    clip_ids: list[tuple[int, str]] = []  # (index, clip_id)

    with ThreadPoolExecutor(max_workers=max_par) as pool:
        future_map = {
            pool.submit(
                _render_one,
                source, cand, out_path, words, caption_settings,
                encoder, enc_opts, job_id, src_w, src_h, proxy_path,
            ): (idx, cand)
            for idx, cand, out_path in tasks
        }

        for future in as_completed(future_map):
            idx, cand = future_map[future]
            try:
                clip_id = future.result()
                if clip_id:
                    clip_ids.append((idx, clip_id))
            except Exception as exc:
                # Log but don't abort — other clips may still succeed
                print(f"  [warn] clip {idx+1} render failed: {exc}")

    # Return in original order (virality-ranked, since finalists already sorted)
    clip_ids.sort(key=lambda x: x[0])
    return [cid for _, cid in clip_ids]


# ── Per-clip render ───────────────────────────────────────────────────────────

def _render_one(
    source: str,
    cand: dict,
    out_path: str,
    words: list[dict],
    caption_settings: dict,
    encoder: str,
    enc_opts: list[str],
    job_id: str,
    src_w: int,
    src_h: int,
    proxy_path: str | None = None,
) -> str | None:
    """Render a single clip. Returns clip_id on success, None on failure."""
    start_s = float(cand["start_s"])
    end_s = float(cand["end_s"])
    duration = end_s - start_s

    # ── Framing plan: reuse stored plan or generate a new one ────────────────
    fp_json = cand.get("framing_plan")
    if fp_json:
        try:
            framing_plan = json.loads(fp_json)
        except Exception:
            framing_plan = None
    else:
        framing_plan = None

    if framing_plan is None and proxy_path:
        try:
            framing_plan = plan_clip_v2(proxy_path, start_s, end_s, src_w, src_h)
            # Persist so re-renders can reuse without re-analyzing
            with db.db() as _conn:
                _conn.execute(
                    "UPDATE candidates SET framing_plan=? WHERE id=?",
                    (json.dumps(framing_plan), cand["id"]),
                )
        except Exception as _fp_err:
            print(f"  [reframe] plan_clip_v2 failed, using center crop: {_fp_err}")
            framing_plan = None

    # Build crop filter — use keypoints for dynamic scene-aware framing (v2 plan)
    if framing_plan and not framing_plan.get("fallback"):
        x_offset = framing_plan.get("x_offset")
        kp = framing_plan.get("keypoints") or []
        # Only use dynamic expression when there are meaningful distinct positions
        use_dynamic = (
            framing_plan.get("version", 1) >= 2
            and len(kp) > 1
            and len({x for _, x in kp}) > 1
        )
        crop_filter = _compute_crop_filter(
            src_w, src_h,
            x_offset=x_offset,
            keypoints=kp if use_dynamic else None,
            clip_start_s=start_s,
        )
    else:
        crop_filter = _compute_crop_filter(src_w, src_h)

    # Extract + normalize words for this clip window
    clip_words = extract_clip_words(words, start_s, end_s)

    # Build ASS subtitle file
    ass_path = _write_ass(clip_words, caption_settings)

    try:
        success = _run_ffmpeg(
            source, start_s, duration,
            crop_filter, ass_path,
            encoder, enc_opts,
            out_path,
        )
    finally:
        if ass_path:
            try:
                os.unlink(ass_path)
            except OSError:
                pass

    if not success:
        return None

    # Probe output metadata
    meta = _probe(out_path)

    # Caption data for DB (normalized timestamps already in clip_words)
    caption_data = {
        "words": clip_words,
        "has_audio": len(clip_words) > 0,
        "clip_start": start_s,
        "clip_end": end_s,
    }

    # Technical QA: verify the rendered file is valid
    technical_qa, qa_notes = _check_technical_qa(meta, out_path, duration)

    # Create DB record (short lock)
    with db.db() as conn:
        clip_id = str(__import__("uuid").uuid4())
        ts = __import__("datetime").datetime.utcnow().isoformat()
        conn.execute(
            """INSERT INTO clips
               (id, job_id, candidate_id, output_path, captioned_path,
                width, height, fps, duration_s, file_size,
                technical_qa, visual_qa, qa_notes, platform_fit_scores,
                prepublish_decision, prepublish_score, caption_data, caption_settings,
                created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                clip_id, job_id, cand["id"],
                out_path, out_path,          # output_path = captioned_path (one file)
                meta.get("width", TARGET_W),
                meta.get("height", TARGET_H),
                meta.get("fps", 30.0),
                meta.get("duration", duration),
                meta.get("size", 0),
                technical_qa, "PENDING", json.dumps(qa_notes), "{}",
                "PENDING", 0.0,
                json.dumps(caption_data),
                json.dumps(caption_settings),
                ts,
            )
        )

    return clip_id


def _write_ass(words: list[dict], settings: dict) -> str | None:
    """Write ASS subtitle content to a temp file. Returns path or None."""
    if not words or not settings.get("enabled", True):
        return None
    content = build_ass(words, settings, TARGET_W, TARGET_H)
    tmp = tempfile.NamedTemporaryFile(
        suffix=".ass", mode="w", delete=False, encoding="utf-8"
    )
    tmp.write(content)
    tmp.close()
    return tmp.name


def _run_ffmpeg(
    source: str,
    start_s: float,
    duration: float,
    crop_filter: str,
    ass_path: str | None,
    encoder: str,
    enc_opts: list[str],
    out_path: str,
) -> bool:
    """Single FFmpeg call: trim + crop/scale + optional caption burn."""
    if ass_path:
        safe_ass = ass_path.replace("\\", "/").replace(":", "\\:")
        vf = f"{crop_filter},ass='{safe_ass}'"
    else:
        vf = crop_filter

    cmd = [
        CONFIG.ffmpeg_path, "-y",
        "-ss", str(start_s),
        "-i", source,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", encoder,
    ] + enc_opts + [
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    return result.returncode == 0


def _check_technical_qa(meta: dict, out_path: str, expected_duration: float) -> tuple[str, dict]:
    """Return (technical_qa, qa_notes) based on probed output file metadata."""
    import os as _os
    notes = {}

    file_size = meta.get("size", 0)
    if file_size == 0:
        try:
            file_size = _os.path.getsize(out_path)
        except OSError:
            file_size = 0

    if file_size == 0:
        return "FAIL", {"error": "empty output file", "size": 0}

    if not meta.get("width") or not meta.get("height"):
        return "FAIL", {"error": "no video stream detected"}

    actual_duration = meta.get("duration", 0.0)
    if actual_duration > 0 and expected_duration > 0:
        deviation = abs(actual_duration - expected_duration) / expected_duration
        if deviation > 0.15:
            notes["duration_warning"] = (
                f"expected {expected_duration:.1f}s, got {actual_duration:.1f}s"
            )
            if deviation > 0.40:
                return "FAIL", {"error": f"duration mismatch: {notes['duration_warning']}"}

    fps = meta.get("fps", 0.0)
    if fps > 0 and fps < 10.0:
        return "FAIL", {"error": f"fps too low: {fps:.1f}"}

    return "PASS", notes


def _compute_crop_filter(
    src_w: int,
    src_h: int,
    x_offset: int | None = None,
    keypoints: list | None = None,
    clip_start_s: float = 0.0,
) -> str:
    """Compute FFmpeg crop+scale filter to convert source to 1080x1920.

    When keypoints is provided (list of [rel_time_s, x_offset] from a v2
    FramingPlan), the crop x position is expressed as an FFmpeg `if` chain
    so it changes at scene boundaries — giving scene-aware framing without
    an intermediate re-encode.

    keypoints times are RELATIVE to the clip start (t=0 in the trimmed clip).
    When only x_offset is given the filter is static.
    """
    src_w = src_w or TARGET_W
    src_h = src_h or TARGET_H
    src_ratio = src_w / src_h
    target_ratio = TARGET_W / TARGET_H

    if abs(src_ratio - target_ratio) < 0.01:
        return f"scale={TARGET_W}:{TARGET_H}"

    elif src_ratio > target_ratio:
        # Wider than 9:16 → crop width
        new_w = int(src_h * target_ratio)
        center = (src_w - new_w) // 2

        if keypoints and len(keypoints) > 1:
            # Build an `if(lt(t,T), X, ...)` chain from relative keypoints
            x_expr = _build_keypoint_expr(keypoints, center, src_w - new_w)
            return (
                f"crop={new_w}:{src_h}:'({x_expr})':0,"
                f"scale={TARGET_W}:{TARGET_H}"
            )

        # Static offset
        x_off = center if x_offset is None else max(0, min(int(x_offset), src_w - new_w))
        return f"crop={new_w}:{src_h}:{x_off}:0,scale={TARGET_W}:{TARGET_H}"

    else:
        # Taller than 9:16 → crop height (x_offset not applicable)
        new_h = int(src_w / target_ratio)
        y_offset = (src_h - new_h) // 2
        return f"crop={src_w}:{new_h}:0:{y_offset},scale={TARGET_W}:{TARGET_H}"


def _build_keypoint_expr(
    keypoints: list,
    center_fallback: int,
    max_x: int,
) -> str:
    """Build a nested FFmpeg if-chain from keypoints.

    Semantics: each keypoint [T, X] means "use offset X starting at time T
    until the next keypoint's time."  The last offset holds to end of clip.

    keypoints: [[rel_time_s, x_offset], ...]  (relative to clip start, t=0)
    Returns e.g.: if(lt(t\\,8.500)\\,400\\,if(lt(t\\,18.000)\\,620\\,400))
    """
    if not keypoints:
        return str(center_fallback)

    kp = sorted(keypoints, key=lambda k: k[0])
    clamped = [(t, max(0, min(int(x), max_x))) for t, x in kp]

    # Build right-to-left using TRANSITION times (each keypoint's time is
    # when we SWITCH TO that offset, so the boundary between segment i and i+1
    # is clamped[i+1][0]).
    # Result:  if(lt(t,T1),X0,if(lt(t,T2),X1,...,Xlast))
    expr = str(clamped[-1][1])
    for i in range(len(clamped) - 2, -1, -1):
        boundary_t = clamped[i + 1][0]
        this_x = clamped[i][1]
        expr = f"if(lt(t\\,{boundary_t:.3f})\\,{this_x}\\,{expr})"
    return expr


def _probe(path: str) -> dict:
    cmd = [
        CONFIG.ffprobe_path, "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return {}
    import json as _json
    data = _json.loads(result.stdout)
    fmt = data.get("format", {})
    vs = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    fps_str = vs.get("r_frame_rate", "30/1")
    try:
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) else 30.0
    except Exception:
        fps = 30.0
    return {
        "duration": float(fmt.get("duration", 0)),
        "size": int(fmt.get("size", 0)),
        "width": vs.get("width", TARGET_W),
        "height": vs.get("height", TARGET_H),
        "fps": round(fps, 3),
    }
