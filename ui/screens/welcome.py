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

        philosophy = InfoBox(
            "tip",
            "Before you begin",
            "You choose where people connect, then name each profile.",
            [
                "1. Choose the server address and port",
                "2. Add a name, username and password for every person or device",
                "3. Review the plan before anything is changed",
            ],
        )
        self.console.print()
        self.console.print(philosophy.render())

        features = InfoBox(
            "info",
            "What you get",
            "A conventional OpenVPN setup with separate access for every profile.",
            [
                "🔑 A different certificate and key for every profile",
                "👤 Certificate + password, or certificate-only",
                "🌐 TCP or UDP, domain or IP, and your chosen port",
                "🧾 A clear review screen before installation",
            ],
        )
        self.console.print(features.render())

        arch = Panel(
            Align.center(
                "[bold]Your device[/bold]  →  [primary]your address and port[/primary]  →  "
                "[success]your VPN[/success]\n\n"
                "[dim]Optional HAProxy uses a clearly marked block.\n"
                "The review screen lists every planned change.[/dim]"
            ),
            title="[primary]Connection path[/primary]",
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
