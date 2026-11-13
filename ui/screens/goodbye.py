"""Goodbye screen with the exact paths and download method."""

from __future__ import annotations

from rich.console import Console

from core.config import InstallConfig
from steps.openvpn import OpenVPNStep
from ui.components import CreditsFooter, InfoBox
from ui.theme import SMALL_LOGO


class GoodbyeScreen:
    def __init__(self, console: Console, config: InstallConfig = None):
        self.console = console
        self.config = config

    async def run(self):
        self.console.print(f"[primary]{SMALL_LOGO}[/primary]")
        if self.config:
            example = self.config.users[0].name if self.config.users else "MHH06-01"
            self.console.print(InfoBox(
                "success", "Summary", "Your VPN is configured.",
                [
                    f"Endpoint: {self.config.remote_host}:{self.config.public_port}/{self.config.vpn_proto}",
                    f"Profiles: {', '.join(u.name for u in self.config.users)}",
                    f"Profiles directory: [path]{self.config.profiles_dir}[/path]",
                    f"Credentials file: [path]{self.config.credentials_file}[/path]",
                    f"Log: [path]/var/log/vpn-installer/install.log[/path]",
                ],
            ).render())
            self.console.print(InfoBox(
                "tip", "Commands", "Useful commands:",
                [
                    "[code]vpn-installer manage[/code] - add/revoke/rotate users",
                    "[code]vpn-installer validate[/code] - re-run checks",
                    "[code]vpn-installer doctor[/code] - diagnose problems",
                    f"[code]vpn-installer download {example}[/code] - show download options",
                    f"[code]journalctl -u {OpenVPNStep.openvpn_service_name()} -f[/code] - live VPN log",
                ],
            ).render())

        self.console.print(CreditsFooter.render())
        self.console.print()
        self.console.print("[dim]Goodbye. Your traffic is yours alone.[/dim]")
