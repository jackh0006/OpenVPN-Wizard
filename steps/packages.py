"""
Step: install only the packages this configuration needs.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable, List

from core.config import InstallConfig
from core.exceptions import SystemError
from steps.base import BaseStep


class PackagesStep(BaseStep):
    @property
    def name(self) -> str:
        return "packages"

    @property
    def display_name(self) -> str:
        return "Install system packages"

    @property
    def description(self) -> str:
        return "OpenVPN, Easy-RSA, iptables and (when needed) HAProxy/3X-UI"

    def packages(self, config: InstallConfig) -> List[str]:
        pkgs = [
            "openvpn",
            "easy-rsa",
            "openssl",
            "iptables",
            "iptables-persistent",
            "curl",
            "ca-certificates",
            "qrencode",
            "socat",
            "net-tools",
            "iproute2",
        ]
        if config.use_haproxy:
            pkgs.append("haproxy")
        if config.enable_vless:
            pkgs.extend(["sqlite3", "certbot"])
        return pkgs

    async def is_already_done(self, config: InstallConfig) -> bool:
        for pkg in self.packages(config):
            if self._run_cmd(["dpkg", "-s", pkg], check=False).returncode != 0:
                return False
        return shutil.which("openvpn") is not None and (
            not config.use_haproxy or shutil.which("haproxy") is not None
        )

    async def execute(self, config: InstallConfig,
                      output_callback: Callable[[str], None] = None) -> bool:
        def log(msg: str):
            if output_callback:
                output_callback(msg)
            self.logger.info(msg)

        env = dict(os.environ)
        env["DEBIAN_FRONTEND"] = "noninteractive"

        # Prevent debconf from asking questions about saving iptables rules.
        self._run_cmd([
            "bash", "-c",
            "echo 'iptables-persistent iptables-persistent/autosave_v4 boolean true' | debconf-set-selections; "
            "echo 'iptables-persistent iptables-persistent/autosave_v6 boolean true' | debconf-set-selections",
        ], env=env, check=False)

        log("Updating package index...")
        self._run_cmd(["apt-get", "update", "-y"], env=env, timeout=600)

        missing = [
            pkg for pkg in self.packages(config)
            if self._run_cmd(["dpkg", "-s", pkg], check=False).returncode != 0
        ]
        if missing:
            log("Installing: " + ", ".join(missing))
            result = self._run_cmd(
                ["apt-get", "install", "-y", "--no-install-recommends", *missing],
                env=env, timeout=1800, check=False,
            )
            if result.returncode != 0:
                raise SystemError(
                    "Package installation failed.\n" + (result.stderr or "")[-2000:],
                    command="apt-get install " + " ".join(missing),
                    fix_hint=(
                        "Check internet access and whether another apt/dpkg process "
                        "is running ('sudo fuser /var/lib/dpkg/lock-frontend'). "
                        "No existing VPN configuration was touched."
                    ),
                )
        else:
            log("All required packages are already installed")

        if config.enable_vless:
            await self._install_xui(log)

        for name, path in (("openvpn", "openvpn"), ("openssl", "openssl"),
                           ("easy-rsa", "/usr/share/easy-rsa/easyrsa")):
            found = Path(path).exists() if path.startswith("/") else shutil.which(path)
            if not found:
                raise SystemError(
                    f"{name} is missing after installation",
                    fix_hint=f"Run: apt-get install -y {name}",
                )
            log(f"  ✓ {name}: {path}")
        if config.use_haproxy and not shutil.which("haproxy"):
            raise SystemError(
                "haproxy is missing after installation",
                fix_hint="Run: apt-get install -y haproxy",
            )
        log("Packages ready")
        return True

    async def _install_xui(self, log) -> None:
        if shutil.which("x-ui"):
            log("  ✓ 3X-UI already installed")
            return
        log("Installing 3X-UI (optional VLESS/Reality support)...")
        result = self._run_cmd([
            "bash", "-c",
            "curl -fsSL https://raw.githubusercontent.com/MHSanaei/3x-ui/master/install.sh "
            "| bash -s -- --version v2.5.3",
        ], timeout=900, check=False)
        if result.returncode != 0 or not shutil.which("x-ui"):
            raise SystemError(
                "3X-UI installation failed.\n" + (result.stderr or "")[-1500:],
                command="3X-UI install script",
                fix_hint=(
                    "Retry, or disable VLESS (run without --enable-vless). "
                    "OpenVPN itself is unaffected."
                ),
            )
        log("  ✓ 3X-UI installed")
