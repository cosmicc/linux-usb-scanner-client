# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Changed

- Installer and documentation now support Debian Linux alongside Ubuntu.
- Installer now fails early with clear messages when `systemctl`, the `input`
  group, or Python 3.10+ are unavailable on the target Debian/Ubuntu host.
- Automatic beep alerts now prefer the system speaker first, then the audio
  card, with console bell kept as a final fallback.
- Alert monitor systemd unit now disables start-rate limiting so repeated
  process failures do not permanently stop alerting.

## [0.1.3] - 2026-06-20

### Changed

- Installer now installs required Ubuntu packages when missing, including `git`,
  Python venv/build support, certificate roots, and ALSA audio tools.
- Installer now attempts to install the optional `beep` package for system
  speaker alerting and continues with a warning if it is unavailable.
- Bumped prerelease version to `0.1.3`.

## [0.1.2] - 2026-06-20

### Documentation

- Clarified that this app requires `industrial-scanner-logger` to accept scan events and that this project is the Linux counterpart to the Windows USB Scanner Client.

### Added

- Independent `linux-usb-scanner-client-monitor.service` for continuous degraded-state beep alerts.
- Configurable `[alerting]` settings for beep interval, backend, tone, and alert patterns.
- `linux-usb-scanner-client monitor` CLI command with one-shot health evaluation and test-beep mode.
- Alert monitor state, active pattern, and beep count visibility in CLI health output.

### Changed

- Bumped prerelease version to `0.1.2`.
- Installer and uninstaller now manage the independent alert monitor service while preserving the app directory.

## [0.1.1] - 2026-06-20

### Documentation

- Expanded scanner config comments with exact commands and examples for finding `vendor_id`, `product_id`, and `device_name`.

### Added

- Opt-in automatic updater that checks GitHub `main` for newer `pyproject.toml` versions, stops the app service, installs the new branch, and restarts the app.
- Root-owned `linux-usb-scanner-client-update.service` and `linux-usb-scanner-client-update.timer` units for periodic update checks.
- `linux-usb-scanner-client auto-update` CLI command with check-only and force modes.
- Auto-update state, remote version, and update error visibility in CLI health output.
- ANSI-colored CLI health output with `--no-color` support for plain text.

### Changed

- Bumped prerelease version to `0.1.1`.
- Documented the auto-update security boundary and disabled-by-default update config.

## [0.1.0] - 2026-06-20

### Added

- Initial headless Ubuntu USB scanner client service.
- `/etc/linux-usb-scanner-client.conf` INI configuration template.
- Linux input-device scanner matching by path, USB vendor/product ID, or device name.
- CR/LF-terminated keyboard-wedge scan capture with persistent SQLite buffering.
- Persistent TCP forwarding to `industrial-scanner-logger` using UTF-8 barcode plus `CRLF`.
- Scanner-availability gating so the service does not connect to the server unless the USB scanner is present.
- CLI health, config-check, and input-device listing commands.
- Systemd unit, installer, and non-destructive uninstaller scripts.
- Unit tests for configuration, keyboard decoding, storage, and TCP sending.
- UTC-only client-side scan metadata and health timestamps.
- Health storage reporting for queue filesystem free space and queue database size.
- Version consistency validation for the initial `0.1.0` app version.

### Changed

- Hardened service and systemd restart behavior so scanner, delivery, and heartbeat loops keep running through recoverable failures.
- Made installer updates non-destructive to `/opt/linux-usb-scanner-client`.
- Made uninstall preserve `/opt/linux-usb-scanner-client` even when `--purge` is used.
- Documented that pending scans are buffered forever until successfully sent.
- Documented that versions advance only when requested by the user.
