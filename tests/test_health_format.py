"""Tests for health output formatting."""

from __future__ import annotations

import unittest

from linux_usb_scanner_client.health import HealthReport, format_health_text


class HealthFormatTests(unittest.TestCase):
    """Health output formatting tests."""

    def test_health_text_is_colored_by_default(self) -> None:
        report = _sample_report(overall_status="ok")

        output = format_health_text(report)

        self.assertIn("\033[", output)
        self.assertIn("Overall", output)

    def test_health_text_can_disable_color(self) -> None:
        report = _sample_report(overall_status="degraded")

        output = format_health_text(report, use_color=False)

        self.assertNotIn("\033[", output)
        self.assertIn("Overall: degraded", output)
        self.assertIn("Queue pending: 3", output)


def _sample_report(overall_status: str) -> HealthReport:
    return HealthReport(
        overall_status=overall_status,
        config_path="/etc/linux-usb-scanner-client.conf",
        service_running=True,
        heartbeat_age_seconds=1.2,
        scanner_state="connected",
        scanner_available=True,
        scanner_device_path="/dev/input/event4",
        scanner_device_name="Honeywell USB Keyboard",
        scanner_state_updated_at="2026-06-20T12:00:00Z",
        server_state="connected",
        server_connected=True,
        server_target="10.10.10.5:55256",
        queue={
            "pending_count": 3,
            "oldest_pending_at": "2026-06-20T12:01:00Z",
            "newest_pending_at": "2026-06-20T12:02:00Z",
            "max_attempts": 1,
            "last_error": None,
            "last_error_at": None,
            "sent_count": 10,
        },
        storage={
            "path": "/var/lib/linux-usb-scanner-client",
            "total_bytes": 100,
            "used_bytes": 50,
            "free_bytes": 50,
            "database_bytes": 10,
            "min_free_bytes": 25,
            "low_space": False,
        },
        update_state="up_to_date",
        update_checked_at="2026-06-20T12:04:00Z",
        update_remote_version="0.1.1",
        update_remote_commit="abcdef123456",
        update_message="Installed version is current.",
        update_error=None,
        monitor_state="healthy",
        monitor_alert=None,
        monitor_alert_beeps=None,
        monitor_checked_at="2026-06-20T12:05:00Z",
        monitor_error=None,
        last_scan_at="2026-06-20T12:02:00Z",
        last_scan_length=34,
        last_delivery_at="2026-06-20T12:03:00Z",
        last_error=None,
        warnings=[],
    )


if __name__ == "__main__":
    unittest.main()
