# Changelog

All notable changes to this project are documented here.

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
