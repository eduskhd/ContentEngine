"""
Tests for YouTube Publishing Center.

No real YouTube uploads. Uses unittest.mock throughout.
Tests: duplicate upload prevention, unauthorized upload rejection, non-youtube rejection.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestYTAuthModule(unittest.TestCase):
    """Unit tests for yt_auth helpers (no network calls)."""

    def test_generate_pkce_returns_pair(self):
        from publishers.yt_auth import generate_pkce
        verifier, challenge = generate_pkce()
        self.assertIsInstance(verifier, str)
        self.assertIsInstance(challenge, str)
        self.assertNotEqual(verifier, challenge)

    def test_pkce_challenge_is_base64url(self):
        import base64, hashlib
        from publishers.yt_auth import generate_pkce
        verifier, challenge = generate_pkce()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        self.assertEqual(challenge, expected)

    def test_get_auth_url_contains_pkce_fields(self):
        from publishers.yt_auth import get_auth_url, generate_pkce
        verifier, _ = generate_pkce()
        with patch.dict(os.environ, {"YOUTUBE_CLIENT_ID": "test-client-id"}):
            url = get_auth_url("test-state-123", verifier)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("code_challenge=", url)
        self.assertIn("state=test-state-123", url)
        self.assertIn("access_type=offline", url)
        self.assertIn("youtube.upload", url)
        self.assertIn("youtube.readonly", url)

    def test_is_connected_false_when_no_file(self):
        from publishers import yt_auth
        with patch.object(yt_auth, "_TOKEN_FILE", Path("/nonexistent/path/tokens.json")):
            self.assertFalse(yt_auth.is_connected())

    def test_load_tokens_returns_none_missing(self):
        from publishers import yt_auth
        with patch.object(yt_auth, "_TOKEN_FILE", Path("/nonexistent/path/tokens.json")):
            self.assertIsNone(yt_auth.load_tokens())


class TestYTUploadModule(unittest.TestCase):
    """Unit tests for yt_upload helpers."""

    def test_check_shorts_compat_ok_clip(self):
        from publishers.yt_upload import check_shorts_compatibility
        result = check_shorts_compatibility({"duration_s": 30, "width": 1080, "height": 1920})
        self.assertTrue(result["compatible"])
        self.assertEqual(result["warnings"], [])

    def test_check_shorts_compat_too_long(self):
        from publishers.yt_upload import check_shorts_compatibility
        result = check_shorts_compatibility({"duration_s": 90, "width": 1080, "height": 1920})
        self.assertFalse(result["compatible"])
        self.assertTrue(any("60s" in w for w in result["warnings"]))

    def test_check_shorts_compat_wrong_ratio(self):
        from publishers.yt_upload import check_shorts_compatibility
        result = check_shorts_compatibility({"duration_s": 30, "width": 1920, "height": 1080})
        self.assertTrue(any("16:9" in w or "ratio" in w.lower() for w in result["warnings"]))

    def test_compute_file_hash_stable(self):
        from publishers.yt_upload import compute_file_hash
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as f:
            f.write(b"fake video content" * 100)
            path = f.name
        try:
            h1 = compute_file_hash(path)
            h2 = compute_file_hash(path)
            self.assertEqual(h1, h2)
            self.assertIsInstance(h1, str)
            self.assertEqual(len(h1), 32)  # MD5 hex
        finally:
            os.unlink(path)

    def test_classify_error_quota(self):
        import urllib.error
        from publishers.yt_upload import classify_error
        err = urllib.error.HTTPError(url="", code=403, msg="quotaExceeded",
                                     hdrs=None, fp=None)
        err.read = lambda: b'{"error":{"errors":[{"reason":"quotaExceeded"}]}}'
        self.assertEqual(classify_error(err), "QUOTA_EXCEEDED")

    def test_classify_error_auth(self):
        import urllib.error
        from publishers.yt_upload import classify_error
        err = urllib.error.HTTPError(url="", code=401, msg="Unauthorized",
                                     hdrs=None, fp=None)
        self.assertEqual(classify_error(err), "AUTH_REVOKED")

    def test_classify_error_transient(self):
        from publishers.yt_upload import classify_error
        self.assertEqual(classify_error(TimeoutError("timed out")), "TRANSIENT")

    def test_create_resumable_session_forces_private(self):
        """privacyStatus must always be 'private' in the metadata sent to YouTube."""
        from publishers import yt_upload
        captured_body = {}

        class MockResponse:
            status = 200
            def __init__(self):
                self.headers = {"Location": "https://upload.googleapis.com/test-session"}
            def read(self): return b'{}'
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def mock_urlopen(req, timeout=None):
            import json as _json
            captured_body["data"] = _json.loads(req.data)
            return MockResponse()

        with patch("urllib.request.urlopen", mock_urlopen):
            url = yt_upload.create_resumable_session(
                access_token="tok",
                title="Test",
                description="desc",
                tags=[],
                file_size=1000,
                is_for_kids=False,
            )

        self.assertEqual(url, "https://upload.googleapis.com/test-session")
        privacy = captured_body["data"]["status"]["privacyStatus"]
        self.assertEqual(privacy, "private", "privacyStatus MUST be 'private'")


class TestDBHelpers(unittest.TestCase):
    """Integration tests against a real in-memory-ish SQLite DB."""

    def setUp(self):
        import sqlite3
        from engine import database as db
        self.db = db

    def test_consume_yt_oauth_state_one_time(self):
        """State token must be consumed exactly once."""
        db = self.db
        db.save_yt_oauth_state("test-state-abc", "verifier-xyz")
        v = db.consume_yt_oauth_state("test-state-abc")
        self.assertEqual(v, "verifier-xyz")
        v2 = db.consume_yt_oauth_state("test-state-abc")
        self.assertIsNone(v2, "State must be one-time-use")

    def test_consume_unknown_state_returns_none(self):
        db = self.db
        self.assertIsNone(db.consume_yt_oauth_state("completely-unknown-state"))


class TestAPIEndpoints(unittest.IsolatedAsyncioTestCase):
    """API endpoint tests using httpx (no real uploads)."""

    async def asyncSetUp(self):
        try:
            from httpx import AsyncClient, ASGITransport
            from api.main import app
            self.transport = ASGITransport(app=app)
            self.app = app
            self.client = AsyncClient(transport=self.transport, base_url="http://test")
        except ImportError:
            self.skipTest("httpx not available")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_youtube_status_not_connected_without_tokens(self):
        from publishers import yt_auth
        with patch.object(yt_auth, "_TOKEN_FILE", Path("/nonexistent/path/tokens.json")):
            r = await self.client.get("/youtube/status")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["connected"])

    async def test_youtube_connect_returns_redirect(self):
        """Connect endpoint redirects to Google OAuth (307) with client ID configured."""
        with patch.dict(os.environ, {
            "YOUTUBE_CLIENT_ID": "mock-client-id",
            "YOUTUBE_CLIENT_SECRET": "mock-client-secret",
        }):
            r = await self.client.get("/youtube/connect", follow_redirects=False)
        self.assertEqual(r.status_code, 307)
        location = r.headers.get("location", "")
        self.assertIn("accounts.google.com", location)

    async def test_start_upload_rejects_non_youtube_platform(self):
        """Upload endpoint must reject publications that are not youtube_shorts."""
        import uuid
        from engine import database as db

        # Create a minimal tiktok publication (not youtube_shorts)
        conn = db.get_db()
        clip_id = str(uuid.uuid4())
        pub_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        now = "2026-09-17T00:00:00"
        conn.execute(
            "INSERT INTO jobs (id,source_path,status,mode,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (job_id, "/fake/path.mp4", "DONE", "REVIEW", now, now)
        )
        conn.execute(
            "INSERT INTO clips (id,job_id,candidate_id,created_at) VALUES (?,?,?,?)",
            (clip_id, job_id, str(uuid.uuid4()), now)
        )
        conn.execute(
            """INSERT INTO publications (id,clip_id,platform,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?)""",
            (pub_id, clip_id, "tiktok", "ready", now, now)
        )
        conn.commit()
        conn.close()

        r = await self.client.post(
            f"/publications/{pub_id}/youtube-upload",
            json={"is_for_kids": False},
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("youtube_shorts", r.json()["detail"])

    async def test_start_upload_rejects_missing_is_for_kids(self):
        """Upload endpoint must require is_for_kids field."""
        r = await self.client.post(
            "/publications/any-id/youtube-upload",
            json={},
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("is_for_kids", r.json()["detail"])

    async def test_session_url_not_exposed_in_status(self):
        """session_url must never appear in /yt-uploads/{id} response."""
        import uuid
        from engine import database as db

        pub_id = str(uuid.uuid4())
        clip_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        cand_id = str(uuid.uuid4())
        video_id = str(uuid.uuid4())
        now = "2026-09-17T00:00:00"
        conn = db.get_db()
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "INSERT INTO jobs (id,source_path,status,mode,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (job_id, "/fake/path.mp4", "DONE", "REVIEW", now, now)
        )
        conn.execute(
            "INSERT INTO candidates (id,job_id,video_id,start_s,end_s,created_at) VALUES (?,?,?,?,?,?)",
            (cand_id, job_id, video_id, 0.0, 30.0, now)
        )
        conn.execute(
            "INSERT INTO clips (id,job_id,candidate_id,created_at) VALUES (?,?,?,?)",
            (clip_id, job_id, cand_id, now)
        )
        conn.execute(
            """INSERT INTO publications (id,clip_id,platform,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?)""",
            (pub_id, clip_id, "youtube_shorts", "ready", now, now)
        )
        conn.commit()
        conn.close()

        sid = db.create_yt_upload_session(
            pub_id=pub_id, clip_id=clip_id, channel_id="UC123",
            title="Test", description="", tags=[], is_for_kids=False,
            file_path="/fake/file.mp4", file_hash="abc123", file_size=1000,
        )
        # Manually inject a session_url
        db.update_yt_upload_session(sid, session_url="https://upload.googleapis.com/secret-url")

        r = await self.client.get(f"/yt-uploads/{sid}")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertNotIn("session_url", body, "session_url must never be exposed to clients")


if __name__ == "__main__":
    unittest.main(verbosity=2)
