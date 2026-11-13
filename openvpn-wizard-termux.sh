#!/data/data/com.termux/files/usr/bin/bash
# OpenVPN Wizard v2 - Android/Termux profile fetcher
#
# Termux cannot create a tun device without root, so the correct Android flow
# is: download the .ovpn here and hand it to OpenVPN Connect with termux-open.
#
# Usage:
#   pkg install openssh
#   ./openvpn-wizard-termux.sh --server root@203.0.113.10 --profile MHH06-01
#
# No credentials are embedded in this script.

set -euo pipefail

SERVER=""; PROFILE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --server) SERVER="$2"; shift 2 ;;
        --profile) PROFILE="$2"; shift 2 ;;
        --help|-h) grep '^# ' "$0" | sed 's/^# //'; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

[[ -d /data/data/com.termux ]] || { echo "Run this inside Termux on Android." >&2; exit 1; }
[[ -n "$SERVER" && -n "$PROFILE" ]] || {
    echo "Usage: $0 --server root@IP --profile NAME" >&2
    exit 2
}

pkg install -y openssh >/dev/null
command -v scp >/dev/null || { echo "scp is unavailable" >&2; exit 1; }

DEST="$HOME/storage/downloads"
if [[ ! -d "$DEST" ]]; then
    echo "Grant storage access once with: termux-setup-storage"
    DEST="$HOME"
fi

TARGET="$DEST/${PROFILE}.ovpn"
[[ -e "$TARGET" ]] && { echo "$TARGET already exists; move it first." >&2; exit 1; }

echo "Downloading ${PROFILE} from ${SERVER}..."
scp -q -o StrictHostKeyChecking=accept-new \
    "${SERVER}:/etc/openvpn/clients/${PROFILE}.ovpn" "$TARGET"

grep -q '^<ca>' "$TARGET" && grep -q '^<key>' "$TARGET" || {
    rm -f "$TARGET"; echo "Downloaded file is not a valid profile." >&2; exit 1;
}
chmod 600 "$TARGET"

echo "Saved: $TARGET"
echo
echo "Open it with OpenVPN Connect:"
echo "  termux-open \"$TARGET\""
if command -v termux-open >/dev/null; then
    read -r -p "Open now? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] && termux-open "$TARGET"
fi
echo
echo "In OpenVPN Connect, import the file, then enter the username/password"
echo "shown by the installer on the VPS (certificate-only profiles skip this)."
