"""Tests for queue storage capacity reporting."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from linux_usb_scanner_client.storage_monitor import build_storage_status


class StorageMonitorTests(unittest.TestCase):
    """Storage capacity tests."""

    def test_reports_database_footprint_and_low_space(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "queue.sqlite3"
            database_path.write_bytes(b"abc")
            status = build_storage_status(database_path, min_free_mb=10**12)

        self.assertEqual(status.database_bytes, 3)
        self.assertTrue(status.low_space)
        self.assertGreater(status.total_bytes, 0)


if __name__ == "__main__":
    unittest.main()
