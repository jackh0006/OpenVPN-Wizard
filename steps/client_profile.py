"""
Step: generate one standard .ovpn profile per user and a root-only
credentials sheet.

Profiles are written with mode 600 inside a mode-700 directory.  Nothing is
served over HTTP.  Distribution happens over SSH/SCP or the explicit one-shot
HTTPS command (``vpn-installer download --serve``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

from core.config import InstallConfig, sanitize_profile_name
from core.render import utc_now
from management.profile_gen import ProfileGenerator
from steps.base import BaseStep


class ClientProfileStep(BaseStep):
    @property
    def name(self) -> str:
        return "client_profile"

    @property
    def display_name(self) -> str:
        return "Generate .ovpn profiles"

    @property
    def description(self) -> str:
        return "One unique certificate/key per user; standard OpenVPN Connect compatible files"

    async def is_already_done(self, config: InstallConfig) -> bool:
        return False

    async def execute(self, config: InstallConfig,
                      output_callback: Callable[[str], None] = None) -> bool:
        def log(msg: str):
            if output_callback:
                output_callback(msg)
            self.logger.info(msg)

        profiles_dir = Path(config.profiles_dir)
        profiles_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(profiles_dir, 0o700)

        log("Rendering client profiles from the per-user certificates...")
        generator = ProfileGenerator(config)
        paths = generator.save_all(profiles_dir)
        for path in paths:
            log(f"  ✓ {path.name} ({path.stat().st_size} bytes, mode 600)")

        self._write_credentials(config)
        self._write_manifest(config)
        self._install_helper()

        log(f"{len(paths)} profile(s) ready in {profiles_dir}")
        return True

    def _write_credentials(self, config: InstallConfig) -> None:
        path = Path(config.credentials_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# OpenVPN Wizard v2 - VPN credentials",
            f"# Generated: {utc_now()}",
            f"# Server: {config.remote_host}:{config.public_port}/{config.vpn_proto}",
            "# Keep this file private (mode 600). Delete it after distributing",
            "# credentials to the users. It is never served over the network.",
            "",
        ]
        for user in config.users:
            lines.extend([
                f"Profile:  {sanitize_profile_name(user.name)}",
                f"File:     {config.profiles_dir}/{sanitize_profile_name(user.name)}.ovpn",
                f"Username: {user.username}",
            ])
            if config.auth_mode == "userpass":
                lines.append(f"Password: {user.password}")
            else:
                lines.append("Password: (not used - certificate-only profile)")
            lines.append("")
        self._atomic_write(path, "\n".join(lines), 0o600)

    def _write_manifest(self, config: InstallConfig) -> None:
        manifest = {
            "generated_at": utc_now(),
            "endpoint": config.remote_host,
            "port": config.public_port,
            "proto": config.vpn_proto,
            "auth_mode": config.auth_mode,
            "access_mode": config.access_mode,
            "profiles": [
                {
                    "name": u.name,
                    "username": u.username,
                    "cert_name": u.safe_cert_name,
                    "file": f"{config.profiles_dir}/{sanitize_profile_name(u.name)}.ovpn",
                }
                for u in config.users
            ],
        }
        path = Path(config.profiles_dir) / "manifest.json"
        self._atomic_write(path, json.dumps(manifest, indent=2) + "\n", 0o600)

    def _install_helper(self) -> None:
        helper = """#!/usr/bin/env bash
# Installed by OpenVPN Wizard v2. Runs on the VPS.
set -euo pipefail
DIR="/etc/openvpn/clients"
cmd="${1:-list}"
case "$cmd" in
  list)
    ls -1 "$DIR"/*.ovpn 2>/dev/null | sed 's#.*/##; s/\\.ovpn$//' || true
    ;;
  show)
    name="${2:?Usage: ovpn-show show <profile>}"
    [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || { echo "Invalid name" >&2; exit 1; }
    cat "$DIR/$name.ovpn"
    ;;
  path)
    name="${2:?Usage: ovpn-show path <profile>}"
    [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || { echo "Invalid name" >&2; exit 1; }
    echo "$DIR/$name.ovpn"
    ;;
  scp)
    name="${2:?Usage: ovpn-show scp <profile>}"
    ip="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
    echo "scp root@${ip}:$DIR/$name.ovpn ~/Downloads/"
    ;;
  *)
    echo "Usage: ovpn-show [list|show <profile>|path <profile>|scp <profile>]" >&2
    exit 2
    ;;
esac
"""
        path = Path("/usr/local/bin/ovpn-show")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(path, helper, 0o755)
        except OSError as exc:
            self.logger.warning("Could not install /usr/local/bin/ovpn-show: %s", exc)

    @staticmethod
    def _atomic_write(path: Path, content: str, mode: int) -> None:
        tmp = path.with_name(path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
        os.chmod(path, mode)

    async def rollback(self, config: InstallConfig, rollback_data: dict) -> bool:
        for user in config.users:
            path = Path(config.profiles_dir) / f"{sanitize_profile_name(user.name)}.ovpn"
            path.unlink(missing_ok=True)
        Path(config.credentials_file).unlink(missing_ok=True)
        return True
