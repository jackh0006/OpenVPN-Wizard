#!/usr/bin/env bash
# OpenVPN Wizard v2 - Linux client setup
#
# This runs on the CLIENT machine, not the VPS. It copies a profile from the
# VPS over SSH (or accepts a local file), installs OpenVPN, and creates a
# systemd service. No credentials are hardcoded.
#
# Usage:
#   sudo bash openvpn-wizard-linux.sh --server root@203.0.113.10 --profile MHH06-01
#   sudo bash openvpn-wizard-linux.sh --server root@vpn.example.com --profile MHH06-01 \
#        --user mhh06-01
#   sudo bash openvpn-wizard-linux.sh --file ./MHH06-01.ovpn
#
# For username/password profiles you will be prompted once; the password is
# written to /etc/openvpn/client/auth.txt (mode 600), never to this script.

set -euo pipefail

SERVER=""; PROFILE=""; LOCAL_FILE=""; USERNAME=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --server) SERVER="$2"; shift 2 ;;
        --profile) PROFILE="$2"; shift 2 ;;
        --file) LOCAL_FILE="$2"; shift 2 ;;
        --user) USERNAME="$2"; shift 2 ;;
        --help|-h)
            grep '^# ' "$0" | sed 's/^# //'; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
log() { echo -e "${CYAN}[*]${NC} $*"; }
ok()  { echo -e "${GREEN}[✓]${NC} $*"; }
die() { echo -e "${RED}[✗]${NC} $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root: sudo $0 ..."

if [[ -f /etc/os-release ]]; then . /etc/os-release; else die "Cannot detect OS"; fi
case "${ID:-}" in
    ubuntu|debian) apt-get update -qq && apt-get install -y -qq openvpn openssh-client ;;
    fedora|rhel|centos|rocky|almalinux) dnf install -y openvpn openssh-clients ;;
    arch|manjaro) pacman -Sy --noconfirm openvpn openssh ;;
    *) die "Unsupported distro: ${ID:-unknown}" ;;
esac

mkdir -p /etc/openvpn/client
if [[ -n "$LOCAL_FILE" ]]; then
    [[ -f "$LOCAL_FILE" ]] || die "File not found: $LOCAL_FILE"
    [[ -n "$PROFILE" ]] || PROFILE="$(basename "$LOCAL_FILE" .ovpn)"
    install -m 600 "$LOCAL_FILE" "/etc/openvpn/client/${PROFILE}.conf"
else
    [[ -n "$SERVER" && -n "$PROFILE" ]] || die "Use --file, or --server and --profile"
    command -v scp >/dev/null || die "scp is required (openssh-client)"
    log "Downloading ${PROFILE} from ${SERVER}..."
    scp -q -o StrictHostKeyChecking=accept-new \
        "${SERVER}:/etc/openvpn/clients/${PROFILE}.ovpn" \
        "/etc/openvpn/client/${PROFILE}.conf"
    chmod 600 "/etc/openvpn/client/${PROFILE}.conf"
fi

if grep -q '^auth-user-pass' "/etc/openvpn/client/${PROFILE}.conf"; then
    [[ -n "$USERNAME" ]] || read -r -p "VPN username: " USERNAME
    read -r -s -p "VPN password: " PASSWORD; echo
    [[ -n "$USERNAME" && -n "$PASSWORD" ]] || die "Username and password are required for this profile."
    printf '%s\n%s\n' "$USERNAME" "$PASSWORD" > /etc/openvpn/client/auth.txt
    chmod 600 /etc/openvpn/client/auth.txt
    # Point the profile at the local credentials file.
    if ! grep -q '^auth-user-pass /etc/openvpn/client/auth.txt' "/etc/openvpn/client/${PROFILE}.conf"; then
        sed -i 's#^auth-user-pass$#auth-user-pass /etc/openvpn/client/auth.txt#' \
            "/etc/openvpn/client/${PROFILE}.conf"
    fi
fi

systemctl daemon-reload
systemctl enable "openvpn-client@${PROFILE}.service"
systemctl restart "openvpn-client@${PROFILE}.service"

sleep 4
if ip link show tun0 >/dev/null 2>&1 || ip link show tun1 >/dev/null 2>&1; then
    ok "VPN connected."
else
    echo "[!] The service is not connected yet. Check: journalctl -u openvpn-client@${PROFILE} -f"
fi

echo
echo "Status:  systemctl status openvpn-client@${PROFILE}"
echo "Logs:    journalctl -u openvpn-client@${PROFILE} -f"
echo "Stop:    systemctl stop openvpn-client@${PROFILE}"
echo "Remove:  systemctl disable --now openvpn-client@${PROFILE} && rm /etc/openvpn/client/${PROFILE}.conf"
