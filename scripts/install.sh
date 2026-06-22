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
REQUIRED_APT_PACKAGES=(
  ca-certificates
  git
  python3
  python3-dev
  python3-pip
  python3-venv
  build-essential
  alsa-utils
)
OPTIONAL_APT_PACKAGES=(
  beep
)
MINIMUM_PYTHON_MAJOR=3
MINIMUM_PYTHON_MINOR=10

usage() {
  cat <<'USAGE'
Usage: sudo scripts/install.sh [--overwrite-config]

Installs linux-usb-scanner-client as a systemd service on Debian or Ubuntu.

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

package_installed() {
  local package="$1"
  dpkg-query -W -f='${Status}' "${package}" 2>/dev/null | grep -q "install ok installed"
}

install_debian_ubuntu_packages() {
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "apt-get is required. This installer supports Debian and Ubuntu systems." >&2
    exit 1
  fi

  local package
  local missing_required=()
  local missing_optional=()

  for package in "${REQUIRED_APT_PACKAGES[@]}"; do
    if ! package_installed "${package}"; then
      missing_required+=("${package}")
    fi
  done

  for package in "${OPTIONAL_APT_PACKAGES[@]}"; do
    if ! package_installed "${package}"; then
      missing_optional+=("${package}")
    fi
  done

  if [[ "${#missing_required[@]}" -eq 0 && "${#missing_optional[@]}" -eq 0 ]]; then
    echo "Required Debian/Ubuntu packages are already installed."
    return
  fi

  export DEBIAN_FRONTEND=noninteractive
  echo "Updating apt package lists..."
  apt-get update

  if [[ "${#missing_required[@]}" -gt 0 ]]; then
    echo "Installing required Debian/Ubuntu packages: ${missing_required[*]}"
    apt-get install -y --no-install-recommends "${missing_required[@]}"
  fi

  if [[ "${#missing_optional[@]}" -gt 0 ]]; then
    echo "Installing optional Debian/Ubuntu packages: ${missing_optional[*]}"
    if ! apt-get install -y --no-install-recommends "${missing_optional[@]}"; then
      echo "Warning: optional package install failed: ${missing_optional[*]}" >&2
      echo "The app can still run, but the matching optional alert backend may be unavailable." >&2
    fi
  fi
}

verify_python_version() {
  local current_version
  current_version="$(
    python3 - "${MINIMUM_PYTHON_MAJOR}" "${MINIMUM_PYTHON_MINOR}" <<'PY'
import sys

minimum = (int(sys.argv[1]), int(sys.argv[2]))

print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
raise SystemExit(0 if sys.version_info >= minimum else 1)
PY
  )" || {
    echo "python3 ${MINIMUM_PYTHON_MAJOR}.${MINIMUM_PYTHON_MINOR} or newer is required." >&2
    echo "Detected python3 ${current_version:-unknown}." >&2
    echo "Use Debian 12 or newer, Ubuntu 22.04 or newer, or install a supported python3 before running this installer." >&2
    exit 1
  }
}

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl is required. This installer manages systemd services." >&2
  exit 1
fi

if ! getent group input >/dev/null; then
  echo "The input group is required so the service can read /dev/input/event* devices." >&2
  echo "Create or enable the distribution's input device group before running this installer." >&2
  exit 1
fi

install_debian_ubuntu_packages
verify_python_version

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
install -o root -g root -m 0644 \
  "${INSTALL_DIR}/systemd/linux-usb-scanner-client-monitor.service" \
  "${MONITOR_UNIT_PATH}"
install -o root -g root -m 0644 \
  "${INSTALL_DIR}/systemd/linux-usb-scanner-client-update.service" \
  "${UPDATE_UNIT_PATH}"
install -o root -g root -m 0644 \
  "${INSTALL_DIR}/systemd/linux-usb-scanner-client-update.timer" \
  "${UPDATE_TIMER_PATH}"

systemctl daemon-reload
systemctl enable "${APP_NAME}.service"
systemctl enable "${APP_NAME}-monitor.service"
systemctl enable "${APP_NAME}-update.timer"
systemctl restart "${APP_NAME}-update.timer"
systemctl restart "${APP_NAME}.service"
systemctl restart "${APP_NAME}-monitor.service"

echo "Installed ${APP_NAME}."
echo "Edit ${CONFIG_PATH}, then run: sudo systemctl restart ${APP_NAME}"
echo "Check health with: sudo ${INSTALL_DIR}/venv/bin/linux-usb-scanner-client health"
echo "Auto-update timer is installed; set [updates] enabled = true in ${CONFIG_PATH} to allow updates."
echo "Alert monitor is installed; configure [alerting] in ${CONFIG_PATH} for beep behavior."
