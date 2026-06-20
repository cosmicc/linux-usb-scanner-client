"""Health report generation for the scanner client CLI."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .config import AppConfig, validate_operational_config
from .storage import ScanStore, queue_summary_to_dict
from .storage_monitor import build_storage_status
from .timeutil import parse_utc_timestamp, utc_now


@dataclass(frozen=True)
class HealthReport:
    """Structured health report."""

    overall_status: str
    config_path: str
    service_running: bool
    heartbeat_age_seconds: float | None
    scanner_state: str
    scanner_available: bool
    scanner_device_path: str
    scanner_device_name: str
    scanner_state_updated_at: str | None
    server_state: str
    server_connected: bool
    server_target: str
    queue: dict[str, object]
    storage: dict[str, object]
    last_scan_at: str | None
    last_scan_length: int | None
    last_delivery_at: str | None
    last_error: str | None
    warnings: list[str]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly report dictionary."""

        return asdict(self)


def build_health_report(config: AppConfig) -> HealthReport:
    """Build a service health report from config, status, and queue state."""

    store = ScanStore(config.buffer.database_path)
    store.initialize()
    status = store.status_snapshot()
    queue = store.queue_summary()

    heartbeat_at = _status_value(status, "heartbeat_at")
    heartbeat_time = parse_utc_timestamp(heartbeat_at)
    heartbeat_age = None
    service_running = False
    if heartbeat_time is not None:
        heartbeat_age = max(0.0, (utc_now() - heartbeat_time).total_seconds())
        service_running = heartbeat_age <= 15

    scanner_state = _status_value(status, "scanner_state") or "unknown"
    scanner_available = _status_value(status, "scanner_available") == "true"
    server_state = _status_value(status, "server_state") or "unknown"
    server_connected = _status_value(status, "server_connected") == "true"
    storage = build_storage_status(
        config.buffer.database_path,
        config.buffer.storage_min_free_mb,
    )

    warnings = validate_operational_config(config)
    last_error = (
        _status_value(status, "last_server_error")
        or _status_value(status, "last_scanner_error")
        or queue.last_error
    )

    if warnings or not service_running:
        overall = "error"
    elif not scanner_available or scanner_state != "connected":
        overall = "error"
    elif storage.low_space:
        overall = "degraded"
    elif not server_connected or server_state == "unavailable":
        overall = "degraded"
    elif queue.pending_count:
        overall = "degraded"
    else:
        overall = "ok"

    return HealthReport(
        overall_status=overall,
        config_path=str(config.path),
        service_running=service_running,
        heartbeat_age_seconds=heartbeat_age,
        scanner_state=scanner_state,
        scanner_available=scanner_available,
        scanner_device_path=_status_value(status, "scanner_device_path") or "",
        scanner_device_name=_status_value(status, "scanner_device_name") or "",
        scanner_state_updated_at=_status_value(status, "scanner_state_updated_at"),
        server_state=server_state,
        server_connected=server_connected,
        server_target=f"{config.server.host}:{config.server.port}",
        queue=queue_summary_to_dict(queue),
        storage=storage.to_dict(),
        last_scan_at=_status_value(status, "last_scan_at"),
        last_scan_length=_optional_int(_status_value(status, "last_scan_length")),
        last_delivery_at=_status_value(status, "last_delivery_at"),
        last_error=last_error,
        warnings=warnings,
    )


def format_health_text(report: HealthReport) -> str:
    """Format a concise human-readable health report."""

    heartbeat = (
        "unknown"
        if report.heartbeat_age_seconds is None
        else f"{report.heartbeat_age_seconds:.1f}s ago"
    )
    queue = report.queue
    storage = report.storage
    lines = [
        f"Overall: {report.overall_status}",
        f"Service running: {'yes' if report.service_running else 'no'}",
        f"Heartbeat: {heartbeat}",
        (
            "Scanner: "
            f"{report.scanner_state} "
            f"({'available' if report.scanner_available else 'unavailable'})"
        ),
        f"Scanner state updated: {report.scanner_state_updated_at or 'unknown'}",
        f"Scanner device: {report.scanner_device_name or 'unknown'} {report.scanner_device_path}",
        (
            "Server: "
            f"{report.server_state} "
            f"({'connected' if report.server_connected else 'not connected'}) "
            f"{report.server_target}"
        ),
        f"Queue pending: {queue['pending_count']}",
        f"Queue oldest pending: {queue['oldest_pending_at'] or 'none'}",
        f"Queue max attempts: {queue['max_attempts']}",
        f"Storage path: {storage['path']}",
        f"Storage free: {_format_bytes(int(storage['free_bytes']))}",
        f"Storage minimum free: {_format_bytes(int(storage['min_free_bytes']))}",
        f"Queue database size: {_format_bytes(int(storage['database_bytes']))}",
        f"Storage state: {'low space' if storage['low_space'] else 'ok'}",
        f"Last scan: {report.last_scan_at or 'none'}",
        f"Last scan length: {report.last_scan_length if report.last_scan_length is not None else 'none'}",
        f"Last delivery: {report.last_delivery_at or 'none'}",
    ]
    if report.last_error:
        lines.append(f"Last error: {report.last_error}")
    if report.warnings:
        lines.append("Warnings:")
        lines.extend(f"  - {warning}" for warning in report.warnings)
    return "\n".join(lines)


def _status_value(status: dict[str, dict[str, str]], key: str) -> str | None:
    item = status.get(key)
    if not item:
        return None
    return item.get("value")


def _optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _format_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"
