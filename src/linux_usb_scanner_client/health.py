"""Health report generation for the scanner client CLI."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .config import AppConfig, validate_operational_config
from .storage import ScanStore, queue_summary_to_dict
from .storage_monitor import build_storage_status
from .timeutil import parse_utc_timestamp, utc_now

ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_DIM = "\033[2m"
ANSI_RED = "\033[31m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_BLUE = "\033[34m"
ANSI_MAGENTA = "\033[35m"
ANSI_CYAN = "\033[36m"


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
    update_state: str
    update_checked_at: str | None
    update_remote_version: str | None
    update_remote_commit: str | None
    update_message: str | None
    update_error: str | None
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
        update_state=_status_value(status, "update_state") or (
            "enabled" if config.updates.enabled else "disabled"
        ),
        update_checked_at=_status_value(status, "last_update_check_at"),
        update_remote_version=_status_value(status, "update_remote_version"),
        update_remote_commit=_status_value(status, "update_remote_commit"),
        update_message=_status_value(status, "update_message"),
        update_error=_status_value(status, "update_error"),
        last_scan_at=_status_value(status, "last_scan_at"),
        last_scan_length=_optional_int(_status_value(status, "last_scan_length")),
        last_delivery_at=_status_value(status, "last_delivery_at"),
        last_error=last_error,
        warnings=warnings,
    )


def format_health_text(report: HealthReport, *, use_color: bool = True) -> str:
    """Format a concise human-readable health report."""

    heartbeat = (
        "unknown"
        if report.heartbeat_age_seconds is None
        else f"{report.heartbeat_age_seconds:.1f}s ago"
    )
    queue = report.queue
    storage = report.storage
    scanner_availability = "available" if report.scanner_available else "unavailable"
    server_availability = "connected" if report.server_connected else "not connected"
    lines = [
        _line(
            "Overall",
            _paint_status(report.overall_status, _overall_color(report.overall_status), use_color),
            use_color,
        ),
        _line(
            "Service running",
            _paint_status("yes" if report.service_running else "no", ANSI_GREEN if report.service_running else ANSI_RED, use_color),
            use_color,
        ),
        _line("Heartbeat", _paint_unknown(heartbeat, use_color), use_color),
        _line(
            "Scanner",
            _paint_status(
                f"{report.scanner_state} ({scanner_availability})",
                ANSI_GREEN if report.scanner_available and report.scanner_state == "connected" else ANSI_RED,
                use_color,
            ),
            use_color,
        ),
        _line(
            "Scanner state updated",
            _paint_unknown(report.scanner_state_updated_at or "unknown", use_color),
            use_color,
        ),
        _line(
            "Scanner device",
            _paint_path(
                f"{report.scanner_device_name or 'unknown'} {report.scanner_device_path}".strip(),
                use_color,
            ),
            use_color,
        ),
        _line(
            "Server",
            (
                _paint_status(
                    f"{report.server_state} ({server_availability})",
                    ANSI_GREEN if report.server_connected else ANSI_RED,
                    use_color,
                )
                + " "
                + _paint_path(report.server_target, use_color)
            ),
            use_color,
        ),
        _line(
            "Queue pending",
            _paint_count(int(queue["pending_count"]), warning_when_positive=True, use_color=use_color),
            use_color,
        ),
        _line(
            "Queue oldest pending",
            _paint_unknown(str(queue["oldest_pending_at"] or "none"), use_color),
            use_color,
        ),
        _line(
            "Queue max attempts",
            _paint_count(int(queue["max_attempts"]), warning_when_positive=True, use_color=use_color),
            use_color,
        ),
        _line("Storage path", _paint_path(str(storage["path"]), use_color), use_color),
        _line("Storage free", _paint_status(_format_bytes(int(storage["free_bytes"])), ANSI_GREEN, use_color), use_color),
        _line(
            "Storage minimum free",
            _paint_status(_format_bytes(int(storage["min_free_bytes"])), ANSI_BLUE, use_color),
            use_color,
        ),
        _line(
            "Queue database size",
            _paint_status(_format_bytes(int(storage["database_bytes"])), ANSI_BLUE, use_color),
            use_color,
        ),
        _line(
            "Storage state",
            _paint_status("low space" if storage["low_space"] else "ok", ANSI_RED if storage["low_space"] else ANSI_GREEN, use_color),
            use_color,
        ),
        _line(
            "Update state",
            _paint_status(report.update_state, _update_color(report.update_state), use_color),
            use_color,
        ),
        _line(
            "Update checked",
            _paint_unknown(report.update_checked_at or "none", use_color),
            use_color,
        ),
        _line(
            "Update remote version",
            _paint_unknown(report.update_remote_version or "none", use_color),
            use_color,
        ),
        _line("Last scan", _paint_unknown(report.last_scan_at or "none", use_color), use_color),
        _line(
            "Last scan length",
            _paint_unknown(
                str(report.last_scan_length) if report.last_scan_length is not None else "none",
                use_color,
            ),
            use_color,
        ),
        _line("Last delivery", _paint_unknown(report.last_delivery_at or "none", use_color), use_color),
    ]
    if report.last_error:
        lines.append(_line("Last error", _paint_status(report.last_error, ANSI_RED, use_color), use_color))
    if report.update_error:
        lines.append(_line("Update error", _paint_status(report.update_error, ANSI_RED, use_color), use_color))
    if report.update_message:
        lines.append(_line("Update message", _paint_unknown(report.update_message, use_color), use_color))
    if report.warnings:
        lines.append(_paint_status("Warnings:", ANSI_YELLOW, use_color))
        lines.extend(f"  - {_paint_status(warning, ANSI_YELLOW, use_color)}" for warning in report.warnings)
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


def _line(label: str, value: str, use_color: bool) -> str:
    return f"{_paint_label(label, use_color)} {value}"


def _paint(text: str, color: str, use_color: bool, *, bold: bool = False) -> str:
    if not use_color:
        return text
    prefix = f"{ANSI_BOLD if bold else ''}{color}"
    return f"{prefix}{text}{ANSI_RESET}"


def _paint_label(label: str, use_color: bool) -> str:
    return _paint(f"{label}:", ANSI_CYAN, use_color, bold=True)


def _paint_status(text: str, color: str, use_color: bool) -> str:
    return _paint(text, color, use_color, bold=True)


def _paint_path(text: str, use_color: bool) -> str:
    if text == "unknown":
        return _paint_unknown(text, use_color)
    return _paint(text, ANSI_MAGENTA, use_color)


def _paint_unknown(text: str, use_color: bool) -> str:
    if text in {"none", "unknown", ""}:
        return _paint(text or "unknown", ANSI_DIM, use_color)
    return _paint(text, ANSI_BLUE, use_color)


def _paint_count(value: int, *, warning_when_positive: bool, use_color: bool) -> str:
    if value == 0:
        return _paint_status(str(value), ANSI_GREEN, use_color)
    color = ANSI_YELLOW if warning_when_positive else ANSI_BLUE
    return _paint_status(str(value), color, use_color)


def _overall_color(overall_status: str) -> str:
    if overall_status == "ok":
        return ANSI_GREEN
    if overall_status == "degraded":
        return ANSI_YELLOW
    return ANSI_RED


def _update_color(update_state: str) -> str:
    if update_state in {"up_to_date", "updated", "disabled", "enabled"}:
        return ANSI_GREEN
    if update_state in {"checking", "update_available", "updating"}:
        return ANSI_YELLOW
    return ANSI_RED
