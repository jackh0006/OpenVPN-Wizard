"""
Step: enable and verify the services that this configuration actually uses.
"""

from __future__ import annotations

import asyncio
import socket
from typing import Callable, List, Tuple

from core.config import InstallConfig
from core.exceptions import ServiceError
from steps.base import BaseStep
from steps.openvpn import OpenVPNStep


class ServicesStep(BaseStep):
    @property
    def name(self) -> str:
        return "services"

    @property
    def display_name(self) -> str:
        return "Start and verify services"

    @property
    def description(self) -> str:
        return "OpenVPN, plus HAProxy and 3X-UI only when configured"

    def services(self, config: InstallConfig) -> List[Tuple[str, str]]:
        items = [(OpenVPNStep.openvpn_service_name(), "OpenVPN")]
        if config.use_haproxy:
            items.append(("haproxy", "HAProxy"))
        if config.enable_vless:
            items.append(("x-ui", "3X-UI"))
        return items

    async def is_already_done(self, config: InstallConfig) -> bool:
        return all(self._is_service_active(svc) for svc, _ in self.services(config))

    async def execute(self, config: InstallConfig,
                      output_callback: Callable[[str], None] = None) -> bool:
        def log(msg: str):
            if output_callback:
                output_callback(msg)
            self.logger.info(msg)

        for service, display in self.services(config):
            log(f"Enabling {display} ({service})...")
            enable = self._run_cmd(["systemctl", "enable", service], check=False)
            if enable.returncode != 0:
                raise ServiceError(
                    f"Service unit not found: {service}",
                    service=service,
                    fix_hint=(
                        "Install the matching package (haproxy/openvpn/x-ui) and "
                        "run 'systemctl daemon-reload'. Nothing was changed."
                    ),
                )
            start = self._run_cmd(["systemctl", "restart", service], check=False)
            await asyncio.sleep(2)
            if start.returncode != 0 or not self._is_service_active(service):
                journal = self._run_cmd(
                    ["journalctl", "-u", service, "-n", "40", "--no-pager"], check=False
                )
                raise ServiceError(
                    f"{display} failed to start.\n{(journal.stdout or '')[-2000:]}",
                    service=service,
                    fix_hint=f"Run: systemctl status {service} --no-pager -l",
                )
            log(f"  ✓ {display} is active")

        await self._verify_listeners(config, log)
        return True

    async def _verify_listeners(self, config: InstallConfig, log) -> None:
        if config.use_haproxy:
            await self._wait_tcp(config.public_port, "127.0.0.1", "HAProxy public listener", log)
            await self._wait_tcp(config.internal_port, "127.0.0.1", "OpenVPN loopback", log)
        else:
            if config.vpn_proto == "udp":
                await self._wait_udp(config.public_port, "OpenVPN UDP", log)
            else:
                await self._wait_tcp(config.public_port, "127.0.0.1", "OpenVPN public listener", log)

        if config.enable_vless:
            for port, name in (
                (config.xui_inbound1_port, "VLESS-TLS 1"),
                (config.xui_tls2_port, "VLESS-TLS 2"),
                (config.xui_inbound2_port, "VLESS-Reality"),
            ):
                await self._wait_tcp(port, "127.0.0.1", name, log, required=False)

    async def _wait_tcp(self, port: int, host: str, name: str, log,
                        required: bool = True, attempts: int = 12) -> None:
        for _ in range(attempts):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    if sock.connect_ex((host, port)) == 0:
                        log(f"  ✓ {name} listening on {host}:{port}")
                        return
            except OSError:
                pass
            await asyncio.sleep(1)
        if required:
            raise ServiceError(
                f"{name} is not listening on {host}:{port}",
                service="openvpn" if "OpenVPN" in name else "haproxy",
                fix_hint=(
                    f"Check 'ss -ltnp | grep :{port}' and the service journal. "
                    "Another process may own the port."
                ),
            )
        log(f"  ⚠ {name} did not answer on {host}:{port} yet")

    async def _wait_udp(self, port: int, name: str, log, attempts: int = 12) -> None:
        for _ in range(attempts):
            result = self._run_cmd(["ss", "-lunH", f"sport = :{port}"], check=False)
            if result.returncode == 0 and result.stdout.strip():
                log(f"  ✓ {name} listening on UDP/{port}")
                return
            await asyncio.sleep(1)
        raise ServiceError(
            f"{name} is not listening on UDP/{port}",
            service="openvpn",
            fix_hint=f"Check 'ss -lunp | grep :{port}' and journalctl -u openvpn@server",
        )
