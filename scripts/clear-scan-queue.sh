#!/usr/bin/env bash
set -euo pipefail

APP_NAME="linux-usb-scanner-client"
APP_SERVICE="${APP_NAME}.service"
MONITOR_SERVICE="${APP_NAME}-monitor.service"
CONFIG_PATH="/etc/linux-usb-scanner-client.conf"
DEFAULT_DATABASE_PATH="/var/lib/linux-usb-scanner-client/scans.sqlite3"

if [[ "${EUID}" -ne 0 ]]; then
  echo "${0##*/} must be run as root. Re-run with sudo." >&2
  exit 1
fi

usage() {
  cat <<'USAGE'
Usage: sudo scripts/clear-scan-queue.sh [--yes] [--include-sent] [--config PATH]
                                      [--database PATH] [--no-restart]

Deletes queued scan payloads from the SQLite queue database. By default this
clears only pending scans and preserves sent scan metadata. The installed app
service and monitor service are stopped before the delete and restarted if they
were running.

Options:
  --yes            Skip the interactive CLEAR confirmation.
  --include-sent   Also remove sent scan metadata from the scans table.
  --config PATH    Config file path. Default: /etc/linux-usb-scanner-client.conf
  --database PATH  Queue database path. Overrides [buffer] database_path.
  --no-restart     Do not stop or restart systemd services.
  -h, --help       Show this help.
USAGE
}

ASSUME_YES=false
INCLUDE_SENT=false
DATABASE_PATH=""
RESTART_SERVICES=true
APP_WAS_ACTIVE=false
MONITOR_WAS_ACTIVE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes)
      ASSUME_YES=true
      shift
      ;;
    --include-sent)
      INCLUDE_SENT=true
      shift
      ;;
    --config)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --config" >&2
        exit 2
      fi
      CONFIG_PATH="$2"
      shift 2
      ;;
    --database)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --database" >&2
        exit 2
      fi
      DATABASE_PATH="$2"
      shift 2
      ;;
    --no-restart)
      RESTART_SERVICES=false
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to clear the SQLite queue safely." >&2
  exit 1
fi

resolve_database_path() {
  python3 - "${CONFIG_PATH}" "${DATABASE_PATH}" "${DEFAULT_DATABASE_PATH}" <<'PY'
from __future__ import annotations

import configparser
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
database_override = sys.argv[2]
default_database_path = sys.argv[3]

if database_override:
    print(Path(database_override))
    raise SystemExit(0)

parser = configparser.ConfigParser()
read_files = parser.read(config_path)
if not read_files:
    print(f"Unable to read config file: {config_path}", file=sys.stderr)
    raise SystemExit(1)

print(parser.get("buffer", "database_path", fallback=default_database_path).strip())
PY
}

unit_loaded() {
  local unit="$1"
  [[ "$(systemctl show "${unit}" --property=LoadState --value 2>/dev/null || true)" == "loaded" ]]
}

stop_services() {
  if [[ "${RESTART_SERVICES}" != true || ! -d /run/systemd/system ]]; then
    return
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    return
  fi

  if unit_loaded "${MONITOR_SERVICE}" && systemctl is-active --quiet "${MONITOR_SERVICE}"; then
    MONITOR_WAS_ACTIVE=true
    echo "Stopping ${MONITOR_SERVICE}..."
    systemctl stop "${MONITOR_SERVICE}"
  fi
  if unit_loaded "${APP_SERVICE}" && systemctl is-active --quiet "${APP_SERVICE}"; then
    APP_WAS_ACTIVE=true
    echo "Stopping ${APP_SERVICE}..."
    systemctl stop "${APP_SERVICE}"
  fi
}

restart_services() {
  local status=$?
  trap - EXIT

  if [[ "${APP_WAS_ACTIVE}" == true ]]; then
    echo "Starting ${APP_SERVICE}..."
    systemctl start "${APP_SERVICE}" || status=1
  fi
  if [[ "${MONITOR_WAS_ACTIVE}" == true ]]; then
    echo "Starting ${MONITOR_SERVICE}..."
    systemctl start "${MONITOR_SERVICE}" || status=1
  fi

  exit "${status}"
}

clear_queue() {
  python3 - "${RESOLVED_DATABASE_PATH}" "${INCLUDE_SENT}" <<'PY'
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

database_path = Path(sys.argv[1])
include_sent = sys.argv[2] == "true"

if not database_path.exists():
    print(f"No queue database found: {database_path}")
    raise SystemExit(0)
if not database_path.is_file():
    print(f"Queue database path is not a file: {database_path}", file=sys.stderr)
    raise SystemExit(1)

timestamp = (
    datetime.now(timezone.utc)
    .replace(microsecond=0)
    .isoformat()
    .replace("+00:00", "Z")
)
conn = sqlite3.connect(database_path, timeout=30)
conn.row_factory = sqlite3.Row
try:
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'scans'"
    ).fetchone()
    if table is None:
        print(f"No scans table found in {database_path}; nothing to clear.")
        raise SystemExit(0)

    pending_count = int(
        conn.execute("SELECT COUNT(*) FROM scans WHERE status = 'pending'").fetchone()[0]
    )
    sent_count = int(
        conn.execute("SELECT COUNT(*) FROM scans WHERE status = 'sent'").fetchone()[0]
    )

    with conn:
        if include_sent:
            deleted = int(conn.execute("DELETE FROM scans").rowcount)
        else:
            deleted = int(
                conn.execute("DELETE FROM scans WHERE status = 'pending'").rowcount
            )

        status_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'service_status'"
        ).fetchone()
        if status_table is not None:
            values = {
                "queue_last_cleared_at": timestamp,
                "queue_last_cleared_pending_count": str(pending_count),
                "queue_last_cleared_sent_count": str(sent_count if include_sent else 0),
            }
            conn.executemany(
                """
                INSERT INTO service_status(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key)
                DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                [(key, value, timestamp) for key, value in values.items()],
            )

    conn.execute("VACUUM")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
finally:
    conn.close()

if include_sent:
    print(f"Deleted {deleted} scan rows from {database_path}.")
else:
    print(f"Deleted {deleted} pending scan rows from {database_path}.")
    print(f"Preserved {sent_count} sent scan metadata rows.")
PY
}

RESOLVED_DATABASE_PATH="$(resolve_database_path)"

if [[ "${ASSUME_YES}" != true ]]; then
  echo "This permanently deletes queued scan payloads from:"
  echo "  ${RESOLVED_DATABASE_PATH}"
  if [[ "${INCLUDE_SENT}" == true ]]; then
    echo "Sent scan metadata will also be removed."
  else
    echo "Only pending scans will be removed; sent scan metadata is preserved."
  fi
  echo "Type CLEAR to continue:"
  read -r confirmation
  if [[ "${confirmation}" != "CLEAR" ]]; then
    echo "Aborted."
    exit 1
  fi
fi

trap restart_services EXIT
stop_services
clear_queue
echo "Scan queue clear complete."
