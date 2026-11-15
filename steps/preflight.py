"""Read-only safety gate that runs before packages, firewall, or HAProxy."""

from __future__ import annotations
from typing import Callable
from core.config import InstallConfig
from core.exceptions import HAProxyConflictError, PortConflictError
from steps.base import BaseStep
from utils.haproxy import HAProxyManager
from utils.net import inspect_port


class PreflightStep(BaseStep):
    @property
    def name(self) -> str:
        return "preflight"

    @property
    def display_name(self) -> str:
        return "Safety preflight (read-only)"

    @property
    def description(self) -> str:
        return "Check ports and HAProxy compatibility before changing anything"

    async def execute(
        self, config: InstallConfig, output_callback: Callable[[str], None] = None
    ) -> bool:
        def report(message: str) -> None:
            self.logger.info(message)
            if output_callback:
                output_callback(message)

        public = inspect_port(config.public_port)
        if config.use_haproxy:
            if public.tcp_owner and "haproxy" not in public.tcp_owner.lower():
                raise PortConflictError(config.public_port, public.description)
            strategy = HAProxyManager(config).describe()
            if strategy["action"] == "conflict":
                raise HAProxyConflictError(
                    f"HAProxy cannot safely use TCP {config.public_port}: {strategy['reason']}",
                    fix_hint="Choose another --port. No file or service was changed.",
                )
            report(f"Preflight: HAProxy action is {strategy['action']} ({strategy['reason']}).")
        elif (
            not public.available and "openvpn" not in (public.tcp_owner + public.udp_owner).lower()
        ):
            raise PortConflictError(config.public_port, public.description)
        backend = inspect_port(config.openvpn_listen_port)
        if (
            config.use_haproxy
            and not backend.available
            and "openvpn" not in (backend.tcp_owner + backend.udp_owner).lower()
        ):
            raise PortConflictError(config.openvpn_listen_port, backend.description)
        report("Preflight passed: no unrelated process will be changed.")
        return True
