#!/usr/bin/env bash
# Compatibility launcher for the maintained OpenVPN Wizard bootstrap.
#
# Keep this filename for existing bookmarks, but never duplicate installation
# logic here: install.sh is the single audited update path.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/install.sh" ]]; then
    exec bash "$SCRIPT_DIR/install.sh" "$@"
fi

echo "Downloading the current OpenVPN Wizard bootstrap..."
curl -fsSL https://raw.githubusercontent.com/jackh0006/OpenVPN-Wizard/main/install.sh \
    | bash -s -- "$@"
