"""Tests for degraded-state alert monitor behavior."""

from __future__ import annotations

import io
import subprocess
import sys
import unittest
from unittest.mock import patch

from linux_usb_scanner_client.alert_monitor import (
    AlertMonitorError,
    BeepPlayer,
    choose_alert,
)
from linux_usb_scanner_client.config import AlertingConfig
from linux_usb_scanner_client.health import HealthReport


class AlertMonitorTests(unittest.TestCase):
    """Alert monitor tests."""

    def test_app_not_running_has_highest_priority(self) -> None:
        report = _report(service_running=False, scanner_available=False)
        alert = choose_alert(report, AlertingConfig())

        self.assertIsNotNone(alert)
        self.assertEqual(alert.name, "app_not_running")
        self.assertEqual(alert.beep_count, 5)

    def test_scanner_unavailable_has_second_priority(self) -> None:
        report = _report(service_running=True, scanner_available=False)
        alert = choose_alert(report, AlertingConfig())

        self.assertIsNotNone(alert)
        self.assertEqual(alert.name, "scanner_unavailable")
        self.assertEqual(alert.beep_count, 3)

    def test_server_unavailable_has_one_beep(self) -> None:
        report = _report(
            service_running=True,
            scanner_available=True,
            scanner_state="connected",
            server_connected=False,
            server_state="unavailable",
        )
        alert = choose_alert(report, AlertingConfig())

        self.assertIsNotNone(alert)
        self.assertEqual(alert.name, "server_unavailable")
        self.assertEqual(alert.beep_count, 1)

    def test_healthy_report_has_no_alert(self) -> None:
        report = _report(
            service_running=True,
            scanner_available=True,
            scanner_state="connected",
            server_connected=True,
            server_state="connected",
        )
        alert = choose_alert(report, AlertingConfig())

        self.assertIsNone(alert)

    def test_stdout_backend_writes_bell_character(self) -> None:
        player = BeepPlayer(AlertingConfig(backend="stdout", beep_gap_ms=0))
        original_stdout = sys.stdout
        try:
            captured = io.StringIO()
            sys.stdout = captured
            player.play_pattern(3)
        finally:
            sys.stdout = original_stdout

        self.assertEqual(captured.getvalue(), "\a\a\a")

    def test_auto_backend_prefers_audio_card(self) -> None:
        player = _RecordingBeepPlayer(AlertingConfig(backend="auto"))

        player.play_one_beep()

        self.assertEqual(player.backends, ["aplay"])

    def test_auto_backend_uses_system_speaker_after_audio_card_failure(self) -> None:
        player = _RecordingBeepPlayer(
            AlertingConfig(backend="auto"),
            failing_backends={"aplay"},
        )

        player.play_one_beep()

        self.assertEqual(player.backends, ["aplay", "beep"])

    def test_auto_backend_keeps_console_bell_as_final_fallback(self) -> None:
        player = _RecordingBeepPlayer(
            AlertingConfig(backend="auto"),
            failing_backends={"beep", "aplay"},
        )

        player.play_one_beep()

        self.assertEqual(player.backends, ["aplay", "beep", "console_bell"])

    def test_auto_backend_reuses_working_backend_for_pattern(self) -> None:
        player = _RecordingBeepPlayer(
            AlertingConfig(backend="auto", beep_gap_ms=0),
            failing_backends={"aplay"},
        )

        player.play_pattern(3)

        self.assertEqual(player.backends, ["aplay", "beep", "beep", "beep"])

    def test_beep_backend_tolerates_empty_error_nonzero_exit(self) -> None:
        player = BeepPlayer(AlertingConfig(backend="beep", beep_command="/usr/bin/beep"))
        completed = subprocess.CompletedProcess(
            args=["/usr/bin/beep"],
            returncode=1,
            stdout="",
            stderr="",
        )

        with (
            self.assertLogs(
                "linux_usb_scanner_client.alert_monitor",
                level="WARNING",
            ) as logs,
            patch(
                "linux_usb_scanner_client.alert_monitor.shutil.which",
                return_value="/usr/bin/beep",
            ),
            patch(
                "linux_usb_scanner_client.alert_monitor.subprocess.run",
                return_value=completed,
            ),
        ):
            player.play_one_beep()
            player.play_one_beep()

        self.assertEqual(len(logs.output), 1)
        self.assertIn("best-effort system-speaker beep", logs.output[0])

    def test_beep_backend_raises_when_command_reports_error(self) -> None:
        player = BeepPlayer(AlertingConfig(backend="beep", beep_command="/usr/bin/beep"))
        completed = subprocess.CompletedProcess(
            args=["/usr/bin/beep"],
            returncode=1,
            stdout="",
            stderr="speaker unavailable",
        )

        with (
            patch(
                "linux_usb_scanner_client.alert_monitor.shutil.which",
                return_value="/usr/bin/beep",
            ),
            patch(
                "linux_usb_scanner_client.alert_monitor.subprocess.run",
                return_value=completed,
            ),
        ):
            with self.assertRaisesRegex(AlertMonitorError, "speaker unavailable"):
                player.play_one_beep()


class _RecordingBeepPlayer(BeepPlayer):
    """Capture backend attempts without touching host audio devices."""

    def __init__(
        self, config: AlertingConfig, failing_backends: set[str] | None = None
    ) -> None:
        super().__init__(config)
        self.backends: list[str] = []
        self.failing_backends = failing_backends or set()

    def _play_backend(self, backend: str) -> None:
        self.backends.append(backend)
        if backend in self.failing_backends:
            raise AlertMonitorError(f"{backend} unavailable")


def _report(
    *,
    service_running: bool,
    scanner_available: bool,
    scanner_state: str = "unavailable",
    server_connected: bool = False,
    server_state: str = "unknown",
) -> HealthReport:
    return HealthReport(
        overall_status="ok",
        config_path="/etc/linux-usb-scanner-client.conf",
        service_running=service_running,
        heartbeat_age_seconds=1.0 if service_running else None,
        scanner_state=scanner_state,
        scanner_available=scanner_available,
        scanner_device_path="/dev/input/event4" if scanner_available else "",
        scanner_device_name="Honeywell USB Keyboard" if scanner_available else "",
        scanner_state_updated_at="2026-06-20T12:00:00Z",
        server_state=server_state,
        server_connected=server_connected,
        server_target="10.10.10.5:55256",
        queue={
            "pending_count": 0,
            "oldest_pending_at": None,
            "newest_pending_at": None,
            "max_attempts": 0,
            "last_error": None,
            "last_error_at": None,
            "sent_count": 0,
        },
        storage={
            "path": "/var/lib/linux-usb-scanner-client",
            "total_bytes": 100,
            "used_bytes": 10,
            "free_bytes": 90,
            "database_bytes": 10,
            "min_free_bytes": 25,
            "low_space": False,
        },
        update_state="disabled",
        update_checked_at=None,
        update_remote_version=None,
        update_remote_commit=None,
        update_message=None,
        update_error=None,
        monitor_state="healthy",
        monitor_alert=None,
        monitor_alert_beeps=None,
        monitor_checked_at=None,
        monitor_error=None,
        last_scan_at=None,
        last_scan_length=None,
        last_delivery_at=None,
        last_error=None,
        warnings=[],
    )


if __name__ == "__main__":
    unittest.main()
