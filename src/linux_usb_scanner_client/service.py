"""Long-running scanner capture and TCP delivery service."""

from __future__ import annotations

import logging
import os
import select
import signal
import threading
import time
from dataclasses import dataclass, field

from .config import AppConfig, validate_operational_config
from .device import (
    DeviceError,
    categorize_key_event,
    find_matching_devices,
    is_key_event,
    open_input_device,
)
from .keyboard import KeyboardDecoder, ScanAccumulator
from .storage import ScanStore
from .storage_monitor import build_storage_status
from .tcp_sender import TcpScanSender, TcpSenderError
from .timeutil import utc_timestamp

LOGGER = logging.getLogger(__name__)


@dataclass
class RuntimeState:
    """Thread-safe runtime scanner state shared with the delivery worker."""

    scanner_available: bool = False
    scanner_state: str = "starting"
    scanner_device_path: str = ""
    scanner_device_name: str = ""
    last_error: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)

    def update(
        self,
        *,
        available: bool,
        state: str,
        device_path: str = "",
        device_name: str = "",
        last_error: str = "",
    ) -> None:
        """Update the scanner status atomically."""

        with self.lock:
            self.scanner_available = available
            self.scanner_state = state
            self.scanner_device_path = device_path
            self.scanner_device_name = device_name
            self.last_error = last_error

    def snapshot(self) -> dict[str, str | bool]:
        """Return a copy of the scanner status."""

        with self.lock:
            return {
                "scanner_available": self.scanner_available,
                "scanner_state": self.scanner_state,
                "scanner_device_path": self.scanner_device_path,
                "scanner_device_name": self.scanner_device_name,
                "last_error": self.last_error,
            }


class ScannerClientService:
    """Coordinate input-device scanning, persistent buffering, and TCP delivery."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.store = ScanStore(config.buffer.database_path)
        self.stop_event = threading.Event()
        self.runtime_state = RuntimeState()
        self.delivery_thread = threading.Thread(
            target=self._delivery_loop,
            name="delivery-worker",
            daemon=True,
        )
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="heartbeat-worker",
            daemon=True,
        )

    def run(self) -> int:
        """Run the service until SIGTERM, SIGINT, or an unrecoverable error."""

        self.store.initialize()
        self.store.set_status_many(
            {
                "service_started_at": utc_timestamp(),
                "service_pid": str(os.getpid()),
                "config_path": str(self.config.path),
                "server_host": self.config.server.host,
                "server_port": str(self.config.server.port),
            }
        )

        warnings = validate_operational_config(self.config)
        if warnings:
            LOGGER.warning("Operational config warnings: %s", "; ".join(warnings))

        self._install_signal_handlers()
        self.delivery_thread.start()
        self.heartbeat_thread.start()

        try:
            self._scanner_loop()
        finally:
            self.stop_event.set()
            self.delivery_thread.join(timeout=10)
            self.heartbeat_thread.join(timeout=5)
            self.store.set_status_many(
                {
                    "scanner_state": "stopped",
                    "scanner_available": "false",
                    "server_state": "stopped",
                    "server_connected": "false",
                    "service_stopped_at": utc_timestamp(),
                }
            )
        return 0

    def _install_signal_handlers(self) -> None:
        def request_stop(signum: int, _frame: object) -> None:
            LOGGER.info("Received signal %s; stopping", signum)
            self.stop_event.set()

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)

    def _scanner_loop(self) -> None:
        if not self.config.scanner.has_matcher:
            self.runtime_state.update(
                available=False,
                state="misconfigured",
                last_error="scanner matcher is not configured",
            )
            self._persist_scanner_state()

        while not self.stop_event.is_set():
            if not self.config.scanner.has_matcher:
                time.sleep(self.config.scanner.reconnect_interval)
                continue

            try:
                matches = find_matching_devices(self.config.scanner)
            except DeviceError as exc:
                self.runtime_state.update(
                    available=False,
                    state="device_error",
                    last_error=str(exc),
                )
                self._persist_scanner_state()
                LOGGER.error("Unable to inspect input devices: %s", exc)
                time.sleep(self.config.scanner.reconnect_interval)
                continue
            except Exception as exc:
                self.runtime_state.update(
                    available=False,
                    state="device_error",
                    last_error=str(exc),
                )
                self._persist_scanner_state_safely()
                LOGGER.exception("Unexpected input-device discovery error")
                time.sleep(self.config.scanner.reconnect_interval)
                continue

            if not matches:
                self.runtime_state.update(available=False, state="unavailable")
                self._persist_scanner_state()
                time.sleep(self.config.scanner.reconnect_interval)
                continue

            device_info = matches[0]
            try:
                self._read_device(device_info.path, device_info.name)
            except OSError as exc:
                self.runtime_state.update(
                    available=False,
                    state="unavailable",
                    last_error=str(exc),
                )
                self._persist_scanner_state()
                LOGGER.warning(
                    "Scanner device unavailable path=%s error=%s",
                    device_info.path,
                    exc,
                )
                time.sleep(self.config.scanner.reconnect_interval)
            except Exception as exc:
                self.runtime_state.update(
                    available=False,
                    state="scanner_error",
                    last_error=str(exc),
                )
                self._persist_scanner_state_safely()
                LOGGER.exception("Unexpected scanner read error path=%s", device_info.path)
                time.sleep(self.config.scanner.reconnect_interval)

    def _read_device(self, path: str, name: str) -> None:
        decoder = KeyboardDecoder()
        accumulator = ScanAccumulator(
            max_chars=self.config.scanner.max_scan_chars,
            send_empty_scans=self.config.scanner.send_empty_scans,
        )
        device = open_input_device(path)
        grabbed = False
        try:
            if self.config.scanner.grab_device:
                device.grab()
                grabbed = True

            self.runtime_state.update(
                available=True,
                state="connected",
                device_path=path,
                device_name=name,
            )
            self._persist_scanner_state()
            LOGGER.info("Scanner device connected path=%s name=%s", path, name)

            while not self.stop_event.is_set():
                readable, _, _ = select.select([device.fd], [], [], 0.5)
                if not readable:
                    continue
                for event in device.read():
                    if not is_key_event(event):
                        continue
                    key_event = categorize_key_event(event)
                    character = decoder.feed_key(key_event.keycode, key_event.keystate)
                    if character is None:
                        continue
                    completed = accumulator.feed_character(character)
                    if completed is None:
                        continue
                    captured_at = utc_timestamp()
                    scan_id = self.store.enqueue_scan(completed.barcode, captured_at)
                    self.store.set_status("last_scan_id", str(scan_id))
                    LOGGER.info(
                        "Queued scan id=%s length=%s",
                        scan_id,
                        completed.length,
                    )
        finally:
            if grabbed:
                try:
                    device.ungrab()
                except OSError:
                    pass
            device.close()

    def _delivery_loop(self) -> None:
        sender = TcpScanSender(self.config.server)
        last_cleanup = 0.0

        while not self.stop_event.is_set():
            state = self.runtime_state.snapshot()
            if not state["scanner_available"]:
                sender.disconnect()
                reason = str(state["scanner_state"])
                self.store.set_status_many(
                    {
                        "server_state": f"not_attempted_scanner_{reason}",
                        "server_connected": "false",
                    }
                )
                time.sleep(self.config.server.poll_interval)
                continue

            try:
                if not sender.connected:
                    sender.connect()
                    self.store.set_status_many(
                        {
                            "server_state": "connected",
                            "server_connected": "true",
                            "last_server_connect_at": utc_timestamp(),
                        }
                    )
                    LOGGER.info(
                        "Connected to scanner logger host=%s port=%s",
                        self.config.server.host,
                        self.config.server.port,
                    )

                scan = self.store.fetch_next_due()
                if scan is None:
                    now = time.monotonic()
                    if now - last_cleanup > 3600:
                        removed = self.store.cleanup_sent(
                            self.config.buffer.sent_retention_days
                        )
                        if removed:
                            LOGGER.info("Cleaned up sent scan rows count=%s", removed)
                        last_cleanup = now
                    time.sleep(self.config.server.poll_interval)
                    continue

                sender.send_scan(scan.barcode)
                self.store.mark_sent(scan.id)
                self.store.set_status_many(
                    {
                        "server_state": "connected",
                        "server_connected": "true",
                    }
                )
                LOGGER.info(
                    "Delivered queued scan id=%s attempts=%s",
                    scan.id,
                    scan.attempts,
                )
            except TcpSenderError as exc:
                sender.disconnect()
                error = str(exc)
                self.store.set_status_many(
                    {
                        "server_state": "unavailable",
                        "server_connected": "false",
                        "last_server_error": error[:500],
                        "last_server_error_at": utc_timestamp(),
                    }
                )
                scan = self.store.fetch_next_due()
                if scan is not None:
                    self.store.mark_failed(
                        scan.id,
                        error,
                        self.config.server.retry_interval,
                    )
                LOGGER.warning(
                    "Scanner logger unavailable host=%s port=%s error=%s",
                    self.config.server.host,
                    self.config.server.port,
                    error,
                )
                time.sleep(self.config.server.retry_interval)
            except Exception as exc:
                sender.disconnect()
                LOGGER.exception("Unexpected delivery worker error")
                self._set_status_safely(
                    {
                        "server_state": "delivery_error",
                        "server_connected": "false",
                        "last_server_error": str(exc)[:500],
                        "last_server_error_at": utc_timestamp(),
                    }
                )
                time.sleep(self.config.server.retry_interval)

        sender.disconnect()

    def _heartbeat_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.store.heartbeat()
                self._persist_storage_status()
            except Exception:
                LOGGER.exception("Unable to update service heartbeat")
            time.sleep(5)

    def _persist_scanner_state(self) -> None:
        state = self.runtime_state.snapshot()
        self.store.set_status_many(
            {
                "scanner_available": "true" if state["scanner_available"] else "false",
                "scanner_state": str(state["scanner_state"]),
                "scanner_device_path": str(state["scanner_device_path"]),
                "scanner_device_name": str(state["scanner_device_name"]),
                "last_scanner_error": str(state["last_error"])[:500],
                "scanner_state_updated_at": utc_timestamp(),
            }
        )

    def _persist_scanner_state_safely(self) -> None:
        try:
            self._persist_scanner_state()
        except Exception:
            LOGGER.exception("Unable to persist scanner state")

    def _persist_storage_status(self) -> None:
        storage = build_storage_status(
            self.config.buffer.database_path,
            self.config.buffer.storage_min_free_mb,
        )
        self.store.set_status_many(
            {
                "storage_path": storage.path,
                "storage_free_bytes": str(storage.free_bytes),
                "storage_database_bytes": str(storage.database_bytes),
                "storage_low_space": "true" if storage.low_space else "false",
            }
        )
        if storage.low_space:
            LOGGER.warning(
                "Queue storage is below configured free-space threshold "
                "path=%s free_bytes=%s min_free_bytes=%s",
                storage.path,
                storage.free_bytes,
                storage.min_free_bytes,
            )

    def _set_status_safely(self, values: dict[str, str]) -> None:
        try:
            self.store.set_status_many(values)
        except Exception:
            LOGGER.exception("Unable to persist service status")
