#!/usr/bin/env bash
set -euo pipefail

APP_NAME="linux-usb-scanner-client"
APP_SERVICE="${APP_NAME}.service"
MONITOR_SERVICE="${APP_NAME}-monitor.service"
UPDATE_SERVICE="${APP_NAME}-update.service"
UPDATE_TIMER="${APP_NAME}-update.timer"
UNITS=(
  "${APP_SERVICE}"
  "${MONITOR_SERVICE}"
  "${UPDATE_SERVICE}"
  "${UPDATE_TIMER}"
)

if [[ "${EUID}" -ne 0 ]]; then
  echo "${0##*/} must be run as root. Re-run with sudo." >&2
  exit 1
fi

usage() {
  cat <<'USAGE'
Usage: sudo scripts/restart-services.sh [--run-update-check]

Reloads systemd and restarts the installed linux-usb-scanner-client units that
are expected to stay active: the scanner service, alert monitor service, and
auto-update timer.

Options:
  --run-update-check   Also run the root-owned one-shot auto-update service.
  -h, --help           Show this help.
USAGE
}

RUN_UPDATE_CHECK=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-update-check)
      RUN_UPDATE_CHECK=true
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

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl is required. This helper restarts systemd units." >&2
  exit 1
fi

unit_property() {
  local unit="$1"
  local property="$2"
  systemctl show "${unit}" --property="${property}" --value 2>/dev/null || true
}

require_loaded_unit() {
  local unit="$1"
  local load_state
  load_state="$(unit_property "${unit}" LoadState)"
  if [[ "${load_state}" != "loaded" ]]; then
    echo "Required unit is not loaded: ${unit}" >&2
    echo "Install or reinstall ${APP_NAME} before running this helper." >&2
    exit 1
  fi
}

restart_unit() {
  local unit="$1"
  echo "Restarting ${unit}..."
  systemctl restart "${unit}"
}

verify_active_unit() {
  local unit="$1"
  if ! systemctl is-active --quiet "${unit}"; then
    echo "Restart failed: ${unit} is not active." >&2
    systemctl --no-pager --full status "${unit}" >&2 || true
    exit 1
  fi
}

verify_update_service_result() {
  local result
  result="$(unit_property "${UPDATE_SERVICE}" Result)"
  if [[ "${result}" != "success" ]]; then
    echo "Auto-update check failed: ${UPDATE_SERVICE} result=${result:-unknown}." >&2
    systemctl --no-pager --full status "${UPDATE_SERVICE}" >&2 || true
    exit 1
  fi
}

print_unit_summary() {
  local unit
  local active_state
  local sub_state
  local enabled_state
  local result

  printf "\n%-45s %-12s %-12s %-12s %s\n" "Unit" "Active" "Sub" "Enabled" "Result"
  for unit in "${UNITS[@]}"; do
    active_state="$(unit_property "${unit}" ActiveState)"
    sub_state="$(unit_property "${unit}" SubState)"
    enabled_state="$(unit_property "${unit}" UnitFileState)"
    result="$(unit_property "${unit}" Result)"
    printf "%-45s %-12s %-12s %-12s %s\n" \
      "${unit}" \
      "${active_state:-unknown}" \
      "${sub_state:-unknown}" \
      "${enabled_state:-unknown}" \
      "${result:-unknown}"
  done
}

echo "Reloading systemd manager configuration..."
systemctl daemon-reload

for unit in "${UNITS[@]}"; do
  require_loaded_unit "${unit}"
done

echo "Resetting failed unit state..."
systemctl reset-failed "${UNITS[@]}" 2>/dev/null || true

restart_unit "${UPDATE_TIMER}"
restart_unit "${APP_SERVICE}"
restart_unit "${MONITOR_SERVICE}"

if [[ "${RUN_UPDATE_CHECK}" == true ]]; then
  echo "Running ${UPDATE_SERVICE} once..."
  systemctl restart "${UPDATE_SERVICE}"
  verify_update_service_result
else
  echo "Skipping ${UPDATE_SERVICE}; use --run-update-check to run the one-shot updater."
fi

verify_active_unit "${UPDATE_TIMER}"
verify_active_unit "${APP_SERVICE}"
verify_active_unit "${MONITOR_SERVICE}"

print_unit_summary
echo
echo "Restart complete. Run full diagnostics with: sudo /opt/${APP_NAME}/scripts/check-health.sh"
