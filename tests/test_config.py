"""Tests for configuration loading."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from linux_usb_scanner_client.config import ConfigError, load_config, validate_operational_config


class ConfigTests(unittest.TestCase):
    """Configuration parser tests."""

    def test_loads_hex_device_ids_and_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "client.conf"
            path.write_text(
                """
[scanner]
vendor_id = 0x0c2e
product_id = 0x0901

[server]
host = logger.local
port = 55256

[buffer]
database_path = {db}

[logging]
log_file = {log}
log_level = info
""".format(
                    db=Path(temp_dir) / "queue.sqlite3",
                    log=Path(temp_dir) / "client.log",
                ),
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(config.scanner.vendor_id, 0x0C2E)
        self.assertEqual(config.scanner.product_id, 0x0901)
        self.assertEqual(config.server.host, "logger.local")
        self.assertEqual(config.server.port, 55256)
        self.assertEqual(config.buffer.storage_min_free_mb, 1024)
        self.assertEqual(config.logging.log_level, "INFO")
        self.assertEqual(validate_operational_config(config), [])

    def test_requires_valid_port(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "client.conf"
            path.write_text(
                """
[scanner]
device_path = /dev/input/event9

[server]
host = 127.0.0.1
port = 70000
""",
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_config(path)

    def test_warns_without_scanner_matcher(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "client.conf"
            path.write_text(
                """
[server]
host = 127.0.0.1
""",
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertTrue(validate_operational_config(config))


if __name__ == "__main__":
    unittest.main()
