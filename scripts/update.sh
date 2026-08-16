#!/usr/bin/env bash
# =============================================================================
# update.sh — VDL2 API update script
#
# Updates an existing VDL2 API installation by pulling the latest code from
# git and restarting the service. Must be run as root (or via sudo).
#
# Usage:
#   sudo bash /opt/vdl2-api/scripts/update.sh
#
# What this script does:
#   1. Verifies the installation and required tools exist
#   2. Stops the vdl2-api service gracefully
#   3. Backs up the current .env and database
#   4. Pulls the latest code from git (origin/main)
#   5. Updates Python dependencies
#   6. Reinstalls systemd units if they have changed
#   7. Restarts the service
#   8. Verifies the service came back up healthy
#
# The database and .env are never overwritten.
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
VENV_DIR="${INSTALL_DIR}/venv"
BACKUP_DIR="${DATA_DIR}/backups"

# ---------------------------------------------------------------------------
# Privilege check
# ---------------------------------------------------------------------------
if [[ "${EUID}" -ne 0 ]]; then
    die "This script must be run as root. Try: sudo bash ${INSTALL_DIR}/scripts/update.sh"
fi

echo ""
echo "=============================================="
echo "  VDL2 API — Update"
echo "=============================================="
echo ""

# ---------------------------------------------------------------------------
# Step 1: Verify installation and required tools
# ---------------------------------------------------------------------------
info "Verifying installation and dependencies..."

[[ -d "${INSTALL_DIR}" ]]       || die "Installation not found at ${INSTALL_DIR}. Run install.sh first."
[[ -d "${VENV_DIR}" ]]          || die "Virtual environment not found at ${VENV_DIR}. Run install.sh first."
[[ -f "${INSTALL_DIR}/.env" ]]  || die ".env not found at ${INSTALL_DIR}/.env. Run install.sh first."
[[ -d "${INSTALL_DIR}/.git" ]]  || die "${INSTALL_DIR} is not a git repository. Cannot pull updates."

ok "  Installation found at ${INSTALL_DIR}"

# Git 2.35.2+ refuses to operate in directories owned by a different user.
# Mark the install directory safe so root can run git commands in it.
git config --global --add safe.directory "${INSTALL_DIR}"

# Check required tools
for cmd in git rsync curl; do
    if ! command -v "${cmd}" &>/dev/null; then
        die "Required tool '${cmd}' not found. Install with: sudo apt install ${cmd}"
    fi
    ok "  Found: ${cmd}"
done

echo ""

# ---------------------------------------------------------------------------
# Step 2: Stop the service
# ---------------------------------------------------------------------------
info "Stopping vdl2-api.service..."

if systemctl is-active --quiet vdl2-api.service; then
    systemctl stop vdl2-api.service
    ok "  vdl2-api.service stopped"
else
    ok "  vdl2-api.service was not running"
fi

# Leave dumpvdl2 running — it writes to the spool independently and the
# collector will catch up when the API restarts.
echo ""

# ---------------------------------------------------------------------------
# Step 3: Back up .env and database
# ---------------------------------------------------------------------------
info "Creating backup..."

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="${BACKUP_DIR}/${TIMESTAMP}"
mkdir -p "${BACKUP_PATH}"

cp "${INSTALL_DIR}/.env" "${BACKUP_PATH}/.env"
ok "  Backed up .env to ${BACKUP_PATH}/.env"

DB_FILE="${DATA_DIR}/vdl2.db"
if [[ -f "${DB_FILE}" ]]; then
    # Use SQLite's online backup to get a consistent copy even if dumpvdl2
    # is still writing to the spool.
    if command -v sqlite3 &>/dev/null; then
        sqlite3 "${DB_FILE}" ".backup '${BACKUP_PATH}/vdl2.db'"
        ok "  Backed up database to ${BACKUP_PATH}/vdl2.db"
    else
        cp "${DB_FILE}" "${BACKUP_PATH}/vdl2.db"
        ok "  Copied database to ${BACKUP_PATH}/vdl2.db (sqlite3 not available for online backup)"
    fi
else
    ok "  No database found — nothing to back up"
fi

# Keep only the 5 most recent backups
BACKUP_COUNT=$(find "${BACKUP_DIR}" -maxdepth 1 -mindepth 1 -type d | wc -l)
if [[ "${BACKUP_COUNT}" -gt 5 ]]; then
    find "${BACKUP_DIR}" -maxdepth 1 -mindepth 1 -type d | sort | head -n -5 | xargs rm -rf
    ok "  Pruned old backups (keeping 5 most recent)"
fi

echo ""

# ---------------------------------------------------------------------------
# Step 4: Pull latest code from git
# ---------------------------------------------------------------------------
info "Pulling latest code from git..."

cd "${INSTALL_DIR}"

# Show what we're updating from/to
CURRENT_SHA=$(git rev-parse --short HEAD)
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
info "  Current: ${CURRENT_BRANCH} @ ${CURRENT_SHA}"

# Fetch and pull — preserve .env and any local-only files
# git will not overwrite untracked files; .env is in .gitignore
git fetch origin
git pull --ff-only origin "${CURRENT_BRANCH}"

NEW_SHA=$(git rev-parse --short HEAD)

if [[ "${CURRENT_SHA}" == "${NEW_SHA}" ]]; then
    ok "  Already up to date (${NEW_SHA})"
else
    ok "  Updated ${CURRENT_SHA} → ${NEW_SHA}"
    # Show a brief summary of what changed
    git log --oneline "${CURRENT_SHA}..${NEW_SHA}" | while read -r line; do
        info "    ${line}"
    done
fi

echo ""

# ---------------------------------------------------------------------------
# Step 5: Update Python dependencies
# ---------------------------------------------------------------------------
info "Updating Python dependencies..."

# Run pip as root with HOME pointed at the install dir so the cache does not
# attempt to write to /home/vdl2 which does not exist (system user).
HOME="${INSTALL_DIR}" "${VENV_DIR}/bin/pip" install --quiet --no-cache-dir --upgrade pip
HOME="${INSTALL_DIR}" "${VENV_DIR}/bin/pip" install --quiet --no-cache-dir -r "${INSTALL_DIR}/requirements.txt"
ok "  Python dependencies updated"
echo ""

# ---------------------------------------------------------------------------
# Step 6: Reinstall systemd units if changed
# ---------------------------------------------------------------------------
info "Checking systemd units..."

UNITS_CHANGED=false

for unit in dumpvdl2.service vdl2-api.service; do
    src="${INSTALL_DIR}/systemd/${unit}"
    dst="/etc/systemd/system/${unit}"
    if [[ ! -f "${src}" ]]; then
        warn "  Unit file not found: ${src} — skipping"
        continue
    fi
    if [[ ! -f "${dst}" ]] || ! diff -q "${src}" "${dst}" &>/dev/null; then
        cp "${src}" "${dst}"
        UNITS_CHANGED=true
        ok "  Updated ${dst}"
    else
        ok "  ${unit} unchanged"
    fi
done

if [[ "${UNITS_CHANGED}" == true ]]; then
    systemctl daemon-reload
    ok "  systemd daemon reloaded"
fi

echo ""

# ---------------------------------------------------------------------------
# Step 7: Restart the service
# ---------------------------------------------------------------------------
info "Starting vdl2-api.service..."

systemctl start vdl2-api.service
ok "  vdl2-api.service started"
echo ""

# ---------------------------------------------------------------------------
# Step 8: Health check
# ---------------------------------------------------------------------------
info "Waiting for service to become healthy..."

API_PORT=$(grep -E '^VDL2_API_PORT=' "${INSTALL_DIR}/.env" 2>/dev/null | cut -d= -f2 || echo "5001")
API_PORT="${API_PORT:-5001}"

ATTEMPTS=0
MAX_ATTEMPTS=15

until curl --silent --fail "http://localhost:${API_PORT}/api/v1/health" &>/dev/null; do
    ATTEMPTS=$((ATTEMPTS + 1))
    if [[ "${ATTEMPTS}" -ge "${MAX_ATTEMPTS}" ]]; then
        warn "  Health check did not pass after ${MAX_ATTEMPTS} seconds"
        warn "  Check service status: journalctl -u vdl2-api.service -n 50"
        break
    fi
    sleep 1
done

if [[ "${ATTEMPTS}" -lt "${MAX_ATTEMPTS}" ]]; then
    ok "  Service is healthy (responded in ${ATTEMPTS}s)"
fi

echo ""

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo "=============================================="
echo -e "  ${GREEN}Update complete${NC}"
echo "=============================================="
echo ""
echo "  Backup saved to: ${BACKUP_PATH}"
echo "  Now running:     $(git -C "${INSTALL_DIR}" rev-parse --short HEAD)"
echo ""
echo "  Service status:"
echo "    sudo systemctl status vdl2-api.service"
echo "    journalctl -u vdl2-api.service -f"
echo ""
echo "  API health:"
echo "    curl http://localhost:${API_PORT}/api/v1/health"
echo ""
