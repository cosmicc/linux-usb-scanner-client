# AGENTS.md

## Project Overview

`linux-usb-scanner-client` is a headless Ubuntu service for USB keyboard-wedge barcode scanners. It reads scan keystrokes from a configured `/dev/input/event*` device, buffers completed CR/LF-terminated scans in SQLite, and forwards them to `industrial-scanner-logger` over the same TCP framing used by the Windows USB scanner client: one UTF-8 barcode followed by `CRLF`.

The service intentionally opens and holds the TCP connection only while the configured USB scanner is available. If the scanner is unplugged, inaccessible, or not matched by config, the service must not connect to `industrial-scanner-logger`; this lets the server detect scanner availability through its connected TCP clients.

## Required Files

Every meaningful change must keep these files current:

- `AGENTS.md` for agent-facing architecture, workflow, and operational instructions.
- `README.md` for user-facing install, config, operation, health, and troubleshooting instructions.
- `CHANGELOG.md` for notable changes.

## Architecture

- `src/linux_usb_scanner_client/config.py` loads and validates INI config from `/etc/linux-usb-scanner-client.conf`.
- `src/linux_usb_scanner_client/device.py` discovers matching Linux input devices through `evdev`.
- `src/linux_usb_scanner_client/keyboard.py` translates keyboard events into scan frames and completes scans only on Enter/CR/LF.
- `src/linux_usb_scanner_client/storage.py` owns the persistent SQLite queue and service status tables.
- `src/linux_usb_scanner_client/storage_monitor.py` reports queue volume free space and database footprint.
- `src/linux_usb_scanner_client/tcp_sender.py` owns the persistent TCP client connection and sends `barcode + "\r\n"`.
- `src/linux_usb_scanner_client/service.py` coordinates scanner monitoring, queueing, TCP connection gating, retry, and shutdown.
- `src/linux_usb_scanner_client/health.py` builds CLI health output from the service status table and queue state.
- `src/linux_usb_scanner_client/auto_update.py` checks GitHub main for newer versions and applies updates through the root-owned update service.
- `src/linux_usb_scanner_client/cli.py` is the command entry point.

## Security Rules

- Never hardcode secrets, private hosts, tokens, or environment-specific values.
- Do not log raw barcode values. Health output may show timestamps, counts, device names, queue depth, attempts, and error summaries, but not full scan payloads.
- Require an explicit scanner matcher before processing input. Valid matchers are `device_path`, `vendor_id`/`product_id`, or `device_name`. Do not default to reading every keyboard.
- Keep `/etc/linux-usb-scanner-client.conf` root-owned and readable by the service group only when installed.
- Keep the SQLite queue under `/var/lib/linux-usb-scanner-client/` with ownership limited to the service user.
- Preserve the app directory on every uninstall, including purge.
- Preserve pending queued scans forever until they are delivered. Cleanup may remove only already-sent metadata.
- Keep auto-update disabled by default. Enabling it allows a root systemd service to run `scripts/install.sh` from the configured Git repository branch, so it must remain restricted to trusted repositories.

## Development Workflow

Use the local virtual environment when available:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
PYTHONPATH=src python -m unittest discover -s tests
```

Before editing scanner behavior, inspect the current `industrial-scanner-logger` TCP receiver and the Windows USB scanner client if the wire protocol might have changed. The expected protocol is a persistent TCP client connection to port `55256` by default, with each scan sent as UTF-8 text plus `CRLF`.

## Versioning

The app started at version `0.1.0`; the current prerelease version is `0.1.1`. Do not advance the version unless the user explicitly asks for a version bump. When a version bump is requested, keep `pyproject.toml`, `src/linux_usb_scanner_client/__init__.py`, `README.md`, and `CHANGELOG.md` aligned, and update the version consistency test.

## Deployment Workflow

- Update `config/linux-usb-scanner-client.conf` when adding or changing settings.
- Update `systemd/linux-usb-scanner-client.service` and `scripts/install.sh` together when service paths, users, permissions, or startup behavior change.
- Keep `scripts/install.sh` and `scripts/uninstall.sh` non-destructive to `/opt/linux-usb-scanner-client`.
- Run `bash -n scripts/install.sh scripts/uninstall.sh` after shell script changes.
- Run `PYTHONPATH=src python -m unittest discover -s tests` after Python changes.

## Operational Expectations

- `linux-usb-scanner-client health` must show scanner state, server connection state, queue depth, oldest pending scan, heartbeat freshness, storage free space, auto-update state, and recent errors.
- Human-readable `linux-usb-scanner-client health` output is ANSI-colored by default; use `--no-color` for plain text and `--json` for structured output.
- `linux-usb-scanner-client list-devices` must help identify the correct scanner matcher for `/etc/linux-usb-scanner-client.conf`.
- Server connection attempts are blocked whenever the scanner is unavailable.
- Backlog delivery is best effort: failed TCP connects or sends leave scans queued with attempt metadata and retry later.
- All client-generated timestamps must be UTC ISO-8601 strings ending in `Z`. The TCP wire protocol sends barcode frames only; server-side scan timestamps are controlled by `industrial-scanner-logger`.
