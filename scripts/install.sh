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

usage() {
  cat <<'USAGE'
Usage: sudo scripts/install.sh [--overwrite-config]

Installs linux-usb-scanner-client as a systemd service.

Options:
  --overwrite-config   Replace /etc/linux-usb-scanner-client.conf with the template.
  -h, --help           Show this help.
USAGE
}

OVERWRITE_CONFIG=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --overwrite-config)
      OVERWRITE_CONFIG=true
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
  echo "This installer must be run as root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required." >&2
  exit 1
}

if ! getent group "${SERVICE_GROUP}" >/dev/null; then
  groupadd --system "${SERVICE_GROUP}"
fi

if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
  useradd \
    --system \
    --gid "${SERVICE_GROUP}" \
    --groups input \
    --home-dir "${STATE_DIR}" \
    --shell /usr/sbin/nologin \
    "${SERVICE_USER}"
else
  usermod -a -G input "${SERVICE_USER}"
fi

install -d -o root -g root -m 0755 "${INSTALL_DIR}"
install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0750 "${STATE_DIR}"
touch "${LOG_PATH}"
chown "${SERVICE_USER}:${SERVICE_GROUP}" "${LOG_PATH}"
chmod 0640 "${LOG_PATH}"

tar -C "${REPO_DIR}" \
  --exclude './.git' \
  --exclude './.venv' \
  --exclude './__pycache__' \
  --exclude '*/__pycache__' \
  --exclude '*.pyc' \
  -cf - . | tar -C "${INSTALL_DIR}" -xf -

python3 -m venv "${INSTALL_DIR}/venv"
"${INSTALL_DIR}/venv/bin/python" -m pip install --upgrade pip
"${INSTALL_DIR}/venv/bin/python" -m pip install -r "${INSTALL_DIR}/requirements.txt"
"${INSTALL_DIR}/venv/bin/python" -m pip install -e "${INSTALL_DIR}"

if [[ "${OVERWRITE_CONFIG}" == true || ! -f "${CONFIG_PATH}" ]]; then
  install -o root -g "${SERVICE_GROUP}" -m 0640 \
    "${INSTALL_DIR}/config/linux-usb-scanner-client.conf" \
    "${CONFIG_PATH}"
else
  echo "Preserving existing ${CONFIG_PATH}"
fi

install -o root -g root -m 0644 \
  "${INSTALL_DIR}/systemd/linux-usb-scanner-client.service" \
  "${UNIT_PATH}"

systemctl daemon-reload
systemctl enable "${APP_NAME}.service"
systemctl restart "${APP_NAME}.service"

echo "Installed ${APP_NAME}."
echo "Edit ${CONFIG_PATH}, then run: sudo systemctl restart ${APP_NAME}"
echo "Check health with: sudo ${INSTALL_DIR}/venv/bin/linux-usb-scanner-client health"
