"""
Success screen: exact download commands, profile list, and next steps.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.align import Align

from core.config import InstallConfig
from core.state import InstallState
from ui.components import CreditsFooter, InfoBox, SectionHeader


class SuccessScreen:
    def __init__(self, console: Console, config: InstallConfig, state: InstallState):
        self.console = console
        self.config = config
        self.state = state

    async def run(self):
        self.console.clear()
        self.console.print(SectionHeader(6, 6, "Installation complete", "🎉").render())
        self.console.print(Panel(
            Align.center(
                "[bold success]✅ Your VPN is ready[/bold success]\n\n"
                f"[primary]{self.config.remote_host}:{self.config.public_port}/"
                f"{self.config.vpn_proto}[/primary]  •  "
                f"{len(self.config.users)} profile(s)"
            ),
            border_style="success", padding=(1, 2),
        ))

        self._profile_table()
        self._download_help()
        self._security_notes()

        self.console.print()
        self.console.print(CreditsFooter.render())
        self.console.print()
        self.console.print("[dim]Press Enter to continue...[/dim]")
        try:
            self.console.input()
        except (KeyboardInterrupt, EOFError):
            pass

    def _profile_table(self):
        table = Table(show_header=True, header_style="primary", box=None, padding=(0, 1))
        table.add_column("#", width=3)
        table.add_column("Profile", width=22)
        table.add_column("Username", width=18)
        table.add_column("File", width=44)
        for i, user in enumerate(self.config.users, 1):
            table.add_row(
                str(i), user.name, user.username,
                str(Path(self.config.profiles_dir) / f"{user.name}.ovpn"),
            )
        self.console.print()
        self.console.print(Panel(table, title="[primary]Profiles[/primary]",
                                 border_style="primary"))

        self.console.print(InfoBox(
            "security", "Credentials file",
            "Usernames and passwords are stored only in a root-only file:",
            [f"[path]{self.config.credentials_file}[/path] (mode 600)",
             "Delete it after distributing credentials."],
        ).render())

    def _download_help(self):
        example = self.config.users[0].name if self.config.users else "MHH06-01"
        host = self.config.remote_host
        path = f"/etc/openvpn/clients/{example}.ovpn"
        lines = [
            "[bold]Linux / macOS / WSL[/bold] (runs on your device):",
            f"  [code]scp root@{host}:{path} ~/Downloads/[/code]",
            "",
            "[bold]Windows PowerShell[/bold]:",
            f"  [code]scp root@{host}:{path} $env:USERPROFILE\\Downloads\\[/code]",
            "",
            "[bold]Android (Termux)[/bold]:",
            f"  [code]scp root@{host}:{path} ~/storage/downloads/[/code]",
            "",
            "[bold]Any device with a browser (one-time HTTPS link)[/bold]:",
            f"  [code]sudo vpn-installer download {example} --serve[/code]",
            "  Prints a random token URL that works once, then shuts down.",
            "",
            f"[dim]A helper for your local machine is in scripts/download-ovpn.sh "
            f"(and .ps1 for Windows).[/dim]",
        ]
        self.console.print()
        self.console.print(Panel("\n".join(lines), title="[primary]Download[/primary]",
                                 border_style="primary", padding=(1, 2)))

    def _security_notes(self):
        notes = [
            "Import the .ovpn into OpenVPN Connect (Android/iOS), OpenVPN GUI "
            "(Windows) or Tunnelblick (macOS).",
            "Each profile has a different certificate and key. Revoking one user "
            "does not affect the others.",
            "Usernames/passwords are only used when authentication is "
            "certificate + password; certificate-only profiles skip the prompt.",
            "Test on a phone on mobile data (not the same Wi-Fi as the VPS) to "
            "confirm the path through your ISP works.",
        ]
        if self.config.vpn_proto == "tcp":
            notes.append(
                "TCP is robust through firewalls but can feel slower on lossy "
                "links (TCP-over-TCP). If throughput matters, re-run with UDP."
            )
        self.console.print(InfoBox("tip", "Good to know", "A few honest notes:",
                                   notes).render())
        self.console.print(InfoBox(
            "warning", "What this can and cannot hide",
            "Traffic is encrypted and authenticated end-to-end, and TCP/443 "
            "blends in with HTTPS at the port level. No VPN can guarantee "
            "invisibility to a determined DPI system that blocks unknown "
            "protocols; VLESS/Reality (optional) is the stronger anti-DPI path.",
        ).render())
