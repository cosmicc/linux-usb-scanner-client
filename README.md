# Linux USB Scanner Client

Headless Ubuntu service for USB keyboard-wedge barcode scanners. It reads scans
from a configured Linux input device, stores completed scans in a persistent
SQLite queue, and forwards them to
[`industrial-scanner-logger`](https://github.com/cosmicc/industrial-scanner-logger/tree/dev)
over TCP.

This is the Linux counterpart to the Windows
[`usb-scanner-client`](https://github.com/cosmicc/usb-scanner-client). It does
not provide a GUI. It is meant to run continuously under systemd and keep the
scanner ready for industrial use.

## Current Behavior

- Current version: `0.1.0`.
- Runs as `linux-usb-scanner-client.service` on Ubuntu.
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
- Avoids logging raw barcode values.

The server derives `scanner_id` from the last octet of the client computer's
IPv4 address. This client does not send a scanner ID in the payload.

All client-generated scan metadata and health timestamps are UTC ISO-8601
values ending in `Z`. The TCP protocol itself sends only barcode frames, because
that is what `industrial-scanner-logger` currently accepts. The logger remains
responsible for its own server-side receive timestamp.

## Install

From the project directory on Ubuntu:

```bash
sudo scripts/install.sh
```

The installer:

- creates a `linux-usb-scanner-client` system user and group;
- adds the service user to the `input` group so it can read `/dev/input/event*`;
- installs the app under `/opt/linux-usb-scanner-client`;
- creates a Python virtual environment;
- installs `/etc/linux-usb-scanner-client.conf` if it does not already exist;
- installs and starts `linux-usb-scanner-client.service`.

The existing config is preserved unless you run:

```bash
sudo scripts/install.sh --overwrite-config
```

## Configure the Scanner

List keyboard-like input devices:

```bash
/opt/linux-usb-scanner-client/venv/bin/linux-usb-scanner-client list-devices
```

Example output:

```text
/dev/input/event4  name='Honeywell USB Keyboard'  vendor_id=0x0c2e  product_id=0x0901  phys='usb-0000:00:14.0-1/input0'
```

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
send_timeout = 5
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
- recent scanner or server error.

Raw barcode payloads are intentionally not printed in health output.
The queue database itself contains raw scans, so installed deployments keep it
restricted to the service identity. Run health with `sudo` unless your operator
account has been intentionally granted access.

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
