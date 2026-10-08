"""ContentEngine REST API."""
import uuid, shutil, asyncio, datetime, json, zipfile, tempfile, subprocess, threading
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, BackgroundTasks, HTTPException, UploadFile, File, Form, Query, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from engine.config import CONFIG
from engine import database as dbmod
from engine.pipeline import process_video
from engine.downloader import is_url, validate_url, get_video_info

app = FastAPI(title="AI Content Engine", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Accept"],
)

# In-memory job status cache (mirrors DB)
_jobs: dict = {}

# Worker pool — injected by server.py at startup
pool = None


def _get_pipeline_snapshot() -> dict:
    """Capture current processing config for evaluation linkage."""
    git_hash = "unknown"
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=str(Path(__file__).parent.parent),
        )
        if r.returncode == 0:
            git_hash = r.stdout.strip()
    except Exception:
        pass
    import os as _os
    return {
        "git_hash": git_hash,
        "whisper_model": CONFIG.whisper_model,
        "min_candidate_composite": CONFIG.min_candidate_composite,
        "min_clip_duration": CONFIG.min_clip_duration,
        "max_clip_duration": CONFIG.max_clip_duration,
        "target_clips": CONFIG.target_clips,
        "intro_skip_ratio": CONFIG.intro_skip_ratio,
        "outro_skip_ratio": CONFIG.outro_skip_ratio,
        "caption_min_word_confidence": CONFIG.caption_min_word_confidence,
        "llm_enabled": bool(_os.environ.get("ANTHROPIC_API_KEY", "").strip()),
        "captured_at": datetime.datetime.utcnow().isoformat(),
    }


# ── LIFECYCLE ───────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    dbmod.init_db()
    if pool is not None:
        pool.start()


@app.on_event("shutdown")
async def shutdown():
    if pool is not None:
        pool.stop()


# ── HEALTH ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Liveness + readiness check. Returns degraded details when components fail."""
    import shutil as _shutil
    checks: dict[str, str] = {}

    # DB connectivity
    try:
        with dbmod.db() as conn:
            conn.execute("SELECT 1").fetchone()
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"

    # FFmpeg presence
    checks["ffmpeg"] = "ok" if Path(CONFIG.ffmpeg_path).exists() else "missing"
    checks["ffprobe"] = "ok" if Path(CONFIG.ffprobe_path).exists() else "missing"

    # Worker liveness
    if pool is not None:
        alive = sum(1 for w in pool.workers if w.is_alive())
        checks["workers"] = f"{alive}/{len(pool.workers)} alive"
    else:
        checks["workers"] = "pool not started"

    # Disk space on output directory
    try:
        usage = _shutil.disk_usage(CONFIG.output_dir)
        free_gb = usage.free / (1024 ** 3)
        checks["disk_free_gb"] = f"{free_gb:.1f}"
        if free_gb < 2.0:
            checks["disk_warning"] = "< 2 GB free"
    except Exception:
        checks["disk_free_gb"] = "unknown"

    # LLM availability
    import os as _os
    llm_enabled = bool(_os.environ.get("ANTHROPIC_API_KEY", "").strip())
    checks["llm"] = "enabled" if llm_enabled else "disabled"

    all_ok = all(v in ("ok",) or v.endswith("alive") or v.replace(".", "").isdigit()
                 for k, v in checks.items() if k != "disk_warning")
    status = "ok" if checks["database"] == "ok" else "degraded"

    return {
        "status": status,
        "mode": CONFIG.mode,
        "version": "1.0.0",
        "llm_enabled": llm_enabled,
        "checks": checks,
    }


# ── JOBS ────────────────────────────────────────────────────────────────────

@app.post("/jobs")
async def create_job(
    video: UploadFile = File(...),
    clips: int = Form(3),
    platforms: str = Form("tiktok,instagram"),
    mode: str = Form("REVIEW"),
    creator: str = Form(""),
    creator_id: str = Form(""),
    video_name: str = Form(""),
    language: str = Form("auto"),
):
    job_id = str(uuid.uuid4())

    upload_dir = Path(CONFIG.output_dir) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    # Strip directory components from filename to prevent path traversal
    safe_filename = Path(video.filename or "upload.mp4").name or "upload.mp4"
    # Force .mp4 extension — pipeline always expects a video container
    upload_path = upload_dir / f"{job_id}_{safe_filename}"

    MAX_UPLOAD_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB
    bytes_written = 0
    header_bytes = b""
    with open(upload_path, "wb") as f:
        for chunk in video.file:
            bytes_written += len(chunk)
            if bytes_written > MAX_UPLOAD_BYTES:
                f.close()
                upload_path.unlink(missing_ok=True)
                raise HTTPException(413, "File too large — maximum upload size is 10 GB")
            if len(header_bytes) < 16:
                header_bytes += chunk
            f.write(chunk)

    # Validate magic bytes — reject non-video uploads after writing so we have
    # the full header available even for very small first chunks.
    _ALLOWED_MAGIC = [
        b"\x00\x00\x00",          # MP4/MOV (ftyp box starts at byte 4)
        b"\x1a\x45\xdf\xa3",      # MKV / WebM (EBML)
        b"RIFF",                  # AVI
        b"OggS",                  # OGG video
        b"\x00\x00\x01\xba",      # MPEG-PS
        b"\x00\x00\x01\xb3",      # MPEG video
    ]
    is_video = any(header_bytes.startswith(sig) for sig in _ALLOWED_MAGIC)
    # MP4 containers place 'ftyp' at offset 4; check that too
    if not is_video and len(header_bytes) >= 12:
        is_video = header_bytes[4:8] in (b"ftyp", b"mdat", b"moov", b"free", b"wide")
    if not is_video:
        upload_path.unlink(missing_ok=True)
        raise HTTPException(415, "Unsupported file type — only video files are accepted")

    # Resolve creator name from creator_id if provided
    resolved_creator = creator or "unknown"
    resolved_creator_id = creator_id or None
    if creator_id:
        cr = dbmod.get_creator(creator_id)
        if cr:
            resolved_creator = cr["name"]
        else:
            resolved_creator_id = None

    _jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "source": str(upload_path),
        "clips_requested": clips,
        "platforms": platforms.split(","),
        "mode": mode,
        "creator": resolved_creator,
        "creator_id": resolved_creator_id,
        "video_name": video_name or "",
        "language": language or "auto",
        "created_at": datetime.datetime.utcnow().isoformat(),
        "result": None,
        "error": None,
    }

    if pool is not None:
        pool.submit(job_id, str(upload_path), clips, platforms.split(","), mode, resolved_creator)
    else:
        raise HTTPException(503, "Worker pool not available")

    snap = _get_pipeline_snapshot()
    snap_str = json.dumps(snap)
    with dbmod.db() as conn:
        conn.execute("UPDATE jobs SET pipeline_snapshot=? WHERE id=?", [snap_str, job_id])
        if resolved_creator_id:
            conn.execute("UPDATE jobs SET creator_id=? WHERE id=?",
                         [resolved_creator_id, job_id])

    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs")
async def list_jobs(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str = Query(None),
):
    # Merge DB (persistent) with in-memory (live status + result)
    conn = dbmod.get_db()
    conditions, params = [], []
    if status:
        conditions.append("j.status=?")
        params.append(status.upper())
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = conn.execute(f"""
        SELECT j.id, j.source_path, j.status, j.mode, j.creator,
               j.created_at, j.updated_at, j.error,
               v.creator_slug, v.video_slug, v.source_title, v.source_platform, v.source_url,
               COALESCE(j.creator_id, v.creator_id) as creator_id, v.id as video_id,
               (SELECT COUNT(*) FROM clips c WHERE c.job_id = j.id) as clip_count
        FROM jobs j
        LEFT JOIN videos v ON v.job_id = j.id
        {where}
        ORDER BY j.created_at DESC
        LIMIT ? OFFSET ?
    """, params + [limit, offset]).fetchall()
    conn.close()

    db_map = {}
    for r in rows:
        jid = r[0]
        if jid in db_map:
            continue  # skip duplicate rows (multiple videos per job edge case)
        db_map[jid] = {
            "id": jid,
            "source": r[1],
            "status": (r[2] or "").lower(),  # normalize to lowercase for consistent CSS chip styling
            "mode": r[3],
            "creator": r[4],
            "created_at": r[5],
            "updated_at": r[6],
            "error": r[7],
            "creator_slug": r[8] or r[4] or "local",
            "video_slug": r[9] or jid[:8],
            "source_title": r[10] or "",
            "source_platform": r[11] or "local",
            "source_url": r[12] or r[1] or "",
            "creator_id": r[13],
            "video_id": r[14],
            "clip_count": r[15] or 0,
            "result": None,
        }

    # Overlay live in-memory data (has result, real-time status)
    for jid, live in _jobs.items():
        if jid in db_map:
            db_map[jid].update({k: v for k, v in live.items() if v is not None})
        else:
            db_map[jid] = live

    return list(db_map.values())


@app.get("/jobs/url-info")
async def url_info(url: str):
    """Fetch video metadata without downloading — used by the New Job preview UI."""
    if not is_url(url):
        raise HTTPException(400, "Invalid URL — must start with http:// or https://")
    try:
        validate_url(url)
    except ValueError as exc:
        raise HTTPException(400, f"URL not allowed: {exc}")
    try:
        info = get_video_info(url)
    except RuntimeError as exc:
        raise HTTPException(422, str(exc))

    # Suggest matching creator by channel_id or display name
    suggested_creator_id = None
    suggested_creator_name = None
    channel_id = info.get("channel_id", "")
    channel_name = info.get("channel", "")
    if channel_id or channel_name:
        with dbmod.db() as conn:
            row = None
            if channel_id:
                row = conn.execute(
                    "SELECT id, name FROM creators WHERE external_channel_id=?",
                    (channel_id,),
                ).fetchone()
            if not row and channel_name:
                row = conn.execute(
                    "SELECT id, name FROM creators WHERE LOWER(name)=LOWER(?)",
                    (channel_name,),
                ).fetchone()
            if row:
                suggested_creator_id = row["id"]
                suggested_creator_name = row["name"]

    return {
        **info,
        "suggested_creator_id": suggested_creator_id,
        "suggested_creator_name": suggested_creator_name,
    }


@app.get("/jobs/url-check")
async def url_check(url: str):
    """Check if a URL already exists in the library (duplicate detection)."""
    with dbmod.db() as conn:
        rows = conn.execute("""
            SELECT j.id, j.status, v.source_title, j.created_at
            FROM jobs j LEFT JOIN videos v ON v.job_id = j.id
            WHERE v.source_url = ? OR j.source_path = ?
            ORDER BY j.created_at DESC LIMIT 5
        """, (url, url)).fetchall()
    if rows:
        return {
            "exists": True,
            "jobs": [{"id": r["id"], "status": r["status"],
                      "title": r["source_title"] or "", "created_at": r["created_at"]}
                     for r in rows],
        }
    return {"exists": False, "jobs": []}


@app.post("/jobs/from-url")
async def create_job_from_url(
    url: str = Body(..., embed=True),
    clips: int = Body(3),
    platforms: str = Body("tiktok,instagram"),
    mode: str = Body("REVIEW"),
    creator: str = Body(""),
    creator_id: str = Body(""),
    video_name: str = Body(""),
    content_type: str = Body("auto"),
    language: str = Body("auto"),
    eval_mode: bool = Body(False),
):
    """Submit a job by providing a video URL (YouTube, TikTok, Instagram, etc.)."""
    if not is_url(url):
        raise HTTPException(400, "Invalid URL — must start with http:// or https://")
    try:
        validate_url(url)
    except ValueError as exc:
        raise HTTPException(400, f"URL not allowed: {exc}")

    # Idempotency: skip when eval_mode=True (intentional re-evaluation experiment)
    if not eval_mode:
        with dbmod.db() as conn:
            existing = conn.execute("""
                SELECT j.id, j.status FROM jobs j
                LEFT JOIN videos v ON v.job_id = j.id
                WHERE (v.source_url = ? OR j.source_path = ?)
                  AND LOWER(j.status) NOT IN ('failed')
                ORDER BY j.created_at DESC LIMIT 1
            """, (url, url)).fetchone()
        if existing:
            return {"job_id": existing["id"], "status": existing["status"].lower(), "duplicate": True}

    job_id = str(uuid.uuid4())
    resolved_creator = creator or "unknown"
    resolved_creator_id = creator_id or None
    if creator_id:
        cr = dbmod.get_creator(creator_id)
        if cr:
            resolved_creator = cr["name"]
        else:
            resolved_creator_id = None

    _jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "source_url": url,
        "source": url,
        "clips_requested": clips,
        "platforms": platforms.split(","),
        "mode": mode,
        "creator": resolved_creator,
        "creator_id": resolved_creator_id,
        "video_name": video_name or "",
        "content_type": content_type or "auto",
        "language": language or "auto",
        "created_at": datetime.datetime.utcnow().isoformat(),
        "result": None,
        "error": None,
    }

    # Create DB row now so the dedup check (j.source_path=url) finds it
    # immediately — prevents race window where a second submission slips through
    # before the worker has run create_job.  Worker will call create_job with
    # preset_id=job_id, find this row, and skip re-insert.
    snap = _get_pipeline_snapshot()
    dbmod.create_job(
        url, mode, clips, platforms.split(","),
        resolved_creator, content_type or "auto",
        preset_id=job_id, pipeline_snapshot=snap,
    )
    if resolved_creator_id:
        dbmod.update_job(job_id)  # touch updated_at; creator_id set below
        with dbmod.db() as conn:
            conn.execute("UPDATE jobs SET creator_id=? WHERE id=?",
                         [resolved_creator_id, job_id])

    if pool is not None:
        pool.submit(job_id, url, clips, platforms.split(","), mode, resolved_creator)
    else:
        raise HTTPException(503, "Worker pool not available")

    if video_name:
        with dbmod.db() as conn:
            conn.execute(
                "UPDATE videos SET source_title=? WHERE job_id=?",
                [video_name, job_id],
            )

    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    if job_id in _jobs:
        return _jobs[job_id]
    conn = dbmod.get_db()
    row = conn.execute("SELECT * FROM jobs WHERE id=?", [job_id]).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Job not found")
    return dict(row)


@app.get("/jobs/{job_id}/events")
async def job_events(job_id: str):
    """Server-Sent Events stream — pushes status updates until job completes."""
    async def event_generator() -> AsyncGenerator[str, None]:
        last_status = None
        last_stage = None
        while True:
            job = _jobs.get(job_id)
            if job is None:
                # Job not in memory — look it up in DB (completed in a prior session)
                conn = dbmod.get_db()
                row = conn.execute("SELECT status, error FROM jobs WHERE id=?", [job_id]).fetchone()
                conn.close()
                if row:
                    db_status = (row[0] or "").lower()
                    payload = {"job_id": job_id, "status": db_status, "stage": row[0], "result": None, "error": row[1]}
                    yield f"data: {json.dumps(payload)}\n\n"
                else:
                    yield f"data: {json.dumps({'error': 'job not found'})}\n\n"
                break
            status = job["status"]
            # Read pipeline stage from DB — updated at each step by the pipeline
            db_stage = None
            try:
                conn = dbmod.get_db()
                srow = conn.execute("SELECT status FROM jobs WHERE id=?", [job_id]).fetchone()
                conn.close()
                if srow:
                    db_stage = srow[0]
            except Exception:
                pass
            if status != last_status or db_stage != last_stage:
                last_status = status
                last_stage = db_stage
                payload = {
                    "job_id": job_id,
                    "status": status,
                    "stage": db_stage,
                    "result": job.get("result"),
                    "error": job.get("error"),
                }
                yield f"data: {json.dumps(payload)}\n\n"
            if status in ("completed", "failed"):
                break
            await asyncio.sleep(2)

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── CLIPS ───────────────────────────────────────────────────────────────────

@app.get("/clips")
async def list_clips(
    decision: str = Query(None),
    creator_id: str = Query(None),
    job_id: str = Query(None),
    video_id: str = Query(None),
    series_id: str = Query(None),
    limit: int = Query(50, le=500),
):
    conn = dbmod.get_db()
    conditions, params = [], []

    if decision:
        conditions.append("cl.prepublish_decision=?")
        params.append(decision)
    if creator_id:
        if creator_id == "__unassigned__":
            conditions.append("(v.creator_id IS NULL OR v.creator_id='')")
        else:
            conditions.append("v.creator_id=?")
            params.append(creator_id)
    if job_id:
        conditions.append("cl.job_id=?")
        params.append(job_id)
    if video_id:
        conditions.append("v.id=?")
        params.append(video_id)
    if series_id:
        conditions.append("ca.series_id=?")
        params.append(series_id)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    # When fetching a specific series, return in series_part order
    order = "ca.series_part ASC, cl.created_at ASC" if series_id else "cl.created_at DESC"
    params.append(limit)

    rows = conn.execute(f"""
        SELECT cl.*,
               ca.hook_score, ca.virality_score, ca.visual_score, ca.audio_score,
               ca.start_s, ca.end_s, ca.platform_scores,
               ca.series_id, ca.series_part,
               v.creator_slug, v.video_slug, v.source_title, v.source_platform,
               v.creator_id, v.id as video_id,
               cs.title as series_title
        FROM clips cl
        LEFT JOIN candidates ca ON cl.candidate_id = ca.id
        LEFT JOIN videos v ON ca.video_id = v.id
        LEFT JOIN clip_series cs ON cs.id = ca.series_id
        {where}
        ORDER BY {order} LIMIT ?
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/clips/{clip_id}")
async def get_clip(clip_id: str):
    conn = dbmod.get_db()
    row = conn.execute("""
        SELECT cl.*,
               ca.hook_score, ca.virality_score, ca.start_s, ca.end_s,
               v.id as video_id, v.creator_id, v.creator_slug, v.source_title
        FROM clips cl
        LEFT JOIN candidates ca ON cl.candidate_id = ca.id
        LEFT JOIN videos v ON ca.video_id = v.id
        WHERE cl.id=?
    """, [clip_id]).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Clip not found")
    return dict(row)


def _resolve_clip_path(captioned: str, output: str) -> str | None:
    """Return the best available file path for a clip, preferring captioned."""
    for p in (captioned, output):
        if p and Path(p).exists():
            return p
    return None


@app.get("/clips/{clip_id}/download")
async def download_clip(clip_id: str):
    conn = dbmod.get_db()
    row = conn.execute(
        "SELECT captioned_path, output_path FROM clips WHERE id=?", [clip_id]
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Clip not found")
    path = _resolve_clip_path(row[0], row[1])
    if not path:
        raise HTTPException(404, "Clip file not found on disk")
    return FileResponse(path, media_type="video/mp4", filename=f"clip_{clip_id[:8]}.mp4")


@app.get("/clips/{clip_id}/preview")
async def preview_clip(clip_id: str):
    """Serve clip inline (no attachment header) so browser <video> can play it."""
    conn = dbmod.get_db()
    row = conn.execute(
        "SELECT captioned_path, output_path FROM clips WHERE id=?", [clip_id]
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Clip not found")
    path = _resolve_clip_path(row[0], row[1])
    if not path:
        raise HTTPException(404, "Clip file not found on disk")
    return FileResponse(path, media_type="video/mp4")


@app.get("/clips/{clip_id}/thumbnail")
async def get_clip_thumbnail(clip_id: str):
    """Extract and cache a poster frame from a clip for use in review cards."""
    conn = dbmod.get_db()
    row = conn.execute(
        "SELECT captioned_path, output_path FROM clips WHERE id=?", [clip_id]
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Clip not found")

    thumb_dir = Path(CONFIG.output_dir) / "thumbnails"
    thumb_path = thumb_dir / f"clip_{clip_id}.jpg"
    if thumb_path.exists():
        return FileResponse(str(thumb_path), media_type="image/jpeg")

    clip_file = _resolve_clip_path(row[0], row[1])
    if not clip_file:
        raise HTTPException(404, "Clip file not found on disk")

    thumb_dir.mkdir(parents=True, exist_ok=True)
    cmd = [CONFIG.ffmpeg_path, "-y", "-ss", "1", "-i", clip_file,
           "-frames:v", "1", "-q:v", "5", "-vf", "scale=160:-2", str(thumb_path)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=15, check=True)
    except Exception:
        raise HTTPException(500, "Thumbnail generation failed")

    return FileResponse(str(thumb_path), media_type="image/jpeg")


# ── DOWNLOAD ALL ─────────────────────────────────────────────────────────────

@app.get("/jobs/{job_id}/download-all")
async def download_all_clips(job_id: str, background_tasks: BackgroundTasks):
    """Bundle all clips for a job into a ZIP and return it."""
    conn = dbmod.get_db()
    rows = conn.execute(
        "SELECT id, captioned_path, output_path FROM clips WHERE job_id=?",
        [job_id]
    ).fetchall()
    conn.close()

    available = [(r[0], r[1] or r[2]) for r in rows if (r[1] or r[2]) and Path(r[1] or r[2]).exists()]
    if not available:
        raise HTTPException(404, "No clips found for this job (job may still be running)")

    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, (clip_id, path) in enumerate(available, 1):
            zf.write(path, f"clip_{i:02d}_{clip_id[:8]}.mp4")

    def _cleanup(path: str):
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass

    background_tasks.add_task(_cleanup, tmp.name)
    return FileResponse(tmp.name, media_type="application/zip",
                        filename=f"clips_{job_id[:8]}.zip")


# ── MANUAL REVIEW ─────────────────────────────────────────────────────────────

@app.get("/review/pending")
async def pending_review(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str = Query(None),  # REVIEW|PUBLISH|REJECT|all — default: REVIEW (pending queue)
):
    """Clips for manual review, paginated.

    status=REVIEW (default) → pending queue (needs human decision)
    status=PUBLISH           → approved clips
    status=REJECT            → rejected clips
    status=all               → everything
    """
    conn = dbmod.get_db()
    effective = (status or "REVIEW").upper()
    if effective == "ALL":
        where = ""
        params: list = []
    else:
        where = "WHERE cl.prepublish_decision=?"
        params = [effective]
    rows = conn.execute(f"""
        SELECT cl.id, cl.captioned_path, cl.output_path, cl.prepublish_score,
               cl.prepublish_decision, cl.created_at, cl.job_id,
               ca.hook_score, ca.virality_score, ca.start_s, ca.end_s,
               v.source_title, v.duration_s as video_duration
        FROM clips cl
        JOIN candidates ca ON cl.candidate_id = ca.id
        JOIN videos v ON v.id = ca.video_id
        {where}
        ORDER BY cl.created_at DESC, ca.virality_score DESC
        LIMIT ? OFFSET ?
    """, params + [limit, offset]).fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "output_path": r[1] or r[2],
            "prepublish_score": r[3],
            "decision": r[4],
            "created_at": r[5],
            "job_id": r[6],
            "hook_score": r[7],
            "viral_score": r[8],
            "start_s": r[9],
            "end_s": r[10],
            "source_title": r[11],
            "video_duration": r[12],
        }
        for r in rows
    ]


@app.post("/review/{clip_id}/approve")
async def approve_clip(clip_id: str, reason: str = "manual_approval"):
    conn = dbmod.get_db()
    conn.execute(
        "UPDATE clips SET prepublish_decision='PUBLISH', review_notes=? WHERE id=?",
        [reason, clip_id],
    )
    conn.commit()
    conn.close()
    return {"status": "approved", "clip_id": clip_id}


@app.post("/review/{clip_id}/reject")
async def reject_clip(clip_id: str, reason: str = "manual_rejection"):
    conn = dbmod.get_db()
    conn.execute(
        "UPDATE clips SET prepublish_decision='REJECT', review_notes=? WHERE id=?",
        [reason, clip_id],
    )
    conn.commit()
    conn.close()
    return {"status": "rejected", "clip_id": clip_id}


@app.post("/clips/{clip_id}/return-to-review")
async def return_clip_to_review(clip_id: str):
    """Reset a clip's editorial decision to 'REVIEW' so it reappears in the pending queue.
    The clip_evaluations history is preserved for audit purposes."""
    with dbmod.db() as conn:
        row = conn.execute("SELECT id FROM clips WHERE id=?", [clip_id]).fetchone()
        if not row:
            raise HTTPException(404, "Clip not found")
        conn.execute(
            "UPDATE clips SET prepublish_decision='REVIEW', review_notes='' WHERE id=?",
            [clip_id],
        )
    return {"status": "returned_to_review", "clip_id": clip_id}


@app.post("/videos/{video_id}/verify-rights")
async def verify_rights(video_id: str):
    """Explicit manual action: marks rights_verified=1 for a video."""
    conn = dbmod.get_db()
    conn.execute("UPDATE videos SET rights_verified=1 WHERE id=?", [video_id])
    conn.commit()
    conn.close()
    return {"status": "rights_verified", "video_id": video_id}


# ── CAPTIONS ─────────────────────────────────────────────────────────────────

@app.get("/captions/presets")
async def list_caption_presets():
    from engine.captions.presets import list_presets, get_preset
    return {name: get_preset(name) for name in list_presets()}


@app.get("/clips/{clip_id}/captions")
async def get_clip_captions(clip_id: str):
    caption_data, caption_settings = dbmod.get_clip_captions(clip_id)
    from engine.captions.presets import default_settings
    from engine.captions.extractor import group_words
    settings = caption_settings or default_settings()
    words = (caption_data or {}).get("words", [])
    groups = group_words(words, int(settings.get("max_words", 4)))
    return {
        "clip_id": clip_id,
        "caption_data": caption_data or {"words": [], "has_audio": False},
        "caption_settings": settings,
        "groups": groups,
        "word_count": len(words),
    }


@app.put("/clips/{clip_id}/captions")
async def update_clip_captions(clip_id: str, body: dict = Body(...)):
    """Update caption settings and/or corrected words for a clip."""
    conn = dbmod.get_db()
    row = conn.execute("SELECT id FROM clips WHERE id=?", [clip_id]).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Clip not found")

    caption_data = body.get("caption_data")
    caption_settings = body.get("caption_settings")

    # If only updating settings, preserve existing words
    if caption_settings and not caption_data:
        existing_data, _ = dbmod.get_clip_captions(clip_id)
        caption_data = existing_data

    dbmod.update_clip_captions(clip_id,
                               caption_data=caption_data,
                               caption_settings=caption_settings)
    return {"status": "updated", "clip_id": clip_id}


@app.post("/clips/{clip_id}/re-render")
async def re_render_captions(clip_id: str):
    """Re-burn captions into the clip using current caption_settings."""
    from engine.captions.renderer import burn_captions_ass

    conn = dbmod.get_db()
    row = conn.execute("SELECT * FROM clips WHERE id=?", [clip_id]).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Clip not found")

    caption_data, caption_settings = dbmod.get_clip_captions(clip_id)
    if not caption_data:
        raise HTTPException(400, "No caption data for this clip")

    source = row["output_path"]
    if not source or not Path(source).exists():
        raise HTTPException(400, "Source clip file not found")

    out_path = source.replace(".mp4", "_captioned.mp4")
    words = caption_data.get("words", [])
    w = row["width"] or 1080
    h = row["height"] or 1920

    success = burn_captions_ass(source, out_path, words, caption_settings, w, h)
    if not success:
        raise HTTPException(500, "Caption render failed")

    dbmod.update_clip(clip_id, captioned_path=out_path)
    return {"status": "rendered", "clip_id": clip_id, "output": out_path}


@app.post("/clips/{clip_id}/retranscribe")
async def retranscribe_clip(clip_id: str):
    """Rebuild caption_data for a clip from its video's transcript cache.

    Useful for clips created before the caption_data feature was added.
    If the video transcript cache is missing, re-runs Whisper on the audio.
    """
    import os as _os
    from engine.captions.extractor import extract_clip_words

    conn = dbmod.get_db()
    clip = conn.execute("SELECT * FROM clips WHERE id=?", [clip_id]).fetchone()
    conn.close()
    if not clip:
        raise HTTPException(404, "Clip not found")

    conn = dbmod.get_db()
    cand = conn.execute("SELECT * FROM candidates WHERE id=?", [clip["candidate_id"]]).fetchone()
    conn.close()
    if not cand:
        raise HTTPException(404, "Candidate not found")

    start_s, end_s = float(cand["start_s"]), float(cand["end_s"])

    conn = dbmod.get_db()
    video = conn.execute("SELECT * FROM videos WHERE id=?", [cand["video_id"]]).fetchone()
    conn.close()
    if not video:
        raise HTTPException(404, "Video record not found")

    # Try transcript cache first
    words = dbmod.get_cached_words(video["id"])
    source = "cache"

    if words is None:
        from engine.transcription import _extract_audio, _run_whisper, _flatten_to_words, _has_audio_stream
        video_path = video["path"]
        if not video_path or not _os.path.exists(video_path):
            raise HTTPException(422, "Video file not found on disk — cannot retranscribe")
        if not _has_audio_stream(video_path):
            raise HTTPException(422, "Video has no audio stream")
        audio_path = _extract_audio(video_path, video["id"])
        segments = _run_whisper(audio_path)
        words = _flatten_to_words(segments)
        dbmod.save_words_cache(video["id"], words)
        source = "transcribed"

    clip_words = extract_clip_words(words, start_s, end_s)
    caption_data = {
        "words": clip_words,
        "has_audio": len(clip_words) > 0,
        "clip_start": start_s,
        "clip_end": end_s,
    }

    dbmod.update_clip_captions(clip_id, caption_data=caption_data)

    return {
        "clip_id": clip_id,
        "words_count": len(clip_words),
        "has_audio": caption_data["has_audio"],
        "source": source,
    }


# ── SMART REFRAME ─────────────────────────────────────────────────────────────

# In-memory map of variant_id → thread for running smart reframe jobs
_reframe_threads: dict = {}


def _run_reframe_job(
    variant_id: str,
    clip_id: str,
    source_path: str,
    proxy_path: str | None,
    clip_start: float,
    clip_end: float,
    src_w: int,
    src_h: int,
    words: list,
    content_hint: str,
) -> None:
    """Background thread: run plan_clip_v2, render variant, optionally Cloudinary."""
    import time
    from pathlib import Path as _Path

    try:
        dbmod.update_reframe_variant(variant_id, status="analyzing")

        # ── Analysis ──────────────────────────────────────────────────────────
        t0 = time.time()
        if proxy_path and _Path(proxy_path).exists():
            from engine.reframe.planner import plan_clip_v2
            plan = plan_clip_v2(
                proxy_path, clip_start, clip_end, src_w, src_h,
                content_hint=content_hint,
            )
        else:
            from engine.reframe.planner import plan_clip
            plan = plan_clip(
                source_path, clip_start, clip_end, src_w, src_h,
            )
        analysis_time = round(time.time() - t0, 2)

        dbmod.update_reframe_variant(
            variant_id,
            status="rendering",
            strategy=plan.get("strategy"),
            plan_json=json.dumps(plan),
            analysis_time_s=analysis_time,
        )

        # ── Render variant clip ───────────────────────────────────────────────
        import tempfile, subprocess
        from engine.hw_accel import detect_encoder
        from engine.captions.extractor import extract_clip_words
        from engine.captions.presets import default_settings
        from engine.captions.renderer import build_ass
        from engine.renderers.render_clip import _compute_crop_filter, _run_ffmpeg

        caption_settings = dict(default_settings())
        clip_words = extract_clip_words(words, clip_start, clip_end)
        ass_content = build_ass(clip_words, caption_settings, 1080, 1920) if clip_words and caption_settings.get("enabled", True) else None

        ass_path = None
        if ass_content:
            tmp = tempfile.NamedTemporaryFile(suffix=".ass", mode="w", delete=False, encoding="utf-8")
            tmp.write(ass_content)
            tmp.close()
            ass_path = tmp.name

        x_offset = plan.get("x_offset")
        kp = plan.get("keypoints") or []
        use_dynamic = (
            plan.get("version", 1) >= 2 and len(kp) > 1 and len({x for _, x in kp}) > 1
        )
        crop_filter = _compute_crop_filter(
            src_w, src_h,
            x_offset=x_offset,
            keypoints=kp if use_dynamic else None,
            clip_start_s=clip_start,
        )

        encoder, enc_opts, _ = detect_encoder()
        out_dir = _Path(CONFIG.output_dir) / "reframe_variants"
        out_dir.mkdir(parents=True, exist_ok=True)
        variant_path = str(out_dir / f"{variant_id}.mp4")

        t1 = time.time()
        duration = clip_end - clip_start
        ok = _run_ffmpeg(source_path, clip_start, duration, crop_filter, ass_path, encoder, enc_opts, variant_path)
        render_time = round(time.time() - t1, 2)

        if ass_path:
            try:
                import os as _os
                _os.unlink(ass_path)
            except OSError:
                pass

        if not ok or not _Path(variant_path).exists():
            dbmod.update_reframe_variant(variant_id, status="failed", error="FFmpeg render failed", render_time_s=render_time)
            return

        # ── Optional Cloudinary comparison ────────────────────────────────────
        from engine.reframe.cloudinary_adapter import compare_with_cloudinary, _check_credentials
        creds = _check_credentials()
        if creds["ok"]:
            cld = compare_with_cloudinary(source_path, clip_start, clip_end, clip_id)
            dbmod.update_reframe_variant(
                variant_id,
                status="done",
                variant_path=variant_path,
                render_time_s=render_time,
                cloudinary_url=cld.url,
                cloudinary_public_id=cld.public_id,
            )
        else:
            dbmod.update_reframe_variant(
                variant_id,
                status="done",
                variant_path=variant_path,
                render_time_s=render_time,
            )

    except Exception as exc:
        dbmod.update_reframe_variant(variant_id, status="failed", error=str(exc)[:500])


@app.post("/clips/{clip_id}/smart-reframe")
async def start_smart_reframe(
    clip_id: str,
    background_tasks: BackgroundTasks,
    content_hint: str = "auto",
):
    """Start a smart-reframe job for a clip.

    content_hint: 'auto' | 'talking_head' | 'conversation' | 'action' | 'webcam'

    Returns immediately with variant_id; poll GET /clips/{clip_id}/smart-reframe.
    """
    conn = dbmod.get_db()
    clip = conn.execute("SELECT * FROM clips WHERE id=?", [clip_id]).fetchone()
    if not clip:
        conn.close()
        raise HTTPException(404, "Clip not found")

    cand = conn.execute("SELECT * FROM candidates WHERE id=?", [clip["candidate_id"]]).fetchone()
    video = conn.execute(
        "SELECT * FROM videos WHERE id=?", [cand["video_id"]]
    ).fetchone() if cand else None
    conn.close()

    if not cand or not video:
        raise HTTPException(404, "Candidate or video record missing")

    source_path = video["path"]
    if not source_path or not Path(source_path).exists():
        raise HTTPException(400, "Source video file not found on disk")

    proxy_path = video["proxy_path"] if "proxy_path" in video.keys() else None
    clip_start = float(cand["start_s"])
    clip_end = float(cand["end_s"])
    src_w = int(video["width"] if video["width"] else 1920)
    src_h = int(video["height"] if video["height"] else 1080)
    words = dbmod.get_cached_words(video["id"]) or []

    variant_id = dbmod.create_reframe_variant(clip_id, content_hint)

    import threading
    t = threading.Thread(
        target=_run_reframe_job,
        args=(variant_id, clip_id, source_path, proxy_path,
              clip_start, clip_end, src_w, src_h, words, content_hint),
        daemon=True,
    )
    _reframe_threads[variant_id] = t
    t.start()

    return {"variant_id": variant_id, "clip_id": clip_id, "status": "pending"}


@app.get("/clips/{clip_id}/smart-reframe")
async def get_smart_reframe_status(clip_id: str):
    """Poll status of the latest smart-reframe job for a clip."""
    conn = dbmod.get_db()
    clip = conn.execute("SELECT id FROM clips WHERE id=?", [clip_id]).fetchone()
    conn.close()
    if not clip:
        raise HTTPException(404, "Clip not found")

    variant = dbmod.latest_reframe_variant(clip_id)
    if not variant:
        return {"clip_id": clip_id, "variant": None}

    return {
        "clip_id": clip_id,
        "variant": {
            "id": variant["id"],
            "status": variant["status"],
            "strategy": variant["strategy"],
            "content_hint": variant.get("content_hint"),
            "variant_path": variant.get("variant_path"),
            "variant_url": (
                f"/clips/{clip_id}/smart-reframe/{variant['id']}/video"
                if variant.get("variant_path") and variant["status"] == "done"
                else None
            ),
            "cloudinary_url": variant.get("cloudinary_url"),
            "analysis_time_s": variant.get("analysis_time_s"),
            "render_time_s": variant.get("render_time_s"),
            "error": variant.get("error"),
            "created_at": variant.get("created_at"),
            "plan": json.loads(variant["plan_json"]) if variant.get("plan_json") else None,
        },
    }


@app.get("/clips/{clip_id}/smart-reframe/{variant_id}/video")
async def serve_reframe_variant(clip_id: str, variant_id: str):
    """Serve the rendered variant mp4 for in-browser comparison."""
    variant = dbmod.get_reframe_variant(variant_id)
    if not variant or variant["clip_id"] != clip_id:
        raise HTTPException(404, "Variant not found")
    vpath = variant.get("variant_path")
    if not vpath or not Path(vpath).exists():
        raise HTTPException(404, "Variant video file not found")
    return FileResponse(vpath, media_type="video/mp4")


@app.post("/clips/{clip_id}/smart-reframe/{variant_id}/accept")
async def accept_reframe_variant(clip_id: str, variant_id: str):
    """Replace the clip's output_path with the accepted variant.

    This keeps the DB record (same clip_id), preserves publication history,
    and does NOT re-enqueue any pending uploads.
    """
    conn = dbmod.get_db()
    clip = conn.execute("SELECT * FROM clips WHERE id=?", [clip_id]).fetchone()
    conn.close()
    if not clip:
        raise HTTPException(404, "Clip not found")

    variant = dbmod.get_reframe_variant(variant_id)
    if not variant or variant["clip_id"] != clip_id:
        raise HTTPException(404, "Variant not found")
    if variant["status"] != "done":
        raise HTTPException(400, f"Variant status is '{variant['status']}' — must be 'done' to accept")

    vpath = variant["variant_path"]
    if not vpath or not Path(vpath).exists():
        raise HTTPException(400, "Variant file missing on disk")

    # Safety: only swap if no upload session is currently active for this clip
    conn = dbmod.get_db()
    active_upload = conn.execute(
        "SELECT id FROM yt_upload_sessions WHERE clip_id=? AND status IN ('uploading','processing')",
        [clip_id],
    ).fetchone()
    conn.close()
    if active_upload:
        raise HTTPException(409, "Clip has an active upload in progress — cannot replace file now")

    dbmod.update_clip(clip_id, output_path=vpath, captioned_path=vpath)
    dbmod.update_reframe_variant(variant_id, status="accepted")

    return {"clip_id": clip_id, "variant_id": variant_id, "new_path": vpath}


# ── WORKERS ──────────────────────────────────────────────────────────────────

@app.get("/workers/stats")
async def worker_stats():
    if pool is None:
        return {"workers": [], "queue": {}}
    return pool.stats()


# ── PUBLISHING ───────────────────────────────────────────────────────────────

@app.post("/clips/{clip_id}/publish")
async def publish_clip(clip_id: str, platforms: str, caption: str = "", hashtags: str = ""):
    """
    Publishes a clip. Only works when:
    - CONFIG.mode == 'AUTO'
    - rights_verified = 1
    - prepublish_decision = 'PUBLISH'
    - publisher is_authorized() = True
    """
    if CONFIG.mode != "AUTO":
        raise HTTPException(403, f"Publishing disabled in {CONFIG.mode} mode. Set mode=AUTO explicitly.")

    from publishers import get_publisher

    conn = dbmod.get_db()
    clip_row = conn.execute("SELECT * FROM clips WHERE id=?", [clip_id]).fetchone()
    if not clip_row:
        conn.close()
        raise HTTPException(404, "Clip not found")

    clip_dict = dict(clip_row)

    cand = conn.execute(
        "SELECT video_id FROM candidates WHERE id=?", [clip_dict["candidate_id"]]
    ).fetchone()
    video_row = conn.execute(
        "SELECT rights_verified FROM videos WHERE id=?", [cand["video_id"] if cand else ""]
    ).fetchone() if cand else None

    rights_ok = video_row and video_row[0] == 1
    gate_ok = clip_dict.get("prepublish_decision") == "PUBLISH"

    if not rights_ok:
        conn.close()
        raise HTTPException(403, "rights_verified must be 1 — call POST /videos/{id}/verify-rights first")
    if not gate_ok:
        conn.close()
        raise HTTPException(403, f"prepublish_decision is '{clip_dict.get('prepublish_decision')}', must be PUBLISH")

    hashtag_list = [h.strip().lstrip("#") for h in hashtags.split(",") if h.strip()]
    platform_list = [p.strip() for p in platforms.split(",") if p.strip()]
    results = []

    for platform in platform_list:
        publisher = get_publisher(platform)
        if not publisher.is_authorized():
            results.append({"platform": platform, "success": False, "error": "Not authorized — run OAuth flow first"})
            continue

        import types
        clip_obj = types.SimpleNamespace(**clip_dict)
        result = publisher.publish(clip_obj, caption=caption, hashtags=hashtag_list)
        results.append({
            "platform": platform,
            "success": result.success,
            "post_id": result.post_id,
            "url": result.url,
            "error": result.error,
        })

        if result.success:
            conn.execute(
                "INSERT INTO publish_log (clip_id, platform, post_id, url, published_at) VALUES (?,?,?,?,?)",
                [clip_id, platform, result.post_id, result.url, datetime.datetime.utcnow().isoformat()],
            )
            conn.commit()

    conn.close()
    return {"clip_id": clip_id, "results": results}


# ── OAUTH ────────────────────────────────────────────────────────────────────

@app.get("/oauth/{platform}/start")
async def oauth_start(platform: str):
    from publishers import get_publisher
    publisher = get_publisher(platform)
    url, state = publisher.get_auth_url(f"http://localhost:8000/oauth/{platform}/callback")
    return {"auth_url": url, "state": state}


@app.get("/oauth/{platform}/callback")
async def oauth_callback(platform: str, request: Request, code: str = None, state: str = None, error: str = None):
    if platform == "youtube":
        # Delegate to the proper YouTube PKCE handler
        return await youtube_oauth_callback(code=code, state=state, error=error)
    from publishers import get_publisher
    publisher = get_publisher(platform)
    tokens = publisher.exchange_code(code, f"http://localhost:8000/oauth/{platform}/callback")
    return {
        "platform": platform,
        "tokens": tokens,
        "instructions": "Copy these tokens to your .env file and restart the server.",
    }


# ── YOUTUBE OAUTH ────────────────────────────────────────────────────────────

@app.get("/youtube/status")
async def youtube_status():
    """Connection status and channel info. Never exposes tokens."""
    from publishers import yt_auth
    try:
        connected = yt_auth.is_connected()
        if not connected:
            return {"connected": False}
        token = yt_auth.get_valid_token()
        if not token:
            return {"connected": False}
        try:
            info = yt_auth.fetch_channel_info(token)
            return {
                "connected": True,
                "channel_id": info["channel_id"],
                "channel_title": info["title"],
                "thumbnail_url": info.get("thumbnail_url", ""),
            }
        except Exception:
            return {"connected": True, "channel_id": None, "channel_title": None}
    except RuntimeError as e:
        # Client ID / Secret not configured
        return {"connected": False, "error": str(e)}


@app.get("/youtube/connect")
async def youtube_connect():
    """Start YouTube OAuth flow — redirects browser directly to Google."""
    import secrets as _secrets
    from publishers import yt_auth
    from fastapi import HTTPException
    from fastapi.responses import RedirectResponse
    try:
        state = _secrets.token_urlsafe(24)
        verifier, _ = yt_auth.generate_pkce()
        dbmod.save_yt_oauth_state(state, verifier)
        auth_url = yt_auth.get_auth_url(state, verifier)
        return RedirectResponse(url=auth_url)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/oauth/youtube/callback")
async def youtube_oauth_callback(
    code: str = None,
    state: str = None,
    error: str = None,
):
    """OAuth callback. Validates state (one-time), exchanges code, stores tokens."""
    from fastapi.responses import HTMLResponse as _HTML
    from publishers import yt_auth

    if error:
        return _HTML(f"<h2>Authorization denied</h2><p>{error}</p>", status_code=400)

    if not code or not state:
        return _HTML("<h2>Missing parameters</h2>", status_code=400)

    code_verifier = dbmod.consume_yt_oauth_state(state)
    if not code_verifier:
        return _HTML("<h2>Invalid or expired state parameter</h2>", status_code=400)

    try:
        token_data = yt_auth.exchange_code(code, code_verifier)
        access_token = token_data.get("access_token")
        channel = yt_auth.fetch_channel_info(access_token)
        return _HTML(
            f"""
            <html><body style="font-family:sans-serif;background:#111;color:#eee;padding:40px">
            <h2 style="color:#4ade80">YouTube Connected</h2>
            <p>Channel: <b>{channel['title']}</b></p>
            <p>You can close this tab and return to the dashboard.</p>
            </body></html>
            """
        )
    except Exception as exc:
        return _HTML(f"<h2>Authorization failed</h2><p>{exc}</p>", status_code=500)


@app.post("/youtube/disconnect")
async def youtube_disconnect():
    """Revoke YouTube tokens and clear connection."""
    from publishers import yt_auth
    yt_auth.revoke_tokens()
    return {"disconnected": True}


@app.post("/youtube/sync")
async def youtube_sync(background_tasks: BackgroundTasks):
    """
    Trigger a full channel sync in the background.
    Reconciles all local publications with the actual state of @contentenginelv.
    Safe to call multiple times — idempotent.
    """
    from publishers import yt_auth
    try:
        token = yt_auth.get_valid_token()
        if not token:
            raise HTTPException(400, "YouTube not connected")
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    def _do_sync():
        from publishers.yt_sync import run_channel_sync
        try:
            result = run_channel_sync(token)
            import logging
            logging.getLogger(__name__).info("[/youtube/sync] %s", result)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("[/youtube/sync] background sync failed")

    background_tasks.add_task(_do_sync)
    return {"queued": True, "message": "Sync iniciado en segundo plano"}


@app.get("/youtube/sync/status")
async def youtube_sync_status():
    """Return the last sync state for the connected channel."""
    from publishers.yt_sync import CHANNEL_ID
    with dbmod.db() as conn:
        row = conn.execute(
            "SELECT * FROM yt_sync_state WHERE channel_id=?", (CHANNEL_ID,)
        ).fetchone()
    if not row:
        return {"channel_id": CHANNEL_ID, "last_sync_at": None, "never_synced": True}
    return dict(row)


# ── YOUTUBE UPLOADS ───────────────────────────────────────────────────────────

@app.post("/publications/{pub_id}/youtube-upload")
async def start_youtube_upload(pub_id: str, body: dict = Body({})):
    """
    Validate and enqueue a YouTube upload for a publication.

    Security rules enforced here:
    - Publication platform must be youtube_shorts
    - Clip file must exist on disk
    - YouTube account must be connected
    - is_for_kids must be provided as boolean (required by YouTube ToS)
    - privacyStatus is passed through to YouTube; YouTube may override to 'private' for unaudited API projects
    """
    from publishers import yt_auth
    from publishers.yt_upload import compute_file_hash

    if "is_for_kids" not in body:
        raise HTTPException(400, "is_for_kids (boolean) is required by YouTube Terms of Service")
    is_for_kids = bool(body["is_for_kids"])

    _valid_privacy = {"private", "unlisted", "public"}
    privacy_status = body.get("privacy_status", "private")
    if privacy_status not in _valid_privacy:
        raise HTTPException(422, f"privacy_status must be one of {sorted(_valid_privacy)}")

    conn = dbmod.get_db()
    pub = conn.execute("SELECT * FROM publications WHERE id=?", [pub_id]).fetchone()
    conn.close()
    if not pub:
        raise HTTPException(404, "Publication not found")
    pub = dict(pub)

    if pub["platform"] != "youtube_shorts":
        raise HTTPException(400, "This publication is not for youtube_shorts")

    # Check for existing session
    existing = dbmod.get_yt_upload_session_by_pub(pub_id)
    if existing:
        return {"session_id": existing["id"], "status": existing["status"], "existing": True}

    # Validate clip
    conn = dbmod.get_db()
    clip = conn.execute("""
            SELECT cl.*, ca.id as candidate_id
            FROM clips cl
            JOIN candidates ca ON cl.candidate_id = ca.id
            WHERE cl.id=?
        """, [pub["clip_id"]]).fetchone()
    conn.close()

    if not clip:
        raise HTTPException(404, "Clip not found")
    clip = dict(clip)

    # Verify file
    file_path = clip.get("captioned_path") or clip.get("output_path")
    if not file_path or not Path(file_path).exists():
        raise HTTPException(400, "Clip file not found on disk")

    # Verify YouTube connected
    if not yt_auth.is_connected():
        raise HTTPException(400, "YouTube account not connected — use /youtube/connect first")

    token = yt_auth.get_valid_token()
    if not token:
        raise HTTPException(400, "YouTube token invalid — re-authenticate via /youtube/connect")

    channel_info = yt_auth.fetch_channel_info(token)
    channel_id = channel_info["channel_id"]

    file_size = Path(file_path).stat().st_size
    file_hash = compute_file_hash(file_path)

    title = (body.get("title") or pub.get("title") or "").strip()[:100]
    description = (body.get("description") or pub.get("caption") or "").strip()[:5000]
    _valid, _reason = dbmod.validate_pub_metadata(title, description)
    if not _valid:
        raise HTTPException(400, f"METADATA_INVALID: {_reason} — edit title/description in Publishing before uploading")
    tags_raw = body.get("tags")
    if tags_raw is None:
        raw_hashtags = pub.get("hashtags") or "[]"
        try:
            hashtags = json.loads(raw_hashtags) if isinstance(raw_hashtags, str) else raw_hashtags
        except Exception:
            hashtags = []
        tags = [t.lstrip("#") for t in hashtags if t]
    else:
        tags = [str(t) for t in tags_raw]

    session_id = dbmod.create_yt_upload_session(
        pub_id=pub_id,
        clip_id=pub["clip_id"],
        channel_id=channel_id,
        title=title,
        description=description,
        tags=tags,
        is_for_kids=is_for_kids,
        file_path=str(file_path),
        file_hash=file_hash,
        file_size=file_size,
        privacy_status=privacy_status,
        series_id=pub.get("series_id") or None,
        series_part=pub.get("series_part") or 0,
    )

    return {"session_id": session_id, "status": "pending", "existing": False}


def _safe_yt_session(row: dict) -> dict:
    """Strip session_url before returning to clients."""
    r = dict(row)
    r.pop("session_url", None)
    return r


@app.get("/yt-uploads/{session_id}")
async def get_yt_upload_status(session_id: str):
    """Poll upload status. Does NOT expose session_url."""
    row = dbmod.get_yt_upload_session(session_id)
    if not row:
        raise HTTPException(404, "Upload session not found")
    return _safe_yt_session(row)


@app.post("/yt-uploads/{session_id}/cancel")
async def cancel_yt_upload(session_id: str):
    """Cancel an upload session if it is still pending."""
    row = dbmod.get_yt_upload_session(session_id)
    if not row:
        raise HTTPException(404, "Upload session not found")
    if row["status"] != "pending":
        raise HTTPException(400, f"Cannot cancel session in status '{row['status']}' — only 'pending' can be cancelled")
    dbmod.update_yt_upload_session(
        session_id,
        status="cancelled",
        updated_at=datetime.utcnow().isoformat(),
    )
    return {"cancelled": True}


@app.get("/publications/{pub_id}/yt-upload")
async def get_pub_yt_upload(pub_id: str):
    """Get the YouTube upload session for a publication, if one exists."""
    row = dbmod.get_yt_upload_session_by_pub(pub_id)
    if not row:
        raise HTTPException(404, "No upload session for this publication")
    return row


# ── ANALYTICS ────────────────────────────────────────────────────────────────

@app.get("/analytics/summary")
async def analytics_summary():
    from analytics.collector import AnalyticsCollector
    return AnalyticsCollector().summary()


@app.post("/analytics/collect")
async def collect_analytics():
    from analytics.collector import AnalyticsCollector
    AnalyticsCollector().collect_all()
    return {"status": "collected"}


# ── LEARNING ─────────────────────────────────────────────────────────────────

@app.post("/learning/autopsy")
async def run_autopsy():
    from learning.autopsy import ContentAutopsy
    return ContentAutopsy().run_autopsy()


@app.get("/learning/weight-suggestions")
async def weight_suggestions():
    from learning.autopsy import ContentAutopsy
    return ContentAutopsy().suggest_weight_adjustments()


# ── ANALYSIS ─────────────────────────────────────────────────────────────────

@app.get("/jobs/{job_id}/analysis")
async def get_job_analysis(job_id: str):
    """Full viral analysis: ranked candidates + detected series for a job."""
    conn = dbmod.get_db()
    job = conn.execute("SELECT * FROM jobs WHERE id=?", [job_id]).fetchone()
    if not job:
        conn.close()
        raise HTTPException(404, "Job not found")

    video = conn.execute("SELECT * FROM videos WHERE job_id=?", [job_id]).fetchone()
    candidates = conn.execute(
        "SELECT * FROM candidates WHERE job_id=? ORDER BY virality_score DESC",
        [job_id]
    ).fetchall()
    series_rows = conn.execute(
        "SELECT * FROM clip_series WHERE job_id=? ORDER BY series_score DESC",
        [job_id]
    ).fetchall()
    conn.close()

    top_clips = []
    for c in candidates:
        cd = dict(c)
        try:
            cd["score_breakdown"] = json.loads(cd.get("score_breakdown") or "{}")
        except Exception:
            cd["score_breakdown"] = {}
        try:
            cd["virality_reasons"] = json.loads(cd.get("virality_reasons") or "[]")
        except Exception:
            cd["virality_reasons"] = []
        try:
            cd["platform_scores"] = json.loads(cd.get("platform_scores") or "{}")
        except Exception:
            cd["platform_scores"] = {}
        top_clips.append(cd)

    series_list = []
    for s in series_rows:
        sd = dict(s)
        try:
            sd["series_reasons"] = json.loads(sd.get("series_reasons") or "[]")
        except Exception:
            sd["series_reasons"] = []
        conn2 = dbmod.get_db()
        raw_parts = conn2.execute(
            "SELECT * FROM candidates WHERE series_id=? ORDER BY series_part ASC, start_s ASC",
            [sd["id"]]
        ).fetchall()
        conn2.close()
        # Collapse multiple candidates with the same series_part into one entry
        grouped: dict = {}
        for p in raw_parts:
            pd = dict(p)
            pn = pd.get("series_part") or 1
            if pn not in grouped:
                grouped[pn] = pd
            else:
                # Expand bounds to cover all candidates in this part
                grouped[pn]["start_s"] = min(grouped[pn]["start_s"], pd["start_s"])
                grouped[pn]["end_s"] = max(grouped[pn]["end_s"], pd["end_s"])
        sd["parts"] = [grouped[k] for k in sorted(grouped.keys())]
        series_list.append(sd)

    high_virality = sum(1 for c in top_clips if (c.get("virality_score") or 0) >= 70)

    return {
        "job_id": job_id,
        "video": {
            "duration_s": video["duration_s"] if video else None,
            "title": video["source_title"] if video else None,
            "platform": video["source_platform"] if video else None,
            "width": video["width"] if video else None,
            "height": video["height"] if video else None,
        } if video else {},
        "stats": {
            "total_candidates": len(top_clips),
            "high_virality_count": high_virality,
            "series_count": len(series_list),
        },
        "top_clips": top_clips,
        "series": series_list,
    }


@app.get("/jobs/{job_id}/timing")
async def get_job_timing(job_id: str):
    """Return per-stage timing data for a completed job."""
    rows = dbmod.get_pipeline_timings(job_id)
    if not rows:
        return {"job_id": job_id, "stages": [], "message": "No timing data (job may predate instrumentation)"}
    total = sum(r["duration_s"] for r in rows if r["status"] == "ok")
    return {
        "job_id": job_id,
        "total_s": round(total, 1),
        "stages": [
            {
                "stage": r["stage"],
                "duration_s": round(r["duration_s"], 2),
                "status": r["status"],
                "meta": json.loads(r["meta"]) if r.get("meta") else {},
            }
            for r in rows
        ],
    }


@app.get("/performance/summary")
async def get_performance_summary():
    """Aggregate timing stats across all jobs."""
    conn = dbmod.get_db()
    rows = conn.execute("""
        SELECT stage, AVG(duration_s) as avg_s, MIN(duration_s) as min_s,
               MAX(duration_s) as max_s, COUNT(*) as runs
        FROM pipeline_timings
        WHERE status='ok'
        GROUP BY stage
        ORDER BY avg_s DESC
    """).fetchall()
    conn.close()
    return {
        "stages": [
            {"stage": r["stage"], "avg_s": round(r["avg_s"], 1),
             "min_s": round(r["min_s"], 1), "max_s": round(r["max_s"], 1),
             "runs": r["runs"]}
            for r in rows
        ]
    }


@app.get("/jobs/{job_id}/series")
async def get_job_series(job_id: str):
    """List all detected series for a job."""
    conn = dbmod.get_db()
    job = conn.execute("SELECT id FROM jobs WHERE id=?", [job_id]).fetchone()
    conn.close()
    if not job:
        raise HTTPException(404, "Job not found")
    return dbmod.get_job_series(job_id)


@app.post("/jobs/{job_id}/generate-top")
async def generate_top_clips(
    job_id: str,
    n: int = Query(5, ge=1, le=20),
    min_score: float = Query(0.0, ge=0.0, le=100.0),
    candidate_id: str = Query(None),
):
    """Generate top N candidates as clips (skips candidates that already have a clip).
    If candidate_id is provided, generates only that specific candidate."""
    conn = dbmod.get_db()
    job = conn.execute("SELECT * FROM jobs WHERE id=?", [job_id]).fetchone()
    if not job:
        conn.close()
        raise HTTPException(404, "Job not found")

    video = conn.execute("SELECT * FROM videos WHERE job_id=?", [job_id]).fetchone()
    if not video:
        conn.close()
        raise HTTPException(404, "No video for this job")

    if candidate_id:
        # Generate a specific candidate (if not already generated)
        candidates = conn.execute("""
            SELECT ca.* FROM candidates ca
            LEFT JOIN clips cl ON cl.candidate_id = ca.id
            WHERE ca.id=? AND ca.job_id=? AND cl.id IS NULL
        """, [candidate_id, job_id]).fetchall()
    else:
        # Top candidates that don't yet have a clip
        candidates = conn.execute("""
            SELECT ca.* FROM candidates ca
            LEFT JOIN clips cl ON cl.candidate_id = ca.id
            WHERE ca.job_id=? AND (ca.virality_score >= ? OR ?) AND cl.id IS NULL
            ORDER BY ca.virality_score DESC LIMIT ?
        """, [job_id, min_score, min_score == 0, n]).fetchall()
    conn.close()

    if not candidates:
        return {"generated": [], "message": "No ungenerated candidates found"}

    from engine.renderers.render_clip import render_clips_onepass

    source_path = video["path"]
    cand_dicts = [dict(c) for c in candidates]

    # Load cached words for captions
    words = dbmod.get_cached_words(video["id"]) or []

    creator_slug = video.get("creator_slug") or "unknown"
    video_slug = video.get("video_slug") or "clips"
    output_subdir = f"{creator_slug}/{video_slug}"

    src_w = video.get("width") or 1920
    src_h = video.get("height") or 1080

    clip_ids = render_clips_onepass(
        job_id=job_id, source=source_path, finalists=cand_dicts,
        words=words, src_w=src_w, src_h=src_h, output_subdir=output_subdir,
    )

    return {"generated": clip_ids, "count": len(clip_ids)}


@app.post("/jobs/{job_id}/generate-series/{series_id}")
async def generate_series_clips(job_id: str, series_id: str):
    """Generate all clips for a detected series."""
    conn = dbmod.get_db()
    job = conn.execute("SELECT * FROM jobs WHERE id=?", [job_id]).fetchone()
    series = conn.execute("SELECT * FROM clip_series WHERE id=? AND job_id=?",
                          [series_id, job_id]).fetchone()
    if not job or not series:
        conn.close()
        raise HTTPException(404, "Job or series not found")

    video = conn.execute("SELECT * FROM videos WHERE job_id=?", [job_id]).fetchone()
    parts = conn.execute(
        "SELECT * FROM candidates WHERE series_id=? ORDER BY series_part ASC",
        [series_id]
    ).fetchall()
    conn.close()

    if not parts or not video:
        raise HTTPException(404, "Series parts or video not found")

    from engine.renderers.render_clip import render_clips_onepass

    source_path = video["path"]
    part_dicts = [dict(p) for p in parts]
    creator_slug = video.get("creator_slug") or "unknown"
    video_slug = video.get("video_slug") or "series"
    output_subdir = f"{creator_slug}/{video_slug}/series"

    words = dbmod.get_cached_words(video["id"]) or []
    src_w = video.get("width") or 1920
    src_h = video.get("height") or 1080

    clip_ids = render_clips_onepass(
        job_id=job_id, source=source_path, finalists=part_dicts,
        words=words, src_w=src_w, src_h=src_h, output_subdir=output_subdir,
    )

    return {"series_id": series_id, "generated": clip_ids, "count": len(clip_ids)}


# ── CREATORS ─────────────────────────────────────────────────────────────────

@app.get("/collections")
async def list_collections():
    return dbmod.get_all_collections()


@app.post("/collections")
async def create_collection(body: dict = Body(...)):
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    cid = dbmod.create_collection(
        name=name,
        description=body.get("description", ""),
        color=body.get("color", "#3b82f6"),
    )
    return dbmod.get_collection(cid)


@app.get("/collections/{collection_id}")
async def get_collection(collection_id: str):
    c = dbmod.get_collection(collection_id)
    if not c:
        raise HTTPException(404, "Collection not found")
    return c


@app.put("/collections/{collection_id}")
async def update_collection(collection_id: str, body: dict = Body(...)):
    c = dbmod.get_collection(collection_id)
    if not c:
        raise HTTPException(404, "Collection not found")
    dbmod.update_collection(
        collection_id,
        name=body.get("name"),
        description=body.get("description"),
        color=body.get("color"),
    )
    return dbmod.get_collection(collection_id)


@app.delete("/collections/{collection_id}")
async def delete_collection(collection_id: str):
    c = dbmod.get_collection(collection_id)
    if not c:
        raise HTTPException(404, "Collection not found")
    dbmod.delete_collection(collection_id)
    return {"status": "deleted", "collection_id": collection_id}


@app.get("/collections/{collection_id}/videos")
async def get_collection_videos(
    collection_id: str,
    sort: str = Query("newest"),
    limit: int = Query(200, le=500),
):
    c = dbmod.get_collection(collection_id)
    if not c:
        raise HTTPException(404, "Collection not found")
    return dbmod.get_collection_videos(collection_id, sort=sort, limit=limit)


@app.post("/collections/{collection_id}/items")
async def add_collection_items(collection_id: str, body: dict = Body(...)):
    c = dbmod.get_collection(collection_id)
    if not c:
        raise HTTPException(404, "Collection not found")
    items = body.get("items", [])
    added = dbmod.add_collection_items(collection_id, items)
    return {"status": "added", "count": added}


@app.delete("/collections/{collection_id}/items")
async def remove_collection_items(collection_id: str, body: dict = Body(...)):
    c = dbmod.get_collection(collection_id)
    if not c:
        raise HTTPException(404, "Collection not found")
    items = body.get("items", [])
    removed = dbmod.remove_collection_items(collection_id, items)
    return {"status": "removed", "count": removed}


@app.get("/creators")
async def list_creators(search: str = Query("")):
    creators = dbmod.get_creators()
    if search:
        q = search.strip().lower()
        import unicodedata
        def norm(s): return unicodedata.normalize('NFD', s or '').encode('ascii','ignore').decode().lower()
        nq = norm(q)
        creators = [c for c in creators if nq in norm(c.get('name','')) or nq in norm(c.get('handle',''))]
    return creators


@app.post("/creators")
async def create_creator(body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    # Prevent duplicates (case-insensitive)
    conn = dbmod.get_db()
    existing = conn.execute(
        "SELECT id FROM creators WHERE name=? COLLATE NOCASE", [name]
    ).fetchone()
    conn.close()
    if existing:
        return {"id": existing[0], "created": False}
    cid = dbmod.create_creator(
        name=name,
        display_name=body.get("display_name"),
        handle=body.get("handle"),
        platform=body.get("platform"),
        channel_url=body.get("channel_url"),
        external_channel_id=body.get("external_channel_id"),
    )
    return {"id": cid, "created": True}


@app.get("/creators/{creator_id}")
async def get_creator(creator_id: str):
    c = dbmod.get_creator(creator_id)
    if not c:
        raise HTTPException(404, "Creator not found")
    return c


@app.put("/creators/{creator_id}")
async def update_creator(creator_id: str, body: dict = Body(...)):
    conn = dbmod.get_db()
    row = conn.execute("SELECT id FROM creators WHERE id=?", [creator_id]).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Creator not found")
    allowed = {"name","display_name","handle","platform","channel_url","is_favorite","avatar_color"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if updates:
        dbmod.update_creator(creator_id, **updates)
    return {"status": "updated"}


@app.get("/creators/{creator_id}/impact")
async def get_creator_impact(creator_id: str):
    """Return content counts for a creator — used by the delete confirmation modal."""
    with dbmod.db() as conn:
        row = conn.execute("SELECT id FROM creators WHERE id=?", [creator_id]).fetchone()
    if not row:
        raise HTTPException(404, "Creator not found")
    return dbmod.get_creator_impact(creator_id)


@app.get("/creators/{creator_id}/packages")
async def list_creator_packages(creator_id: str):
    conn = dbmod.get_db()
    try:
        if creator_id == "__unassigned__":
            slugs = [r[0] for r in conn.execute(
                "SELECT DISTINCT creator_slug FROM videos WHERE creator_id IS NULL AND creator_slug IS NOT NULL"
            ).fetchall()]
        else:
            slugs = [r[0] for r in conn.execute(
                "SELECT DISTINCT creator_slug FROM videos WHERE creator_id=? AND creator_slug IS NOT NULL",
                (creator_id,),
            ).fetchall()]
        if not slugs:
            return []
        placeholders = ",".join("?" * len(slugs))
        rows = conn.execute(
            f"""SELECT p.*, COUNT(i.id) as item_count
                FROM clip_packages p
                LEFT JOIN clip_package_items i ON i.package_id = p.id
                WHERE p.creator_slug IN ({placeholders})
                GROUP BY p.id
                ORDER BY p.created_at DESC""",
            slugs,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/packages")
async def list_packages_global(
    creator_id: str = Query(""),
    sort: str = Query("newest"),
    page: int = Query(1),
    limit: int = Query(24),
    search: str = Query(""),
):
    """Return all clip_packages with latest_clip_at, clip_count, creator info. Paginated."""
    sort_map = {
        "newest": "CASE WHEN ps.latest_clip_at IS NULL THEN 1 ELSE 0 END, ps.latest_clip_at DESC, p.id DESC",
        "oldest": "CASE WHEN ps.latest_clip_at IS NULL THEN 1 ELSE 0 END, ps.latest_clip_at ASC, p.id ASC",
        "name_asc": "p.name COLLATE NOCASE ASC, p.id ASC",
        "name_desc": "p.name COLLATE NOCASE DESC, p.id ASC",
    }
    order_clause = sort_map.get(sort, sort_map["newest"])

    base_cte = """
        WITH creator_map AS (
            SELECT v.creator_slug, MIN(c.id) AS creator_id, MIN(c.name) AS creator_name,
                   MIN(c.avatar_color) AS avatar_color
            FROM videos v
            JOIN creators c ON c.id = v.creator_id
            WHERE v.creator_slug IS NOT NULL AND v.creator_id IS NOT NULL
            GROUP BY v.creator_slug
        ),
        pkg_clips AS (
            SELECT pi.package_id, cl.candidate_id, MIN(cl.created_at) AS birth
            FROM clip_package_items pi
            JOIN publications pub ON pub.id = pi.pub_id
            JOIN clips cl ON cl.id = pub.clip_id
            LEFT JOIN candidates ca ON ca.id = cl.candidate_id
            WHERE (ca.id IS NULL OR ca.status != 'GROUPED_ALT')
            GROUP BY pi.package_id, cl.candidate_id
        ),
        pkg_stats AS (
            SELECT package_id, COUNT(DISTINCT candidate_id) AS clip_count, MAX(birth) AS latest_clip_at
            FROM pkg_clips
            GROUP BY package_id
        )
    """

    where_parts = []
    params: list = []

    if creator_id == "__unassigned__":
        where_parts.append("cm.creator_id IS NULL")
    elif creator_id:
        where_parts.append("cm.creator_id = ?")
        params.append(creator_id)

    if search:
        where_parts.append("p.name LIKE ?")
        params.append(f"%{search}%")

    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    select_body = f"""
        SELECT p.id, p.name, p.description, p.creator_slug, p.created_at, p.updated_at,
               COALESCE(ps.clip_count, 0) AS clip_count,
               ps.latest_clip_at,
               cm.creator_id, cm.creator_name, cm.avatar_color,
               (SELECT COUNT(*) FROM clip_package_items WHERE package_id = p.id) AS item_count
        FROM clip_packages p
        LEFT JOIN pkg_stats ps ON ps.package_id = p.id
        LEFT JOIN creator_map cm ON cm.creator_slug = p.creator_slug
        {where_clause}
    """

    conn = dbmod.get_db()
    try:
        count_row = conn.execute(
            base_cte + f"SELECT COUNT(*) FROM clip_packages p LEFT JOIN pkg_stats ps ON ps.package_id = p.id LEFT JOIN creator_map cm ON cm.creator_slug = p.creator_slug {where_clause}",
            params,
        ).fetchone()
        total = count_row[0] if count_row else 0

        offset = (max(page, 1) - 1) * limit
        rows = conn.execute(
            base_cte + select_body + f"ORDER BY {order_clause} LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        packages = [dict(r) for r in rows]
        pages = max(1, (total + limit - 1) // limit)
        return {"packages": packages, "total": total, "page": page, "pages": pages}
    finally:
        conn.close()


@app.delete("/creators/{creator_id}")
async def delete_creator(creator_id: str, action: str = Query("unassign")):
    conn = dbmod.get_db()
    row = conn.execute("SELECT id FROM creators WHERE id=?", [creator_id]).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Creator not found")
    if action not in ("unassign", "delete_all"):
        raise HTTPException(400, "action must be 'unassign' or 'delete_all'")
    dbmod.delete_creator(creator_id, action=action)
    return {"status": "deleted", "action": action}


# ── VIDEOS ────────────────────────────────────────────────────────────────────

@app.get("/videos")
async def list_videos(
    creator_id: str = Query(None),
    status: str = Query(None),
    search: str = Query(None),
    platform: str = Query(None),
    sort: str = Query("newest"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    virality_min: float = Query(None),
    virality_max: float = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    collection_id: str = Query(None),
):
    return dbmod.get_all_videos(
        creator_id=creator_id, status=status, search=search,
        platform=platform, sort=sort, limit=limit, offset=offset,
        virality_min=virality_min, virality_max=virality_max,
        date_from=date_from, date_to=date_to, collection_id=collection_id,
    )


@app.patch("/videos/{video_id}/creator")
async def assign_video_creator(video_id: str, body: dict = Body(...)):
    creator_id = body.get("creator_id")  # None means unassign
    conn = dbmod.get_db()
    row = conn.execute("SELECT id FROM videos WHERE id=?", [video_id]).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Video not found")
    dbmod.assign_video_creator(video_id, creator_id)
    return {"status": "assigned", "video_id": video_id, "creator_id": creator_id}


@app.post("/videos/bulk-assign")
async def bulk_assign_creator(body: dict = Body(...)):
    video_ids = body.get("video_ids", [])
    creator_id = body.get("creator_id")  # None = unassign
    for vid in video_ids:
        dbmod.assign_video_creator(vid, creator_id)
    return {"status": "assigned", "count": len(video_ids)}


@app.delete("/videos/{video_id}")
async def delete_video(video_id: str, delete_clips: bool = Query(True)):
    conn = dbmod.get_db()
    row = conn.execute("SELECT id FROM videos WHERE id=?", [video_id]).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Video not found")
    dbmod.delete_video_by_id(video_id, delete_clips=delete_clips)
    return {"status": "deleted", "video_id": video_id}


@app.post("/videos/bulk-delete-impact")
async def bulk_delete_impact(body: dict = Body(...)):
    video_ids = body.get("video_ids", [])
    if not video_ids:
        raise HTTPException(400, "No video_ids provided")
    return dbmod.get_bulk_delete_impact(video_ids)


@app.post("/videos/bulk-delete")
async def bulk_delete_videos(body: dict = Body(...)):
    video_ids = body.get("video_ids", [])
    delete_clips = body.get("delete_clips", True)
    for vid in video_ids:
        try:
            dbmod.delete_video_by_id(vid, delete_clips=delete_clips)
        except Exception:
            pass
    return {"status": "deleted", "count": len(video_ids)}


@app.delete("/clips/{clip_id}")
async def delete_clip(clip_id: str):
    conn = dbmod.get_db()
    row = conn.execute("SELECT id FROM clips WHERE id=?", [clip_id]).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Clip not found")
    dbmod.delete_clip_by_id(clip_id)
    return {"status": "deleted", "clip_id": clip_id}


@app.post("/clips/bulk-delete")
async def bulk_delete_clips(body: dict = Body(...)):
    clip_ids = body.get("clip_ids", [])
    deleted = 0
    for cid in clip_ids:
        try:
            dbmod.delete_clip_by_id(cid)
            deleted += 1
        except Exception:
            pass
    return {"status": "deleted", "count": deleted}


@app.get("/videos/{video_id}/thumbnail")
async def get_video_thumbnail(video_id: str):
    conn = dbmod.get_db()
    row = conn.execute("SELECT * FROM videos WHERE id=?", [video_id]).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Video not found")

    # Check existing thumbnail
    thumb_path = row["thumbnail_path"] if row["thumbnail_path"] else None
    if thumb_path and Path(thumb_path).exists():
        return FileResponse(thumb_path, media_type="image/jpeg")

    # Generate thumbnail
    video_path = row["path"]
    if not video_path or not Path(video_path).exists():
        raise HTTPException(404, "Video file not found on disk")

    thumb_dir = Path(CONFIG.output_dir) / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = str(thumb_dir / f"{video_id}.jpg")
    duration_s = row["duration_s"] or 10
    seek_time = max(1.0, duration_s * 0.08)

    cmd = [CONFIG.ffmpeg_path, "-y", "-ss", str(seek_time), "-i", video_path,
           "-frames:v", "1", "-q:v", "5", "-vf", "scale=320:-1", thumb_path]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30, check=True)
    except Exception:
        raise HTTPException(500, "Thumbnail generation failed")

    # Save thumbnail path to DB
    upd_conn = dbmod.get_db()
    upd_conn.execute("UPDATE videos SET thumbnail_path=? WHERE id=?", [thumb_path, video_id])
    upd_conn.commit(); upd_conn.close()

    return FileResponse(thumb_path, media_type="image/jpeg")


@app.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str):
    conn = dbmod.get_db()
    row = conn.execute("SELECT * FROM jobs WHERE id=?", [job_id]).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Job not found")
    if row["status"] not in ("FAILED", "failed"):
        raise HTTPException(400, f"Job status is '{row['status']}', only FAILED jobs can be retried")

    source = row["source_path"]
    creator = row["creator"] or "unknown"
    clips = row["target_clips"] or 3
    platforms = json.loads(row["target_platforms"] or '["tiktok","instagram"]')

    # Clear error, reset status
    dbmod.update_job(job_id, status="QUEUED", error=None)
    _jobs[job_id] = {
        "id": job_id, "status": "queued", "source": source,
        "creator": creator, "created_at": row["created_at"],
        "result": None, "error": None,
    }
    if pool is not None:
        pool.submit(job_id, source, clips, platforms, row["mode"] or "REVIEW", creator)
    else:
        raise HTTPException(503, "Worker pool not available")
    return {"status": "requeued", "job_id": job_id}


# ── VIDEO PACKAGES ────────────────────────────────────────────────────────────

@app.get("/videos/{video_id}/package")
async def get_video_package(video_id: str):
    """Return the complete ordered clip list for a source video (the video package)."""
    pkg = dbmod.get_video_package(video_id)
    if not pkg:
        raise HTTPException(404, "Video not found")
    return pkg


@app.post("/videos/{video_id}/package/ensure-publications")
async def ensure_package_publications(video_id: str):
    """Create missing youtube_shorts publications for all non-rejected clips (idempotent)."""
    pkg = dbmod.get_video_package(video_id)
    if not pkg:
        raise HTTPException(404, "Video not found")
    result = dbmod.ensure_video_package_publications(video_id)
    return result


@app.post("/videos/{video_id}/package/publish")
async def publish_video_package(video_id: str, body: dict = Body(...)):
    """
    Ensure publications exist then create an upload batch with all ready
    youtube_shorts clips from this video, ordered by position.
    Body: { idempotency_key, privacy_status?, name? }
    """
    from publishers import yt_auth, yt_upload as _uploader
    import os as _os2

    if not dbmod.get_video_package(video_id):
        raise HTTPException(404, "Video not found")

    idempotency_key = (body.get("idempotency_key") or "").strip()
    if not idempotency_key:
        raise HTTPException(400, "idempotency_key required")

    existing_batch = dbmod.get_batch_by_idempotency(idempotency_key)
    if existing_batch:
        return {"batch_id": existing_batch["id"], "duplicate": True, "queued": 0, "skipped": []}

    if not yt_auth.is_connected():
        raise HTTPException(400, "YouTube not connected")

    privacy_status = (body.get("privacy_status") or "public").strip()
    if privacy_status not in {"private", "unlisted", "public"}:
        raise HTTPException(422, "privacy_status must be private, unlisted or public")

    # Ensure all clips have publications
    dbmod.ensure_video_package_publications(video_id)

    pkg = dbmod.get_video_package(video_id)
    tokens = yt_auth.load_tokens()
    channel_id = (tokens or {}).get("channel_id", "")
    name = (body.get("name") or f"Package: {(pkg['source_title'] or video_id[:8])[:50]}").strip()

    # Collect ready youtube_shorts publications ordered by position
    members_by_pos = sorted(pkg["members"], key=lambda m: m["position"])
    queued_pairs = []
    skipped = []

    for m in members_by_pos:
        yt_pubs = [p for p in m["publications"] if p["platform"] == "youtube_shorts"
                   and p["status"] not in ("archived", "published", "public", "unlisted", "private")]
        if not yt_pubs:
            # Already published or no publication
            already = [p for p in m["publications"] if p["platform"] == "youtube_shorts"
                       and p["status"] in ("published", "public", "unlisted", "private")]
            if already:
                skipped.append({"clip_id": m["clip_id"], "position": m["position"],
                                 "reason": "already_published", "pub_id": already[0]["id"]})
            elif m["prepublish_decision"] == "REJECT":
                skipped.append({"clip_id": m["clip_id"], "position": m["position"],
                                 "reason": "rejected"})
            continue

        pub_row = yt_pubs[0]
        pub_id = pub_row["id"]

        if not m["file_ok"]:
            skipped.append({"clip_id": m["clip_id"], "position": m["position"],
                             "pub_id": pub_id, "reason": "file_missing"})
            continue

        full_pub = dbmod.get_publication(pub_id)
        _title = (full_pub.get("title") or "").strip() if full_pub else ""
        _desc  = (full_pub.get("caption") or "").strip() if full_pub else ""
        _valid, _reason = dbmod.validate_pub_metadata(_title, _desc)
        if not _valid:
            skipped.append({"clip_id": m["clip_id"], "position": m["position"],
                             "pub_id": pub_id, "reason": f"metadata_invalid: {_reason}"})
            continue

        existing_session = dbmod.get_yt_upload_session_by_pub(pub_id)
        if existing_session:
            s_status = existing_session.get("status")
            if s_status in ("pending", "uploading", "processing", "paused",
                            "public", "unlisted", "private", "needs_check"):
                queued_pairs.append((pub_id, existing_session["id"]))
                continue
            # Error state — reset for retry
            try:
                fhash = _uploader.compute_file_hash(m["file_path"])
            except Exception:
                skipped.append({"clip_id": m["clip_id"], "position": m["position"],
                                 "pub_id": pub_id, "reason": "hash_failed"})
                continue
            dbmod.update_yt_upload_session(
                existing_session["id"],
                status="pending", session_url=None, remote_video_id=None,
                bytes_sent=0, file_path=m["file_path"], file_hash=fhash,
                file_size=_os2.path.getsize(m["file_path"]),
                privacy_status=privacy_status,
                error_message=None, error_code=None,
                locked_at=None, locked_by=None, attempts=0,
                updated_at=datetime.datetime.utcnow().isoformat(),
            )
            queued_pairs.append((pub_id, existing_session["id"]))
            continue

        try:
            fhash = _uploader.compute_file_hash(m["file_path"])
        except Exception:
            skipped.append({"clip_id": m["clip_id"], "position": m["position"],
                             "pub_id": pub_id, "reason": "hash_failed"})
            continue

        tags = []
        try:
            raw = (full_pub or {}).get("hashtags") or "[]"
            tags = json.loads(raw) if raw.startswith("[") else [t.lstrip("#") for t in raw.split() if t]
        except Exception:
            pass

        session_id = dbmod.create_yt_upload_session(
            pub_id=pub_id,
            clip_id=m["clip_id"],
            channel_id=channel_id,
            title=_title[:100],
            description=_desc[:5000],
            tags=tags,
            is_for_kids=False,
            file_path=m["file_path"],
            file_hash=fhash,
            file_size=_os2.path.getsize(m["file_path"]),
            privacy_status=privacy_status,
            series_id=(full_pub or {}).get("series_id") or None,
            series_part=(full_pub or {}).get("series_part") or 0,
        )
        queued_pairs.append((pub_id, session_id))

    if not queued_pairs:
        return {"batch_id": None, "queued": 0, "skipped": skipped,
                "error": "No publishable clips found in package"}

    batch_id = dbmod.create_upload_batch(name, channel_id, idempotency_key, queued_pairs,
                                         approved_privacy=privacy_status)
    return {"batch_id": batch_id, "duplicate": False, "queued": len(queued_pairs),
            "skipped": skipped, "total_in_package": pkg["total_clips"]}


@app.get("/videos/{video_id}/package/batches")
async def get_package_batches(video_id: str):
    """Return upload batches associated with this video package."""
    if not dbmod.get_video_package(video_id):
        raise HTTPException(404, "Video not found")
    return dbmod.get_video_package_batches(video_id)


@app.post("/videos/backfill-packages")
async def backfill_all_packages():
    """Create missing youtube_shorts publications for all existing videos (idempotent admin op)."""
    conn = dbmod.get_db()
    video_ids = [r["id"] for r in conn.execute("SELECT id FROM videos").fetchall()]
    conn.close()
    total_created = total_skipped = 0
    results = []
    for vid in video_ids:
        r = dbmod.ensure_video_package_publications(vid)
        total_created += r["created"]
        total_skipped += r["skipped"]
        if r["created"]:
            results.append({"video_id": vid, **r})
    return {"total_created": total_created, "total_skipped": total_skipped,
            "videos_with_new_pubs": len(results), "details": results}


# ── PUBLISHING ─────────────────────────────────────────────────────────────────

_VALID_PLATFORMS = {"tiktok", "youtube_shorts", "instagram_reels"}
_VALID_PUB_STATUSES = {"draft", "ready", "scheduled", "publishing", "published", "failed", "cancelled"}


def _clip_can_be_ready(clip_row) -> bool:
    path = clip_row.get("captioned_path") or clip_row.get("output_path")
    if not path or not Path(path).exists():
        return False
    if clip_row.get("prepublish_decision") == "REJECT":
        return False
    return True


def _fetch_clip_for_pub(conn, clip_id: str):
    return conn.execute("""
        SELECT cl.id, cl.captioned_path, cl.output_path, cl.prepublish_decision,
               ca.series_id, ca.series_part, v.creator_id, v.id as video_id
        FROM clips cl
        JOIN candidates ca ON cl.candidate_id = ca.id
        LEFT JOIN videos v ON ca.video_id = v.id
        WHERE cl.id=?
    """, [clip_id]).fetchone()


@app.get("/publications/stats")
async def publication_stats():
    return dbmod.get_publication_stats()


@app.get("/publications")
async def list_publications(
    status: str = Query(None),
    creator_id: str = Query(None),
    platform: str = Query(None),
    search: str = Query(None),
    sort: str = Query("newest"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    series_only: bool = Query(False),
    standalone_only: bool = Query(False),
):
    return dbmod.get_publications(
        status=status, creator_id=creator_id, platform=platform,
        search=search, sort=sort, limit=limit, offset=offset,
        series_only=series_only, standalone_only=standalone_only,
    )


@app.post("/publications")
async def create_publication(body: dict = Body(...)):
    clip_id = body.get("clip_id")
    platform = (body.get("platform") or "").lower()
    if not clip_id:
        raise HTTPException(400, "clip_id is required")
    if platform not in _VALID_PLATFORMS:
        raise HTTPException(400, f"platform must be one of: {', '.join(sorted(_VALID_PLATFORMS))}")
    conn = dbmod.get_db()
    clip = _fetch_clip_for_pub(conn, clip_id)
    dup = conn.execute(
        "SELECT id FROM publications WHERE clip_id=? AND platform=?", [clip_id, platform]
    ).fetchone()
    conn.close()
    if not clip:
        raise HTTPException(404, "Clip not found")
    if dup:
        return {"id": dup[0], "created": False, "message": "Publication already exists for this platform"}
    clip_d = dict(clip)
    status = "ready" if _clip_can_be_ready(clip_d) else "draft"
    pub_id = dbmod.create_publication(
        clip_id=clip_id, platform=platform,
        creator_id=clip_d.get("creator_id"), video_id=clip_d.get("video_id"),
        series_id=clip_d.get("series_id"), series_part=clip_d.get("series_part", 0),
        publication_order=body.get("publication_order", clip_d.get("series_part", 0)),
        status=status,
    )
    meta = dbmod.generate_clip_metadata(clip_id)
    dbmod.update_publication(pub_id, title=meta["title"], caption=meta["caption"],
                             hashtags=meta["hashtags"])
    dbmod.log_publication_audit(pub_id, "created", f"platform={platform} status={status}")
    return {"id": pub_id, "created": True, "status": status}


@app.get("/publications/{pub_id}")
async def get_publication(pub_id: str):
    p = dbmod.get_publication(pub_id)
    if not p:
        raise HTTPException(404, "Publication not found")
    return p


@app.put("/publications/{pub_id}")
async def update_publication(pub_id: str, body: dict = Body(...)):
    conn = dbmod.get_db()
    row = conn.execute("SELECT id FROM publications WHERE id=?", [pub_id]).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Publication not found")
    allowed = {"title", "caption", "hashtags", "notes", "platform_overrides",
               "scheduled_at", "external_url", "external_post_id"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if updates:
        # If the user is editing title or caption, mark as manually edited
        if "title" in updates or "caption" in updates:
            updates["meta_version"] = "manual"
        dbmod.update_publication(pub_id, **updates)
        dbmod.log_publication_audit(pub_id, "metadata_updated", f"fields={list(updates.keys())}")
    return {"status": "updated"}


@app.delete("/publications/{pub_id}")
async def delete_publication(pub_id: str):
    conn = dbmod.get_db()
    row = conn.execute("SELECT id FROM publications WHERE id=?", [pub_id]).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Publication not found")
    dbmod.log_publication_audit(pub_id, "deleted")
    dbmod.delete_publication(pub_id)
    return {"status": "deleted"}


@app.post("/publications/{pub_id}/mark-ready")
async def mark_publication_ready(pub_id: str):
    conn = dbmod.get_db()
    row = conn.execute("""
        SELECT p.id, p.status, cl.captioned_path, cl.output_path, cl.prepublish_decision
        FROM publications p JOIN clips cl ON p.clip_id = cl.id WHERE p.id=?
    """, [pub_id]).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Publication not found")
    if row["status"] == "published":
        raise HTTPException(400, "Publication already published — use mark-published to re-record")
    if not _clip_can_be_ready(dict(row)):
        raise HTTPException(400, "Clip is not ready: file missing or clip rejected")
    dbmod.update_publication(pub_id, status="ready")
    dbmod.log_publication_audit(pub_id, "marked_ready")
    return {"status": "ready", "pub_id": pub_id}


@app.post("/publications/{pub_id}/mark-published")
async def mark_publication_published(pub_id: str, body: dict = Body({})):
    conn = dbmod.get_db()
    row = conn.execute("SELECT id FROM publications WHERE id=?", [pub_id]).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Publication not found")
    published_at = body.get("published_at") or datetime.datetime.utcnow().isoformat()
    dbmod.update_publication(
        pub_id, status="published", published_at=published_at,
        external_url=body.get("external_url", ""),
        external_post_id=body.get("external_post_id", ""),
    )
    dbmod.log_publication_audit(pub_id, "marked_published",
                                f"url={body.get('external_url','')} at={published_at}")
    # Record initial metrics if provided
    metric_fields = {'views','likes','comments','shares','saves','avg_watch_time_s','completion_rate','followers_generated'}
    initial_metrics = {k: v for k, v in body.items() if k in metric_fields and v is not None}
    if initial_metrics:
        dbmod.add_publication_metrics(pub_id, **initial_metrics)
    return {"status": "published", "pub_id": pub_id, "published_at": published_at}


@app.post("/publications/{pub_id}/metrics")
async def record_publication_metrics(pub_id: str, body: dict = Body(...)):
    conn = dbmod.get_db()
    row = conn.execute("SELECT id FROM publications WHERE id=?", [pub_id]).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Publication not found")
    allowed = {'views','likes','comments','shares','saves','avg_watch_time_s','completion_rate','followers_generated'}
    kwargs = {k: v for k, v in body.items() if k in allowed}
    mid = dbmod.add_publication_metrics(pub_id, **kwargs)
    return {"status": "recorded", "metric_id": mid}


@app.post("/publications/{pub_id}/cancel")
async def cancel_publication(pub_id: str):
    conn = dbmod.get_db()
    row = conn.execute("SELECT id, status FROM publications WHERE id=?", [pub_id]).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Publication not found")
    if row["status"] == "published":
        raise HTTPException(400, "Cannot cancel an already published post")
    dbmod.update_publication(pub_id, status="cancelled")
    dbmod.log_publication_audit(pub_id, "cancelled")
    return {"status": "cancelled"}


@app.post("/publications/bulk-create")
async def bulk_create_publications(body: dict = Body(...)):
    clip_ids = body.get("clip_ids", [])
    platforms = [p.lower() for p in body.get("platforms", [])]
    if not clip_ids or not platforms:
        raise HTTPException(400, "clip_ids and platforms are required")
    invalid = set(platforms) - _VALID_PLATFORMS
    if invalid:
        raise HTTPException(400, f"Invalid platforms: {invalid}")
    created, skipped = [], []
    for clip_id in clip_ids:
        for platform in platforms:
            conn = dbmod.get_db()
            clip = _fetch_clip_for_pub(conn, clip_id)
            dup = conn.execute(
                "SELECT id FROM publications WHERE clip_id=? AND platform=?", [clip_id, platform]
            ).fetchone()
            conn.close()
            if dup:
                skipped.append({"clip_id": clip_id, "platform": platform, "pub_id": dup[0]})
                continue
            if not clip:
                continue
            clip_d = dict(clip)
            status = "ready" if _clip_can_be_ready(clip_d) else "draft"
            pub_id = dbmod.create_publication(
                clip_id=clip_id, platform=platform,
                creator_id=clip_d.get("creator_id"), video_id=clip_d.get("video_id"),
                series_id=clip_d.get("series_id"), series_part=clip_d.get("series_part", 0),
                publication_order=clip_d.get("series_part", 0), status=status,
            )
            meta = dbmod.generate_clip_metadata(clip_id)
            dbmod.update_publication(pub_id, title=meta["title"], caption=meta["caption"],
                                     hashtags=meta["hashtags"])
            dbmod.log_publication_audit(pub_id, "created", f"platform={platform} bulk-create")
            created.append({"pub_id": pub_id, "clip_id": clip_id, "platform": platform, "status": status})
    return {"created": created, "skipped": skipped,
            "total_created": len(created), "total_skipped": len(skipped)}


@app.post("/publications/bulk-action")
async def bulk_publication_action(body: dict = Body(...)):
    pub_ids = body.get("pub_ids", [])
    action = body.get("action", "")
    if not pub_ids or not action:
        raise HTTPException(400, "pub_ids and action are required")
    success, failed = [], []
    for pub_id in pub_ids:
        try:
            if action == "mark_ready":
                conn = dbmod.get_db()
                row = conn.execute("""
                    SELECT p.id, cl.captioned_path, cl.output_path, cl.prepublish_decision
                    FROM publications p JOIN clips cl ON p.clip_id=cl.id WHERE p.id=?
                """, [pub_id]).fetchone()
                conn.close()
                if row and _clip_can_be_ready(dict(row)):
                    dbmod.update_publication(pub_id, status="ready")
                    dbmod.log_publication_audit(pub_id, "marked_ready", "bulk")
                    success.append(pub_id)
                else:
                    failed.append(pub_id)
            elif action == "mark_published":
                dbmod.update_publication(pub_id, status="published",
                                         published_at=datetime.datetime.utcnow().isoformat())
                dbmod.log_publication_audit(pub_id, "marked_published", "bulk")
                success.append(pub_id)
            elif action in ("cancel", "delete"):
                if action == "delete":
                    dbmod.log_publication_audit(pub_id, "deleted", "bulk")
                    dbmod.delete_publication(pub_id)
                else:
                    dbmod.update_publication(pub_id, status="cancelled")
                    dbmod.log_publication_audit(pub_id, "cancelled", "bulk")
                success.append(pub_id)
            else:
                failed.append(pub_id)
        except Exception:
            failed.append(pub_id)
    return {"success": success, "failed": failed}


# ── Metadata remediation ──────────────────────────────────────────────────────

_GENERIC_TITLE_VALUES = {"short", "untitled", "clip", "video", "short 1", "clip 1"}


def _title_is_generic(title: str | None) -> bool:
    if not title:
        return True
    return (title.strip().lower() in _GENERIC_TITLE_VALUES or
            not title.strip())


@app.post("/publications/remediate-metadata")
async def remediate_publication_metadata(body: dict = Body({})):
    """
    Fill in publications with missing or generic title/caption.
    Preserves manually-set (meta_version='manual') and custom non-generic content.

    dry_run=true: returns what would be changed without modifying DB.
    force=true: regenerates even publications that already have content.
    """
    dry_run = body.get("dry_run", False)
    force = body.get("force", False)

    conn = dbmod.get_db()
    rows = conn.execute("""
        SELECT p.id, p.clip_id, p.title, p.caption, p.meta_version
        FROM publications p
        WHERE p.status NOT IN ('archived', 'cancelled')
        ORDER BY p.created_at ASC
    """).fetchall()
    conn.close()

    results = {"examined": 0, "updated": 0, "skipped": 0, "errors": 0, "details": []}

    for row in rows:
        results["examined"] += 1
        pub_id = row["id"]
        clip_id = row["clip_id"]
        current_title = row["title"] or ""
        current_caption = row["caption"] or ""
        meta_version = row["meta_version"] or ""

        # Never overwrite manual edits unless force=True
        if meta_version == "manual" and not force:
            results["skipped"] += 1
            results["details"].append({"pub_id": pub_id, "action": "skipped", "reason": "manual"})
            continue

        # Check if content needs updating:
        # - empty/generic title or caption
        # - OR old-generator output (no meta_version) that fails current validation
        _meta_valid, _ = dbmod.validate_pub_metadata(current_title, current_caption)
        needs_update = (
            force or
            _title_is_generic(current_title) or
            not current_caption.strip() or
            (not meta_version and not _meta_valid)
        )
        if not needs_update:
            results["skipped"] += 1
            continue

        # Generate new metadata
        try:
            meta = dbmod.generate_clip_metadata(clip_id)
        except Exception as exc:
            results["errors"] += 1
            results["details"].append({"pub_id": pub_id, "action": "error", "reason": str(exc)})
            continue

        new_title = meta.get("title") or ""
        new_caption = meta.get("caption") or ""
        new_meta_version = meta.get("meta_version") or "deterministic_v1"

        # Skip if generation produced no useful content (e.g. orphaned clip)
        if not new_title and not new_caption:
            results["skipped"] += 1
            results["details"].append({
                "pub_id": pub_id, "action": "skipped",
                "reason": f"no data available (meta_version={new_meta_version})",
            })
            continue

        results["details"].append({
            "pub_id": pub_id,
            "action": "updated" if not dry_run else "would_update",
            "title_before": current_title[:60],
            "title_after": new_title[:60],
            "meta_version": new_meta_version,
        })

        if not dry_run:
            try:
                dbmod.update_publication(
                    pub_id,
                    title=new_title,
                    caption=new_caption,
                    hashtags=meta.get("hashtags", []),
                    meta_version=new_meta_version,
                    title_prev=current_title or None,
                    caption_prev=current_caption or None,
                )
                dbmod.log_publication_audit(pub_id, "metadata_remediated",
                                            f"version={new_meta_version}")
                results["updated"] += 1
            except Exception as exc:
                results["errors"] += 1
                results["details"][-1]["action"] = "error"
                results["details"][-1]["reason"] = str(exc)

    return results


@app.get("/publications/download-zip")
async def download_publications_zip(
    background_tasks: BackgroundTasks,
    pub_ids: str = Query(..., description="Comma-separated publication IDs"),
):
    ids = [pid.strip() for pid in pub_ids.split(",") if pid.strip()]
    if not ids:
        raise HTTPException(400, "No publication IDs provided")
    items = []
    for pub_id in ids:
        p = dbmod.get_publication(pub_id)
        if not p:
            continue
        path = p.get("captioned_path") or p.get("output_path")
        if not path or not Path(path).exists():
            continue
        score = int(p.get("virality_score") or 0)
        platform = p.get("platform", "clip")
        series_part = p.get("series_part", 0)
        c_slug = (p.get("creator_slug") or "creator").lower().replace(" ", "-")
        v_slug = (p.get("video_slug") or "video")[:20]
        if series_part:
            fname = f"{c_slug}_{v_slug}_series_part{series_part:02d}_{score}.mp4"
        else:
            fname = f"{c_slug}_{v_slug}_{platform}_{score}.mp4"
        items.append((path, fname))
    if not items:
        raise HTTPException(404, "No downloadable files found")
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, fname in items:
            zf.write(path, fname)

    def _cleanup(path: str):
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass

    background_tasks.add_task(_cleanup, tmp.name)
    return FileResponse(tmp.name, media_type="application/zip",
                        filename=f"publications_{len(items)}_clips.zip")


@app.post("/clips/{clip_id}/prepare")
async def prepare_clip_for_publishing(clip_id: str, body: dict = Body({})):
    platforms = [p.lower() for p in body.get("platforms", list(_VALID_PLATFORMS))]
    invalid = set(platforms) - _VALID_PLATFORMS
    if invalid:
        raise HTTPException(400, f"Invalid platforms: {invalid}")
    conn = dbmod.get_db()
    clip = _fetch_clip_for_pub(conn, clip_id)
    conn.close()
    if not clip:
        raise HTTPException(404, "Clip not found")
    clip_d = dict(clip)
    meta = dbmod.generate_clip_metadata(clip_id)
    created, skipped = [], []
    for platform in platforms:
        conn2 = dbmod.get_db()
        dup = conn2.execute(
            "SELECT id FROM publications WHERE clip_id=? AND platform=?", [clip_id, platform]
        ).fetchone()
        conn2.close()
        if dup:
            skipped.append({"platform": platform, "pub_id": dup[0]})
            continue
        status = "ready" if _clip_can_be_ready(clip_d) else "draft"
        pub_id = dbmod.create_publication(
            clip_id=clip_id, platform=platform,
            creator_id=clip_d.get("creator_id"), video_id=clip_d.get("video_id"),
            series_id=clip_d.get("series_id"), series_part=clip_d.get("series_part", 0),
            publication_order=clip_d.get("series_part", 0), status=status,
        )
        dbmod.update_publication(pub_id, title=meta["title"], caption=meta["caption"],
                                 hashtags=meta["hashtags"])
        dbmod.log_publication_audit(pub_id, "created", f"platform={platform} via prepare-clip")
        created.append({"pub_id": pub_id, "platform": platform, "status": status})
    return {"clip_id": clip_id, "created": created, "skipped": skipped, "metadata": meta}


@app.post("/clips/{clip_id}/generate-metadata")
async def generate_clip_metadata(clip_id: str):
    conn = dbmod.get_db()
    row = conn.execute("SELECT id FROM clips WHERE id=?", [clip_id]).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Clip not found")
    return dbmod.generate_clip_metadata(clip_id)


@app.get("/clips/{clip_id}/publications")
async def get_clip_publications(clip_id: str):
    return dbmod.get_publications_for_clip(clip_id)


# ── ADMIN / OBSERVABILITY ─────────────────────────────────────────────────────

@app.get("/admin/status")
async def admin_status():
    """Operational snapshot: queue, workers, recent errors, storage, performance."""
    import shutil as _shutil
    import os as _os

    # ── Queue + worker stats ─────────────────────────────────────────────────
    queue_stats = pool.queue.stats() if pool else {}
    worker_info = [
        {"id": w.worker_id, "active_job": w.active_job, "alive": w.is_alive()}
        for w in (pool.workers if pool else [])
    ]

    # ── Recent failures (last 10 failed jobs) ───────────────────────────────
    conn = dbmod.get_db()
    failed_jobs = conn.execute("""
        SELECT id, creator, source_path, error, updated_at
        FROM jobs WHERE status='FAILED'
        ORDER BY updated_at DESC LIMIT 10
    """).fetchall()
    recent_errors = [
        {"job_id": r[0][:8], "creator": r[1], "error": (r[3] or "")[:120], "at": r[4]}
        for r in failed_jobs
    ]

    # ── DB stats ─────────────────────────────────────────────────────────────
    db_stats = {}
    for table in ("jobs", "videos", "candidates", "clips", "publications", "pipeline_timings"):
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        db_stats[table] = row[0] if row else 0
    conn.close()

    db_size_mb = 0.0
    try:
        db_size_mb = round(_os.path.getsize(CONFIG.db_path) / (1024 * 1024), 1)
    except Exception:
        pass

    # ── Storage breakdown ─────────────────────────────────────────────────────
    def _dir_size_mb(path: str) -> float:
        total = 0
        try:
            for entry in _os.scandir(path):
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat().st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += int(_dir_size_mb(entry.path) * 1024 * 1024)
        except Exception:
            pass
        return round(total / (1024 * 1024), 1)

    out = CONFIG.output_dir
    storage = {
        "uploads_mb":   _dir_size_mb(_os.path.join(out, "uploads")),
        "downloads_mb": _dir_size_mb(_os.path.join(out, "downloads")),
        "audio_mb":     _dir_size_mb(_os.path.join(out, "audio")),
        "proxies_mb":   _dir_size_mb(_os.path.join(out, "proxies")),
        "clips_mb":     _dir_size_mb(out) - _dir_size_mb(_os.path.join(out, "uploads"))
                        - _dir_size_mb(_os.path.join(out, "downloads"))
                        - _dir_size_mb(_os.path.join(out, "audio"))
                        - _dir_size_mb(_os.path.join(out, "proxies"))
                        - _dir_size_mb(_os.path.join(out, "thumbnails")),
        "thumbnails_mb": _dir_size_mb(_os.path.join(out, "thumbnails")),
    }
    try:
        disk = _shutil.disk_usage(out)
        storage["disk_free_gb"] = round(disk.free / (1024 ** 3), 1)
        storage["disk_total_gb"] = round(disk.total / (1024 ** 3), 1)
        storage["disk_used_pct"] = round((disk.used / disk.total) * 100, 1)
    except Exception:
        pass

    # ── Average pipeline stage times (last 50 jobs) ──────────────────────────
    conn2 = dbmod.get_db()
    perf_rows = conn2.execute("""
        SELECT stage, AVG(duration_s) as avg_s, COUNT(*) as runs
        FROM pipeline_timings WHERE status='ok'
        GROUP BY stage ORDER BY avg_s DESC
    """).fetchall()
    conn2.close()
    avg_times = [{"stage": r[0], "avg_s": round(r[1], 1), "runs": r[2]} for r in perf_rows]

    return {
        "queue": queue_stats,
        "workers": worker_info,
        "recent_errors": recent_errors,
        "database": {**db_stats, "db_size_mb": db_size_mb},
        "storage": storage,
        "avg_stage_times": avg_times,
    }


@app.get("/admin/orphans")
async def admin_orphan_check():
    """Detect orphaned files (on disk but no DB record) and orphaned DB records (no file)."""
    import os as _os

    conn = dbmod.get_db()

    # ── Clips: DB records with missing files ─────────────────────────────────
    clips = conn.execute(
        "SELECT id, captioned_path, output_path FROM clips"
    ).fetchall()
    missing_files = []
    for cl in clips:
        path = cl["captioned_path"] or cl["output_path"]
        if path and not Path(path).exists():
            missing_files.append({"clip_id": cl["id"][:8], "path": path})

    # ── Videos: DB records with missing source files ─────────────────────────
    videos = conn.execute("SELECT id, path FROM videos").fetchall()
    missing_videos = []
    for v in videos:
        if v["path"] and not Path(v["path"]).exists():
            missing_videos.append({"video_id": v["id"][:8], "path": v["path"]})

    conn.close()

    return {
        "clips_with_missing_files": len(missing_files),
        "videos_with_missing_files": len(missing_videos),
        "details": {
            "clips": missing_files[:20],
            "videos": missing_videos[:20],
        },
    }


# ── QUALITY EVALUATIONS ──────────────────────────────────────────────────────

_VALID_DECISIONS = {"publish_as_is", "publish_after_edit", "rejected", ""}
_DECISION_TO_PREPUB = {
    "publish_as_is": "PUBLISH",
    "publish_after_edit": "REVIEW",
    "rejected": "REJECT",
}
_VALID_REJECTION_REASONS = {
    "seleccion_floja", "falta_contexto", "corte_incompleto", "duplicado",
    "transcripcion", "captions", "encuadre", "otros",
}


@app.post("/clips/{clip_id}/evaluate")
async def upsert_clip_evaluation(clip_id: str, body: dict = Body(...)):
    """Create or update the human quality evaluation for a clip."""
    with dbmod.db() as conn:
        row = conn.execute(
            "SELECT id, job_id FROM clips WHERE id=?", [clip_id]
        ).fetchone()
    if not row:
        raise HTTPException(404, "Clip not found")

    decision = str(body.get("decision", ""))
    if decision not in _VALID_DECISIONS:
        raise HTTPException(400, f"Invalid decision '{decision}'. "
                            f"Must be one of: {sorted(_VALID_DECISIONS - {''})}")

    rejection_reasons = [str(r) for r in (body.get("rejection_reasons") or [])]
    bad = [r for r in rejection_reasons if r not in _VALID_REJECTION_REASONS]
    if bad:
        raise HTTPException(400, f"Unknown rejection reason(s): {bad}")

    correction_notes = str(body.get("correction_notes", ""))[:2000]
    edit_time_seconds = max(0, int(body.get("edit_time_seconds", 0)))

    # Keep prepublish_decision in sync with the structured evaluation
    if decision in _DECISION_TO_PREPUB:
        dbmod.update_clip(clip_id, prepublish_decision=_DECISION_TO_PREPUB[decision])

    snap = _get_pipeline_snapshot()
    eval_id = dbmod.upsert_evaluation(
        clip_id,
        job_id=row["job_id"] or "",
        decision=decision,
        rejection_reasons=rejection_reasons,
        correction_notes=correction_notes,
        edit_time_seconds=edit_time_seconds,
        pipeline_version=snap.get("git_hash", ""),
        config_snapshot=snap,
    )
    return {"eval_id": eval_id, "clip_id": clip_id, "decision": decision}


@app.get("/clips/{clip_id}/evaluation")
async def get_clip_evaluation(clip_id: str):
    """Return the evaluation record for a clip (404 if not yet evaluated)."""
    ev = dbmod.get_evaluation(clip_id)
    if not ev:
        raise HTTPException(404, "No evaluation found for this clip")
    return ev


@app.get("/evaluations")
async def list_evaluations(
    job_id: str = Query(None),
    decision: str = Query(None),
    from_date: str = Query(None),
    to_date: str = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List all evaluations with optional filters."""
    return dbmod.list_evaluations(
        job_id=job_id, decision=decision,
        from_date=from_date, to_date=to_date,
        limit=limit, offset=offset,
    )


@app.get("/evaluations/export")
async def export_evaluations(
    fmt: str = Query("json", alias="format"),
    job_id: str = Query(None),
    from_date: str = Query(None),
    to_date: str = Query(None),
):
    """Export evaluations as JSON or CSV."""
    rows = dbmod.list_evaluations(
        job_id=job_id, from_date=from_date, to_date=to_date, limit=10000
    )
    if fmt == "csv":
        import io, csv as _csv
        buf = io.StringIO()
        fields = [
            "id", "clip_id", "job_id", "decision", "rejection_reasons",
            "correction_notes", "edit_time_seconds", "pipeline_version",
            "source_title", "creator_slug", "duration_s", "virality_score",
            "hook_score", "job_created_at", "created_at",
        ]
        writer = _csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            r["rejection_reasons"] = ";".join(r.get("rejection_reasons") or [])
            writer.writerow(r)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=evaluations.csv"},
        )
    return rows


# ── CLIP PACKAGES ─────────────────────────────────────────────────────────────

@app.post("/packages")
async def create_package(body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    description = (body.get("description") or "").strip()
    pub_ids = body.get("pub_ids") or []
    pid = dbmod.create_package(name, description)
    if pub_ids:
        dbmod.add_package_items(pid, pub_ids)
    return {"id": pid, "name": name}


@app.get("/packages/{package_id}")
async def get_package(package_id: str):
    pkg = dbmod.get_package(package_id)
    if not pkg:
        raise HTTPException(404, "Package not found")
    return pkg


@app.put("/packages/{package_id}")
async def update_package(package_id: str, body: dict = Body(...)):
    if not dbmod.get_package(package_id):
        raise HTTPException(404, "Package not found")
    dbmod.update_package(package_id, **{k: v for k, v in body.items() if k in ("name", "description")})
    return {"status": "updated"}


@app.delete("/packages/{package_id}")
async def delete_package(package_id: str):
    if not dbmod.get_package(package_id):
        raise HTTPException(404, "Package not found")
    dbmod.delete_package(package_id)
    return {"deleted": True}


@app.post("/packages/{package_id}/items")
async def add_package_items(package_id: str, body: dict = Body(...)):
    if not dbmod.get_package(package_id):
        raise HTTPException(404, "Package not found")
    pub_ids = body.get("pub_ids") or []
    if not pub_ids:
        raise HTTPException(400, "pub_ids required")
    return {"added": dbmod.add_package_items(package_id, pub_ids)}


@app.delete("/packages/{package_id}/items")
async def remove_package_items(package_id: str, body: dict = Body(...)):
    if not dbmod.get_package(package_id):
        raise HTTPException(404, "Package not found")
    pub_ids = body.get("pub_ids") or []
    return {"removed": dbmod.remove_package_items(package_id, pub_ids)}


# ── UPLOAD BATCHES ────────────────────────────────────────────────────────────

import os as _os

@app.post("/upload-batches")
async def create_upload_batch(body: dict = Body(...)):
    """
    Validate selected publications, create yt_upload_sessions, and group them as a batch.
    idempotency_key prevents double-submit. privacyStatus is passed through to YouTube.
    """
    from publishers import yt_auth, yt_upload as _uploader

    idempotency_key = (body.get("idempotency_key") or "").strip()
    if not idempotency_key:
        raise HTTPException(400, "idempotency_key required")

    existing_batch = dbmod.get_batch_by_idempotency(idempotency_key)
    if existing_batch:
        return {"batch_id": existing_batch["id"], "duplicate": True, "queued": 0, "skipped": []}

    _valid_privacy = {"private", "unlisted", "public"}
    privacy_status = (body.get("privacy_status") or "private").strip()
    if privacy_status not in _valid_privacy:
        raise HTTPException(422, f"privacy_status must be one of {sorted(_valid_privacy)}")

    pub_ids = body.get("pub_ids") or []
    if not pub_ids:
        raise HTTPException(400, "pub_ids required")

    if not yt_auth.is_connected():
        raise HTTPException(400, "YouTube not connected")

    tokens = yt_auth.load_tokens()
    channel_id = (tokens or {}).get("channel_id", "")
    name = (body.get("name") or f"Batch {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M')}").strip()

    queued_pairs = []
    skipped = []

    for pub_id in pub_ids:
        pub = dbmod.get_publication(pub_id)
        if not pub:
            skipped.append({"pub_id": pub_id, "reason": "Publication not found"})
            continue
        if pub.get("platform") != "youtube_shorts":
            skipped.append({"pub_id": pub_id, "reason": "Not a YouTube Shorts publication"})
            continue

        clip = dbmod.get_clip(pub["clip_id"])

        file_path = None
        if clip:
            for attr in ("captioned_path", "output_path"):
                p = clip.get(attr)
                if p and Path(p).exists():
                    file_path = p
                    break
        if not file_path:
            skipped.append({"pub_id": pub_id, "reason": "Clip file not found on disk"})
            continue

        existing_session = dbmod.get_yt_upload_session_by_pub(pub_id)
        if existing_session:
            status = existing_session.get("status")
            # Active/in-progress — don't touch, include in batch as-is
            if status in ("pending", "uploading", "processing", "paused"):
                queued_pairs.append((pub_id, existing_session["id"]))
                continue
            # Already uploaded (terminal) — include in batch so progress is visible, no re-upload
            if status in ("public", "unlisted", "private", "needs_check"):
                queued_pairs.append((pub_id, existing_session["id"]))
                continue
            # Error/cancelled — reset the existing session so the worker can retry it
            if existing_session:
                try:
                    file_hash = _uploader.compute_file_hash(file_path)
                except Exception:
                    skipped.append({"pub_id": pub_id, "reason": "Could not hash file"})
                    continue
                file_size = _os.path.getsize(file_path)
                tags = []
                try:
                    raw = pub.get("hashtags") or "[]"
                    tags = json.loads(raw) if raw.startswith("[") else [t.lstrip("#") for t in raw.split() if t]
                except Exception:
                    pass
                dbmod.update_yt_upload_session(
                    existing_session["id"],
                    status="pending",
                    session_url=None,
                    remote_video_id=None,
                    bytes_sent=0,
                    file_path=file_path,
                    file_hash=file_hash,
                    file_size=file_size,
                    privacy_status=privacy_status,
                    error_message=None,
                    error_code=None,
                    locked_at=None,
                    locked_by=None,
                    attempts=0,
                    updated_at=datetime.datetime.utcnow().isoformat(),
                )
                queued_pairs.append((pub_id, existing_session["id"]))
                continue

        try:
            file_hash = _uploader.compute_file_hash(file_path)
        except Exception:
            skipped.append({"pub_id": pub_id, "reason": "Could not hash file"})
            continue

        file_size = _os.path.getsize(file_path)
        tags = []
        try:
            raw = pub.get("hashtags") or "[]"
            tags = json.loads(raw) if raw.startswith("[") else [t.lstrip("#") for t in raw.split() if t]
        except Exception:
            pass

        _title = (pub.get("title") or "").strip()
        _desc  = (pub.get("caption") or "").strip()
        _valid_b, _reason_b = dbmod.validate_pub_metadata(_title, _desc)
        if not _valid_b:
            skipped.append({"pub_id": pub_id, "reason": f"METADATA_INVALID: {_reason_b}"})
            continue
        session_id = dbmod.create_yt_upload_session(
            pub_id=pub_id,
            clip_id=pub["clip_id"],
            channel_id=channel_id,
            title=_title[:100],
            description=_desc[:5000],
            tags=tags,
            is_for_kids=False,
            file_path=file_path,
            file_hash=file_hash,
            file_size=file_size,
            privacy_status=privacy_status,
            series_id=pub.get("series_id") or None,
            series_part=pub.get("series_part") or 0,
        )
        queued_pairs.append((pub_id, session_id))

    if not queued_pairs:
        return {"batch_id": None, "queued": 0, "skipped": skipped,
                "error": "No valid YouTube Shorts publications to upload"}

    batch_id = dbmod.create_upload_batch(name, channel_id, idempotency_key, queued_pairs,
                                         approved_privacy=privacy_status)
    return {"batch_id": batch_id, "duplicate": False, "queued": len(queued_pairs), "skipped": skipped}


@app.get("/upload-batches")
async def list_upload_batches(limit: int = Query(50, le=200)):
    return dbmod.list_upload_batches(limit)


@app.get("/upload-batches/{batch_id}")
async def get_upload_batch(batch_id: str):
    batch = dbmod.get_upload_batch(batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    return batch


@app.post("/upload-batches/{batch_id}/pause")
async def pause_upload_batch(batch_id: str):
    if not dbmod.get_upload_batch(batch_id):
        raise HTTPException(404, "Batch not found")
    dbmod.pause_upload_batch(batch_id)
    return {"status": "paused"}


@app.post("/upload-batches/{batch_id}/resume")
async def resume_upload_batch(batch_id: str):
    if not dbmod.get_upload_batch(batch_id):
        raise HTTPException(404, "Batch not found")
    dbmod.resume_upload_batch(batch_id)
    return {"status": "resumed"}


@app.post("/upload-batches/{batch_id}/retry-errors")
async def retry_batch_errors(batch_id: str):
    if not dbmod.get_upload_batch(batch_id):
        raise HTTPException(404, "Batch not found")
    dbmod.retry_batch_errors(batch_id)
    return {"status": "retrying"}


@app.post("/yt-upload-sessions/{session_id}/update-privacy")
async def update_session_privacy(session_id: str, body: dict = Body({})):
    """
    Change the privacy of an already-uploaded YouTube video.
    Only valid for sessions in terminal state with a remote_video_id.
    Calls videos.update via YouTube Data API v3 — no re-upload.
    """
    from publishers import yt_auth
    import urllib.request

    _valid_privacy = {"private", "unlisted", "public"}
    privacy_status = (body.get("privacy_status") or "").strip()
    if privacy_status not in _valid_privacy:
        raise HTTPException(422, f"privacy_status must be one of {sorted(_valid_privacy)}")

    conn = dbmod.get_db()
    session = conn.execute(
        "SELECT * FROM yt_upload_sessions WHERE id=?", [session_id]
    ).fetchone()
    conn.close()
    if not session:
        raise HTTPException(404, "Session not found")
    session = dict(session)

    video_id = session.get("remote_video_id")
    if not video_id:
        raise HTTPException(400, "No remote_video_id — video not yet uploaded to YouTube")

    terminal = {"public", "unlisted", "private", "needs_check"}
    if session.get("status") not in terminal:
        raise HTTPException(400, f"Session status '{session.get('status')}' is not in a terminal state")

    if not yt_auth.is_connected():
        raise HTTPException(400, "YouTube account not connected")
    token = yt_auth.get_valid_token()
    if not token:
        raise HTTPException(400, "YouTube token invalid — re-authenticate via /youtube/connect")

    body_bytes = json.dumps({
        "id": video_id,
        "status": {"privacyStatus": privacy_status},
    }).encode()
    req = urllib.request.Request(
        f"https://www.googleapis.com/youtube/v3/videos?part=status",
        data=body_bytes,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        returned_privacy = result.get("status", {}).get("privacyStatus", "unknown")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        raise HTTPException(502, f"YouTube API error {e.code}: {err_body[:300]}")

    conn2 = dbmod.get_db()
    conn2.execute(
        "UPDATE yt_upload_sessions SET status=?, remote_privacy_status=?, privacy_status=?, updated_at=datetime('now') WHERE id=?",
        [returned_privacy, returned_privacy, privacy_status, session_id],
    )
    conn2.commit()
    conn2.close()

    mismatch = returned_privacy != privacy_status
    return {
        "requested": privacy_status,
        "returned": returned_privacy,
        "mismatch": mismatch,
    }


# ── YT QUEUE STATUS ───────────────────────────────────────────────────────────

@app.get("/yt/queue-status")
async def yt_queue_status():
    """
    Lightweight status snapshot of the YouTube upload queue.
    Used by the dashboard service status block.
    """
    from datetime import datetime, timezone as _tz
    now_iso = datetime.now(tz=_tz.utc).isoformat()
    conn = dbmod.get_db()
    try:
        uploading = conn.execute(
            "SELECT COUNT(*) FROM yt_upload_sessions WHERE status IN ('uploading','processing')"
        ).fetchone()[0]
        pending_total = conn.execute(
            "SELECT COUNT(*) FROM yt_upload_sessions WHERE status='pending'"
        ).fetchone()[0]
        pending_eligible = conn.execute(
            "SELECT COUNT(*) FROM yt_upload_sessions WHERE status='pending' "
            "AND (next_attempt_at IS NULL OR next_attempt_at <= ?)",
            (now_iso,),
        ).fetchone()[0]
        pending_waiting = conn.execute(
            "SELECT COUNT(*) FROM yt_upload_sessions WHERE status='pending' "
            "AND next_attempt_at > ?",
            (now_iso,),
        ).fetchone()[0]
        next_row = conn.execute(
            "SELECT MIN(next_attempt_at) FROM yt_upload_sessions "
            "WHERE status='pending' AND next_attempt_at > ?",
            (now_iso,),
        ).fetchone()
        next_attempt_at = next_row[0] if next_row else None
        pending_quota = conn.execute(
            "SELECT COUNT(*) FROM yt_upload_sessions WHERE status='pending'"
            " AND error_code='QUOTA_EXCEEDED' AND next_attempt_at > ?",
            (now_iso,),
        ).fetchone()[0]
    finally:
        conn.close()

    if uploading > 0:
        worker_state = "active"
    elif pending_eligible > 0:
        worker_state = "working"
    elif pending_waiting > 0:
        worker_state = "waiting"
    elif pending_total == 0:
        worker_state = "idle"
    else:
        worker_state = "idle"

    return {
        "worker_state": worker_state,
        "uploading": uploading,
        "pending_eligible": pending_eligible,
        "pending_waiting": pending_waiting,
        "pending_total": pending_total,
        "pending_quota": pending_quota,
        "next_attempt_at": next_attempt_at,
    }


_retry_pending_lock = threading.Lock()


@app.post("/yt/retry-pending")
async def yt_retry_pending():
    """
    Clear internal retry waits on eligible pending sessions so the worker picks
    them up on its next poll (≤15s). Explicit user action — clears ALL non-fatal
    waits including QUOTA_EXCEEDED, TRANSIENT, and sessions with no error_code.

    Skips: currently locked (uploading), fatal errors (PERMISSION_ERROR /
    AUTH_REVOKED / INVALID_FILE), cancelled, and sessions already eligible.
    Returns count cleared and fresh queue state.
    """
    from datetime import datetime, timezone as _tz

    _FATAL = ("PERMISSION_ERROR", "AUTH_REVOKED", "INVALID_FILE")
    now_iso = datetime.now(tz=_tz.utc).isoformat()

    if not _retry_pending_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Reintento ya en curso")

    try:
        conn = dbmod.get_db()
        try:
            placeholders = ",".join("?" * len(_FATAL))
            result = conn.execute(
                f"""UPDATE yt_upload_sessions
                    SET next_attempt_at = NULL, updated_at = ?
                    WHERE status = 'pending'
                      AND next_attempt_at IS NOT NULL
                      AND next_attempt_at > ?
                      AND (locked_by IS NULL OR locked_by = '')
                      AND (error_code IS NULL OR error_code NOT IN ({placeholders}))""",
                [now_iso, now_iso, *_FATAL],
            )
            cleared = result.rowcount
            conn.commit()

            uploading = conn.execute(
                "SELECT COUNT(*) FROM yt_upload_sessions WHERE status IN ('uploading','processing')"
            ).fetchone()[0]
            pending_total = conn.execute(
                "SELECT COUNT(*) FROM yt_upload_sessions WHERE status='pending'"
            ).fetchone()[0]
            pending_eligible = conn.execute(
                "SELECT COUNT(*) FROM yt_upload_sessions WHERE status='pending' "
                "AND (next_attempt_at IS NULL OR next_attempt_at <= ?)",
                (now_iso,),
            ).fetchone()[0]
            pending_waiting = conn.execute(
                "SELECT COUNT(*) FROM yt_upload_sessions WHERE status='pending' "
                "AND next_attempt_at > ?",
                (now_iso,),
            ).fetchone()[0]
            pending_quota = conn.execute(
                "SELECT COUNT(*) FROM yt_upload_sessions WHERE status='pending' "
                "AND error_code='QUOTA_EXCEEDED' AND next_attempt_at > ?",
                (now_iso,),
            ).fetchone()[0]
            next_row = conn.execute(
                "SELECT MIN(next_attempt_at) FROM yt_upload_sessions "
                "WHERE status='pending' AND next_attempt_at > ?",
                (now_iso,),
            ).fetchone()
            next_attempt_at = next_row[0] if next_row else None
        finally:
            conn.close()
    finally:
        _retry_pending_lock.release()

    if uploading > 0:
        worker_state = "active"
    elif pending_eligible > 0:
        worker_state = "working"
    elif pending_waiting > 0:
        worker_state = "waiting"
    else:
        worker_state = "idle"

    return {
        "cleared": cleared,
        "worker_state": worker_state,
        "uploading": uploading,
        "pending_eligible": pending_eligible,
        "pending_waiting": pending_waiting,
        "pending_total": pending_total,
        "pending_quota": pending_quota,
        "next_attempt_at": next_attempt_at,
    }


# ── STORAGE SUMMARY ───────────────────────────────────────────────────────────

@app.get("/storage/summary")
async def storage_summary():
    """Detailed storage breakdown with file-presence check."""
    import shutil as _shutil

    def _dir_size_mb(path: str) -> float:
        total = 0
        try:
            for entry in _os.scandir(path):
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat().st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += int(_dir_size_mb(entry.path) * 1024 * 1024)
        except Exception:
            pass
        return round(total / (1024 * 1024), 1)

    out = CONFIG.output_dir
    subdirs = ["downloads", "uploads", "audio", "proxies", "clips", "thumbnails"]
    dirs = {}
    for sub in subdirs:
        p = _os.path.join(out, sub)
        size = _dir_size_mb(p)
        try:
            count = len([f for f in _os.scandir(p) if f.is_file()])
        except Exception:
            count = 0
        dirs[sub] = {"size_mb": size, "files": count}

    # Creator-named render directories (e.g. mrbeast/, kai_cenat_live/)
    creator_dirs = {}
    other_mb = 0.0
    try:
        for entry in _os.scandir(out):
            if entry.is_dir() and entry.name not in subdirs:
                size = _dir_size_mb(entry.path)
                if size > 0:
                    creator_dirs[entry.name] = {"size_mb": size}
                other_mb += size
    except Exception:
        pass

    total_mb = _dir_size_mb(out)
    db_mb = 0.0
    try:
        db_mb = round(_os.path.getsize(CONFIG.db_path) / (1024 * 1024), 1)
    except Exception:
        pass

    disk = {}
    try:
        u = _shutil.disk_usage(out)
        disk = {
            "free_gb": round(u.free / (1024 ** 3), 1),
            "total_gb": round(u.total / (1024 ** 3), 1),
            "used_pct": round((u.used / u.total) * 100, 1),
        }
    except Exception:
        pass

    with dbmod.db() as conn:
        clip_rows = conn.execute("SELECT id, captioned_path, output_path FROM clips").fetchall()
        video_rows = conn.execute("SELECT id, path FROM videos").fetchall()

    missing_clips = [
        {"id": r["id"][:8], "path": r["captioned_path"] or r["output_path"]}
        for r in clip_rows
        if (r["captioned_path"] or r["output_path"]) and
           not Path(r["captioned_path"] or r["output_path"]).exists()
    ]
    missing_videos = [
        {"id": r["id"][:8], "path": r["path"]}
        for r in video_rows
        if r["path"] and not Path(r["path"]).exists()
    ]

    return {
        "output_dir": out,
        "db_path": CONFIG.db_path,
        "db_size_mb": db_mb,
        "total_output_mb": total_mb,
        "other_dirs_mb": round(other_mb, 1),
        "creator_dirs": creator_dirs,
        "dirs": dirs,
        "disk": disk,
        "missing_clips": len(missing_clips),
        "missing_videos": len(missing_videos),
        "missing_details": {
            "clips": missing_clips[:10],
            "videos": missing_videos[:10],
        },
        "scanned_at": datetime.datetime.utcnow().isoformat(),
    }


@app.post("/storage/scan")
async def storage_scan():
    """Rescan file presence and return updated counts."""
    with dbmod.db() as conn:
        clip_rows = conn.execute("SELECT id, captioned_path, output_path FROM clips").fetchall()
        video_rows = conn.execute("SELECT id, path FROM videos").fetchall()
    missing_clips = sum(
        1 for r in clip_rows
        if (r["captioned_path"] or r["output_path"]) and
           not Path(r["captioned_path"] or r["output_path"]).exists()
    )
    missing_videos = sum(
        1 for r in video_rows if r["path"] and not Path(r["path"]).exists()
    )
    return {
        "missing_clips": missing_clips,
        "missing_videos": missing_videos,
        "scanned_at": datetime.datetime.utcnow().isoformat(),
    }


# ── MISSED MOMENTS ────────────────────────────────────────────────────────────

@app.post("/jobs/{job_id}/missed-moments")
async def add_missed_moment(job_id: str, body: dict = Body(...)):
    """Record a good moment the pipeline missed. start_s and end_s are in seconds."""
    start_s = float(body.get("start_s", 0))
    end_s = float(body.get("end_s", 0))
    notes = str(body.get("notes", ""))[:500]

    if end_s <= start_s:
        raise HTTPException(400, "end_s must be greater than start_s")
    if end_s - start_s < 3:
        raise HTTPException(400, "Minimum moment duration is 3 seconds")

    with dbmod.db() as conn:
        job_row = conn.execute("SELECT id FROM jobs WHERE id=?", [job_id]).fetchone()
        video_row = conn.execute(
            "SELECT id FROM videos WHERE job_id=? LIMIT 1", [job_id]
        ).fetchone()
    if not job_row:
        raise HTTPException(404, "Job not found")

    video_id = video_row["id"] if video_row else ""
    moment_id = dbmod.add_missed_moment(job_id, video_id, start_s, end_s, notes)
    return {"id": moment_id, "job_id": job_id, "start_s": start_s, "end_s": end_s, "notes": notes}


@app.get("/jobs/{job_id}/missed-moments")
async def get_missed_moments(job_id: str):
    """List all missed moments recorded for a job."""
    return dbmod.list_missed_moments(job_id)


@app.delete("/missed-moments/{moment_id}")
async def delete_missed_moment(moment_id: str):
    dbmod.delete_missed_moment(moment_id)
    return {"deleted": True}


# ── DASHBOARD ────────────────────────────────────────────────────────────────

_dashboard_path = Path(__file__).parent.parent / "dashboard"


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    html_file = _dashboard_path / "index.html"
    if not html_file.exists():
        return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)
    return HTMLResponse(html_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import uvicorn
    dbmod.init_db()
    uvicorn.run(app, host="127.0.0.1", port=8000)
