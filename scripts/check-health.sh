#!/usr/bin/env bash
set -uo pipefail

APP_NAME="linux-usb-scanner-client"
CONFIG_PATH="/etc/linux-usb-scanner-client.conf"
INSTALLED_CLIENT="/opt/linux-usb-scanner-client/venv/bin/linux-usb-scanner-client"
LOG_PATH="/var/log/linux-usb-scanner-client.log"
UNIT_NAMES=(
  "linux-usb-scanner-client.service"
  "linux-usb-scanner-client-monitor.service"
  "linux-usb-scanner-client-update.timer"
  "linux-usb-scanner-client-update.service"
)

if [[ "${EUID}" -ne 0 ]]; then
  echo "${0##*/} must be run as root. Re-run with sudo." >&2
  exit 1
fi

usage() {
  cat <<'USAGE'
Usage: sudo scripts/check-health.sh [--config PATH]

Summarizes linux-usb-scanner-client health, USB input-device visibility,
server connection state, queue state, scan totals, alert monitor state, and
systemd units.

Options:
  --config PATH   Config file path. Default: /etc/linux-usb-scanner-client.conf
  -h, --help      Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --config" >&2
        exit 2
      fi
      CONFIG_PATH="$2"
      shift 2
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

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
HEALTH_JSON="$(mktemp)"
DEVICES_JSON="$(mktemp)"
trap 'rm -f "${HEALTH_JSON}" "${DEVICES_JSON}"' EXIT

CLIENT_CMD=()
if [[ -x "${INSTALLED_CLIENT}" ]]; then
  CLIENT_CMD=("${INSTALLED_CLIENT}")
elif [[ -x "${REPO_DIR}/.venv/bin/linux-usb-scanner-client" ]]; then
  CLIENT_CMD=("${REPO_DIR}/.venv/bin/linux-usb-scanner-client")
elif [[ -d "${REPO_DIR}/src" ]] && command -v python3 >/dev/null 2>&1; then
  CLIENT_CMD=(env "PYTHONPATH=${REPO_DIR}/src" python3 -m linux_usb_scanner_client)
else
  echo "Unable to find ${APP_NAME} CLI." >&2
  echo "Install the app or run this script from the project checkout with python3 available." >&2
  exit 2
fi

format_command() {
  local rendered=""
  local arg
  for arg in "${CLIENT_CMD[@]}"; do
    rendered+="$(printf "%q" "${arg}") "
  done
  printf "%s" "${rendered% }"
}

run_client() {
  "${CLIENT_CMD[@]}" --config "${CONFIG_PATH}" "$@"
}

print_header() {
  printf "\n== %s ==\n" "$1"
}

unit_property() {
  local unit="$1"
  local property="$2"
  systemctl show "${unit}" --property="${property}" --value 2>/dev/null || true
}

unit_state_is_ok() {
  local unit="$1"
  local active_state
  active_state="$(unit_property "${unit}" ActiveState)"
  case "${unit}" in
    *.timer)
      [[ "${active_state}" == "active" ]]
      ;;
    *.service)
      if [[ "${unit}" == *"-update.service" ]]; then
        [[ "${active_state}" == "inactive" || "${active_state}" == "active" ]]
      else
        [[ "${active_state}" == "active" ]]
      fi
      ;;
    *)
      [[ "${active_state}" == "active" ]]
      ;;
  esac
}

print_units() {
  print_header "Systemd Units"
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl: unavailable"
    return 1
  fi

  local unit
  local active_state
  local sub_state
  local enabled_state
  local result
  local all_ok=0
  for unit in "${UNIT_NAMES[@]}"; do
    active_state="$(unit_property "${unit}" ActiveState)"
    sub_state="$(unit_property "${unit}" SubState)"
    enabled_state="$(unit_property "${unit}" UnitFileState)"
    result="$(unit_property "${unit}" Result)"
    printf "%-45s active=%-10s sub=%-10s enabled=%-10s result=%s\n" \
      "${unit}" \
      "${active_state:-unknown}" \
      "${sub_state:-unknown}" \
      "${enabled_state:-unknown}" \
      "${result:-unknown}"
    if ! unit_state_is_ok "${unit}"; then
      all_ok=1
    fi
  done
  return "${all_ok}"
}

print_health_summary() {
  python3 - "${HEALTH_JSON}" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
queue = data.get("queue", {})
storage = data.get("storage", {})

def value(name, default="unknown"):
    item = data.get(name)
    if item is None or item == "":
        return default
    return item

def yes_no(flag):
    return "yes" if flag else "no"

rows = [
    ("Overall", value("overall_status")),
    ("Config", value("config_path")),
    ("Service running", yes_no(data.get("service_running"))),
    ("Heartbeat age", f"{data['heartbeat_age_seconds']:.1f}s" if data.get("heartbeat_age_seconds") is not None else "unknown"),
    ("USB scanner", f"{value('scanner_state')} ({'available' if data.get('scanner_available') else 'unavailable'})"),
    ("Scanner device", f"{value('scanner_device_name')} {value('scanner_device_path', '')}".strip()),
    ("Server", f"{value('server_state')} ({'connected' if data.get('server_connected') else 'not connected'}) {value('server_target', '')}".strip()),
    ("Queue pending", str(queue.get("pending_count", "unknown"))),
    ("Queue oldest pending", str(queue.get("oldest_pending_at") or "none")),
    ("Queue max attempts", str(queue.get("max_attempts", "unknown"))),
    ("Storage free", f"{storage.get('free_bytes', 'unknown')} bytes"),
    ("Storage low space", yes_no(storage.get("low_space"))),
    ("Alert monitor", value("monitor_state")),
    ("Alert pattern", value("monitor_alert", "none")),
    ("Alert beeps", str(value("monitor_alert_beeps", "none"))),
    ("Auto update", value("update_state")),
    ("Last scan", value("last_scan_at", "none")),
    ("Last delivery", value("last_delivery_at", "none")),
    ("Last error", value("last_error", "none")),
]
for label, item in rows:
    print(f"{label + ':':<22} {item}")

warnings = data.get("warnings") or []
if warnings:
    print("Warnings:")
    for warning in warnings:
        print(f"  - {warning}")
PY
}

print_devices() {
  print_header "USB Scanner/Input Devices"
  local devices_status=0
  run_client list-devices --json >"${DEVICES_JSON}" 2>"${DEVICES_JSON}.err" || devices_status=$?
  if [[ "${devices_status}" -ne 0 ]]; then
    echo "Unable to list keyboard-like input devices."
    if [[ -s "${DEVICES_JSON}.err" ]]; then
      sed 's/^/  /' "${DEVICES_JSON}.err"
    fi
    rm -f "${DEVICES_JSON}.err"
    return "${devices_status}"
  fi
  rm -f "${DEVICES_JSON}.err"
  python3 - "${DEVICES_JSON}" <<'PY'
import json
import sys
from pathlib import Path

devices = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not devices:
    print("No keyboard-like USB/input devices found.")
    raise SystemExit(1)
for device in devices:
    print(
        f"{device.get('path', 'unknown')}: "
        f"name={device.get('name', 'unknown')!r} "
        f"vendor_id={device.get('vendor_id', 'unknown')} "
        f"product_id={device.get('product_id', 'unknown')}"
    )
PY
}

print_scan_totals() {
  print_header "Scan Totals"
  python3 - "${CONFIG_PATH}" <<'PY'
import configparser
import sqlite3
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

DEFAULT_DATABASE_PATH = Path("/var/lib/linux-usb-scanner-client/scans.sqlite3")

config_path = Path(sys.argv[1])
parser = configparser.ConfigParser()
if not parser.read(config_path):
    print(f"Unable to read config: {config_path}")
    raise SystemExit(1)

database_path = Path(
    parser.get("buffer", "database_path", fallback=str(DEFAULT_DATABASE_PATH))
)
if not database_path.exists():
    print(f"{database_path}: missing")
    raise SystemExit(1)

today = datetime.now(timezone.utc).date()
yesterday = today - timedelta(days=1)


def utc_bounds(day):
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return (
        start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def count_for_day(connection, day):
    start, end = utc_bounds(day)
    row = connection.execute(
        """
        SELECT COUNT(*) AS scan_count
        FROM scans
        WHERE captured_at >= ?
          AND captured_at < ?
        """,
        (start, end),
    ).fetchone()
    return int(row[0])


try:
    database_uri = database_path.resolve(strict=False).as_uri() + "?mode=ro"
    with sqlite3.connect(database_uri, uri=True) as connection:
        print(f"Database: {database_path}")
        print(f"Today ({today.isoformat()} UTC): {count_for_day(connection, today)}")
        print(
            f"Yesterday ({yesterday.isoformat()} UTC): "
            f"{count_for_day(connection, yesterday)}"
        )
except sqlite3.Error as exc:
    print(f"Unable to count scans in {database_path}: {exc}")
    raise SystemExit(1)
PY
}

print_log_status() {
  print_header "Log File"
  if [[ -e "${LOG_PATH}" ]]; then
    ls -lh "${LOG_PATH}"
  else
    echo "${LOG_PATH}: missing"
    return 1
  fi
}

main() {
  local health_status=0
  local unit_status=0
  local device_status=0
  local totals_status=0
  local log_status=0

  echo "${APP_NAME} health check"
  echo "Time: $(date -Is)"
  echo "CLI: $(format_command)"
  echo "Config: ${CONFIG_PATH}"

  print_header "App Health"
  run_client health --json >"${HEALTH_JSON}" 2>"${HEALTH_JSON}.err" || health_status=$?
  if [[ -s "${HEALTH_JSON}" ]]; then
    print_health_summary
  else
    echo "Unable to build health report."
  fi
  if [[ -s "${HEALTH_JSON}.err" ]]; then
    echo "Health command stderr:"
    sed 's/^/  /' "${HEALTH_JSON}.err"
  fi
  rm -f "${HEALTH_JSON}.err"

  print_units || unit_status=$?
  print_devices || device_status=$?
  print_scan_totals || totals_status=$?
  print_log_status || log_status=$?

  print_header "Result"
  if [[ "${health_status}" -eq 0 && "${unit_status}" -eq 0 && "${device_status}" -eq 0 && "${totals_status}" -eq 0 && "${log_status}" -eq 0 ]]; then
    echo "OK"
    return 0
  fi
  echo "One or more checks failed or reported a degraded state."
  echo "Exit details: health=${health_status} units=${unit_status} devices=${device_status} totals=${totals_status} log=${log_status}"
  return 1
}

main "$@"
