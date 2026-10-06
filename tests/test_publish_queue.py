"""
Tests for the autonomous YouTube publish queue.

Covers: quota cycles, consecutive rejections, cross-restart persistence,
concurrent worker exclusion, timezone correctness, HTTP 429 classification,
and Retry-After header extraction.

No real YouTube uploads — all HTTP calls are mocked.
Uses a temporary SQLite file for DB-dependent tests.
"""
import io
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import urllib.error

# ── Helpers ────────────────────────────────────────────────────────────────────

def _utcnow() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _future(minutes: float) -> str:
    return (datetime.now(tz=timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _past(minutes: float) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _make_http_error(code: int, body: bytes = b"", headers: dict | None = None):
    """Build a urllib.error.HTTPError with optional Retry-After header."""
    import http.client
    hdrs = None
    if headers:
        raw = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
        hdrs = http.client.HTTPMessage()
        for k, v in headers.items():
            hdrs[k] = v
    err = urllib.error.HTTPError(url="https://youtube.test", code=code,
                                 msg="error", hdrs=hdrs, fp=io.BytesIO(body))
    return err


def _make_temp_db() -> str:
    """Create a temp SQLite file with the minimal schema for queue tests."""
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS publications (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'pending',
            external_post_id TEXT,
            external_url TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS yt_upload_sessions (
            id TEXT PRIMARY KEY,
            pub_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            file_path TEXT,
            file_hash TEXT,
            file_size INTEGER,
            bytes_sent INTEGER DEFAULT 0,
            session_url TEXT,
            remote_video_id TEXT,
            remote_process_status TEXT,
            remote_privacy_status TEXT,
            privacy_status TEXT DEFAULT 'private',
            title TEXT,
            description TEXT,
            tags TEXT DEFAULT '[]',
            is_for_kids INTEGER DEFAULT 0,
            series_id TEXT,
            series_part INTEGER DEFAULT 0,
            attempts INTEGER DEFAULT 0,
            last_attempt_at TEXT,
            next_attempt_at TEXT,
            error_message TEXT,
            error_code TEXT,
            locked_at TEXT,
            locked_by TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS upload_batches (
            id TEXT PRIMARY KEY,
            name TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS upload_batch_items (
            id TEXT PRIMARY KEY,
            batch_id TEXT,
            pub_id TEXT
        );
    """)
    conn.commit()
    conn.close()
    return path


# ── classify_error ─────────────────────────────────────────────────────────────

class TestClassifyError(unittest.TestCase):

    def _classify(self, exc):
        from publishers.yt_upload import classify_error
        return classify_error(exc)

    def test_http_403_quota_body(self):
        err = _make_http_error(403, b'{"error":{"errors":[{"reason":"quotaExceeded"}]}}')
        self.assertEqual(self._classify(err), "QUOTA_EXCEEDED")

    def test_http_403_user_rate_limit(self):
        err = _make_http_error(403, b'{"error":{"errors":[{"reason":"userRateLimitExceeded"}]}}')
        self.assertEqual(self._classify(err), "QUOTA_EXCEEDED")

    def test_http_429_is_quota_exceeded(self):
        """HTTP 429 Too Many Requests must be classified as QUOTA_EXCEEDED."""
        err = _make_http_error(429)
        self.assertEqual(self._classify(err), "QUOTA_EXCEEDED")

    def test_http_429_with_retry_after_is_quota(self):
        err = _make_http_error(429, b"", {"Retry-After": "3600"})
        self.assertEqual(self._classify(err), "QUOTA_EXCEEDED")

    def test_http_400_upload_limit_exceeded(self):
        err = _make_http_error(400, b'{"error":{"errors":[{"reason":"uploadLimitExceeded"}]}}')
        self.assertEqual(self._classify(err), "QUOTA_EXCEEDED")

    def test_http_401_auth_revoked(self):
        err = _make_http_error(401)
        self.assertEqual(self._classify(err), "AUTH_REVOKED")

    def test_http_500_transient(self):
        err = _make_http_error(500)
        self.assertEqual(self._classify(err), "TRANSIENT")

    def test_http_503_transient(self):
        err = _make_http_error(503)
        self.assertEqual(self._classify(err), "TRANSIENT")

    def test_string_quota_fallback(self):
        """classify_error falls back to string-matching for wrapped errors."""
        from publishers.yt_upload import classify_error
        self.assertEqual(classify_error(RuntimeError("quota exceeded")), "QUOTA_EXCEEDED")

    def test_string_upload_limit_fallback(self):
        from publishers.yt_upload import classify_error
        self.assertEqual(classify_error(RuntimeError("uploadLimitExceeded in body")), "QUOTA_EXCEEDED")

    def test_connection_error_transient(self):
        from publishers.yt_upload import classify_error
        self.assertEqual(classify_error(ConnectionError("reset")), "TRANSIENT")


# ── _extract_retry_after ───────────────────────────────────────────────────────

class TestExtractRetryAfter(unittest.TestCase):

    def _extract(self, exc):
        from workers.yt_upload_worker import _extract_retry_after
        return _extract_retry_after(exc)

    def test_direct_http_error_with_retry_after(self):
        err = _make_http_error(429, b"", {"Retry-After": "1800"})
        self.assertEqual(self._extract(err), 1800)

    def test_direct_http_error_no_header(self):
        err = _make_http_error(429)
        self.assertIsNone(self._extract(err))

    def test_runtime_wrapping_http_error_with_header(self):
        """RuntimeError wrapping an HTTPError must expose Retry-After via __cause__."""
        inner = _make_http_error(429, b"rate limited", {"Retry-After": "900"})
        wrapped = RuntimeError("YouTube API 429 creating upload session: rate limited")
        wrapped.__cause__ = inner
        self.assertEqual(self._extract(wrapped), 900)

    def test_runtime_message_prefix(self):
        """RuntimeError with 'Retry-After: N\\n' prefix (from create_resumable_session)."""
        exc = RuntimeError("Retry-After: 600\nYouTube API 429 creating upload session: too many")
        self.assertEqual(self._extract(exc), 600)

    def test_no_retry_after_returns_none(self):
        self.assertIsNone(self._extract(RuntimeError("some other error")))

    def test_non_numeric_retry_after_returns_none(self):
        err = _make_http_error(429, b"", {"Retry-After": "Sat, 01 Jan 2030 00:00:00 GMT"})
        self.assertIsNone(self._extract(err))


# ── Worker _fail() ─────────────────────────────────────────────────────────────

class TestWorkerFail(unittest.TestCase):
    """Tests for YTUploadWorker._fail() using a mocked database."""

    def _make_worker(self):
        from workers.yt_upload_worker import YTUploadWorker
        w = YTUploadWorker.__new__(YTUploadWorker)
        w._stop_event = threading.Event()
        return w

    @patch("workers.yt_upload_worker.db")
    def test_quota_exceeded_schedules_30min_by_default(self, mock_db):
        """QUOTA_EXCEEDED with no Retry-After → next_attempt_at = now + 30min."""
        mock_db.get_yt_upload_session.return_value = {"attempts": 0, "series_id": None}
        mock_db.update_yt_upload_session = MagicMock()

        w = self._make_worker()
        before = datetime.now(tz=timezone.utc)
        w._fail("sid1", "pub1", "quota", "QUOTA_EXCEEDED")
        after = datetime.now(tz=timezone.utc)

        call_kwargs = mock_db.update_yt_upload_session.call_args[1]
        self.assertEqual(call_kwargs["status"], "pending")
        self.assertEqual(call_kwargs["attempts"], 0)

        nat = datetime.fromisoformat(call_kwargs["next_attempt_at"])
        expected_low = before + timedelta(minutes=29, seconds=55)
        expected_high = after + timedelta(minutes=30, seconds=5)
        self.assertGreater(nat, expected_low, "next_attempt_at should be ~30min from now")
        self.assertLess(nat, expected_high, "next_attempt_at should be ~30min from now")

    @patch("workers.yt_upload_worker.db")
    def test_quota_exceeded_uses_retry_after_when_provided(self, mock_db):
        """Retry-After: 3600 overrides QUOTA_RETRY_MINUTES."""
        mock_db.get_yt_upload_session.return_value = {"attempts": 0, "series_id": None}
        mock_db.update_yt_upload_session = MagicMock()

        w = self._make_worker()
        before = datetime.now(tz=timezone.utc)
        w._fail("sid2", "pub2", "rate limited", "QUOTA_EXCEEDED", retry_after_seconds=3600)
        after = datetime.now(tz=timezone.utc)

        call_kwargs = mock_db.update_yt_upload_session.call_args[1]
        nat = datetime.fromisoformat(call_kwargs["next_attempt_at"])
        expected_low = before + timedelta(minutes=59)
        expected_high = after + timedelta(minutes=61)
        self.assertGreater(nat, expected_low, "Retry-After=3600 should give ~60min delay")
        self.assertLess(nat, expected_high, "Retry-After=3600 should give ~60min delay")

    @patch("workers.yt_upload_worker.db")
    def test_quota_stays_pending_not_error(self, mock_db):
        """QUOTA_EXCEEDED must keep status=pending — never go to error."""
        mock_db.get_yt_upload_session.return_value = {"attempts": 5, "series_id": None}
        mock_db.update_yt_upload_session = MagicMock()

        w = self._make_worker()
        w._fail("sid3", "pub3", "quota", "QUOTA_EXCEEDED")

        call_kwargs = mock_db.update_yt_upload_session.call_args[1]
        self.assertEqual(call_kwargs["status"], "pending")
        self.assertEqual(call_kwargs["attempts"], 0)

    @patch("workers.yt_upload_worker.db")
    def test_transient_schedules_5min_by_default(self, mock_db):
        """TRANSIENT without Retry-After → next_attempt_at = now + 5min."""
        mock_db.get_yt_upload_session.return_value = {"attempts": 1, "series_id": None}
        mock_db.update_yt_upload_session = MagicMock()

        w = self._make_worker()
        before = datetime.now(tz=timezone.utc)
        w._fail("sid4", "pub4", "timeout", "TRANSIENT")
        after = datetime.now(tz=timezone.utc)

        call_kwargs = mock_db.update_yt_upload_session.call_args[1]
        self.assertEqual(call_kwargs["status"], "pending")
        nat = datetime.fromisoformat(call_kwargs["next_attempt_at"])
        self.assertGreater(nat, before + timedelta(minutes=4, seconds=55))
        self.assertLess(nat, after + timedelta(minutes=5, seconds=5))

    @patch("workers.yt_upload_worker.db")
    def test_transient_uses_retry_after_when_provided(self, mock_db):
        mock_db.get_yt_upload_session.return_value = {"attempts": 0, "series_id": None}
        mock_db.update_yt_upload_session = MagicMock()

        w = self._make_worker()
        before = datetime.now(tz=timezone.utc)
        w._fail("sid5", "pub5", "rate limited", "TRANSIENT", retry_after_seconds=120)
        after = datetime.now(tz=timezone.utc)

        call_kwargs = mock_db.update_yt_upload_session.call_args[1]
        nat = datetime.fromisoformat(call_kwargs["next_attempt_at"])
        self.assertGreater(nat, before + timedelta(seconds=115))
        self.assertLess(nat, after + timedelta(seconds=125))

    @patch("workers.yt_upload_worker.db")
    def test_fatal_error_marks_error_status(self, mock_db):
        mock_db.get_yt_upload_session.return_value = {
            "attempts": 1, "series_id": None, "series_part": 0,
        }
        mock_db.update_yt_upload_session = MagicMock()
        mock_db.pause_series_subsequent = MagicMock(return_value=0)

        w = self._make_worker()
        w._fail("sid6", "pub6", "file gone", "INVALID_FILE", fatal=True)

        mock_db.update_yt_upload_session.assert_called_once()
        call_kwargs = mock_db.update_yt_upload_session.call_args[1]
        self.assertEqual(call_kwargs["status"], "error")

    @patch("workers.yt_upload_worker.db")
    def test_next_attempt_at_is_utc_isoformat(self, mock_db):
        """next_attempt_at must be a UTC ISO-8601 string parseable as aware datetime."""
        mock_db.get_yt_upload_session.return_value = {"attempts": 0, "series_id": None}
        mock_db.update_yt_upload_session = MagicMock()

        w = self._make_worker()
        w._fail("sid7", "pub7", "quota", "QUOTA_EXCEEDED")

        call_kwargs = mock_db.update_yt_upload_session.call_args[1]
        nat_str = call_kwargs["next_attempt_at"]
        try:
            nat = datetime.fromisoformat(nat_str)
        except ValueError:
            self.fail(f"next_attempt_at is not valid ISO-8601: {nat_str!r}")
        self.assertIsNotNone(nat.tzinfo, "next_attempt_at must be timezone-aware")


# ── Claim logic (temp DB) ──────────────────────────────────────────────────────

class TestClaimLogic(unittest.TestCase):
    """Integration tests for claim_yt_upload_session() against a real temp DB."""

    def setUp(self):
        self.db_path = _make_temp_db()
        # Patch CONFIG.db_path so database.py uses the temp file
        from engine import config as cfg
        self._orig_db_path = cfg.CONFIG.db_path
        cfg.CONFIG.db_path = self.db_path

    def tearDown(self):
        from engine import config as cfg
        cfg.CONFIG.db_path = self._orig_db_path
        os.unlink(self.db_path)

    def _insert_session(self, sid: str, pub_id: str, next_attempt_at: str | None = None,
                        status: str = "pending", locked_at: str | None = None,
                        series_part: int = 0):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO publications (id, status, updated_at) VALUES (?, 'pending', ?)",
            (pub_id, _utcnow()),
        )
        conn.execute(
            """INSERT INTO yt_upload_sessions
               (id, pub_id, status, file_path, file_hash, file_size, title, description,
                next_attempt_at, locked_at, series_part, attempts, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, pub_id, status, "/fake/file.mp4", "deadbeef", 1000,
             "Test Title", "Test description",
             next_attempt_at, locked_at, series_part, 0, _utcnow(), _utcnow()),
        )
        conn.commit()
        conn.close()

    def test_claim_picks_session_without_next_attempt_at(self):
        self._insert_session("sess-a", "pub-a", next_attempt_at=None)
        from engine.database import claim_yt_upload_session
        result = claim_yt_upload_session("worker-1")
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "sess-a")

    def test_claim_skips_session_with_future_next_attempt_at(self):
        self._insert_session("sess-b", "pub-b", next_attempt_at=_future(60))
        from engine.database import claim_yt_upload_session
        result = claim_yt_upload_session("worker-1")
        self.assertIsNone(result, "Session with future next_attempt_at must not be claimed")

    def test_claim_picks_session_with_past_next_attempt_at(self):
        self._insert_session("sess-c", "pub-c", next_attempt_at=_past(5))
        from engine.database import claim_yt_upload_session
        result = claim_yt_upload_session("worker-1")
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "sess-c")

    def test_claim_skips_locked_session(self):
        self._insert_session("sess-d", "pub-d", locked_at=_future(5))
        from engine.database import claim_yt_upload_session
        result = claim_yt_upload_session("worker-1")
        self.assertIsNone(result, "Fresh locked session must not be claimed")

    def test_claim_reclaims_stale_locked_session(self):
        """A lock older than 5 minutes is stale and can be reclaimed."""
        self._insert_session("sess-e", "pub-e", locked_at=_past(10))
        from engine.database import claim_yt_upload_session
        result = claim_yt_upload_session("worker-1")
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "sess-e")

    def test_claim_is_exclusive_concurrent(self):
        """Two concurrent claim calls must not both succeed for the same session."""
        self._insert_session("sess-f", "pub-f")
        from engine.database import claim_yt_upload_session
        results = []
        errors = []

        def claim():
            try:
                r = claim_yt_upload_session(f"worker-{threading.current_thread().name}")
                results.append(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=claim, name=str(i)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Unexpected errors: {errors}")
        non_none = [r for r in results if r is not None]
        self.assertLessEqual(len(non_none), 1,
                             "At most one worker should claim the session")

    def test_claim_returns_none_when_queue_empty(self):
        from engine.database import claim_yt_upload_session
        result = claim_yt_upload_session("worker-1")
        self.assertIsNone(result)


# ── Quota cycle (integration) ──────────────────────────────────────────────────

class TestQuotaCycle(unittest.TestCase):
    """End-to-end quota cycle: QUOTA_EXCEEDED → pending+next_at → retry → success."""

    def setUp(self):
        self.db_path = _make_temp_db()
        from engine import config as cfg
        self._orig_db_path = cfg.CONFIG.db_path
        cfg.CONFIG.db_path = self.db_path

    def tearDown(self):
        from engine import config as cfg
        cfg.CONFIG.db_path = self._orig_db_path
        os.unlink(self.db_path)

    def test_quota_cycle_pending_retry(self):
        """After QUOTA_EXCEEDED, session returns to pending and is re-claimable after delay."""
        from engine import database as db_mod
        from workers.yt_upload_worker import YTUploadWorker

        sid = "quota-cycle-1"
        pub_id = "pub-cycle-1"
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO publications (id, status, updated_at) VALUES (?, 'pending', ?)",
            (pub_id, _utcnow()),
        )
        conn.execute(
            """INSERT INTO yt_upload_sessions
               (id, pub_id, status, title, description, file_path, file_hash, file_size,
                attempts, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, pub_id, "pending", "T", "D", "/f.mp4", "abc", 1000, 0, _utcnow(), _utcnow()),
        )
        conn.commit()
        conn.close()

        # Simulate QUOTA_EXCEEDED
        w = YTUploadWorker.__new__(YTUploadWorker)
        w._stop_event = threading.Event()
        w._fail(sid, pub_id, "uploadLimitExceeded", "QUOTA_EXCEEDED")

        # Session must now be pending with a future next_attempt_at
        row = db_mod.get_yt_upload_session(sid)
        self.assertEqual(row["status"], "pending")
        self.assertIsNotNone(row["next_attempt_at"])
        nat = datetime.fromisoformat(row["next_attempt_at"])
        self.assertGreater(nat, datetime.now(tz=timezone.utc),
                           "next_attempt_at must be in the future after quota fail")
        self.assertEqual(row["attempts"], 0,
                         "attempts must be reset to 0 after quota fail")

        # Not claimable yet (future next_attempt_at)
        claimed = db_mod.claim_yt_upload_session("worker-test")
        self.assertIsNone(claimed, "Session must not be claimable until next_attempt_at passes")

        # Manually set next_attempt_at to past → claimable again
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE yt_upload_sessions SET next_attempt_at=? WHERE id=?",
            (_past(1), sid),
        )
        conn.commit()
        conn.close()

        claimed = db_mod.claim_yt_upload_session("worker-test")
        self.assertIsNotNone(claimed, "Session must be claimable after next_attempt_at passes")
        self.assertEqual(claimed["id"], sid)

    def test_consecutive_quota_rejections_dont_exhaust_attempts(self):
        """Multiple consecutive QUOTA_EXCEEDED failures must not push status to error."""
        from workers.yt_upload_worker import YTUploadWorker
        from engine import database as db_mod

        sid = "quota-consec-1"
        pub_id = "pub-consec-1"
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO publications (id, status, updated_at) VALUES (?, 'pending', ?)", (pub_id, _utcnow()))
        conn.execute(
            "INSERT INTO yt_upload_sessions (id, pub_id, status, title, description, file_path, file_hash, file_size, attempts, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (sid, pub_id, "pending", "T", "D", "/f.mp4", "abc", 1000, 0, _utcnow(), _utcnow()),
        )
        conn.commit()
        conn.close()

        w = YTUploadWorker.__new__(YTUploadWorker)
        w._stop_event = threading.Event()

        for i in range(5):
            w._fail(sid, pub_id, "quota", "QUOTA_EXCEEDED")
            row = db_mod.get_yt_upload_session(sid)
            self.assertEqual(row["status"], "pending",
                             f"After rejection #{i+1}, status must stay pending (not error)")
            self.assertEqual(row["attempts"], 0,
                             "attempts must remain 0 after each quota rejection")


# ── Cross-restart persistence ──────────────────────────────────────────────────

class TestCrossRestart(unittest.TestCase):
    """Session state survives a simulated worker restart (DB is the source of truth)."""

    def setUp(self):
        self.db_path = _make_temp_db()
        from engine import config as cfg
        self._orig_db_path = cfg.CONFIG.db_path
        cfg.CONFIG.db_path = self.db_path

    def tearDown(self):
        from engine import config as cfg
        cfg.CONFIG.db_path = self._orig_db_path
        os.unlink(self.db_path)

    def test_pending_session_survives_restart(self):
        """A pending session with next_attempt_at is re-claimable after worker restarts."""
        from engine import database as db_mod

        sid = "restart-1"
        pub_id = "pub-restart-1"
        past_nat = _past(5)

        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO publications (id, status, updated_at) VALUES (?, 'pending', ?)", (pub_id, _utcnow()))
        conn.execute(
            "INSERT INTO yt_upload_sessions (id, pub_id, status, title, description, file_path, file_hash, file_size, next_attempt_at, error_code, attempts, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, pub_id, "pending", "T", "D", "/f.mp4", "abc", 1000,
             past_nat, "QUOTA_EXCEEDED", 0, _utcnow(), _utcnow()),
        )
        conn.commit()
        conn.close()

        # Simulate new worker startup (fresh instance, no in-memory state)
        claimed = db_mod.claim_yt_upload_session("new-worker")
        self.assertIsNotNone(claimed, "Session must be re-claimable on worker restart")
        self.assertEqual(claimed["id"], sid)

    def test_uploading_session_with_stale_lock_is_recovered(self):
        """An 'uploading' session with a lock older than 5 minutes is recoverable."""
        from engine import database as db_mod
        from workers.yt_upload_worker import YTUploadWorker

        sid = "restart-stale-1"
        pub_id = "pub-stale-1"
        stale_lock = _past(15)

        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO publications (id, status, updated_at) VALUES (?, 'uploading', ?)", (pub_id, _utcnow()))
        conn.execute(
            "INSERT INTO yt_upload_sessions (id, pub_id, status, title, description, file_path, file_hash, file_size, locked_at, locked_by, bytes_sent, attempts, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, pub_id, "uploading", "T", "D", "/f.mp4", "abc", 1000,
             stale_lock, "dead-worker", 500000, 1, _utcnow(), _utcnow()),
        )
        conn.commit()
        conn.close()

        # Worker startup must unlock stale sessions
        w = YTUploadWorker.__new__(YTUploadWorker)
        w._stop_event = threading.Event()
        from unittest.mock import patch
        with patch.object(w, "_reset_quota_sessions"):
            w._unlock_stale_sessions()

        row = db_mod.get_yt_upload_session(sid)
        self.assertEqual(row["status"], "pending",
                         "Stale-locked uploading session must be unlocked to pending on startup")
        self.assertIsNone(row["locked_at"])
        self.assertIsNone(row["locked_by"])


# ── Timezone correctness ───────────────────────────────────────────────────────

class TestTimezoneCorrectness(unittest.TestCase):

    @patch("workers.yt_upload_worker.db")
    def test_next_attempt_at_is_aware_utc(self, mock_db):
        """next_attempt_at written by _fail() must be UTC-aware ISO-8601."""
        from workers.yt_upload_worker import YTUploadWorker
        mock_db.get_yt_upload_session.return_value = {"attempts": 0, "series_id": None}
        mock_db.update_yt_upload_session = MagicMock()

        w = YTUploadWorker.__new__(YTUploadWorker)
        w._stop_event = threading.Event()
        w._fail("s", "p", "quota", "QUOTA_EXCEEDED")

        kw = mock_db.update_yt_upload_session.call_args[1]
        nat_str = kw["next_attempt_at"]
        nat = datetime.fromisoformat(nat_str)
        self.assertIsNotNone(nat.tzinfo,
                             "next_attempt_at must be timezone-aware (UTC+00:00)")

    @patch("workers.yt_upload_worker.db")
    def test_now_helper_is_utc(self, _mock_db):
        """_now() must return an aware UTC ISO-8601 string."""
        from workers.yt_upload_worker import _now
        s = _now()
        dt = datetime.fromisoformat(s)
        self.assertIsNotNone(dt.tzinfo)
        # UTC offset must be zero
        offset = dt.utcoffset()
        self.assertEqual(offset.total_seconds(), 0,
                         f"_now() offset is {offset}, expected 0 (UTC)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
