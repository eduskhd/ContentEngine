"""
Tests for clip packages and upload batch endpoints.
No real YouTube uploads — all external calls are mocked.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
from engine import database as db


def _make_temp_db(tmp_path):
    from engine.config import CONFIG
    CONFIG.db_path = str(tmp_path / "test.sqlite")
    db.init_db()
    return CONFIG.db_path


class TestPackages(unittest.TestCase):
    def setUp(self):
        from engine.config import CONFIG as _cfg
        self._original_db_path = _cfg.db_path
        self.tmp = tempfile.TemporaryDirectory()
        _make_temp_db(Path(self.tmp.name))

    def tearDown(self):
        from engine.config import CONFIG as _cfg
        _cfg.db_path = self._original_db_path
        self.tmp.cleanup()

    def test_create_and_list_package(self):
        pid = db.create_package("My Pack", "desc")
        self.assertIsNotNone(pid)
        packs = db.list_packages()
        self.assertEqual(len(packs), 1)
        self.assertEqual(packs[0]["name"], "My Pack")
        self.assertEqual(packs[0]["item_count"], 0)

    def test_add_and_remove_items(self):
        pid = db.create_package("Pack A")
        added = db.add_package_items(pid, ["pub1", "pub2", "pub3"])
        self.assertEqual(added, 3)
        pkg = db.get_package(pid)
        self.assertEqual(len(pkg["items"]), 3)

        removed = db.remove_package_items(pid, ["pub1"])
        self.assertEqual(removed, 1)
        pkg = db.get_package(pid)
        self.assertEqual(len(pkg["items"]), 2)

    def test_duplicate_items_ignored(self):
        pid = db.create_package("Pack B")
        db.add_package_items(pid, ["pub1"])
        added2 = db.add_package_items(pid, ["pub1"])
        self.assertEqual(added2, 0)
        pkg = db.get_package(pid)
        self.assertEqual(len(pkg["items"]), 1)

    def test_delete_package(self):
        pid = db.create_package("Del Pack")
        db.add_package_items(pid, ["pub1", "pub2"])
        db.delete_package(pid)
        self.assertIsNone(db.get_package(pid))
        packs = db.list_packages()
        self.assertEqual(len(packs), 0)

    def test_update_package(self):
        pid = db.create_package("Old Name")
        db.update_package(pid, name="New Name", description="new desc")
        pkg = db.get_package(pid)
        self.assertEqual(pkg["name"], "New Name")
        self.assertEqual(pkg["description"], "new desc")


class TestUploadBatches(unittest.TestCase):
    def setUp(self):
        from engine.config import CONFIG as _cfg
        self._original_db_path = _cfg.db_path
        self.tmp = tempfile.TemporaryDirectory()
        _make_temp_db(Path(self.tmp.name))

    def tearDown(self):
        from engine.config import CONFIG as _cfg
        _cfg.db_path = self._original_db_path
        self.tmp.cleanup()

    def _make_batch(self, key="idem-001", pairs=None):
        if pairs is None:
            pairs = [("pub1", "sess1"), ("pub2", "sess2")]
        return db.create_upload_batch("Test Batch", "ch-123", key, pairs)

    def test_create_and_get_batch(self):
        bid = self._make_batch()
        b = db.get_upload_batch(bid)
        self.assertIsNotNone(b)
        self.assertEqual(b["name"], "Test Batch")
        self.assertEqual(b["total_items"], 2)
        self.assertEqual(len(b["items"]), 2)

    def test_idempotency_key_dedup(self):
        self._make_batch("same-key")
        existing = db.get_batch_by_idempotency("same-key")
        self.assertIsNotNone(existing)
        # A second create with the same key should be caught by the caller
        existing2 = db.get_batch_by_idempotency("same-key")
        self.assertEqual(existing["id"], existing2["id"])

    def _insert_session(self, sess_id, pub_id, clip_id, status):
        conn = sqlite3.connect(db.CONFIG.db_path, timeout=10)
        conn.execute("PRAGMA foreign_keys=OFF")
        ts = db.now()
        conn.execute(
            "INSERT INTO yt_upload_sessions (id,pub_id,clip_id,channel_id,status,"
            "bytes_sent,attempts,created_at,updated_at) VALUES (?,?,?,'ch',?,0,0,?,?)",
            (sess_id, pub_id, clip_id, status, ts, ts)
        )
        conn.commit()
        conn.close()

    def test_pause_and_resume(self):
        self._insert_session('sess1', 'p1', 'c1', 'pending')

        bid = db.create_upload_batch("Pausable", "ch", "pause-key", [("p1", "sess1")])
        db.pause_upload_batch(bid)

        b = db.get_upload_batch(bid)
        self.assertEqual(b["paused"], 1)

        with db.db() as conn:
            row = conn.execute("SELECT status FROM yt_upload_sessions WHERE id='sess1'").fetchone()
        self.assertEqual(row["status"], "paused")

        db.resume_upload_batch(bid)
        b2 = db.get_upload_batch(bid)
        self.assertEqual(b2["paused"], 0)

        with db.db() as conn:
            row2 = conn.execute("SELECT status FROM yt_upload_sessions WHERE id='sess1'").fetchone()
        self.assertEqual(row2["status"], "pending")

    def test_retry_errors(self):
        self._insert_session('sessE', 'pE', 'cE', 'error')

        bid = db.create_upload_batch("Retry Batch", "ch", "retry-key", [("pE", "sessE")])
        db.retry_batch_errors(bid)

        with db.db() as conn:
            row = conn.execute("SELECT status, attempts FROM yt_upload_sessions WHERE id='sessE'").fetchone()
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["attempts"], 0)

    def test_batch_derived_status_active(self):
        self._insert_session('sA', 'pA', 'cA', 'uploading')
        bid = db.create_upload_batch("Active", "ch", "active-key", [("pA", "sA")])
        b = db.get_upload_batch(bid)
        self.assertEqual(b["derived_status"], "active")

    def test_batch_derived_status_done(self):
        self._insert_session('sD', 'pD', 'cD', 'private')
        bid = db.create_upload_batch("Done", "ch", "done-key", [("pD", "sD")])
        b = db.get_upload_batch(bid)
        self.assertEqual(b["derived_status"], "done")


if __name__ == "__main__":
    unittest.main()
