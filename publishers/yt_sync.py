"""
YouTube channel sync — reconcile local publications with what's actually on the channel.

Flow:
  1. fetch_channel_uploads()  → list all videos in the uploads playlist (paginated)
  2. fetch_video_details()    → batch status/snippet for up to 50 ids at once
  3. reconcile()              → cross-reference with local yt_upload_sessions / publications

This module is idempotent: running it twice never creates duplicates.
It never re-uploads, never deletes, never publishes.
"""
import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Iterator

logger = logging.getLogger(__name__)

CHANNEL_ID = "UCJu5hBYkfg-yWjvDeI67rkA"
UPLOADS_PLAYLIST = "UUJu5hBYkfg-yWjvDeI67rkA"

_YT_PLAYLIST_URL = "https://www.googleapis.com/youtube/v3/playlistItems"
_YT_VIDEOS_URL   = "https://www.googleapis.com/youtube/v3/videos"
_MAX_RESULTS = 50


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _yt_get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = "(unreadable)"
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(f"YouTube API {exc.code}: {body}") from exc


# ── Channel upload list ───────────────────────────────────────────────────────

def fetch_channel_uploads(token: str, playlist_id: str = UPLOADS_PLAYLIST) -> list[dict]:
    """
    Return all videos from the uploads playlist.
    Each item: {video_id, title, published_at}.
    Handles pagination automatically.
    """
    videos = []
    page_token = None
    while True:
        url = (
            f"{_YT_PLAYLIST_URL}?part=snippet,contentDetails"
            f"&playlistId={playlist_id}&maxResults={_MAX_RESULTS}"
        )
        if page_token:
            url += f"&pageToken={page_token}"
        data = _yt_get(url, token)
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            content = item.get("contentDetails", {})
            vid_id = content.get("videoId") or snippet.get("resourceId", {}).get("videoId")
            if vid_id:
                videos.append({
                    "video_id": vid_id,
                    "title": snippet.get("title", ""),
                    "published_at": snippet.get("publishedAt", ""),
                })
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return videos


# ── Video details (batch) ─────────────────────────────────────────────────────

def fetch_video_details(video_ids: list[str], token: str) -> dict[str, dict]:
    """
    Return status + snippet for up to N video IDs.
    Result: {video_id: {upload_status, privacy_status, title, published_at, thumbnail_url}}
    Missing IDs (deleted/private) are simply absent.
    """
    result = {}
    for i in range(0, len(video_ids), _MAX_RESULTS):
        batch = video_ids[i : i + _MAX_RESULTS]
        ids_param = ",".join(batch)
        url = f"{_YT_VIDEOS_URL}?id={ids_param}&part=status,snippet"
        data = _yt_get(url, token)
        for item in data.get("items", []):
            vid = item["id"]
            status = item.get("status", {})
            snippet = item.get("snippet", {})
            thumbnails = snippet.get("thumbnails", {})
            thumb = (
                thumbnails.get("high", {}).get("url")
                or thumbnails.get("medium", {}).get("url")
                or thumbnails.get("default", {}).get("url")
                or ""
            )
            result[vid] = {
                "upload_status":  status.get("uploadStatus", "unknown"),
                "privacy_status": status.get("privacyStatus", "unknown"),
                "title":          snippet.get("title", ""),
                "published_at":   snippet.get("publishedAt", ""),
                "thumbnail_url":  thumb,
            }
    return result


# ── Full sync ─────────────────────────────────────────────────────────────────

def run_channel_sync(token: str) -> dict:
    """
    Main sync entry point.

    1. List all channel uploads.
    2. Get status details in batches.
    3. Update local yt_upload_sessions + publications.
    4. Detect videos removed from the channel.

    Returns a summary dict.
    """
    from engine import database as _db

    started_at = _now()
    summary = {
        "started_at": started_at,
        "channel_id": CHANNEL_ID,
        "videos_found": 0,
        "videos_matched": 0,
        "videos_updated": 0,
        "videos_unlinked": 0,
        "videos_deleted_on_yt": 0,
        "errors": [],
        "completed_at": None,
    }

    try:
        # 1. List uploads
        channel_videos = fetch_channel_uploads(token)
        summary["videos_found"] = len(channel_videos)
        channel_ids = [v["video_id"] for v in channel_videos]
        channel_id_set = set(channel_ids)

        # 2. Status details
        details = fetch_video_details(channel_ids, token)

        # 3. Load local sessions with video_ids
        with _db.db() as conn:
            sessions = conn.execute(
                "SELECT id, pub_id, clip_id, remote_video_id, status, "
                "remote_privacy_status, remote_process_status, channel_id "
                "FROM yt_upload_sessions WHERE remote_video_id IS NOT NULL"
            ).fetchall()

            session_by_vid = {s["remote_video_id"]: s for s in sessions}

            for vid in channel_ids:
                detail = details.get(vid, {})
                upload_status  = detail.get("upload_status", "unknown")
                privacy_status = detail.get("privacy_status", "unknown")

                if vid in session_by_vid:
                    s = session_by_vid[vid]
                    summary["videos_matched"] += 1

                    # Determine correct session status
                    if upload_status in ("processed", "succeeded"):
                        new_sess_status = privacy_status  # public / unlisted / private
                    elif upload_status == "failed":
                        new_sess_status = "error"
                    else:
                        new_sess_status = "processing"

                    changed = (
                        s["status"] != new_sess_status
                        or s["remote_privacy_status"] != privacy_status
                        or s["remote_process_status"] != upload_status
                    )
                    if changed:
                        conn.execute(
                            "UPDATE yt_upload_sessions "
                            "SET status=?, remote_process_status=?, remote_privacy_status=?, "
                            "updated_at=? WHERE id=?",
                            (new_sess_status, upload_status, privacy_status, _now(), s["id"]),
                        )
                        # Sync pub status
                        pub_status = "published" if new_sess_status in ("public", "unlisted", "private") else new_sess_status
                        ext_url = f"https://studio.youtube.com/video/{vid}/edit"
                        conn.execute(
                            "UPDATE publications SET status=?, external_post_id=?, "
                            "external_url=?, updated_at=? "
                            "WHERE id=? AND status NOT IN ('archived')",
                            (pub_status, vid, ext_url, _now(), s["pub_id"]),
                        )
                        summary["videos_updated"] += 1
                else:
                    # Channel video not matched to any local session
                    summary["videos_unlinked"] += 1

            # 4. Sessions with video_id NOT on channel anymore
            for vid, s in session_by_vid.items():
                if vid not in channel_id_set and s["status"] not in ("error",):
                    conn.execute(
                        "UPDATE yt_upload_sessions "
                        "SET status='error', error_code='VIDEO_DELETED', "
                        "error_message=?, updated_at=? WHERE id=?",
                        (
                            f"Video {vid} no longer found on YouTube channel. "
                            "May have been deleted. Not re-uploading.",
                            _now(),
                            s["id"],
                        ),
                    )
                    conn.execute(
                        "UPDATE publications SET status='needs_check', "
                        "error_message=?, updated_at=? "
                        "WHERE id=? AND status NOT IN ('archived','needs_check')",
                        (
                            f"YouTube video {vid} not found on channel (may be deleted). Manual review.",
                            _now(),
                            s["pub_id"],
                        ),
                    )
                    summary["videos_deleted_on_yt"] += 1

            # 5. Save sync timestamp
            conn.execute(
                "INSERT OR REPLACE INTO yt_sync_state(channel_id, last_sync_at, "
                "last_sync_found, last_sync_matched, last_sync_updated, last_error) "
                "VALUES(?,?,?,?,?,NULL)",
                (
                    CHANNEL_ID,
                    _now(),
                    summary["videos_found"],
                    summary["videos_matched"],
                    summary["videos_updated"],
                ),
            )

    except Exception as exc:
        logger.exception("[yt_sync] sync failed")
        summary["errors"].append(str(exc))
        try:
            with _db.db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO yt_sync_state(channel_id, last_sync_at, "
                    "last_sync_found, last_sync_matched, last_sync_updated, last_error) "
                    "VALUES(?,?,0,0,0,?)",
                    (CHANNEL_ID, _now(), str(exc)),
                )
        except Exception:
            pass

    summary["completed_at"] = _now()
    logger.info(
        "[yt_sync] done — found=%d matched=%d updated=%d unlinked=%d deleted=%d",
        summary["videos_found"],
        summary["videos_matched"],
        summary["videos_updated"],
        summary["videos_unlinked"],
        summary["videos_deleted_on_yt"],
    )
    return summary


# ── Incremental: verify pending sessions ──────────────────────────────────────

def verify_pending_sessions(token: str) -> dict:
    """
    Check yt_upload_sessions that are in 'processing' status (have video_id, not yet public).
    Used at startup and periodically to catch any sessions that completed between restarts.
    """
    from engine import database as _db

    checked = 0
    updated = 0
    with _db.db() as conn:
        rows = conn.execute(
            "SELECT id, pub_id, remote_video_id "
            "FROM yt_upload_sessions "
            "WHERE status='processing' AND remote_video_id IS NOT NULL"
        ).fetchall()

        if not rows:
            return {"checked": 0, "updated": 0}

        vids = [r["remote_video_id"] for r in rows]
        details = fetch_video_details(vids, token)

        for row in rows:
            vid = row["remote_video_id"]
            detail = details.get(vid)
            checked += 1
            if not detail:
                continue
            upload_status  = detail["upload_status"]
            privacy_status = detail["privacy_status"]
            if upload_status in ("processed", "succeeded"):
                new_status = privacy_status
                pub_status = "published"
                conn.execute(
                    "UPDATE yt_upload_sessions SET status=?, remote_process_status=?, "
                    "remote_privacy_status=?, locked_at=NULL, locked_by=NULL, updated_at=? WHERE id=?",
                    (new_status, upload_status, privacy_status, _now(), row["id"]),
                )
                conn.execute(
                    "UPDATE publications SET status=?, external_post_id=?, "
                    "external_url=?, updated_at=? WHERE id=? AND status NOT IN ('archived')",
                    (
                        pub_status, vid,
                        f"https://studio.youtube.com/video/{vid}/edit",
                        _now(), row["pub_id"],
                    ),
                )
                updated += 1

    return {"checked": checked, "updated": updated}
