"""Tests for application logging configuration."""

from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from linux_usb_scanner_client.config import LoggingConfig
from linux_usb_scanner_client.logging_setup import configure_logging


class LoggingSetupTests(unittest.TestCase):
    """Logging setup tests."""

    def tearDown(self) -> None:
        logging.shutdown()
        logging.basicConfig(handlers=[logging.NullHandler()], force=True)

    def test_file_logging_obeys_configured_log_level(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "client.log"
            configure_logging(
                LoggingConfig(log_file=log_path, log_level="WARNING"),
                to_stderr=False,
            )

            logger = logging.getLogger("linux_usb_scanner_client.test")
            logger.info("hidden info message")
            logger.warning("visible warning message")
            logging.shutdown()

            log_text = log_path.read_text(encoding="utf-8")

        self.assertNotIn("hidden info message", log_text)
        self.assertIn("visible warning message", log_text)


if __name__ == "__main__":
    unittest.main()
