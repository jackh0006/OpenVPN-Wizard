"""
Step: attach the VPN to HAProxy without disturbing existing config.
"""

from __future__ import annotations

from typing import Callable

from core.config import InstallConfig
from steps.base import BaseStep
from utils.haproxy import HAProxyManager


class HAProxyStep(BaseStep):
    @property
    def name(self) -> str:
        return "haproxy"

    @property
    def display_name(self) -> str:
        return "Add VPN listener to HAProxy"

    @property
    def description(self) -> str:
        return "Append a marked, reversible frontend/backend block; never rewrite other config"

    async def is_already_done(self, config: InstallConfig) -> bool:
        return False

    async def execute(self, config: InstallConfig,
                      output_callback: Callable[[str], None] = None) -> bool:
        def log(msg: str):
            if output_callback:
                output_callback(msg)
            self.logger.info(msg)

        if not config.use_haproxy:
            log("HAProxy not used for this transport; nothing to change")
            return True

        log(f"Checking HAProxy config at {config.haproxy_cfg}...")
        manager = HAProxyManager(config)
        result = manager.apply()
        if result.reused_existing:
            log("Existing HAProxy frontend already routes non-TLS traffic to OpenVPN; no changes")
            return True
        if not result.changed:
            log("HAProxy configuration already contains the correct VPN block")
            return True
        if result.migrated_v1:
            log("Migrated the old v1 HAProxy layout (backup kept)")
        action = "inserted an additive route and backend" if result.inserted_route else "added the managed block"
        log(f"HAProxy: {action}; backup: {result.backup or 'none'}")
        log("  ✓ HAProxy reloaded; all pre-existing sections were preserved")
        return True

    async def rollback(self, config: InstallConfig, rollback_data: dict) -> bool:
        manager = HAProxyManager(config)
        return manager.remove()
