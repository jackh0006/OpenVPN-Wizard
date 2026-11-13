"""
Step: render and activate the OpenVPN server configuration.

Behind HAProxy the daemon binds only to 127.0.0.1.  In UDP (or --no-haproxy)
mode it binds the public port directly.  The step never leaves a broken
config live: it validates statically, restarts systemd, and restores the
previous file if the daemon does not come up.
"""

from __future__ import annotations

import asyncio
import glob
import shutil
import time
from pathlib import Path
from typing import Callable

from core.config import InstallConfig
from core.exceptions import ServiceError, SystemError
from core.render import render_server_conf, validate_rendered_server, utc_now
from steps.base import BaseStep

OPENVPN_MARKER = "# OpenVPN Wizard v2 - server configuration"


class OpenVPNStep(BaseStep):
    @property
    def name(self) -> str:
        return "openvpn"

    @property
    def display_name(self) -> str:
        return "Configure OpenVPN server"

    @property
    def description(self) -> str:
        return "AEAD ciphers, TLS 1.2+, tls-crypt, CRL, PAM or certificate-only auth"

    async def is_already_done(self, config: InstallConfig) -> bool:
        # Always re-render: this is fast and guarantees settings chosen in the
        # wizard are actually applied (ports, protocol, auth, access policy).
        return False

    async def execute(self, config: InstallConfig,
                      output_callback: Callable[[str], None] = None) -> bool:
        def log(msg: str):
            if output_callback:
                output_callback(msg)
            self.logger.info(msg)

        conf_path = Path(config.openvpn_dir) / "server.conf"
        conf_path.parent.mkdir(parents=True, exist_ok=True)
        Path("/var/log/openvpn").mkdir(parents=True, exist_ok=True)
        Path("/var/lib/openvpn").mkdir(parents=True, exist_ok=True)
        Path("/run/openvpn").mkdir(parents=True, exist_ok=True)
        try:
            import os
            os.chmod("/var/log/openvpn", 0o750)
            os.chmod("/var/lib/openvpn", 0o755)
            os.chmod(config.openvpn_dir, 0o750)
        except OSError:
            pass

        pam_plugin = self._find_pam_plugin() if config.auth_mode == "userpass" else None
        log("Rendering server configuration...")
        rendered = render_server_conf(config, pam_plugin=pam_plugin)

        problems = validate_rendered_server(rendered, config, self.logger)
        if problems:
            raise SystemError(
                "Generated OpenVPN config failed validation: " + "; ".join(problems),
                fix_hint="Re-run 'vpn-installer doctor'. No live file was changed.",
            )

        backup = None
        if conf_path.exists():
            backup = Path(config.backup_dir) / (
                f"openvpn-server.conf.{time.strftime('%Y%m%d-%H%M%S')}"
            )
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(conf_path, backup)
            log(f"Backup created: {backup}")

        log("Writing server configuration...")
        self._write_file(str(conf_path), rendered, mode=0o600, backup=False)

        log("Installing systemd hardening drop-in...")
        self._install_hardening(config)

        log("Restarting OpenVPN...")
        service = self.openvpn_service_name()
        restart = self._run_cmd(["systemctl", "restart", service], check=False)
        await asyncio.sleep(2)
        if restart.returncode != 0 or not self._is_service_active(service):
            status = self._run_cmd(
                ["systemctl", "status", service, "--no-pager", "-l"], check=False
            )
            journal = self._run_cmd(
                ["journalctl", "-u", service, "-n", "60", "--no-pager"], check=False
            )
            if backup and backup.exists():
                shutil.copy2(backup, conf_path)
                self._run_cmd(["systemctl", "restart", service], check=False)
                restored = " The previous configuration was restored."
            else:
                restored = " No previous configuration existed."
            raise ServiceError(
                f"OpenVPN did not start with the new configuration.{restored}\n"
                f"{(journal.stdout or status.stdout or '')[-2500:]}",
                service=service,
                fix_hint=(
                    "Common causes: a certificate/key mismatch, port already in "
                    "use, or an invalid line in a pre-existing file. Check "
                    f"'journalctl -u {service} -n 100 --no-pager'."
                ),
            )

        # Verify the listener rather than trusting systemd alone.
        if config.vpn_proto == "udp":
            listening = await self._wait_for_udp_port(config.openvpn_listen_port)
        else:
            listening = await self._wait_for_port(
                config.openvpn_listen_port, config.openvpn_bind_address
            )
        if not listening:
            raise ServiceError(
                f"OpenVPN is active but not listening on "
                f"{config.openvpn_bind_address}:{config.openvpn_listen_port}.",
                service=service,
                fix_hint=(
                    "Check for another process on that port with "
                    f"'ss -ltnup | grep :{config.openvpn_listen_port}'."
                ),
            )

        log(f"  ✓ OpenVPN active on {config.openvpn_bind_address}:{config.openvpn_listen_port}")
        return True

    # ── Helpers ──────────────────────────────────────────────────────────

    def _find_pam_plugin(self) -> str:
        candidates = glob.glob("/usr/lib/*/openvpn/plugins/openvpn-plugin-auth-pam.so")
        candidates += glob.glob("/usr/lib/openvpn/openvpn-plugin-auth-pam.so")
        if not candidates:
            raise SystemError(
                "OpenVPN PAM authentication plugin was not found.",
                command="openvpn-plugin-auth-pam.so",
                fix_hint=(
                    "Install it with: apt-get install -y openvpn "
                    "(the plugin ships with the openvpn package on Ubuntu)."
                ),
            )
        return candidates[0]

    @staticmethod
    def openvpn_service_name() -> str:
        """Ubuntu/Debian use openvpn@server; upstream uses openvpn-server@server."""
        for base in ("/lib/systemd/system", "/usr/lib/systemd/system"):
            if Path(base, "openvpn@.service").exists():
                return "openvpn@server"
            if Path(base, "openvpn-server@.service").exists():
                return "openvpn-server@server"
        return "openvpn@server"

    def _install_hardening(self, config: InstallConfig) -> None:
        service = self.openvpn_service_name()
        unit = service.split("@", 1)[0] + "@.service"
        dropin_dir = Path("/etc/systemd/system") / f"{unit}.d"
        dropin_dir.mkdir(parents=True, exist_ok=True)
        content = f"""# Managed by OpenVPN Wizard v2 ({utc_now()})
[Service]
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
RestrictRealtime=yes
RemoveIPC=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK
ReadWritePaths=/var/log/openvpn /var/lib/openvpn /run/openvpn
"""
        path = dropin_dir / "10-openvpn-wizard.conf"
        if not path.exists() or path.read_text() != content:
            path.write_text(content)
        self._run_cmd(["systemctl", "daemon-reload"], check=False)

    async def _wait_for_port(self, port: int, host: str, attempts: int = 15) -> bool:
        import socket
        for _ in range(attempts):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    if sock.connect_ex((host, port)) == 0:
                        return True
            except OSError:
                pass
            await asyncio.sleep(1)
        return False

    async def _wait_for_udp_port(self, port: int, attempts: int = 15) -> bool:
        for _ in range(attempts):
            result = self._run_cmd(
                ["ss", "-lunH", f"sport = :{port}"], check=False
            )
            if result.returncode == 0 and result.stdout.strip():
                return True
            await asyncio.sleep(1)
        return False
