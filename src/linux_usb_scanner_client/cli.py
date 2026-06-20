"""Command line interface for linux-usb-scanner-client."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .auto_update import AutoUpdateError, AutoUpdater, format_update_result
from .config import DEFAULT_CONFIG_PATH, ConfigError, load_config, validate_operational_config
from .device import DeviceError, list_keyboard_devices
from .health import build_health_report, format_health_text
from .logging_setup import configure_logging
from .service import ScannerClientService
from .storage import ScanStore


def main(argv: list[str] | None = None) -> int:
    """Run the command line interface."""

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    if args.command == "list-devices":
        return _list_devices(args)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if args.command == "config-check":
        warnings = validate_operational_config(config)
        if warnings:
            print("Config loaded with warnings:")
            for warning in warnings:
                print(f"- {warning}")
            return 1
        print("Config OK")
        return 0

    if args.command == "init-db":
        store = ScanStore(config.buffer.database_path)
        store.initialize()
        print(f"Initialized database: {config.buffer.database_path}")
        return 0

    if args.command == "auto-update":
        updater = AutoUpdater(config)
        try:
            result = updater.run(check_only=args.check_only, force=args.force)
        except AutoUpdateError as exc:
            print(f"Auto-update error: {exc}", file=sys.stderr)
            return 1
        print(format_update_result(result))
        return 0

    if args.command == "health":
        report = build_health_report(config)
        if args.json:
            print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        else:
            print(format_health_text(report, use_color=not args.no_color))
        return 0 if report.overall_status == "ok" else 1

    if args.command == "service":
        configure_logging(config.logging)
        service = ScannerClientService(config)
        return service.run()

    parser.print_help()
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linux-usb-scanner-client",
        description="Headless USB scanner client for industrial-scanner-logger.",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"Config file path. Default: {DEFAULT_CONFIG_PATH}",
    )
    parser.add_argument("--version", action="store_true", help="Print version and exit.")

    subparsers = parser.add_subparsers(dest="command")

    service_parser = subparsers.add_parser("service", help="Run the long-lived service.")
    service_parser.set_defaults(command="service")

    health_parser = subparsers.add_parser("health", help="Show service health.")
    health_parser.add_argument("--json", action="store_true", help="Emit JSON health data.")
    health_parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color in human-readable health output.",
    )
    health_parser.set_defaults(command="health")

    devices_parser = subparsers.add_parser(
        "list-devices",
        help="List keyboard-like input devices for scanner config.",
    )
    devices_parser.add_argument("--json", action="store_true", help="Emit JSON device data.")
    devices_parser.set_defaults(command="list-devices")

    config_parser = subparsers.add_parser("config-check", help="Validate config.")
    config_parser.set_defaults(command="config-check")

    init_db_parser = subparsers.add_parser("init-db", help="Create the queue database.")
    init_db_parser.set_defaults(command="init-db")

    update_parser = subparsers.add_parser(
        "auto-update",
        help="Check GitHub main for a newer version and apply it when enabled.",
    )
    update_parser.add_argument(
        "--check-only",
        action="store_true",
        help="Check for a newer version without stopping or reinstalling the service.",
    )
    update_parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass updates.enabled and reinstall the configured branch.",
    )
    update_parser.set_defaults(command="auto-update")

    return parser


def _list_devices(args: argparse.Namespace) -> int:
    try:
        devices = list_keyboard_devices()
    except DeviceError as exc:
        print(f"Device error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "path": device.path,
                        "name": device.name,
                        "phys": device.phys,
                        "vendor_id": device.vendor_hex,
                        "product_id": device.product_hex,
                        "version": device.version,
                    }
                    for device in devices
                ],
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if not devices:
        print("No keyboard-like input devices found.")
        return 1

    for device in devices:
        print(
            f"{device.path}  name={device.name!r}  "
            f"vendor_id={device.vendor_hex}  product_id={device.product_hex}  "
            f"phys={device.phys!r}"
        )
    return 0
