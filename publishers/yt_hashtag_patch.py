"""
Persistent job: audit and patch hashtag blocks on published YouTube Shorts.

State is persisted at ~/.contentengine/hashtag_patch_state.json so any run
can resume after a quota reset, server restart, or network interruption.

Idempotent: already-correct videos are never written to; re-running is safe.

Quota estimate (YouTube Data API v3):
  - playlistItems.list (channel inventory, paginated): ~5 units
  - videos.list?part=snippet (read descriptions, 50/call): ~5 units
  - videos.update?part=snippet (per video updated):  50 units each

Call run_patch() from POST /admin/update-channel-hashtags.
"""
import json
import logging
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_FILE = Path.home() / ".contentengine" / "hashtag_patch_state.json"
CHANNEL_ID = "UCJu5hBYkfg-yWjvDeI67rkA"
UPLOADS_PLAYLIST = "UUJu5hBYkfg-yWjvDeI67rkA"
_SNIPPET_BATCH_SIZE = 50
_BRAND_TAG = "#ContentEngine"


# ── Exceptions ────────────────────────────────────────────────────────────────

class QuotaExceeded(Exception):
    """Raised when YouTube returns quotaExceeded. Caller should schedule retry."""


# ── State persistence ─────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _empty_state() -> dict:
    return {
        "schema_version": 1,
        "started_at": None,
        "last_run_at": None,
        "channel_id": CHANNEL_ID,
        "channel_inventory": [],        # [{video_id, title, published_at}]
        "pending": [],                  # video_ids not yet processed
        "already_correct": [],          # video_ids with correct hashtags
        "updated": [],                  # [{video_id, pub_id, before, after, verified}]
        "dry_run_plan": [],             # [{video_id, pub_id, before, after}]  — dry_run only
        "forbidden": [],                # [{video_id, error}]
        "unlinked": [],                 # video_ids on channel but not in local DB
        "errors": [],                   # [{video_id, error}]
        "quota_exhausted_at": None,
        "completed": False,
    }


def load_state() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _empty_state()


def save_state(state: dict) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def reset_state() -> None:
    """Clear saved state to start fresh."""
    s = _empty_state()
    save_state(s)


# ── Description helpers ───────────────────────────────────────────────────────

def _extract_hashtag_block(description: str) -> str:
    """
    Return the last paragraph if it consists entirely of hashtag tokens.
    A 'paragraph' is a run of text separated from adjacent paragraphs by blank lines.
    Returns '' if the last paragraph is not a hashtag block.
    """
    if not description:
        return ""
    paragraphs = [p.strip() for p in description.strip().split("\n\n")]
    for para in reversed(paragraphs):
        if not para:
            continue
        words = para.split()
        if words and all(w.startswith("#") for w in words):
            return para
        break
    return ""


def _hashtags_set(description: str) -> frozenset:
    """Normalized set of hashtag tokens in the last hashtag paragraph."""
    block = _extract_hashtag_block(description)
    return frozenset(t.lower() for t in block.split() if t.startswith("#"))


def _description_needs_update(current_desc: str, expected_desc: str) -> bool:
    """
    True if current description is missing the brand tag OR the hashtag sets differ.
    Comparison is case-insensitive.
    """
    if _BRAND_TAG.lower() not in current_desc.lower():
        return True
    current_tags = _hashtags_set(current_desc)
    expected_tags = _hashtags_set(expected_desc)
    return current_tags != expected_tags


def _build_new_description(current_desc: str, expected_desc: str) -> str:
    """
    Preserve the body from current_desc (keeps manual attribution/URL edits),
    but replace the hashtag block at the end with the one from expected_desc.

    If current_desc is empty, fall back to expected_desc entirely.
    If expected_desc has no hashtag block, return current_desc unchanged.
    """
    if not current_desc.strip():
        return expected_desc

    expected_hash_block = _extract_hashtag_block(expected_desc)
    if not expected_hash_block:
        return current_desc

    paragraphs = [p.strip() for p in current_desc.strip().split("\n\n")]
    # Remove trailing hashtag block if present
    if paragraphs:
        last = paragraphs[-1]
        last_words = last.split()
        if last_words and all(w.startswith("#") for w in last_words):
            paragraphs = paragraphs[:-1]

    body = "\n\n".join(p for p in paragraphs if p).rstrip()
    if body:
        return f"{body}\n\n{expected_hash_block}"
    return expected_hash_block


def _check_utf8_length(text: str) -> int:
    return len(text.encode("utf-8"))


# ── YouTube API calls ─────────────────────────────────────────────────────────

def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc)
    return "quotaExceeded" in msg or "userRateLimitExceeded" in msg


def _is_forbidden(exc: Exception) -> bool:
    msg = str(exc)
    return "403" in msg or "forbidden" in msg.lower()


def _fetch_snippets_batch(video_ids: list, token: str) -> dict:
    """
    Fetch snippet for up to 50 video IDs in one call.
    Returns {video_id: snippet_dict}. Missing IDs (deleted) are absent.
    Raises QuotaExceeded on quota errors.
    """
    from publishers.yt_sync import _yt_get
    _YT_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

    result = {}
    for i in range(0, len(video_ids), _SNIPPET_BATCH_SIZE):
        batch = video_ids[i:i + _SNIPPET_BATCH_SIZE]
        ids_param = ",".join(batch)
        url = f"{_YT_VIDEOS_URL}?id={ids_param}&part=snippet"
        try:
            data = _yt_get(url, token)
        except RuntimeError as exc:
            if _is_quota_error(exc):
                raise QuotaExceeded(str(exc)) from exc
            raise
        for item in data.get("items", []):
            result[item["id"]] = item.get("snippet", {})
    return result


def _update_snippet(video_id: str, token: str, new_desc: str) -> None:
    """
    Write new description via videos.update.
    Reads current snippet first to preserve all other fields (title, tags, categoryId).
    Raises urllib.error.HTTPError on API failures.
    """
    from publishers.yt_upload import update_video_description
    update_video_description(video_id, token, new_desc)


# ── Main entry point ──────────────────────────────────────────────────────────

def run_patch(token: str, dry_run: bool = False) -> dict:
    """
    Audit and patch hashtag blocks for all published Shorts on the channel.

    - Fetches channel inventory from YouTube (cached in state file after first run).
    - Reads current snippet for each video in batches (50 per API call).
    - Compares hashtag block against editorial_v1 expected description.
    - Updates only videos where hashtags differ.
    - On QuotaExceeded: saves progress and raises — caller schedules retry.

    Returns a summary dict.
    """
    from publishers.yt_sync import fetch_channel_uploads
    from publishers.yt_upload import read_video_snippet
    from engine import database as _db

    state = load_state()
    state["last_run_at"] = _now()
    state["quota_exhausted_at"] = None

    if not state.get("started_at"):
        state["started_at"] = _now()

    # ── Step 1: Channel inventory ─────────────────────────────────────────────
    if not state["channel_inventory"]:
        logger.info("[hashtag_patch] fetching channel inventory from YouTube…")
        try:
            inventory = fetch_channel_uploads(token, UPLOADS_PLAYLIST)
        except RuntimeError as exc:
            if _is_quota_error(exc):
                state["quota_exhausted_at"] = _now()
                save_state(state)
                raise QuotaExceeded(str(exc)) from exc
            raise

        state["channel_inventory"] = inventory
        all_ids = [v["video_id"] for v in inventory]

        # Build pending: all channel videos minus already-categorized ones
        done_ids = _done_ids(state)
        state["pending"] = [vid for vid in all_ids if vid not in done_ids]
        logger.info(
            "[hashtag_patch] channel inventory: %d videos, %d pending",
            len(all_ids), len(state["pending"]),
        )
        save_state(state)

    # ── Step 2: Build local session index ─────────────────────────────────────
    with _db.db() as conn:
        sessions = conn.execute(
            "SELECT s.id AS session_id, s.remote_video_id, s.pub_id "
            "FROM yt_upload_sessions s "
            "WHERE s.remote_video_id IS NOT NULL"
        ).fetchall()
    session_by_vid = {s["remote_video_id"]: dict(s) for s in sessions}

    # ── Step 3: Process pending in batches ────────────────────────────────────
    pending = list(state["pending"])
    if not pending:
        state["completed"] = True
        save_state(state)
        return _build_summary(state)

    i = 0
    while i < len(pending):
        batch_ids = pending[i:i + _SNIPPET_BATCH_SIZE]

        # Read current YouTube snippets for this batch
        try:
            snippets = _fetch_snippets_batch(batch_ids, token)
        except QuotaExceeded:
            state["quota_exhausted_at"] = _now()
            save_state(state)
            raise

        for vid in batch_ids:
            state["pending"] = [p for p in state["pending"] if p != vid]

            local_sess = session_by_vid.get(vid)
            if not local_sess:
                state["unlinked"].append(vid)
                logger.info("[hashtag_patch] unlinked (no local session): %s", vid)
                continue

            pub_id = local_sess.get("pub_id")
            current_snippet = snippets.get(vid)

            if current_snippet is None:
                # Not returned by videos.list — deleted or private under different account
                state["errors"].append({"video_id": vid, "error": "not returned by videos.list (likely deleted)"})
                logger.warning("[hashtag_patch] not found via API: %s", vid)
                continue

            current_desc = current_snippet.get("description", "")

            # Build expected description
            if not pub_id:
                state["errors"].append({"video_id": vid, "error": "session has no pub_id"})
                continue

            try:
                expected_desc = _db.assemble_pub_youtube_description(pub_id)
            except Exception as exc:
                state["errors"].append({"video_id": vid, "pub_id": pub_id, "error": f"assemble: {exc}"})
                continue

            if not expected_desc or _BRAND_TAG not in expected_desc:
                state["errors"].append({"video_id": vid, "pub_id": pub_id,
                                        "error": f"assembled desc missing {_BRAND_TAG}"})
                continue

            # Compare
            if not _description_needs_update(current_desc, expected_desc):
                state["already_correct"].append(vid)
                logger.debug("[hashtag_patch] already correct: %s", vid)
                continue

            before_block = _extract_hashtag_block(current_desc) or "(none)"
            after_block  = _extract_hashtag_block(expected_desc)

            # dry_run: just record what would change
            if dry_run:
                state["dry_run_plan"].append({
                    "video_id": vid,
                    "pub_id":   pub_id,
                    "before":   before_block,
                    "after":    after_block,
                    "title":    current_snippet.get("title", ""),
                })
                continue

            # Build merged description (preserve body, replace hashtag block)
            new_desc = _build_new_description(current_desc, expected_desc)

            # Guard against exceeding 5 000 UTF-8 bytes
            if _check_utf8_length(new_desc) > 5000:
                new_desc = new_desc.encode("utf-8")[:5000].decode("utf-8", errors="ignore")
                logger.warning("[hashtag_patch] description truncated to 5000 bytes for %s", vid)

            # Write to YouTube
            try:
                _update_snippet(vid, token, new_desc)
            except urllib.error.HTTPError as exc:
                body_text = "(unreadable)"
                try:
                    body_text = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                if exc.code == 403:
                    state["forbidden"].append({"video_id": vid, "error": f"HTTP 403"})
                    logger.warning("[hashtag_patch] 403 forbidden: %s", vid)
                    continue
                if "quotaExceeded" in body_text or _is_quota_error(RuntimeError(body_text)):
                    state["pending"].insert(0, vid)
                    state["quota_exhausted_at"] = _now()
                    save_state(state)
                    raise QuotaExceeded(f"quotaExceeded at {vid}") from exc
                state["errors"].append({"video_id": vid, "error": f"HTTP {exc.code}: {body_text[:200]}"})
                logger.error("[hashtag_patch] error updating %s: %s", vid, body_text[:200])
                continue
            except RuntimeError as exc:
                if _is_quota_error(exc):
                    state["pending"].insert(0, vid)
                    state["quota_exhausted_at"] = _now()
                    save_state(state)
                    raise QuotaExceeded(str(exc)) from exc
                state["errors"].append({"video_id": vid, "error": str(exc)[:200]})
                continue

            # Verify write was accepted
            verified = None
            try:
                verified_snippet = read_video_snippet(vid, token)
                if verified_snippet:
                    verified_desc = verified_snippet.get("description", "")
                    verified = (
                        _BRAND_TAG.lower() in verified_desc.lower()
                        and not _description_needs_update(verified_desc, expected_desc)
                    )
            except Exception as exc:
                logger.warning("[hashtag_patch] verify read failed %s: %s", vid, exc)
                verified = None  # "Verificación pendiente"

            state["updated"].append({
                "video_id": vid,
                "pub_id":   pub_id,
                "title":    current_snippet.get("title", ""),
                "before":   before_block,
                "after":    after_block,
                "verified": verified,
            })
            logger.info("[hashtag_patch] updated %s: %s → %s (verified=%s)",
                        vid, before_block, after_block, verified)

            # Sync local session description
            try:
                with _db.db() as conn:
                    conn.execute(
                        "UPDATE yt_upload_sessions SET description=?, updated_at=? "
                        "WHERE remote_video_id=?",
                        (new_desc, _now(), vid),
                    )
            except Exception as exc:
                logger.warning("[hashtag_patch] local sync failed for %s: %s", vid, exc)

        save_state(state)
        i += _SNIPPET_BATCH_SIZE

    state["completed"] = len(state["pending"]) == 0
    save_state(state)
    return _build_summary(state)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _done_ids(state: dict) -> set:
    done = set(state.get("already_correct", []))
    done.update(u["video_id"] for u in state.get("updated", []))
    done.update(u["video_id"] for u in state.get("dry_run_plan", []))
    done.update(e["video_id"] for e in state.get("forbidden", []))
    done.update(state.get("unlinked", []))
    done.update(e.get("video_id", "") for e in state.get("errors", []))
    return done


def _build_summary(state: dict) -> dict:
    updated_list = [u for u in state.get("updated", []) if not u.get("dry_run")]
    verified_ok   = sum(1 for u in updated_list if u.get("verified") is True)
    verified_pend = sum(1 for u in updated_list if u.get("verified") is None)
    return {
        "channel_id":            state["channel_id"],
        "inventory_total":       len(state["channel_inventory"]),
        "pending":               len(state["pending"]),
        "already_correct":       len(state.get("already_correct", [])),
        "updated":               len(updated_list),
        "verified_ok":           verified_ok,
        "verification_pending":  verified_pend,
        "dry_run_planned":       len(state.get("dry_run_plan", [])),
        "forbidden":             len(state.get("forbidden", [])),
        "unlinked":              len(state.get("unlinked", [])),
        "errors":                len(state.get("errors", [])),
        "completed":             state.get("completed", False),
        "quota_exhausted_at":    state.get("quota_exhausted_at"),
        "last_run_at":           state.get("last_run_at"),
        "sample_updated":        updated_list[:5],
        "sample_dry_run":        state.get("dry_run_plan", [])[:5],
        "sample_errors":         state.get("errors", [])[:5],
        "sample_forbidden":      state.get("forbidden", [])[:5],
        "sample_unlinked":       state.get("unlinked", [])[:5],
    }
