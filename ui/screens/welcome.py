"""
Welcome Screen - Hero screen with philosophy and credits.
"""

from rich.console import Console
from rich.panel import Panel
from rich.align import Align

from ui.theme import get_console, LOGO
from ui.components import InfoBox, CreditsFooter


class WelcomeScreen:
    """Welcome/hero screen."""

    def __init__(self, console: Console = None):
        self.console = console or get_console()

    async def run(self) -> bool:
        """Run the welcome screen. Returns True to continue, False to exit."""
        self._show_welcome()
        return await self._get_choice()

    def _show_welcome(self):
        """Display the welcome screen."""
        self.console.clear()

        # Main logo
        self.console.print(f"[primary]{LOGO}[/primary]")

        # Philosophy box
        philosophy = InfoBox(
            "tip",
            "Our Philosophy",
            "We build tools that respect your privacy. No tracking. No phones home. Ever.",
            [
                "🔒 Your data stays on YOUR server",
                "🔍 Zero telemetry, zero analytics",
                "📖 Completely open source (MIT licensed)",
                "🛡️ Designed for maximum stealth & security",
                "⚡ Optimized for speed & reliability",
            ]
        )
        self.console.print()
        self.console.print(philosophy.render())

        # What this installs
        features = InfoBox(
            "info",
            "What This Installs",
            "A hardened OpenVPN stack that asks exactly what you need",
            [
                "🔐 OpenVPN - AES-256-GCM, TLS 1.2+, tls-crypt",
                "🔑 Easy-RSA PKI - ECDSA P-384, one unique key per user",
                "👤 Certificate + password, or certificate-only",
                "🌐 TCP or UDP, domain or IP, any port",
                "🔓 Free full tunnel, or locked private-network-only",
                "🎯 HAProxy - optional, append-only, never rewrites your config",
                "🧱 Firewall - only the required rules; IPv6 untouched",
                "📦 SQLite metadata - PBKDF2 hashes only, never private keys",
            ]
        )
        self.console.print(features.render())

        # Architecture diagram
        arch = Panel(
            Align.center(
                "[bold]Client[/bold] → [primary]TCP/443[/primary] → [bold]HAProxy[/bold] (optional)\n\n"
                "    ├─ no TLS ClientHello → [success]OpenVPN[/success] (127.0.0.1:1194)\n"
                "    ├─ known SNI → [info]optional VLESS/Reality[/info] (loopback)\n"
                "    └─ anything else → [success]OpenVPN[/success]\n\n"
                "[dim]UDP binds directly. HAProxy gets one marked, reversible block;\n"
                "your existing configuration is never replaced.[/dim]"
            ),
            title="[primary]🏗️ Architecture[/primary]",
            border_style="primary",
            padding=(1, 2),
        )
        self.console.print()
        self.console.print(arch)

        # Credits
        self.console.print()
        self.console.print(CreditsFooter.render())

    async def _get_choice(self) -> bool:
        """Get user choice to continue or exit."""
        self.console.print()
        self.console.print("[primary]1.[/primary] [bold]Continue[/bold] [dim]- Start installation[/dim]")
        self.console.print("[primary]2.[/primary] [bold]Exit[/bold] [dim]- Quit installer[/dim]")

        while True:
            try:
                choice = self.console.input("\n[primary]Your choice [1-2]: [/primary]").strip()
                if choice in ("1", "c", "C", "continue"):
                    return True
                elif choice in ("2", "e", "E", "exit", "quit"):
                    self.console.print("\n[dim]Goodbye! Your privacy matters.[/dim]")
                    return False
                else:
                    self.console.print("[error]Invalid choice. Enter 1 or 2.[/error]")
            except (KeyboardInterrupt, EOFError):
                return False