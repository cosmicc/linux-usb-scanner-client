# Changelog

All notable changes to this project are documented here.

## [1.0.0] - 2026-06-27

### Added

- Added current-day and previous-day UTC scan totals to `scripts/check-health.sh`
  using read-only aggregate counts from the configured SQLite scan queue.

### Changed

- Documented the expanded health-check script output in `README.md` and
  `AGENTS.md`.
- Promoted the project to release version `1.0.0`.

## [0.1.8] - 2026-06-23

### Changed

- All shell scripts under `scripts/` now require root before option parsing and
  fail immediately with a sudo reminder when run as a normal user.
- Documented the root-only script boundary in `README.md` and `AGENTS.md`.
- Bumped prerelease version to `0.1.8`.

## [0.1.7] - 2026-06-23

### Added

- Added `scripts/clear-scan-queue.sh` for explicitly clearing pending queued
  scans from the persistent SQLite database without deleting config, logs, or
  the app directory.
- Added a regression test proving `ScanStore.initialize()` preserves existing
  pending scans when the same queue database is reopened.

### Changed

- Installer documentation and output now state that rerunning `install.sh` on
  an installed system is an update path that preserves app files, config,
  SQLite state, and logs while restarting installed services.
- Uninstaller `--purge` now removes only `/var/lib/linux-usb-scanner-client`
  SQLite/local state; it preserves `/opt/linux-usb-scanner-client`,
  `/etc/linux-usb-scanner-client.conf`, `/var/log/linux-usb-scanner-client.log`,
  and the service identity.
- The systemd app unit now declares persistent `StateDirectory` ownership for
  `/var/lib/linux-usb-scanner-client`.
- Bumped prerelease version to `0.1.7`.

## [0.1.6] - 2026-06-23

### Fixed

- Alert monitor no longer logs an error loop when the `beep` backend makes an
  audible system-speaker beep but exits nonzero without stderr/stdout.

### Changed

- Auto alert backend selection now remembers the first working backend during a
  monitor run instead of retrying failed earlier backends for every beep in a
  multi-beep pattern.
- Clarified audio-card versus system-speaker alert backend behavior in the
  config template, `README.md`, and `AGENTS.md`.
- Bumped prerelease version to `0.1.6`.

## [0.1.5] - 2026-06-23

### Added

- Added `scripts/restart-services.sh` to reload systemd and restart the scanner
  service, alert monitor service, and auto-update timer without rebooting.
- Added an explicit `--run-update-check` option for operators who intentionally
  want the restart helper to run the root-owned one-shot updater.

### Changed

- Documented the full-app restart workflow in `README.md` and `AGENTS.md`.
- Bumped prerelease version to `0.1.5`.

## [0.1.4] - 2026-06-23

### Changed

- Installer and documentation now support Debian Linux alongside Ubuntu.
- Installer now fails early with clear messages when `systemctl`, the `input`
  group, or Python 3.10+ are unavailable on the target Debian/Ubuntu host.
- Automatic beep alerts now prefer the audio card first, then the system
  speaker, with console bell kept as a final fallback.
- Alert monitor systemd unit now disables start-rate limiting so repeated
  process failures do not permanently stop alerting.
- Installer now safely handles being rerun from `/opt/linux-usb-scanner-client`
  without copying the install tree onto itself.
- Installer now verifies that the app service, alert monitor service, and update
  timer are enabled and active before reporting success.
- Installer now installs `acl` and grants/verifies service-user read access to
  both the source app directory and `/opt/linux-usb-scanner-client`.
- Installed app, monitor, and updater units now append stdout/stderr to
  `/var/log/linux-usb-scanner-client.log`, while Python app logging writes to
  the configured `logging.log_file` and obeys `logging.log_level`.
- Added `scripts/check-health.sh` for a quick installed-system diagnostic across
  CLI health, USB input devices, server connectivity, queue/storage state,
  alert/update state, systemd units, and log-file presence.
- Documented that auto-update can only detect app changes when
  `pyproject.toml` is advanced to a higher version and version metadata stays
  aligned.
- Bumped prerelease version to `0.1.4`.

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
