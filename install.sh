#!/usr/bin/env bash
# OpenVPN Wizard v2 - safe bootstrap installer
#
# This script only installs the Python wizard and then hands control to it.
# It does NOT write VPN or HAProxy configuration itself, and it contains no
# credentials. All deployment logic lives in the auditable Python code.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/jackh0006/OpenVPN-Wizard/main/install.sh | sudo bash
#   sudo bash install.sh --help
#   sudo bash install.sh --uninstall

set -euo pipefail

REPO_URL="${VPN_WIZARD_REPO:-https://github.com/jackh0006/OpenVPN-Wizard.git}"
SRC_DIR="${VPN_WIZARD_SRC:-/opt/openvpn-wizard-src}"
VENV_DIR="${VPN_WIZARD_VENV:-/opt/vpn-installer}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYAN}[*]${NC} $*"; }
ok()   { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
die()  { echo -e "${RED}[✗]${NC} $*" >&2; exit 1; }

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'EOF'
OpenVPN Wizard v2 bootstrap

  sudo bash install.sh                 Interactive install
  sudo bash install.sh --uninstall     Safely detach the VPN
  sudo bash install.sh --purge         Detach and delete keys/profiles
  sudo bash install.sh --plan          Render a dry-run plan only

All other arguments are passed to: vpn-installer install
For non-interactive use:
  sudo bash install.sh --non-interactive --server-ip 203.0.113.10 \
       --proto tcp --port 443 --auth userpass --access free --profiles 3
EOF
    exit 0
fi

[[ $EUID -eq 0 ]] || die "Run as root: sudo bash install.sh"

export DEBIAN_FRONTEND=noninteractive
log "Installing bootstrap dependencies (python3, venv, git)..."
apt-get update -y -qq
apt-get install -y -qq --no-install-recommends python3 python3-venv python3-pip git ca-certificates curl

if [[ -d "$SRC_DIR/.git" ]]; then
    log "Updating existing source checkout..."
    git -C "$SRC_DIR" fetch --quiet origin
    git -C "$SRC_DIR" reset --hard --quiet origin/main
else
    log "Cloning $REPO_URL..."
    rm -rf "$SRC_DIR"
    git clone --quiet --depth 1 "$REPO_URL" "$SRC_DIR"
fi

log "Preparing Python virtual environment..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet "$SRC_DIR"

ln -sf "$VENV_DIR/bin/vpn-installer" /usr/local/bin/vpn-installer
ok "Installed: $(command -v vpn-installer)"

case "${1:-}" in
    --uninstall)
        shift
        exec vpn-installer uninstall "$@"
        ;;
    --purge)
        shift
        exec vpn-installer uninstall --purge "$@"
        ;;
    --plan)
        shift
        exec vpn-installer plan "$@"
        ;;
    *)
        exec vpn-installer install "$@"
        ;;
esac
