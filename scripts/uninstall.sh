#!/usr/bin/env bash
set -euo pipefail

APP_NAME="linux-usb-scanner-client"
SERVICE_USER="linux-usb-scanner-client"
SERVICE_GROUP="linux-usb-scanner-client"
INSTALL_DIR="/opt/linux-usb-scanner-client"
CONFIG_PATH="/etc/linux-usb-scanner-client.conf"
STATE_DIR="/var/lib/linux-usb-scanner-client"
LOG_PATH="/var/log/linux-usb-scanner-client.log"
UNIT_PATH="/etc/systemd/system/linux-usb-scanner-client.service"
MONITOR_UNIT_PATH="/etc/systemd/system/linux-usb-scanner-client-monitor.service"
UPDATE_UNIT_PATH="/etc/systemd/system/linux-usb-scanner-client-update.service"
UPDATE_TIMER_PATH="/etc/systemd/system/linux-usb-scanner-client-update.timer"

usage() {
  cat <<'USAGE'
Usage: sudo scripts/uninstall.sh [--purge]

Stops and removes linux-usb-scanner-client service integration.
The app directory is always preserved.
Config, queue database, logs, and service identity are preserved by default.

Options:
  --purge      Also remove config, state, logs, and service user/group. The app directory remains.
  -h, --help   Show this help.
USAGE
}

PURGE=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --purge)
      PURGE=true
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

if [[ "${EUID}" -ne 0 ]]; then
  echo "This uninstaller must be run as root." >&2
  exit 1
fi

systemctl stop "${APP_NAME}-update.timer" 2>/dev/null || true
systemctl disable "${APP_NAME}-update.timer" 2>/dev/null || true
systemctl stop "${APP_NAME}-update.service" 2>/dev/null || true
systemctl stop "${APP_NAME}-monitor.service" 2>/dev/null || true
systemctl disable "${APP_NAME}-monitor.service" 2>/dev/null || true
systemctl stop "${APP_NAME}.service" 2>/dev/null || true
systemctl disable "${APP_NAME}.service" 2>/dev/null || true
rm -f "${UNIT_PATH}" "${MONITOR_UNIT_PATH}" "${UPDATE_UNIT_PATH}" "${UPDATE_TIMER_PATH}"
systemctl daemon-reload

if [[ "${PURGE}" == true ]]; then
  rm -rf "${STATE_DIR}"
  rm -f "${CONFIG_PATH}" "${LOG_PATH}"
  if id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    userdel "${SERVICE_USER}" || true
  fi
  if getent group "${SERVICE_GROUP}" >/dev/null; then
    groupdel "${SERVICE_GROUP}" || true
  fi
  echo "Purged ${APP_NAME} config, state, logs, and service identity."
  echo "Preserved ${INSTALL_DIR}."
else
  echo "Removed ${APP_NAME} service integration."
  echo "Preserved ${CONFIG_PATH}, ${STATE_DIR}, ${LOG_PATH}, ${INSTALL_DIR}, and service identity."
fi
