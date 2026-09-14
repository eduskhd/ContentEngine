"""ContentEngine REST API."""
import uuid, shutil, asyncio, datetime, json, zipfile, tempfile, subprocess
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, BackgroundTasks, HTTPException, UploadFile, File, Form, Query, Body
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

    all_ok = all(v in ("ok",) or v.endswith("alive") or v.replace(".", "").isdigit()
                 for k, v in checks.items() if k != "disk_warning")
    status = "ok" if checks["database"] == "ok" else "degraded"

    return {
        "status": status,
        "mode": CONFIG.mode,
        "version": "1.0.0",
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

    # Persist creator_id on job record immediately
    if resolved_creator_id:
        conn = dbmod.get_db()
        conn.execute("UPDATE jobs SET creator_id=? WHERE id=?", [resolved_creator_id, job_id])
        conn.commit(); conn.close()

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
               COALESCE(j.creator_id, v.creator_id) as creator_id, v.id as video_id
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
):
    """Submit a job by providing a video URL (YouTube, TikTok, Instagram, etc.)."""
    if not is_url(url):
        raise HTTPException(400, "Invalid URL — must start with http:// or https://")
    try:
        validate_url(url)
    except ValueError as exc:
        raise HTTPException(400, f"URL not allowed: {exc}")

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

    if pool is not None:
        pool.submit(job_id, url, clips, platforms.split(","), mode, resolved_creator)
    else:
        raise HTTPException(503, "Worker pool not available")

    # Persist creator_id and video_name on DB job record
    if resolved_creator_id or video_name:
        with dbmod.db() as conn:
            if resolved_creator_id:
                conn.execute("UPDATE jobs SET creator_id=? WHERE id=?",
                             [resolved_creator_id, job_id])
            # video_name stored as source_title placeholder until pipeline sets it
            if video_name:
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
        while True:
            job = _jobs.get(job_id)
            if job is None:
                # Job not in memory — look it up in DB (completed in a prior session)
                conn = dbmod.get_db()
                row = conn.execute("SELECT status, error FROM jobs WHERE id=?", [job_id]).fetchone()
                conn.close()
                if row:
                    db_status = (row[0] or "").lower()
                    payload = {"job_id": job_id, "status": db_status, "result": None, "error": row[1]}
                    yield f"data: {json.dumps(payload)}\n\n"
                else:
                    yield f"data: {json.dumps({'error': 'job not found'})}\n\n"
                break
            status = job["status"]
            if status != last_status:
                last_status = status
                payload = {
                    "job_id": job_id,
                    "status": status,
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

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    rows = conn.execute(f"""
        SELECT cl.*,
               ca.hook_score, ca.virality_score, ca.visual_score, ca.audio_score,
               ca.start_s, ca.end_s, ca.platform_scores,
               v.creator_slug, v.video_slug, v.source_title, v.source_platform,
               v.creator_id, v.id as video_id
        FROM clips cl
        LEFT JOIN candidates ca ON cl.candidate_id = ca.id
        LEFT JOIN videos v ON ca.video_id = v.id
        {where}
        ORDER BY cl.created_at DESC LIMIT ?
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
):
    """Clips for manual review, paginated."""
    conn = dbmod.get_db()
    rows = conn.execute("""
        SELECT cl.id, cl.captioned_path, cl.output_path, cl.prepublish_score,
               cl.prepublish_decision, cl.created_at, cl.job_id,
               ca.hook_score, ca.virality_score, ca.start_s, ca.end_s
        FROM clips cl
        JOIN candidates ca ON cl.candidate_id = ca.id
        ORDER BY cl.created_at DESC, ca.virality_score DESC
        LIMIT ? OFFSET ?
    """, [limit, offset]).fetchall()
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
async def oauth_callback(platform: str, code: str, state: str):
    from publishers import get_publisher
    publisher = get_publisher(platform)
    tokens = publisher.exchange_code(code, f"http://localhost:8000/oauth/{platform}/callback")
    return {
        "platform": platform,
        "tokens": tokens,
        "instructions": "Copy these tokens to your .env file and restart the server.",
    }


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
async def list_creators():
    return dbmod.get_creators()


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
    uvicorn.run(app, host="0.0.0.0", port=8000)
