"""
Background YouTube upload worker.

Claims pending yt_upload_sessions atomically and uploads in chunks.
Survives server restarts by recovering in-progress (stale locked) sessions.
Never uploads if the file hash at approval no longer matches the file on disk.
"""
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine import database as db
from publishers import yt_auth, yt_upload as uploader

logger = logging.getLogger(__name__)

_WORKER_ID = f"yt-{uuid.uuid4().hex[:8]}"

# Error codes that should not be retried (QUOTA_EXCEEDED is daily-renewable — not fatal)
_FATAL_ERRORS = {"PERMISSION_ERROR", "AUTH_REVOKED", "INVALID_FILE"}


class YTUploadWorker(threading.Thread):
    POLL_INTERVAL = 15
    MAX_ATTEMPTS = 3
    PROCESS_POLL_MAX = 10
    PROCESS_POLL_DELAY = 30

    def __init__(self):
        super().__init__(name="yt-upload-worker", daemon=True)
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    SYNC_INTERVAL_MINUTES = 30  # configurable via env YOUTUBE_SYNC_INTERVAL_MINUTES

    def run(self):
        logger.info("[YTUploadWorker] started (worker_id=%s)", _WORKER_ID)
        self._unlock_stale_sessions()
        self._reset_quota_sessions()
        self._startup_recovery()

        # Skip immediate sync — startup already ran _startup_recovery; next sync after interval.
        last_sync_ts = time.time()
        sync_interval = int(os.environ.get("YOUTUBE_SYNC_INTERVAL_MINUTES", self.SYNC_INTERVAL_MINUTES)) * 60

        while not self._stop_event.is_set():
            try:
                # Periodic channel sync
                if time.time() - last_sync_ts >= sync_interval:
                    self._run_periodic_sync()
                    last_sync_ts = time.time()

                session = self._claim_next()
                if session:
                    self._process_session(session)
                else:
                    self._stop_event.wait(self.POLL_INTERVAL)
            except Exception:
                logger.exception("[YTUploadWorker] unexpected error in main loop")
                self._stop_event.wait(self.POLL_INTERVAL)

    def _startup_recovery(self):
        """On startup, verify any sessions stuck in 'processing' state."""
        try:
            from publishers import yt_auth
            from publishers.yt_sync import verify_pending_sessions
            token = yt_auth.get_valid_token()
            if token:
                result = verify_pending_sessions(token)
                if result["checked"] > 0:
                    logger.info(
                        "[YTUploadWorker] startup recovery: checked=%d updated=%d",
                        result["checked"], result["updated"],
                    )
        except Exception:
            logger.warning("[YTUploadWorker] startup recovery skipped (not connected or error)")

    def _run_periodic_sync(self):
        """Periodic channel sync — reconcile local state with YouTube."""
        try:
            from publishers import yt_auth
            from publishers.yt_sync import run_channel_sync
            token = yt_auth.get_valid_token()
            if not token:
                return
            result = run_channel_sync(token)
            logger.info(
                "[YTUploadWorker] periodic sync: found=%d matched=%d updated=%d",
                result["videos_found"], result["videos_matched"], result["videos_updated"],
            )
        except Exception:
            logger.warning("[YTUploadWorker] periodic sync failed (will retry next cycle)")

    # ── Claim ─────────────────────────────────────────────────────────────────

    def _claim_next(self) -> dict | None:
        """Atomically claim a pending session. Returns None if nothing to do."""
        return db.claim_yt_upload_session(_WORKER_ID)

    # ── Stale unlock ──────────────────────────────────────────────────────────

    def _unlock_stale_sessions(self):
        """On startup, release sessions locked >10 min ago so they can be retried."""
        stale = db.list_stale_yt_sessions()
        for s in stale:
            logger.info("[YTUploadWorker] unlocking stale session %s (status=%s)", s["id"], s.get("status"))
            db.update_yt_upload_session(
                s["id"],
                status="pending",
                locked_at=None,
                locked_by=None,
            )

    def _reset_quota_sessions(self):
        """Legacy fallback: reset QUOTA_EXCEEDED sessions that have no next_attempt_at set.

        New failures set next_attempt_at via _fail() and stay as 'pending' — they are
        picked up automatically when their time arrives. This method handles any sessions
        created before the next_attempt_at column existed (revision f1bec0686e1f).
        """
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(hours=23)).isoformat()
        try:
            with db.db() as conn:
                rows = conn.execute(
                    "SELECT id FROM yt_upload_sessions "
                    "WHERE error_code='QUOTA_EXCEEDED' AND status='error' "
                    "AND next_attempt_at IS NULL AND last_attempt_at<?",
                    (cutoff,),
                ).fetchall()
                for row in rows:
                    conn.execute(
                        "UPDATE yt_upload_sessions SET status='pending', error_message=NULL, "
                        "error_code=NULL, locked_at=NULL, locked_by=NULL, attempts=0 WHERE id=?",
                        (row[0],),
                    )
            if rows:
                logger.info("[YTUploadWorker] legacy-reset %d QUOTA_EXCEEDED session(s) after 23h", len(rows))
        except Exception:
            logger.exception("[YTUploadWorker] error in _reset_quota_sessions")

    # ── Process ───────────────────────────────────────────────────────────────

    def _process_session(self, session: dict):
        sid = session["id"]
        pub_id = session["pub_id"]
        logger.info("[YTUploadWorker] processing session %s (pub=%s)", sid, pub_id)

        db.update_yt_upload_session(
            sid,
            last_attempt_at=_now(),
            attempts=session["attempts"] + 1,
            updated_at=_now(),
        )

        try:
            # 1. Validate file still matches
            file_path = session["file_path"]
            if not file_path or not Path(file_path).exists():
                self._fail(sid, pub_id, "File not found on disk", "INVALID_FILE", fatal=True)
                return

            current_hash = uploader.compute_file_hash(file_path)
            if current_hash != session["file_hash"]:
                self._fail(
                    sid, pub_id,
                    "File changed since approval — re-approve before uploading",
                    "INVALID_FILE", fatal=True,
                )
                return

            # 2. Get valid token
            try:
                access_token = yt_auth.get_valid_token()
            except Exception as e:
                self._fail(sid, pub_id, f"Auth error: {e}", "AUTH_REVOKED", fatal=True)
                return

            if not access_token:
                self._fail(sid, pub_id, "YouTube not connected", "AUTH_REVOKED", fatal=True)
                return

            file_size = os.path.getsize(file_path)

            # 3. Get or create upload session URL
            session_url = session.get("session_url")
            bytes_offset = session.get("bytes_sent") or 0

            if session_url and bytes_offset > 0:
                # Try to resume
                try:
                    resume_offset = uploader.resume_session(session_url, file_path)
                    if resume_offset == -1:
                        # Session expired — create new
                        session_url = None
                        bytes_offset = 0
                    else:
                        bytes_offset = resume_offset
                except Exception:
                    session_url = None
                    bytes_offset = 0

            if not session_url:
                tags = []
                try:
                    tags = json.loads(session.get("tags") or "[]")
                except Exception:
                    pass
                approved_privacy = session.get("privacy_status") or "private"
                _title = (session.get("title") or "").strip()
                _desc  = (session.get("description") or "").strip()
                if not _title:
                    self._fail(sid, pub_id,
                               "METADATA_MISSING: title is empty — edit in Publishing before uploading",
                               "INVALID_METADATA")
                    return
                if not _desc:
                    self._fail(sid, pub_id,
                               "METADATA_MISSING: description is empty — edit in Publishing before uploading",
                               "INVALID_METADATA")
                    return
                session_url = uploader.create_resumable_session(
                    access_token=access_token,
                    title=_title[:100],
                    description=_desc[:5000],
                    tags=tags,
                    file_size=file_size,
                    is_for_kids=bool(session.get("is_for_kids")),
                    privacy_status=approved_privacy,
                )
                db.update_yt_upload_session(
                    sid,
                    session_url=session_url,
                    status="uploading",
                    updated_at=_now(),
                )

            db.update_yt_upload_session(sid, status="uploading", updated_at=_now())
            _update_pub_status(pub_id, "publishing")

            # 4. Upload in chunks (skip if already uploaded in a prior run)
            video_id = session.get("remote_video_id") or None
            if video_id:
                # Resuming after a server restart during polling — go straight to step 5
                logger.info("[YTUploadWorker] skipping upload for %s, already have video_id=%s", sid, video_id)
            else:
                while bytes_offset < file_size:
                    if self._stop_event.is_set():
                        # Unlock cleanly for next startup
                        db.update_yt_upload_session(
                            sid,
                            locked_at=None,
                            locked_by=None,
                            bytes_sent=bytes_offset,
                            updated_at=_now(),
                        )
                        return

                    result = uploader.upload_chunk(session_url, file_path, bytes_offset)
                    bytes_offset = result["bytes_sent"]
                    db.update_yt_upload_session(
                        sid, bytes_sent=bytes_offset, updated_at=_now()
                    )

                    if result["done"]:
                        video_id = result["video_id"]
                        break

                if not video_id:
                    self._fail(sid, pub_id, "Upload completed but no video_id returned", "UNKNOWN")
                    return

            # 5. Poll for processing — persist video_id to publication immediately
            # so a crash during polling doesn't lose the upload link.
            db.update_yt_upload_session(
                sid,
                status="processing",
                remote_video_id=video_id,
                bytes_sent=file_size,
                updated_at=_now(),
            )
            _update_pub_status(
                pub_id, "publishing",
                external_post_id=video_id,
                external_url=f"https://studio.youtube.com/video/{video_id}/edit",
            )

            final_status = "private"
            for _ in range(self.PROCESS_POLL_MAX):
                if self._stop_event.is_set():
                    break
                try:
                    access_token = yt_auth.get_valid_token() or access_token
                    yt_status = uploader.poll_video_status(video_id, access_token)
                    process_status = yt_status.get("process_status", "unknown")
                    privacy_status = yt_status.get("privacy_status", "unknown")

                    db.update_yt_upload_session(
                        sid,
                        remote_process_status=process_status,
                        remote_privacy_status=privacy_status,
                        updated_at=_now(),
                    )

                    if process_status in ("processed", "succeeded"):
                        # Map remote privacy to final status
                        if privacy_status == "public":
                            final_status = "public"
                        elif privacy_status == "unlisted":
                            final_status = "unlisted"
                        else:
                            final_status = "private"
                        break
                    if process_status == "failed":
                        final_status = "error"
                        break
                    if process_status == "uploaded":
                        # Not yet processed — keep polling
                        pass
                except Exception:
                    logger.warning("[YTUploadWorker] status poll failed for %s", video_id)
                time.sleep(self.PROCESS_POLL_DELAY)
            else:
                # Polling exhausted — mark needs_check
                final_status = "needs_check"

            # 6. Check for visibility mismatch (YouTube API project restriction)
            approved_privacy = session.get("privacy_status") or "private"
            final_remote_privacy = db.get_yt_upload_session(sid)
            actual_privacy = (final_remote_privacy or {}).get("remote_privacy_status", "unknown")

            if final_status not in ("error", "needs_check") and approved_privacy != "private":
                if actual_privacy not in ("unknown", approved_privacy):
                    # YouTube returned different visibility than requested
                    final_status = "needs_check"
                    db.update_yt_upload_session(
                        sid,
                        error_code="VISIBILITY_MISMATCH",
                        error_message=(
                            f"YouTube devolvió visibilidad '{actual_privacy}' pero se solicitó "
                            f"'{approved_privacy}'. Posible restricción de proyecto API sin auditar "
                            f"(proyectos creados después del 28/07/2020 quedan restringidos a privado)."
                        ),
                        updated_at=_now(),
                    )
                    logger.warning(
                        "[YTUploadWorker] visibility mismatch for %s: approved=%s remote=%s",
                        video_id, approved_privacy, actual_privacy,
                    )

            # 7. Finalize
            db.update_yt_upload_session(
                sid,
                status=final_status,
                locked_at=None,
                locked_by=None,
                updated_at=_now(),
            )
            external_url = f"https://studio.youtube.com/video/{video_id}/edit"
            pub_status = "published" if final_status in ("public", "unlisted", "private") else final_status
            _update_pub_status(pub_id, pub_status,
                               external_post_id=video_id,
                               external_url=external_url)
            logger.info("[YTUploadWorker] session %s done: video_id=%s status=%s",
                        sid, video_id, final_status)

        except Exception as exc:
            error_code = uploader.classify_error(exc)
            retry_after_secs = _extract_retry_after(exc)
            fatal = error_code in _FATAL_ERRORS
            self._fail(sid, pub_id, str(exc), error_code, fatal=fatal, retry_after_seconds=retry_after_secs)

    # ── Failure handling ──────────────────────────────────────────────────────

    # Retry intervals (minutes) — configurable per error class
    QUOTA_RETRY_MINUTES = 30       # uploadLimitExceeded: per-channel daily limit
    TRANSIENT_RETRY_MINUTES = 5    # network/server errors

    def _fail(self, sid: str, pub_id: str, message: str, error_code: str,
              fatal: bool = False, retry_after_seconds: int | None = None):
        logger.error("[YTUploadWorker] session %s failed: %s (%s)", sid, message, error_code)

        session = db.get_yt_upload_session(sid)
        attempts = (session or {}).get("attempts") or 0

        # Quota errors are time-limited, not attempt-limited — schedule retry, stay pending
        if error_code == "QUOTA_EXCEEDED":
            if retry_after_seconds and retry_after_seconds > 0:
                delay_minutes = retry_after_seconds / 60
            else:
                delay_minutes = self.QUOTA_RETRY_MINUTES
            next_attempt = (
                datetime.now(tz=timezone.utc) + timedelta(minutes=delay_minutes)
            ).isoformat()
            logger.info(
                "[YTUploadWorker] session %s QUOTA_EXCEEDED — scheduled retry at %s (delay=%.1fmin)",
                sid, next_attempt, delay_minutes,
            )
            db.update_yt_upload_session(
                sid,
                status="pending",
                error_message=message,
                error_code=error_code,
                next_attempt_at=next_attempt,
                locked_at=None,
                locked_by=None,
                attempts=0,   # reset so MAX_ATTEMPTS doesn't kill quota-retried sessions
                updated_at=_now(),
            )
            return

        if error_code == "TRANSIENT" and not fatal:
            if retry_after_seconds and retry_after_seconds > 0:
                delay_minutes = retry_after_seconds / 60
            else:
                delay_minutes = self.TRANSIENT_RETRY_MINUTES
            next_attempt = (
                datetime.now(tz=timezone.utc) + timedelta(minutes=delay_minutes)
            ).isoformat()
            logger.info(
                "[YTUploadWorker] session %s TRANSIENT — retry in %.1fmin at %s",
                sid, delay_minutes, next_attempt,
            )
            db.update_yt_upload_session(
                sid,
                status="pending",
                error_message=message,
                error_code=error_code,
                next_attempt_at=next_attempt,
                locked_at=None,
                locked_by=None,
                updated_at=_now(),
            )
            return

        # All other errors: respect MAX_ATTEMPTS, then mark error
        if fatal or attempts >= self.MAX_ATTEMPTS:
            status = "error"
        else:
            status = "pending"

        db.update_yt_upload_session(
            sid,
            status=status,
            error_message=message,
            error_code=error_code,
            locked_at=None,
            locked_by=None,
            updated_at=_now(),
        )
        if status == "error":
            _update_pub_status(pub_id, "failed")
            # Cascade-pause later parts of the same series
            series_id = (session or {}).get("series_id")
            series_part = (session or {}).get("series_part") or 0
            if series_id and series_part > 0:
                paused = db.pause_series_subsequent(series_id, series_part)
                if paused:
                    logger.warning(
                        "[YTUploadWorker] paused %d subsequent series parts for series=%s after part %d failed",
                        paused, series_id, series_part,
                    )


def _extract_retry_after(exc: Exception) -> int | None:
    """Extract Retry-After seconds from an HTTPError or a RuntimeError wrapping one."""
    import urllib.error as _ue
    header = None
    http_exc = exc if isinstance(exc, _ue.HTTPError) else (
        exc.__cause__ if isinstance(getattr(exc, "__cause__", None), _ue.HTTPError) else None
    )
    if http_exc is not None and http_exc.headers:
        header = http_exc.headers.get("Retry-After")
    if header is None:
        msg = str(exc)
        if msg.startswith("Retry-After:"):
            try:
                header = msg.split("\n")[0].split(":", 1)[1].strip()
            except Exception:
                pass
    if header is None:
        return None
    try:
        return int(header)
    except (ValueError, TypeError):
        return None


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _update_pub_status(pub_id: str, status: str, **kwargs):
    try:
        from engine import database as _db
        with _db.db() as conn:
            sets = ["status=?", "updated_at=?"]
            vals = [status, _now()]
            for k, v in kwargs.items():
                sets.append(f"{k}=?")
                vals.append(v)
            vals.append(pub_id)
            conn.execute(
                f"UPDATE publications SET {', '.join(sets)} WHERE id=?", vals
            )
    except Exception:
        logger.exception("[YTUploadWorker] failed to update publication %s status", pub_id)
