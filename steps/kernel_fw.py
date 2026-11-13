"""
Step: firewall, NAT and kernel tuning (idempotent, non-destructive).
"""

from __future__ import annotations

from typing import Callable

from core.config import InstallConfig
from steps.base import BaseStep
from utils.firewall import FirewallManager


class KernelFWStep(BaseStep):
    @property
    def name(self) -> str:
        return "kernel_fw"

    @property
    def display_name(self) -> str:
        return "Open ports and tune the system"

    @property
    def description(self) -> str:
        return "Add only the required firewall rules; enable forwarding only for free mode"

    async def is_already_done(self, config: InstallConfig) -> bool:
        return False

    async def execute(self, config: InstallConfig,
                      output_callback: Callable[[str], None] = None) -> bool:
        def log(msg: str):
            if output_callback:
                output_callback(msg)
            self.logger.info(msg)

        if not config.wan_interface:
            from utils.firewall import detect_wan_interface
            config.wan_interface = detect_wan_interface()
            log(f"WAN interface: {config.wan_interface}")

        manager = FirewallManager(config)
        actions = manager.apply()

        if actions.get("ufw"):
            log(f"UFW rules added: {', '.join(actions['ufw'])}")
        if actions.get("iptables"):
            log(f"iptables rules added: {', '.join(actions['iptables'])}")
        if actions.get("sysctl"):
            log(f"Kernel settings applied: {', '.join(actions['sysctl'])}")
        for warning in actions.get("warnings", []):
            log(f"  ⚠ {warning}")

        log(f"  ✓ {config.vpn_proto.upper()}/{config.public_port} is open; existing rules untouched")
        if config.free_tunnel:
            log("  ✓ Full-tunnel NAT enabled (clients can reach the internet)")
        else:
            log("  ✓ Locked mode: no NAT; clients cannot use this VPS as an exit node")
        return True

    async def rollback(self, config: InstallConfig, rollback_data: dict) -> bool:
        FirewallManager(config).remove()
        return True
