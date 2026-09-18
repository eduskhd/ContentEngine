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
from datetime import datetime, timezone
from pathlib import Path

from engine import database as db
from publishers import yt_auth, yt_upload as uploader

logger = logging.getLogger(__name__)

_WORKER_ID = f"yt-{uuid.uuid4().hex[:8]}"

# Error codes that should not be retried
_FATAL_ERRORS = {"QUOTA_EXCEEDED", "PERMISSION_ERROR", "AUTH_REVOKED", "INVALID_FILE"}


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

    def run(self):
        logger.info("[YTUploadWorker] started (worker_id=%s)", _WORKER_ID)
        # On startup, unlock stale sessions so they get re-attempted
        self._unlock_stale_sessions()

        while not self._stop_event.is_set():
            try:
                session = self._claim_next()
                if session:
                    self._process_session(session)
                else:
                    self._stop_event.wait(self.POLL_INTERVAL)
            except Exception:
                logger.exception("[YTUploadWorker] unexpected error in main loop")
                self._stop_event.wait(self.POLL_INTERVAL)

    # ── Claim ─────────────────────────────────────────────────────────────────

    def _claim_next(self) -> dict | None:
        """Atomically claim a pending session. Returns None if nothing to do."""
        return db.claim_yt_upload_session(_WORKER_ID)

    # ── Stale unlock ──────────────────────────────────────────────────────────

    def _unlock_stale_sessions(self):
        """On startup, release sessions locked >10 min ago so they can be retried."""
        stale = db.list_stale_yt_sessions()
        for s in stale:
            logger.info("[YTUploadWorker] unlocking stale session %s", s["id"])
            db.update_yt_upload_session(
                s["id"],
                status="pending",
                locked_at=None,
                locked_by=None,
            )

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
                session_url = uploader.create_resumable_session(
                    access_token=access_token,
                    title=session.get("title") or "Short",
                    description=session.get("description") or "",
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

            # 4. Upload in chunks
            video_id = None
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

            # 5. Poll for processing
            db.update_yt_upload_session(
                sid,
                status="processing",
                remote_video_id=video_id,
                bytes_sent=file_size,
                updated_at=_now(),
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
            fatal = error_code in _FATAL_ERRORS
            self._fail(sid, pub_id, str(exc), error_code, fatal=fatal)

    # ── Failure handling ──────────────────────────────────────────────────────

    def _fail(self, sid: str, pub_id: str, message: str, error_code: str, fatal: bool = False):
        logger.error("[YTUploadWorker] session %s failed: %s (%s)", sid, message, error_code)

        session = db.get_yt_upload_session(sid)
        attempts = (session or {}).get("attempts") or 0

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
