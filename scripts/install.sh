#!/usr/bin/env bash
# =============================================================================
# install.sh — VDL2 API installation script
#
# Installs the VDL2 API service on a Raspberry Pi or Debian/Ubuntu host.
# Must be run as root (or via sudo).
#
# Usage:
#   sudo bash scripts/install.sh
#
# What this script does:
#   1. Checks all system dependencies are present
#   2. Creates the vdl2 system user and data directory
#   3. Installs the application to /opt/vdl2-api
#   4. Creates a Python virtual environment and installs dependencies
#   5. Creates /opt/vdl2-api/.env from .env.example if not already present
#   6. Installs and enables the systemd service units
#   7. Prints next steps
#
# The script is idempotent — running it again on an existing installation
# will update the application files and reinstall dependencies without
# destroying the database or .env configuration.
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()     { error "$*"; exit 1; }

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
INSTALL_DIR="/opt/vdl2-api"
DATA_DIR="/var/lib/vdl2"
SERVICE_USER="vdl2"
PYTHON_MIN_VERSION="3.11"

# Resolve the repository root (the directory containing this script's parent)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ---------------------------------------------------------------------------
# Privilege check
# ---------------------------------------------------------------------------
if [[ "${EUID}" -ne 0 ]]; then
    die "This script must be run as root. Try: sudo bash scripts/install.sh"
fi

echo ""
echo "=============================================="
echo "  VDL2 API — Installation"
echo "=============================================="
echo ""

# ---------------------------------------------------------------------------
# Step 1: Check system dependencies
# ---------------------------------------------------------------------------
info "Checking system dependencies..."

MISSING=()

check_cmd() {
    local cmd="$1"
    local pkg="${2:-$1}"
    if ! command -v "${cmd}" &>/dev/null; then
        MISSING+=("${pkg}")
        warn "  Missing: ${cmd} (install: apt install ${pkg})"
    else
        ok "  Found: ${cmd} ($(command -v "${cmd}"))"
    fi
}

# Python — check version meets minimum
if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_MAJOR=$(echo "${PY_VERSION}" | cut -d. -f1)
    PY_MINOR=$(echo "${PY_VERSION}" | cut -d. -f2)
    MIN_MINOR=$(echo "${PYTHON_MIN_VERSION}" | cut -d. -f2)
    if [[ "${PY_MAJOR}" -lt 3 ]] || [[ "${PY_MAJOR}" -eq 3 && "${PY_MINOR}" -lt "${MIN_MINOR}" ]]; then
        MISSING+=("python${PYTHON_MIN_VERSION}")
        warn "  Python ${PY_VERSION} found but ${PYTHON_MIN_VERSION}+ required"
    else
        ok "  Found: python3 ${PY_VERSION}"
    fi
else
    MISSING+=("python3")
    warn "  Missing: python3"
fi

check_cmd "pip3"       "python3-pip"
check_cmd "git"        "git"
check_cmd "dumpvdl2"   "dumpvdl2"

# python3-venv — test by actually creating a venv
if ! python3 -m venv --help &>/dev/null; then
    MISSING+=("python3-venv")
    warn "  Missing: python3-venv module"
else
    ok "  Found: python3-venv"
fi

if [[ ${#MISSING[@]} -gt 0 ]]; then
    echo ""
    error "The following dependencies are missing:"
    for pkg in "${MISSING[@]}"; do
        error "  - ${pkg}"
    done
    echo ""
    error "Install them with:"
    error "  sudo apt update && sudo apt install ${MISSING[*]}"
    echo ""
    die "Aborting installation."
fi

ok "All system dependencies present."
echo ""

# ---------------------------------------------------------------------------
# Step 2: Create system user and data directory
# ---------------------------------------------------------------------------
info "Setting up system user and data directory..."

if id "${SERVICE_USER}" &>/dev/null; then
    ok "  User '${SERVICE_USER}' already exists"
else
    useradd --system --shell /usr/sbin/nologin --no-create-home "${SERVICE_USER}"
    ok "  Created system user '${SERVICE_USER}'"
fi

if [[ ! -d "${DATA_DIR}" ]]; then
    mkdir -p "${DATA_DIR}"
    ok "  Created data directory ${DATA_DIR}"
else
    ok "  Data directory ${DATA_DIR} already exists"
fi

chown "${SERVICE_USER}:${SERVICE_USER}" "${DATA_DIR}"
chmod 750 "${DATA_DIR}"
ok "  Permissions set on ${DATA_DIR}"

# Allow vdl2 user to access RTL-SDR devices
if getent group plugdev &>/dev/null; then
    usermod -aG plugdev "${SERVICE_USER}"
    ok "  Added '${SERVICE_USER}' to plugdev group (RTL-SDR access)"
else
    warn "  plugdev group not found — RTL-SDR device access may need manual configuration"
fi

echo ""

# ---------------------------------------------------------------------------
# Step 3: Install application files
# ---------------------------------------------------------------------------
info "Installing application to ${INSTALL_DIR}..."

if [[ ! -d "${INSTALL_DIR}" ]]; then
    mkdir -p "${INSTALL_DIR}"
    ok "  Created ${INSTALL_DIR}"
fi

# Copy application files from the repository
rsync -a --delete \
    --exclude='.git' \
    --exclude='.env' \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.egg-info' \
    "${REPO_DIR}/" "${INSTALL_DIR}/"

chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"
ok "  Application files copied to ${INSTALL_DIR}"
echo ""

# ---------------------------------------------------------------------------
# Step 4: Create virtual environment and install Python dependencies
# ---------------------------------------------------------------------------
info "Setting up Python virtual environment..."

VENV_DIR="${INSTALL_DIR}/venv"

if [[ ! -d "${VENV_DIR}" ]]; then
    sudo -u "${SERVICE_USER}" python3 -m venv "${VENV_DIR}"
    ok "  Created virtual environment at ${VENV_DIR}"
else
    ok "  Virtual environment already exists at ${VENV_DIR}"
fi

info "Installing Python dependencies..."
sudo -u "${SERVICE_USER}" "${VENV_DIR}/bin/pip" install --quiet --upgrade pip
sudo -u "${SERVICE_USER}" "${VENV_DIR}/bin/pip" install --quiet -r "${INSTALL_DIR}/requirements.txt"
ok "  Python dependencies installed"
echo ""

# ---------------------------------------------------------------------------
# Step 5: Create .env configuration file
# ---------------------------------------------------------------------------
info "Checking environment configuration..."

ENV_FILE="${INSTALL_DIR}/.env"

if [[ -f "${ENV_FILE}" ]]; then
    ok "  ${ENV_FILE} already exists — not overwriting"
    warn "  Review ${ENV_FILE} to ensure settings are correct"
else
    cp "${INSTALL_DIR}/.env.example" "${ENV_FILE}"
    chown "${SERVICE_USER}:${SERVICE_USER}" "${ENV_FILE}"
    chmod 640 "${ENV_FILE}"
    ok "  Created ${ENV_FILE} from .env.example"
    warn "  Edit ${ENV_FILE} before starting the service"
fi

echo ""

# ---------------------------------------------------------------------------
# Step 6: Install systemd units
# ---------------------------------------------------------------------------
info "Installing systemd service units..."

for unit in dumpvdl2.service vdl2-api.service; do
    src="${INSTALL_DIR}/systemd/${unit}"
    dst="/etc/systemd/system/${unit}"
    if [[ ! -f "${src}" ]]; then
        warn "  Unit file not found: ${src} — skipping"
        continue
    fi
    cp "${src}" "${dst}"
    ok "  Installed ${dst}"
done

systemctl daemon-reload
ok "  systemd daemon reloaded"
echo ""

# ---------------------------------------------------------------------------
# Step 7: Enable services (but do not start — operator must configure first)
# ---------------------------------------------------------------------------
info "Enabling services for automatic start on boot..."

systemctl enable dumpvdl2.service
ok "  Enabled dumpvdl2.service"

systemctl enable vdl2-api.service
ok "  Enabled vdl2-api.service"

echo ""

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo "=============================================="
echo -e "  ${GREEN}Installation complete${NC}"
echo "=============================================="
echo ""
echo "Next steps:"
echo ""
echo "  1. Edit the configuration file:"
echo "       sudo nano ${ENV_FILE}"
echo ""
echo "  2. Start the services:"
echo "       sudo systemctl start dumpvdl2.service"
echo "       sudo systemctl start vdl2-api.service"
echo ""
echo "  3. Check service status:"
echo "       sudo systemctl status dumpvdl2.service"
echo "       sudo systemctl status vdl2-api.service"
echo "       journalctl -u vdl2-api.service -f"
echo ""
echo "  4. Test the API:"
echo "       curl http://localhost:5001/api/v1/health"
echo ""
