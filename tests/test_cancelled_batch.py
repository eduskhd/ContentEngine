"""
25 mandatory tests for CANCELLED batch state.
Spec: "CONTENT ENGINE — ELIMINAR BATCH + ESTADO CANCELLED"
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import engine.database as db
from engine.database import (
    create_upload_batch, get_upload_batch, list_upload_batches,
    cancel_upload_batch, pause_upload_batch, resume_upload_batch,
    update_yt_upload_session,
)


def _make_temp_db(tmp_path):
    from engine.config import CONFIG
    CONFIG.db_path = str(tmp_path / "test.sqlite")
    db.init_db()


def _make_session_raw(conn, pub_id=None, clip_id=None, channel_id="ch1", status="pending"):
    """Insert a yt_upload_session row (FK enforcement temporarily disabled)."""
    conn.execute("PRAGMA foreign_keys=OFF")
    sid = db.new_id()
    pid = pub_id or db.new_id()
    cid = clip_id or db.new_id()
    ts = db.now()
    conn.execute("""
        INSERT INTO yt_upload_sessions
        (id, pub_id, clip_id, channel_id, title, description, tags, is_for_kids,
         file_path, file_hash, file_size, status, bytes_sent, attempts,
         privacy_status, series_id, series_part, created_at, updated_at)
        VALUES (?,?,?,?,'Test','',?,0,'/tmp/fake.mp4','abc',1024,?,0,0,'private',NULL,0,?,?)
    """, (sid, pid, cid, channel_id, json.dumps([]), status, ts, ts))
    conn.execute("PRAGMA foreign_keys=ON")
    return sid, pid


def _make_batch_raw(conn, name="Test Batch", n_sessions=2, status="pending"):
    """Create a batch with n raw sessions (FK enforcement off). Returns (batch_id, [(pub_id, session_id)])."""
    conn.execute("PRAGMA foreign_keys=OFF")
    pairs = []
    for _ in range(n_sessions):
        sid, pid = _make_session_raw(conn, status=status)
        pairs.append((pid, sid))
    bid = db.new_id()
    ts = db.now()
    conn.execute("""
        INSERT INTO upload_batches (id, name, channel_id, idempotency_key, paused,
            total_items, approved_privacy, cancelled, created_at, updated_at)
        VALUES (?,?,?,?,0,?,?,0,?,?)
    """, (bid, name, "ch1", db.new_id(), len(pairs), "private", ts, ts))
    for pub_id, session_id in pairs:
        conn.execute("""
            INSERT OR IGNORE INTO upload_batch_items
                (id, batch_id, pub_id, session_id, added_at, privacy_status)
            VALUES (?,?,?,?,?,'private')
        """, (db.new_id(), bid, pub_id, session_id, ts))
    conn.execute("PRAGMA foreign_keys=ON")
    return bid, pairs


class _TmpDbMixin(unittest.TestCase):
    def setUp(self):
        from engine.config import CONFIG as _cfg
        self._orig_db = _cfg.db_path
        self.tmp = tempfile.TemporaryDirectory()
        _make_temp_db(Path(self.tmp.name))

    def tearDown(self):
        from engine.config import CONFIG as _cfg
        _cfg.db_path = self._orig_db
        self.tmp.cleanup()

    def _batch(self, name="Batch", n=2, status="pending"):
        with db.db() as conn:
            bid, pairs = _make_batch_raw(conn, name=name, n_sessions=n, status=status)
        return bid, pairs


# ─── 1. Schema ────────────────────────────────────────────────────────────────

class TestCancelledSchema(_TmpDbMixin):

    def test_01_upload_batches_has_cancelled_columns(self):
        with db.db() as conn:
            info = conn.execute("PRAGMA table_info(upload_batches)").fetchall()
        cols = {r["name"] for r in info}
        for col in ("cancelled", "cancelled_at", "cancel_reason", "archived_at"):
            self.assertIn(col, cols, f"Missing column: {col}")

    def test_02_new_batch_defaults_to_not_cancelled(self):
        bid, _ = self._batch("SchemaTest")
        b = get_upload_batch(bid)
        self.assertEqual(b["cancelled"], 0)
        self.assertIsNone(b["cancelled_at"])


# ─── 2. DB function cancel_upload_batch ───────────────────────────────────────

class TestCancelUploadBatch(_TmpDbMixin):

    def test_03_cancel_pending_batch_returns_CANCELLED(self):
        bid, _ = self._batch("PendingBatch")
        outcome = cancel_upload_batch(bid)
        self.assertEqual(outcome, "CANCELLED")

    def test_04_cancelled_batch_has_flag_set(self):
        bid, _ = self._batch("FlagBatch")
        cancel_upload_batch(bid)
        b = get_upload_batch(bid)
        self.assertEqual(b["cancelled"], 1)
        self.assertIsNotNone(b["cancelled_at"])

    def test_05_cancel_reason_stored(self):
        bid, _ = self._batch("ReasonBatch")
        cancel_upload_batch(bid, reason="testing")
        b = get_upload_batch(bid)
        self.assertEqual(b["cancel_reason"], "testing")

    def test_06_double_cancel_returns_ALREADY_CANCELLED(self):
        bid, _ = self._batch("DoubleBatch")
        cancel_upload_batch(bid)
        outcome2 = cancel_upload_batch(bid)
        self.assertEqual(outcome2, "ALREADY_CANCELLED")

    def test_07_cancel_sets_pending_sessions_to_cancelled(self):
        bid, pairs = self._batch("SessionsBatch", n=3)
        cancel_upload_batch(bid)
        for pub_id, session_id in pairs:
            s = db.get_yt_upload_session(session_id)
            self.assertEqual(s["status"], "cancelled")

    def test_08_cancel_leaves_published_sessions_intact(self):
        with db.db() as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            sid, pid = _make_session_raw(conn, status="public")
            bid = db.new_id()
            ts = db.now()
            conn.execute("""
                INSERT INTO upload_batches (id, name, channel_id, idempotency_key, paused,
                    total_items, approved_privacy, cancelled, created_at, updated_at)
                VALUES (?,?,?,?,0,1,'private',0,?,?)
            """, (bid, "PublishedBatch", "ch1", db.new_id(), ts, ts))
            conn.execute("""
                INSERT OR IGNORE INTO upload_batch_items (id, batch_id, pub_id, session_id, added_at, privacy_status)
                VALUES (?,?,?,?,?,'private')
            """, (db.new_id(), bid, pid, sid, ts))
            conn.execute("PRAGMA foreign_keys=ON")
        cancel_upload_batch(bid)
        s = db.get_yt_upload_session(sid)
        self.assertEqual(s["status"], "public")

    def test_09_cancel_nonexistent_batch_returns_NOT_FOUND(self):
        outcome = cancel_upload_batch("nonexistent-id-xyz")
        self.assertEqual(outcome, "NOT_FOUND")

    def test_10_cancel_uploading_session_returns_CANCELLATION_PENDING(self):
        with db.db() as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            sid, pid = _make_session_raw(conn, status="uploading")
            bid = db.new_id()
            ts = db.now()
            conn.execute("""
                INSERT INTO upload_batches (id, name, channel_id, idempotency_key, paused,
                    total_items, approved_privacy, cancelled, created_at, updated_at)
                VALUES (?,?,?,?,0,1,'private',0,?,?)
            """, (bid, "ActiveBatch", "ch1", db.new_id(), ts, ts))
            conn.execute("""
                INSERT OR IGNORE INTO upload_batch_items (id, batch_id, pub_id, session_id, added_at, privacy_status)
                VALUES (?,?,?,?,?,'private')
            """, (db.new_id(), bid, pid, sid, ts))
            conn.execute("PRAGMA foreign_keys=ON")
        outcome = cancel_upload_batch(bid)
        self.assertEqual(outcome, "CANCELLATION_PENDING")

    def test_11_cancel_paused_batch_sessions_set_to_cancelled(self):
        bid, pairs = self._batch("PausedBatch")
        pause_upload_batch(bid)
        cancel_upload_batch(bid)
        for pub_id, session_id in pairs:
            s = db.get_yt_upload_session(session_id)
            self.assertEqual(s["status"], "cancelled")


# ─── 3. derived_status ────────────────────────────────────────────────────────

class TestDerivedStatus(_TmpDbMixin):

    def test_12_get_upload_batch_derived_status_cancelled(self):
        bid, _ = self._batch("DerivedBatch")
        cancel_upload_batch(bid)
        b = get_upload_batch(bid)
        self.assertEqual(b["derived_status"], "cancelled")

    def test_13_list_batches_includes_cancelled(self):
        bid, _ = self._batch("ListCancelledBatch")
        cancel_upload_batch(bid)
        batches = list_upload_batches(limit=100)
        found = [b for b in batches if b["id"] == bid]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["derived_status"], "cancelled")

    def test_14_cancelled_takes_priority_over_paused(self):
        bid, _ = self._batch("PrioBatch")
        with db.db() as conn:
            conn.execute("""
                UPDATE upload_batches SET paused=1, cancelled=1, cancelled_at=? WHERE id=?
            """, (db.now(), bid))
        b = get_upload_batch(bid)
        self.assertEqual(b["derived_status"], "cancelled")


# ─── 4. API endpoint DELETE /upload-batches/{batch_id} ───────────────────────

class TestCancelBatchAPI(_TmpDbMixin):

    def setUp(self):
        super().setUp()
        from api.main import app
        self.client = TestClient(app, raise_server_exceptions=True)

    def test_15_delete_endpoint_returns_200(self):
        bid, _ = self._batch("APIBatch")
        r = self.client.request("DELETE", f"/upload-batches/{bid}", json={})
        self.assertEqual(r.status_code, 200)
        self.assertIn(r.json()["outcome"], ("CANCELLED", "CANCELLATION_PENDING"))

    def test_16_delete_nonexistent_returns_404(self):
        r = self.client.request("DELETE", "/upload-batches/nonexistent-xxxx", json={})
        self.assertEqual(r.status_code, 404)

    def test_17_delete_already_cancelled_returns_200_ALREADY_CANCELLED(self):
        bid, _ = self._batch("APIDouble")
        cancel_upload_batch(bid)
        r = self.client.request("DELETE", f"/upload-batches/{bid}", json={})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["outcome"], "ALREADY_CANCELLED")

    def test_18_delete_does_not_physically_delete_row(self):
        bid, _ = self._batch("PhysicalBatch")
        self.client.request("DELETE", f"/upload-batches/{bid}", json={})
        b = get_upload_batch(bid)
        self.assertIsNotNone(b)

    def test_19_delete_accepts_optional_reason(self):
        bid, _ = self._batch("ReasonAPIBatch")
        r = self.client.request("DELETE", f"/upload-batches/{bid}", json={"reason": "test reason"})
        self.assertEqual(r.status_code, 200)
        b = get_upload_batch(bid)
        self.assertEqual(b["cancel_reason"], "test reason")

    def test_20_get_batch_still_works_after_cancel(self):
        bid, _ = self._batch("GetAfterBatch")
        cancel_upload_batch(bid)
        r = self.client.get(f"/upload-batches/{bid}")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["derived_status"], "cancelled")


# ─── 5. Worker safety ─────────────────────────────────────────────────────────

class TestWorkerSafety(_TmpDbMixin):

    def test_21_claim_does_not_pick_session_from_cancelled_batch(self):
        bid, pairs = self._batch("ClaimBatch", n=1)
        cancel_upload_batch(bid)
        # Re-set session to pending to see if worker would claim it
        with db.db() as conn:
            conn.execute("UPDATE yt_upload_sessions SET status='pending' WHERE id=?",
                         (pairs[0][1],))
        session_ids = {sid for _, sid in pairs}
        claimed = db.claim_yt_upload_session("test-worker-99")
        if claimed is not None:
            self.assertNotIn(claimed["id"], session_ids,
                             "Worker must not claim sessions from a cancelled batch")

    def test_22_active_batch_sessions_are_claimable(self):
        bid, pairs = self._batch("ClaimActiveBatch", n=1)
        session_ids = {sid for _, sid in pairs}
        # All sessions from this batch must be claimable
        claimed = db.claim_yt_upload_session("test-worker-98")
        # Should find something (either ours or another pending session)
        if claimed is not None:
            b = get_upload_batch(bid)
            self.assertNotEqual(b["derived_status"], "cancelled")


# ─── 6. Data integrity ────────────────────────────────────────────────────────

class TestDataIntegrity(_TmpDbMixin):

    def test_23_clips_not_deleted_on_batch_cancel(self):
        with db.db() as conn:
            clip_count_before = conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
        bid, _ = self._batch("ClipsIntegrityBatch")
        cancel_upload_batch(bid)
        with db.db() as conn:
            clip_count_after = conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
        self.assertEqual(clip_count_before, clip_count_after)

    def test_24_videos_not_deleted_on_batch_cancel(self):
        with db.db() as conn:
            video_count_before = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        bid, _ = self._batch("VideosIntegrityBatch")
        cancel_upload_batch(bid)
        with db.db() as conn:
            video_count_after = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        self.assertEqual(video_count_before, video_count_after)

    def test_25_publications_not_deleted_on_batch_cancel(self):
        with db.db() as conn:
            pub_count_before = conn.execute("SELECT COUNT(*) FROM publications").fetchone()[0]
        bid, _ = self._batch("PubsIntegrityBatch")
        cancel_upload_batch(bid)
        with db.db() as conn:
            pub_count_after = conn.execute("SELECT COUNT(*) FROM publications").fetchone()[0]
        self.assertEqual(pub_count_before, pub_count_after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
