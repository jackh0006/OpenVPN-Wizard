#!/usr/bin/env bash
# Download a .ovpn profile from your VPS into your local Downloads folder.
#
# This script runs on YOUR device (Linux/macOS/WSL), not on the VPS.
#
# Usage:
#   ./download-ovpn.sh root@203.0.113.10 MHH06-01
#   ./download-ovpn.sh root@vpn.example.com MHH06-01 ~/Downloads
#
# It uses scp (SSH), so nothing extra is exposed on the VPS and the profile is
# encrypted in transit by SSH. It verifies the downloaded file before keeping
# it and refuses to overwrite an existing file.

set -euo pipefail

SERVER="${1:-}"
PROFILE="${2:-}"
DEST="${3:-$HOME/Downloads}"

if [[ -z "$SERVER" || -z "$PROFILE" ]]; then
    echo "Usage: $0 user@server profile-name [download-directory]" >&2
    echo "Example: $0 root@203.0.113.10 MHH06-01" >&2
    exit 2
fi

if ! command -v scp >/dev/null 2>&1; then
    echo "ERROR: scp is not installed. Install the OpenSSH client first." >&2
    exit 1
fi

mkdir -p "$DEST"
TARGET="$DEST/${PROFILE}.ovpn"
if [[ -e "$TARGET" ]]; then
    echo "ERROR: $TARGET already exists. Move it away first." >&2
    exit 1
fi

REMOTE="/etc/openvpn/clients/${PROFILE}.ovpn"
echo "Downloading $PROFILE from $SERVER ..."
scp -q -o StrictHostKeyChecking=accept-new "$SERVER:$REMOTE" "$TARGET"

if ! grep -q '^<ca>' "$TARGET" || ! grep -q '^<key>' "$TARGET"; then
    echo "ERROR: downloaded file does not look like a valid .ovpn profile." >&2
    rm -f "$TARGET"
    exit 1
fi

chmod 600 "$TARGET"
echo "Saved: $TARGET"
echo
echo "Import this file into OpenVPN Connect (Android/iOS), OpenVPN GUI"
echo "(Windows) or Tunnelblick (macOS). Then connect using the username"
echo "and password shown by the installer."
