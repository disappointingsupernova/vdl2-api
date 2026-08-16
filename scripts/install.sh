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
PYTHON_MAX_VERSION="3.13"  # pydantic-core wheels are not yet published for 3.14+

# Override PYTHON to use a specific interpreter, e.g.:
#   PYTHON=python3.12 sudo bash scripts/install.sh
PYTHON="${PYTHON:-python3}"

# Resolve the repository root (the directory containing this script's parent)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ---------------------------------------------------------------------------
# Privilege check
# ---------------------------------------------------------------------------
if [[ "${EUID}" -ne 0 ]]; then
    die "This script must be run as root. Try: PYTHON=${PYTHON} sudo -E bash scripts/install.sh"
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
if command -v "${PYTHON}" &>/dev/null; then
    PY_VERSION=$("${PYTHON}" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_MAJOR=$(echo "${PY_VERSION}" | cut -d. -f1)
    PY_MINOR=$(echo "${PY_VERSION}" | cut -d. -f2)
    MIN_MINOR=$(echo "${PYTHON_MIN_VERSION}" | cut -d. -f2)
    MAX_MINOR=$(echo "${PYTHON_MAX_VERSION}" | cut -d. -f2)
    if [[ "${PY_MAJOR}" -lt 3 ]] || [[ "${PY_MAJOR}" -eq 3 && "${PY_MINOR}" -lt "${MIN_MINOR}" ]]; then
        MISSING+=("python${PYTHON_MIN_VERSION}")
        warn "  Python ${PY_VERSION} found but ${PYTHON_MIN_VERSION}+ required"
    elif [[ "${PY_MAJOR}" -eq 3 && "${PY_MINOR}" -gt "${MAX_MINOR}" ]]; then
        echo ""
        error "Python ${PY_VERSION} is not supported."
        error "pydantic-core has no pre-built wheel and cannot be compiled"
        error "for Python 3.14+ (PyO3 maximum is 3.13 as of this release)."
        error ""
        # Detect distro to give the right install instructions
        if grep -qi ubuntu /etc/os-release 2>/dev/null; then
            error "On Ubuntu, use the deadsnakes PPA to install Python 3.12:"
            error "  sudo apt install software-properties-common"
            error "  sudo add-apt-repository ppa:deadsnakes/ppa"
            error "  sudo apt update"
            error "  sudo apt install python3.12 python3.12-venv"
            error "Then re-run (the -E flag preserves the PYTHON variable through sudo):"
            error "  PYTHON=python3.12 sudo -E bash scripts/install.sh"
        else
            error "On Raspberry Pi OS / Debian:"
            error "  sudo apt install python3.12 python3.12-venv"
            error "Then re-run:"
            error "  PYTHON=python3.12 sudo -E bash scripts/install.sh"
        fi
        echo ""
        die "Aborting — unsupported Python version ${PY_VERSION}."
    else
        ok "  Found: ${PYTHON} ${PY_VERSION}"
    fi
else
    MISSING+=("python3")
    warn "  Missing: ${PYTHON}"
fi

check_cmd "pip3"       "python3-pip"
check_cmd "git"        "git"
check_cmd "rsync"      "rsync"
check_cmd "dumpvdl2"   "dumpvdl2"

# python3-venv — test by actually creating a venv
if ! "${PYTHON}" -m venv --help &>/dev/null; then
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
# Mark the directory safe for git operations run as root (Git 2.35.2+
# refuses to operate in directories owned by a different user).
git config --global --add safe.directory "${INSTALL_DIR}"
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
    "${PYTHON}" -m venv "${VENV_DIR}"
    chown -R "${SERVICE_USER}:${SERVICE_USER}" "${VENV_DIR}"
    ok "  Created virtual environment at ${VENV_DIR}"
else
    ok "  Virtual environment already exists at ${VENV_DIR}"
fi

info "Installing Python dependencies..."
# Run pip as root with HOME pointed at a writable directory so the cache
# does not attempt to write to /home/vdl2 which does not exist (system user).
HOME="${INSTALL_DIR}" "${VENV_DIR}/bin/pip" install --no-cache-dir --upgrade pip
HOME="${INSTALL_DIR}" "${VENV_DIR}/bin/pip" install --no-cache-dir -r "${INSTALL_DIR}/requirements.txt"
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
