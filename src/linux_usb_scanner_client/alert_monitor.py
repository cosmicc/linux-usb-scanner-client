"""Independent degraded-state beep monitor."""

from __future__ import annotations

import io
import logging
import math
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
import wave
from dataclasses import dataclass

from .config import AlertingConfig, AppConfig
from .health import HealthReport, build_health_report
from .storage import ScanStore
from .timeutil import utc_timestamp

LOGGER = logging.getLogger(__name__)
AUTO_BEEP_BACKENDS = ("aplay", "beep", "console_bell")


class AlertMonitorError(RuntimeError):
    """Raised when the monitor cannot play a beep pattern."""


@dataclass(frozen=True)
class AlertPattern:
    """One active monitor alert pattern."""

    name: str
    message: str
    beep_count: int
    priority: int


def choose_alert(report: HealthReport, alerting: AlertingConfig) -> AlertPattern | None:
    """Choose the highest-priority active alert for a health report."""

    if not alerting.enabled:
        return None

    if not report.service_running:
        return AlertPattern(
            name="app_not_running",
            message="App service is not running or heartbeat is stale.",
            beep_count=alerting.app_not_running_beeps,
            priority=1,
        )

    if not report.scanner_available or report.scanner_state != "connected":
        return AlertPattern(
            name="scanner_unavailable",
            message="USB scanner is not detected.",
            beep_count=alerting.scanner_unavailable_beeps,
            priority=2,
        )

    if not report.server_connected or report.server_state != "connected":
        return AlertPattern(
            name="server_unavailable",
            message="Industrial Scanner Logger server is not contactable.",
            beep_count=alerting.server_unavailable_beeps,
            priority=3,
        )

    return None


def pattern_for_name(name: str, alerting: AlertingConfig) -> AlertPattern:
    """Return a configured pattern by alert name."""

    patterns = {
        "app_not_running": AlertPattern(
            name="app_not_running",
            message="App service is not running or heartbeat is stale.",
            beep_count=alerting.app_not_running_beeps,
            priority=1,
        ),
        "scanner_unavailable": AlertPattern(
            name="scanner_unavailable",
            message="USB scanner is not detected.",
            beep_count=alerting.scanner_unavailable_beeps,
            priority=2,
        ),
        "server_unavailable": AlertPattern(
            name="server_unavailable",
            message="Industrial Scanner Logger server is not contactable.",
            beep_count=alerting.server_unavailable_beeps,
            priority=3,
        ),
    }
    try:
        return patterns[name]
    except KeyError as exc:
        raise AlertMonitorError(f"Unknown alert pattern: {name}") from exc


class BeepPlayer:
    """Play quick beep patterns through a configured backend."""

    def __init__(self, config: AlertingConfig) -> None:
        self.config = config
        self._auto_backend: str | None = None
        self._warned_empty_beep_failure = False

    def play_pattern(self, beep_count: int) -> None:
        """Play a configured number of quick beeps."""

        for index in range(beep_count):
            self.play_one_beep()
            if index < beep_count - 1 and self.config.beep_gap_ms > 0:
                time.sleep(self.config.beep_gap_ms / 1000)

    def play_one_beep(self) -> None:
        """Play one quick beep using the selected backend."""

        backend = self.config.backend
        if backend == "auto":
            self._play_auto_backend()
            return
        self._play_backend(backend)

    def _play_auto_backend(self) -> None:
        """Play one beep using the first working backend and remember it."""

        candidates = list(AUTO_BEEP_BACKENDS)
        if self._auto_backend is not None:
            candidates = [
                self._auto_backend,
                *(backend for backend in candidates if backend != self._auto_backend),
            ]

        errors = []
        for candidate in candidates:
            try:
                self._play_backend(candidate)
                self._auto_backend = candidate
                return
            except AlertMonitorError as exc:
                if candidate == self._auto_backend:
                    self._auto_backend = None
                errors.append(f"{candidate}: {exc}")
        raise AlertMonitorError("; ".join(errors))

    def _play_backend(self, backend: str) -> None:
        if backend == "aplay":
            self._play_aplay()
            return
        if backend == "beep":
            self._play_beep_command()
            return
        if backend == "console_bell":
            self._play_console_bell()
            return
        if backend == "stdout":
            sys.stdout.write("\a")
            sys.stdout.flush()
            return
        raise AlertMonitorError(f"Unsupported beep backend: {backend}")

    def _play_aplay(self) -> None:
        command = _resolve_command(self.config.aplay_command)
        if command is None:
            raise AlertMonitorError(f"aplay command not found: {self.config.aplay_command}")
        completed = subprocess.run(
            [command, "-q", "-"],
            input=_wav_tone(self.config.tone_hz, self.config.beep_duration_ms),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            error = completed.stderr.decode(errors="replace").strip()
            raise AlertMonitorError(error or "aplay failed")

    def _play_beep_command(self) -> None:
        command = _resolve_command(self.config.beep_command)
        if command is None:
            raise AlertMonitorError(f"beep command not found: {self.config.beep_command}")
        completed = subprocess.run(
            [
                command,
                "-f",
                str(self.config.tone_hz),
                "-l",
                str(self.config.beep_duration_ms),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            error = (completed.stderr or completed.stdout).strip()
            if error:
                raise AlertMonitorError(error)
            if not self._warned_empty_beep_failure:
                LOGGER.warning(
                    "beep command exited with status %s but produced no error "
                    "output; treating it as a best-effort system-speaker beep",
                    completed.returncode,
                )
                self._warned_empty_beep_failure = True

    def _play_console_bell(self) -> None:
        try:
            with open(self.config.console_device, "wb", buffering=0) as console:
                console.write(b"\a")
        except OSError as exc:
            raise AlertMonitorError(str(exc)) from exc


class AlertMonitor:
    """Run continuous degraded-state beep alerts."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.store = ScanStore(config.buffer.database_path)
        self.beep_player = BeepPlayer(config.alerting)
        self.stop_event = threading.Event()

    def run(self, *, once: bool = False) -> int:
        """Run the monitor loop until stopped."""

        self.store.initialize()
        self._install_signal_handlers()

        while not self.stop_event.is_set():
            try:
                alert = self.run_once()
                if once:
                    return 0
                if alert is not None:
                    self.beep_player.play_pattern(alert.beep_count)
            except Exception as exc:
                LOGGER.exception("Alert monitor iteration failed")
                self._set_status_safely(
                    {
                        "monitor_state": "error",
                        "monitor_error": str(exc)[:500],
                        "monitor_last_check_at": utc_timestamp(),
                    }
                )
            self.stop_event.wait(self.config.alerting.interval_seconds)
        return 0

    def run_once(self) -> AlertPattern | None:
        """Evaluate health once, persist monitor state, and return active alert."""

        report = build_health_report(self.config)
        alert = choose_alert(report, self.config.alerting)
        timestamp = utc_timestamp()
        if not self.config.alerting.enabled:
            self._set_status(
                {
                    "monitor_state": "disabled",
                    "monitor_alert": "",
                    "monitor_alert_message": "",
                    "monitor_alert_beeps": "",
                    "monitor_error": "",
                    "monitor_last_check_at": timestamp,
                }
            )
            return None
        if alert is None:
            self._set_status(
                {
                    "monitor_state": "healthy",
                    "monitor_alert": "",
                    "monitor_alert_message": "",
                    "monitor_alert_beeps": "",
                    "monitor_error": "",
                    "monitor_last_check_at": timestamp,
                }
            )
            return None
        self._set_status(
            {
                "monitor_state": "alerting",
                "monitor_alert": alert.name,
                "monitor_alert_message": alert.message,
                "monitor_alert_beeps": str(alert.beep_count),
                "monitor_error": "",
                "monitor_last_check_at": timestamp,
            }
        )
        return alert

    def test_beep(self, pattern_name: str) -> None:
        """Play one configured alert pattern for operator validation."""

        pattern = pattern_for_name(pattern_name, self.config.alerting)
        self.beep_player.play_pattern(pattern.beep_count)

    def _install_signal_handlers(self) -> None:
        def request_stop(signum: int, _frame: object) -> None:
            LOGGER.info("Received signal %s; stopping alert monitor", signum)
            self.stop_event.set()

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)

    def _set_status(self, values: dict[str, str]) -> None:
        self.store.set_status_many(values)

    def _set_status_safely(self, values: dict[str, str]) -> None:
        try:
            self._set_status(values)
        except Exception:
            LOGGER.exception("Unable to persist monitor status")


def _resolve_command(command: str) -> str | None:
    if "/" in command:
        return command if shutil.which(command) else None
    return shutil.which(command)


def _wav_tone(tone_hz: int, duration_ms: int) -> bytes:
    sample_rate = 44100
    total_frames = max(1, int(sample_rate * duration_ms / 1000))
    amplitude = int(32767 * 0.35)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for frame_index in range(total_frames):
            sample = int(
                amplitude
                * math.sin(2 * math.pi * tone_hz * frame_index / sample_rate)
            )
            frames.extend(struct.pack("<h", sample))
        wav_file.writeframes(bytes(frames))
    return buffer.getvalue()
