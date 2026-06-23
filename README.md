# Linux USB Scanner Client

Headless Debian/Ubuntu service for USB keyboard-wedge barcode scanners. It
reads scans from a configured Linux input device, stores completed scans in a
persistent SQLite queue, and forwards them to
[`industrial-scanner-logger`](https://github.com/cosmicc/industrial-scanner-logger/tree/dev)
over TCP.

This is the Linux counterpart to the Windows
[`usb-scanner-client`](https://github.com/cosmicc/usb-scanner-client). It does
not provide a GUI. It is meant to run continuously under systemd and keep the
scanner ready for industrial use.

## Required Server Component

This app requires the Industrial Scanner Logger server app to accept and process
scan events:

https://github.com/cosmicc/industrial-scanner-logger/tree/dev

`linux-usb-scanner-client` does not classify scans, write the production scan
database, handle duplicates, or serve the scanner dashboard. Its job is to keep
the Linux USB scanner available, buffer scans locally when needed, and forward
each scan to `industrial-scanner-logger` over TCP.

This project is the Linux service version of the Windows USB Scanner Client app:

https://github.com/cosmicc/usb-scanner-client

Use the Windows app on Windows scanner workstations. Use this Linux service on
Debian or Ubuntu scanner hosts that need the same TCP scan forwarding behavior
without a GUI.

## Current Behavior

- Current version: `0.1.4`.
- Runs as `linux-usb-scanner-client.service` on Debian and Ubuntu.
- Runs a separate `linux-usb-scanner-client-monitor.service` for degraded-state beep alerts.
- Stores runtime settings in `/etc/linux-usb-scanner-client.conf`.
- Reads one explicitly configured USB keyboard-wedge scanner from `/dev/input/event*`.
- Completes scans only when the scanner sends Enter, CR, LF, or CRLF.
- Sends each scan to the logger as UTF-8 barcode text followed by `CRLF`.
- Uses TCP port `55256` by default, matching `industrial-scanner-logger`.
- Opens and holds the TCP connection only while the configured USB scanner is available.
- Does not connect to the server when the scanner is missing, inaccessible, or misconfigured.
- Buffers scans in `/var/lib/linux-usb-scanner-client/scans.sqlite3` if the server is unavailable.
- Drains queued scans in capture order after the server is reachable again.
- Provides CLI health output with scanner state, server state, queue depth, backlog age, queue storage free space, heartbeat, and recent errors.
- Beeps continuously during degraded states when alerting is enabled.
- Uses the audio card first for beep alerts, falls back to the system speaker,
  and keeps console bell as a final fallback when `backend = auto`.
- Writes installed service, monitor, and updater logs to `/var/log/linux-usb-scanner-client.log`.
- Avoids logging raw barcode values.

The server derives `scanner_id` from the last octet of the client computer's
IPv4 address. This client does not send a scanner ID in the payload.

All client-generated scan metadata and health timestamps are UTC ISO-8601
values ending in `Z`. The TCP protocol itself sends only barcode frames, because
that is what `industrial-scanner-logger` currently accepts. The logger remains
responsible for its own server-side receive timestamp.

## Install

From the project directory on Debian 12 or newer, or Ubuntu 22.04 or newer:

```bash
sudo scripts/install.sh
```

The installer:

- verifies `systemctl`, the `input` group, and `python3` 3.10 or newer before
  installing the service;
- installs required Debian/Ubuntu packages when missing: `acl`,
  `ca-certificates`, `git`, `python3`, `python3-dev`, `python3-pip`,
  `python3-venv`, `build-essential`, and `alsa-utils`;
- attempts to install the optional `beep` package for system-speaker alerting,
  and continues with a warning if that package is unavailable;
- creates a `linux-usb-scanner-client` system user and group;
- adds the service user to the `input` group so it can read `/dev/input/event*`;
- installs the app under `/opt/linux-usb-scanner-client`;
- creates a Python virtual environment;
- installs `/etc/linux-usb-scanner-client.conf` if it does not already exist;
- installs and starts `linux-usb-scanner-client.service`;
- installs and starts `linux-usb-scanner-client-monitor.service`;
- installs and starts `linux-usb-scanner-client-update.timer`;
- verifies that the app service, alert monitor service, and update timer are
  enabled and active before reporting success.

The installer is safe to rerun from a source checkout or from the installed
`/opt/linux-usb-scanner-client` directory. When the source directory is already
the install directory, it skips the application file copy instead of copying the
tree onto itself.

The installer grants the `linux-usb-scanner-client` service user read/traverse
access to the app directory where `scripts/install.sh` is running from and to
`/opt/linux-usb-scanner-client`. It uses ACLs when available so private parent
directories can stay private instead of making the app tree world-readable.

The existing config is preserved unless you run:

```bash
sudo scripts/install.sh --overwrite-config
```

The installer uses Debian/Ubuntu `apt-get`, so the host needs access to
configured apt repositories during installation or upgrade. Debian 11's default
Python is too old for this package; use Debian 12 or newer, Ubuntu 22.04 or
newer, or provide a supported `python3` 3.10+ interpreter before running the
installer.

## Configure the Scanner

List keyboard-like input devices:

```bash
/opt/linux-usb-scanner-client/venv/bin/linux-usb-scanner-client list-devices
```

Example output:

```text
/dev/input/event4  name='Honeywell USB Keyboard'  vendor_id=0x0c2e  product_id=0x0901  phys='usb-0000:00:14.0-1/input0'
```

The config comments in `/etc/linux-usb-scanner-client.conf` show how to map the
`list-devices` output into `device_path`, `vendor_id`, `product_id`, and
`device_name`. Prefer `vendor_id` plus `product_id` because `/dev/input/event*`
numbers can change after a reboot or USB reconnect.

Edit `/etc/linux-usb-scanner-client.conf` and set a specific scanner matcher:

```ini
[scanner]
vendor_id = 0x0c2e
product_id = 0x0901
device_name = Honeywell
grab_device = true
```

Prefer `vendor_id` and `product_id`, or `device_path`, over a broad name-only
match. The service will not read input until at least one matcher is configured.
This prevents accidentally capturing a normal keyboard.

Then restart:

```bash
sudo systemctl restart linux-usb-scanner-client
```

## Configure the Server

Set the logger target in `/etc/linux-usb-scanner-client.conf`:

```ini
[server]
host = 10.10.10.5
port = 55256
connect_timeout = 5
send_timeout = 1
retry_interval = 5
poll_interval = 1
tcp_keepalive = true
```

When the scanner is present, this service opens a persistent TCP connection to
the logger. When the scanner is absent, it closes or avoids the TCP connection
so the logger can report the scanner as missing.

## Health Check

Human-readable health:

```bash
sudo /opt/linux-usb-scanner-client/venv/bin/linux-usb-scanner-client health
```

Human-readable health is ANSI-colored by default: healthy/up values are green,
warnings are yellow, down/error values are red, labels are cyan, and paths or
targets use accent colors for readability.

Plain text health:

```bash
sudo /opt/linux-usb-scanner-client/venv/bin/linux-usb-scanner-client health --no-color
```

JSON health:

```bash
sudo /opt/linux-usb-scanner-client/venv/bin/linux-usb-scanner-client health --json
```

Health includes:

- service heartbeat freshness;
- scanner availability and matched device;
- server connection state;
- queue pending count;
- oldest pending scan timestamp;
- queue database size and free space on the queue filesystem;
- maximum pending retry attempts;
- last scan time and scan length;
- last delivery time;
- auto-update state and last remote version seen;
- alert monitor state, active beep pattern, and last monitor check;
- recent scanner or server error.

Raw barcode payloads are intentionally not printed in health output.
The queue database itself contains raw scans, so installed deployments keep it
restricted to the service identity. Run health with `sudo` unless your operator
account has been intentionally granted access.

Quick installed-system diagnostic:

```bash
sudo /opt/linux-usb-scanner-client/scripts/check-health.sh
```

The script summarizes the CLI health report, USB keyboard-like scanner devices,
server connection state, queue/storage state, alert monitor state, update state,
systemd unit active/enabled state, and the `/var/log/linux-usb-scanner-client.log`
file. From a source checkout, run `sudo scripts/check-health.sh`.

## Logs

Installed deployments write app, monitor, and updater logs to:

```bash
/var/log/linux-usb-scanner-client.log
```

The Python application logger writes to the path configured by
`logging.log_file`, which defaults to that file. The installed systemd units also
append stdout and stderr to the same file so tracebacks and command output are
available outside the journal. Adjust `logging.log_level` to control Python app
logging volume:

```ini
[logging]
log_file = /var/log/linux-usb-scanner-client.log
log_level = INFO
```

Valid levels are `DEBUG`, `INFO`, `WARNING`, `ERROR`, and `CRITICAL`. Raw
barcode payloads are not written to the log.

## Buffering and Retry

Every completed scan is inserted into the SQLite queue before delivery. If the
TCP server is unavailable or a send fails, the row stays pending with attempt
metadata and a UTC retry timestamp. Once the scanner is present and the server
can be reached, queued scans are sent in the order they were captured.

Pending scans are retained forever until successfully sent. Sent scan metadata
is retained for seven days by default. Cleanup never removes pending scans.

The health check reports free space on the queue database filesystem and marks
health degraded when it drops below `buffer.storage_min_free_mb`. Provision more
disk or move `buffer.database_path` before that threshold is reached; the app
will not delete pending scans to make room.

## Degraded-State Beep Alerts

The installer also starts `linux-usb-scanner-client-monitor.service`. This is a
separate monitor that checks the health data written by the scanner service and
plays the highest-priority active beep pattern:

- `5` quick beeps every interval when the scanner app service is not running or
  its heartbeat is stale.
- `3` quick beeps every interval when the configured USB scanner is not detected.
- `1` quick beep every interval when the Industrial Scanner Logger server is not
  contactable.

Configure the monitor in `/etc/linux-usb-scanner-client.conf`:

```ini
[alerting]
enabled = true
interval_seconds = 5
backend = auto
server_unavailable_beeps = 1
scanner_unavailable_beeps = 3
app_not_running_beeps = 5
```

Restart the monitor after changing alerting settings:

```bash
sudo systemctl restart linux-usb-scanner-client-monitor
```

`backend = auto` tries ALSA audio through `aplay` first, then the Linux `beep`
command for system-speaker alerts, then a console bell as a final fallback.
Different Debian and Ubuntu installs expose different sound paths: the `aplay`
backend may require ALSA output to be configured, while the `beep` backend may
require the `beep` package and system speaker support. Use `enabled = false` to
keep the monitor service running without making sound.

Both the scanner app service and the alert monitor service use systemd
`Restart=always`. The alert monitor also disables systemd start-rate limiting so
it keeps coming back after repeated process failures.

Test one pattern:

```bash
sudo /opt/linux-usb-scanner-client/venv/bin/linux-usb-scanner-client monitor --test-beep scanner_unavailable
```

Evaluate monitor state once without beeping:

```bash
sudo /opt/linux-usb-scanner-client/venv/bin/linux-usb-scanner-client monitor --once
```

## Auto Update

Auto-update is installed as a separate root-owned systemd timer so the scanner
service can continue running as the restricted `linux-usb-scanner-client` user.
The timer runs every 15 minutes, but it does nothing until explicitly enabled in
`/etc/linux-usb-scanner-client.conf`:

```ini
[updates]
enabled = true
repository_url = https://github.com/cosmicc/linux-usb-scanner-client.git
branch = main
service_name = linux-usb-scanner-client.service
```

When enabled, the updater maintains a Git checkout under
`/var/lib/linux-usb-scanner-client/updates/`, fetches the configured branch,
reads its `pyproject.toml` version, and compares it to the installed package
version. If GitHub `main` has a newer version, it stops the app service, runs
the new branch's `scripts/install.sh`, and the installer restarts the app.

Security note: enabling auto-update allows a root systemd service to run the
install script from the configured repository branch. Only enable it for a
repository and branch you control.

Manual update check:

```bash
sudo /opt/linux-usb-scanner-client/venv/bin/linux-usb-scanner-client auto-update --check-only --force
```

Manual forced reinstall from the configured branch, even when versions match:

```bash
sudo /opt/linux-usb-scanner-client/venv/bin/linux-usb-scanner-client auto-update --force
```

## Uninstall

Remove only service integration:

```bash
sudo scripts/uninstall.sh
```

This preserves config, queued scans, logs, install files, and service identity.

Remove config/state/logs and service identity while preserving the app directory:

```bash
sudo scripts/uninstall.sh --purge
```

Use `--purge` only when queued scans and local configuration are no longer
needed. `/opt/linux-usb-scanner-client` is always left intact.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
PYTHONPATH=src python -m unittest discover -s tests
```

Validate shell scripts after editing installer behavior:

```bash
bash -n scripts/install.sh scripts/uninstall.sh
```
