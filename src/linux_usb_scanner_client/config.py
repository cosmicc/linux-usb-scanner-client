"""Configuration loading and validation for linux-usb-scanner-client."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("/etc/linux-usb-scanner-client.conf")
DEFAULT_DATABASE_PATH = Path("/var/lib/linux-usb-scanner-client/scans.sqlite3")
DEFAULT_LOG_PATH = Path("/var/log/linux-usb-scanner-client.log")
DEFAULT_UPDATE_REPOSITORY_URL = "https://github.com/cosmicc/linux-usb-scanner-client.git"


class ConfigError(ValueError):
    """Raised when configuration cannot be loaded safely."""


@dataclass(frozen=True)
class ScannerConfig:
    """USB scanner input-device matching and scan framing settings."""

    device_path: str = ""
    vendor_id: int | None = None
    product_id: int | None = None
    device_name: str = ""
    grab_device: bool = True
    reconnect_interval: float = 2.0
    max_scan_chars: int = 256
    send_empty_scans: bool = False

    @property
    def has_matcher(self) -> bool:
        """Return whether the config identifies a scanner narrowly enough to read."""

        return bool(
            self.device_path
            or self.device_name
            or self.vendor_id is not None
            or self.product_id is not None
        )


@dataclass(frozen=True)
class ServerConfig:
    """industrial-scanner-logger TCP receiver settings."""

    host: str = "127.0.0.1"
    port: int = 55256
    connect_timeout: float = 5.0
    send_timeout: float = 5.0
    retry_interval: float = 5.0
    poll_interval: float = 1.0
    tcp_keepalive: bool = True


@dataclass(frozen=True)
class BufferConfig:
    """Persistent queue storage settings."""

    database_path: Path = DEFAULT_DATABASE_PATH
    sent_retention_days: int = 7
    storage_min_free_mb: int = 1024


@dataclass(frozen=True)
class LoggingConfig:
    """Service logging settings."""

    log_file: Path = DEFAULT_LOG_PATH
    log_level: str = "INFO"


@dataclass(frozen=True)
class UpdateConfig:
    """Automatic update settings."""

    enabled: bool = False
    repository_url: str = DEFAULT_UPDATE_REPOSITORY_URL
    branch: str = "main"
    service_name: str = "linux-usb-scanner-client.service"


@dataclass(frozen=True)
class AppConfig:
    """Complete application configuration."""

    path: Path
    scanner: ScannerConfig
    server: ServerConfig
    buffer: BufferConfig
    logging: LoggingConfig
    updates: UpdateConfig


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Load and validate an INI configuration file."""

    config_path = Path(path)
    parser = configparser.ConfigParser()
    read_files = parser.read(config_path)
    if not read_files:
        raise ConfigError(f"Config file not found or unreadable: {config_path}")

    scanner = ScannerConfig(
        device_path=_get_str(parser, "scanner", "device_path"),
        vendor_id=_get_optional_int(parser, "scanner", "vendor_id"),
        product_id=_get_optional_int(parser, "scanner", "product_id"),
        device_name=_get_str(parser, "scanner", "device_name"),
        grab_device=_get_bool(parser, "scanner", "grab_device", True),
        reconnect_interval=_get_positive_float(
            parser, "scanner", "reconnect_interval", 2.0
        ),
        max_scan_chars=_get_positive_int(parser, "scanner", "max_scan_chars", 256),
        send_empty_scans=_get_bool(parser, "scanner", "send_empty_scans", False),
    )

    server = ServerConfig(
        host=_get_required_str(parser, "server", "host", "127.0.0.1"),
        port=_get_port(parser, "server", "port", 55256),
        connect_timeout=_get_positive_float(
            parser, "server", "connect_timeout", 5.0
        ),
        send_timeout=_get_positive_float(parser, "server", "send_timeout", 5.0),
        retry_interval=_get_positive_float(parser, "server", "retry_interval", 5.0),
        poll_interval=_get_positive_float(parser, "server", "poll_interval", 1.0),
        tcp_keepalive=_get_bool(parser, "server", "tcp_keepalive", True),
    )

    buffer = BufferConfig(
        database_path=Path(
            _get_required_str(
                parser,
                "buffer",
                "database_path",
                str(DEFAULT_DATABASE_PATH),
            )
        ),
        sent_retention_days=_get_nonnegative_int(
            parser, "buffer", "sent_retention_days", 7
        ),
        storage_min_free_mb=_get_nonnegative_int(
            parser, "buffer", "storage_min_free_mb", 1024
        ),
    )

    logging = LoggingConfig(
        log_file=Path(_get_required_str(parser, "logging", "log_file", str(DEFAULT_LOG_PATH))),
        log_level=_get_required_str(parser, "logging", "log_level", "INFO").upper(),
    )
    if logging.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigError("logging.log_level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")

    updates = UpdateConfig(
        enabled=_get_bool(parser, "updates", "enabled", False),
        repository_url=_get_required_str(
            parser,
            "updates",
            "repository_url",
            DEFAULT_UPDATE_REPOSITORY_URL,
        ),
        branch=_get_required_str(parser, "updates", "branch", "main"),
        service_name=_get_required_str(
            parser,
            "updates",
            "service_name",
            "linux-usb-scanner-client.service",
        ),
    )

    return AppConfig(
        path=config_path,
        scanner=scanner,
        server=server,
        buffer=buffer,
        logging=logging,
        updates=updates,
    )


def validate_operational_config(config: AppConfig) -> list[str]:
    """Return non-fatal operational warnings for a loaded config."""

    warnings: list[str] = []
    if not config.scanner.has_matcher:
        warnings.append(
            "scanner matcher is not configured; set device_path, device_name, "
            "vendor_id, or product_id before the service can read scans"
        )
    if config.scanner.device_name and not (
        config.scanner.device_path
        or config.scanner.vendor_id is not None
        or config.scanner.product_id is not None
    ):
        warnings.append(
            "scanner.device_name matching can be broad; prefer device_path or "
            "vendor_id/product_id before enabling grab_device"
        )
    return warnings


def _get_str(parser: configparser.ConfigParser, section: str, option: str) -> str:
    return parser.get(section, option, fallback="").strip()


def _get_required_str(
    parser: configparser.ConfigParser, section: str, option: str, default: str
) -> str:
    value = parser.get(section, option, fallback=default).strip()
    if not value:
        raise ConfigError(f"{section}.{option} is required")
    return value


def _get_bool(
    parser: configparser.ConfigParser, section: str, option: str, default: bool
) -> bool:
    try:
        return parser.getboolean(section, option, fallback=default)
    except ValueError as exc:
        raise ConfigError(f"{section}.{option} must be true or false") from exc


def _get_optional_int(
    parser: configparser.ConfigParser, section: str, option: str
) -> int | None:
    raw = parser.get(section, option, fallback="").strip()
    if not raw:
        return None
    try:
        value = int(raw, 0)
    except ValueError as exc:
        raise ConfigError(f"{section}.{option} must be an integer or hex value") from exc
    if value < 0:
        raise ConfigError(f"{section}.{option} must be non-negative")
    return value


def _get_positive_int(
    parser: configparser.ConfigParser, section: str, option: str, default: int
) -> int:
    value = _get_int(parser, section, option, default)
    if value <= 0:
        raise ConfigError(f"{section}.{option} must be greater than zero")
    return value


def _get_nonnegative_int(
    parser: configparser.ConfigParser, section: str, option: str, default: int
) -> int:
    value = _get_int(parser, section, option, default)
    if value < 0:
        raise ConfigError(f"{section}.{option} must be zero or greater")
    return value


def _get_int(
    parser: configparser.ConfigParser, section: str, option: str, default: int
) -> int:
    raw = parser.get(section, option, fallback=str(default)).strip()
    try:
        return int(raw, 0)
    except ValueError as exc:
        raise ConfigError(f"{section}.{option} must be an integer") from exc


def _get_port(
    parser: configparser.ConfigParser, section: str, option: str, default: int
) -> int:
    value = _get_int(parser, section, option, default)
    if value < 1 or value > 65535:
        raise ConfigError(f"{section}.{option} must be between 1 and 65535")
    return value


def _get_positive_float(
    parser: configparser.ConfigParser, section: str, option: str, default: float
) -> float:
    raw = parser.get(section, option, fallback=str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{section}.{option} must be a number") from exc
    if value <= 0:
        raise ConfigError(f"{section}.{option} must be greater than zero")
    return value
