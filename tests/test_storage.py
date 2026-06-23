"""Tests for persistent queue storage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from linux_usb_scanner_client.storage import ScanStore
from linux_usb_scanner_client.timeutil import parse_utc_timestamp


class StorageTests(unittest.TestCase):
    """SQLite queue tests."""

    def test_enqueue_fetch_mark_sent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ScanStore(Path(temp_dir) / "queue.sqlite3")
            store.initialize()
            scan_id = store.enqueue_scan("1234567890")

            scan = store.fetch_next_due()
            self.assertIsNotNone(scan)
            self.assertEqual(scan.id, scan_id)
            self.assertEqual(scan.barcode, "1234567890")
            self.assertTrue(scan.captured_at.endswith("Z"))
            self.assertIsNotNone(parse_utc_timestamp(scan.captured_at))

            store.mark_sent(scan_id)
            self.assertIsNone(store.fetch_next_due())
            summary = store.queue_summary()

        self.assertEqual(summary.pending_count, 0)
        self.assertEqual(summary.sent_count, 1)

    def test_failed_scan_remains_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ScanStore(Path(temp_dir) / "queue.sqlite3")
            store.initialize()
            scan_id = store.enqueue_scan("1234567890")
            store.mark_failed(scan_id, "connection refused", retry_delay_seconds=0.01)

            summary = store.queue_summary()

        self.assertEqual(summary.pending_count, 1)
        self.assertEqual(summary.max_attempts, 1)
        self.assertEqual(summary.last_error, "connection refused")

    def test_initialize_preserves_existing_pending_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "queue.sqlite3"
            first_store = ScanStore(database_path)
            first_store.initialize()
            first_store.enqueue_scan("1234567890", captured_at="2026-06-23T01:00:00Z")

            second_store = ScanStore(database_path)
            second_store.initialize()
            summary = second_store.queue_summary()
            scan = second_store.fetch_next_due(now="2026-06-23T01:01:00Z")

        self.assertEqual(summary.pending_count, 1)
        self.assertEqual(summary.oldest_pending_at, "2026-06-23T01:00:00Z")
        self.assertIsNotNone(scan)
        self.assertEqual(scan.barcode, "1234567890")


if __name__ == "__main__":
    unittest.main()
