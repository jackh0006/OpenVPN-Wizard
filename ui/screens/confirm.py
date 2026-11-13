"""
Step-by-Step Confirmation Screen - Ask before doing anything.
"""

from typing import List, Tuple
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.align import Align

from ui.components import ConfirmAction, CreditsFooter, SectionHeader
from core.config import InstallConfig


class ConfirmScreen:
    """Step-by-step confirmation with explanations."""

    STEP_DETAILS = {
        "packages": {
            "what": "Install required system packages (HAProxy, OpenVPN, Easy-RSA, 3X-UI, etc.)",
            "why": "These are the building blocks. Without them, nothing works.",
            "files": [
                "/etc/apt/sources.list (package sources)",
                "/var/lib/dpkg/ (package database)",
            ],
            "rollback": "Packages can be removed with apt-get purge",
            "time": "~30-60 seconds",
            "warning": "Requires internet access to download packages",
        },
        "haproxy": {
            "what": "Append a marked VPN frontend/backend block to HAProxy",
            "why": "HAProxy can share a TCP port between the VPN and TLS traffic. Existing config stays byte-for-byte intact.",
            "files": [
                "/etc/haproxy/haproxy.cfg (append-only marked block)",
                "/var/backups/vpn-installer/ (timestamped backup)",
            ],
            "rollback": "Only the marked block is removed; a failed test restores the backup",
            "time": "~3 seconds",
            "warning": "Refuses to touch a port already owned by another frontend",
        },
        "xui": {
            "what": "Deploy 3X-UI panel with 3 inbounds: VLESS-TLS+xhttp on 10000 & 10004, VLESS-Reality+xhttp on 443 (all loopback-only)",
            "why": "3X-UI manages VLESS users and inbounds. We configure it via the SQLite database directly - only HAProxy is ever public.",
            "files": [
                "/etc/x-ui/x-ui.db (SQLite database with inbound configs)",
                "/etc/x-ui/cert.pem, key.pem (TLS certificates for VLESS-TLS)",
                "/usr/local/x-ui/ (3X-UI binary and assets)",
            ],
            "rollback": "Database backup restored, certs preserved",
            "time": "~10 seconds",
            "warning": "Installs 3X-UI from official GitHub release",
        },
        "pki": {
            "what": "Create or reuse the Easy-RSA PKI: CA, server cert, one client cert per user, CRL, tls-crypt key",
            "why": "Every user gets a unique identity so one person can be revoked without affecting others.",
            "files": [
                "/etc/openvpn/pki/ (CA, certs, private keys, CRL)",
                "/etc/openvpn/ca.crt, server.crt, server.key, ta.key, crl.pem",
            ],
            "rollback": "A healthy PKI is reused; an unusable one is moved aside with a timestamp",
            "time": "~10-20 seconds",
            "warning": "New installs use ECDSA P-384 (dh none); an existing RSA PKI gets a real DH file",
        },
        "pam": {
            "what": "Create one non-login PAM account per user",
            "why": "OpenVPN uses PAM to verify the optional password factor against system accounts.",
            "files": [
                "/etc/passwd, /etc/shadow (user account)",
                "/etc/openvpn/users.db (SQLite record)",
            ],
            "rollback": "User can be deleted with userdel",
            "time": "~1 second",
            "warning": "Creates a system user with /usr/sbin/nologin shell",
        },
        "openvpn": {
            "what": "Write the OpenVPN server config (AEAD, TLS 1.2+, tls-crypt, CRL)",
            "why": "Defines transport, authentication and routing policy chosen in the wizard.",
            "files": [
                "/etc/openvpn/server.conf (main config)",
                "/etc/systemd/system/openvpn@.service.d/10-openvpn-wizard.conf (hardening)",
            ],
            "rollback": "Config restored from a timestamped backup if OpenVPN fails to start",
            "time": "~2 seconds",
            "warning": "Loopback bind when HAProxy fronts the VPN; direct bind for UDP/--no-haproxy",
        },
        "kernel_fw": {
            "what": "Enable IPv4 forwarding, configure iptables NAT for VPN subnet",
            "why": "Kernel forwarding + NAT allows VPN clients to reach the internet through the VPS.",
            "files": [
                "/etc/sysctl.d/99-openvpn.conf (IP forwarding)",
                "/etc/iptables/rules.v4 (persistent NAT rules)",
            ],
            "rollback": "sysctl reverted, iptables rules flushed",
            "time": "~3 seconds",
            "warning": "Modifies kernel parameters and firewall rules",
        },
        "services": {
            "what": "Enable and start all services: HAProxy, OpenVPN, 3X-UI",
            "why": "Services must be running for the VPN to work. systemd manages them.",
            "files": [
                "/etc/systemd/system/ (service units)",
            ],
            "rollback": "Services stopped and disabled",
            "time": "~5 seconds",
            "warning": "Restarts services if already running",
        },
        "client_profile": {
            "what": "Generate one standard .ovpn per user with a unique certificate and key",
            "why": "Single-file profiles work with OpenVPN Connect, OpenVPN GUI and Tunnelblick.",
            "files": [
                "/etc/openvpn/clients/<profile>.ovpn (mode 600, directory 700)",
                "/root/openvpn-wizard-credentials.txt (mode 600)",
            ],
            "rollback": "Profile files deleted",
            "time": "~2 seconds",
            "warning": "Contains private keys - never share or serve over HTTP",
        },
        "user_db": {
            "what": "Store user record in SQLite database for management",
            "why": "Enables add/remove/change-password/rename operations later.",
            "files": [
                "/etc/openvpn/users.db (SQLite database)",
            ],
            "rollback": "Database record marked revoked",
            "time": "~1 second",
            "warning": "Stores password hash (SHA-512 crypt)",
        },
    }

    def __init__(self, console: Console, steps: List[Tuple[str, str, object]], config: InstallConfig):
        self.console = console
        self.steps = steps
        self.config = config
        self.skipped = set()
        self.already_done = set()

    async def run(self) -> bool:
        """Run confirmation flow. Returns True to proceed, False to back/exit."""
        # Detect already-completed steps
        await self._detect_already_done()

        while True:
            self._show_overview()
            choice = await self._get_choice()

            if choice == "proceed":
                return True
            elif choice == "back":
                return False
            elif choice == "exit":
                return False
            elif choice.startswith("toggle_"):
                step_id = choice.split("_")[1]
                if step_id in self.skipped:
                    self.skipped.remove(step_id)
                else:
                    self.skipped.add(step_id)
            elif choice.startswith("detail_"):
                step_id = choice.split("_")[1]
                await self._show_detail(step_id)

    async def _detect_already_done(self):
        """Check which steps are already completed."""
        for step_id, _, step_obj in self.steps:
            try:
                if await step_obj.is_already_done(self.config):
                    self.already_done.add(step_id)
            except Exception:
                # If check fails, assume not done
                pass

    def _show_overview(self):
        """Show all steps with status."""
        self.console.clear()
        self.console.print(SectionHeader(3, 7, "Confirm Installation Steps", "✅").render())

        intro = Panel(
            "[bold]Review each step below.[/bold] Each shows what it does, why it's needed, what files change, and rollback info.\n"
            "[dim]Press the step number to see details. Type 'skip' to toggle skip (for re-runs).[/dim]\n"
            "[dim]Steps marked 'DONE' are already complete and will be skipped automatically.[/dim]",
            title="[primary]Instructions[/primary]",
            border_style="primary",
            padding=(1, 2),
        )
        self.console.print(intro)

        # Steps table
        table = Table(show_header=True, header_style="primary", box=None, padding=(0, 1))
        table.add_column("#", width=3, justify="right")
        table.add_column("Step", style="text", width=35)
        table.add_column("Status", width=14)
        table.add_column("Time", width=12)

        for i, (step_id, display_name, _) in enumerate(self.steps, 1):
            if step_id in self.already_done:
                status = "[step.done]✓ DONE[/step.done]"
            elif step_id in self.skipped:
                status = "[step.skipped]⊘ SKIP[/step.skipped]"
            else:
                status = "[step.pending]○ PENDING[/step.pending]"
            time_est = self.STEP_DETAILS.get(step_id, {}).get("time", "~?s")
            table.add_row(str(i), display_name, status, time_est)

        self.console.print()
        self.console.print(table)

        # Summary
        pending = len(self.steps) - len(self.skipped) - len(self.already_done)
        self.console.print()
        summary_parts = [f"[bold]{pending}[/bold] steps will execute"]
        if self.already_done:
            summary_parts.append(f"[step.done]{len(self.already_done)} already done[/step.done]")
        if self.skipped:
            summary_parts.append(f"[step.skipped]{len(self.skipped)} skipped[/step.skipped]")
        self.console.print(Align.center("  |  ".join(summary_parts)))

        self.console.print()
        self.console.print(CreditsFooter.render())

    async def _get_choice(self) -> str:
        """Get user choice."""
        self.console.print()
        self.console.print("[primary]Actions:[/primary]")
        self.console.print("  [primary]1-10.[/primary] View step details")
        self.console.print("  [primary]s <num>.[/primary] Toggle skip for step (e.g., 's 3')")
        self.console.print("  [primary]p.[/primary] [bold]Proceed with Installation[/bold]")
        self.console.print("  [primary]b.[/primary] [bold]Back[/bold]")
        self.console.print("  [primary]q.[/primary] [bold]Exit[/bold]")

        while True:
            try:
                choice = self.console.input("\n[primary]Choice: [/primary]").strip().lower()
                if choice in ("p", "proceed", "continue", "go", "y", "yes"):
                    return "proceed"
                elif choice in ("b", "back"):
                    return "back"
                elif choice in ("q", "quit", "exit"):
                    return "exit"
                elif choice.startswith("s "):
                    try:
                        num = int(choice.split()[1]) - 1
                        if 0 <= num < len(self.steps):
                            return f"toggle_{self.steps[num][0]}"
                    except (ValueError, IndexError):
                        pass
                elif choice.isdigit():
                    num = int(choice) - 1
                    if 0 <= num < len(self.steps):
                        return f"detail_{self.steps[num][0]}"
                else:
                    self.console.print("[error]Invalid choice.[/error]")
            except (KeyboardInterrupt, EOFError):
                return "exit"

    async def _show_detail(self, step_id: str):
        """Show detailed confirmation for a step."""
        detail = self.STEP_DETAILS.get(step_id, {})
        step_name = next((name for sid, name, _ in self.steps if sid == step_id), step_id)
        is_done = step_id in self.already_done

        confirm = ConfirmAction(
            self.console,
            title=f"Step: {step_name}" + (" [step.done]✓ ALREADY DONE[/step.done]" if is_done else ""),
            what=detail.get("what", "Unknown"),
            why=detail.get("why", "Unknown"),
            files_affected=detail.get("files", []),
            rollback_info=detail.get("rollback", "Manual rollback required"),
            estimated_time=detail.get("time", "Unknown"),
            warning=detail.get("warning"),
            show_skip=True,
            show_back=True,
        )

        # We don't use the confirm's ask() since we're in a sub-menu
        # Just display it
        self.console.clear()
        self.console.print(confirm.render())
        if is_done:
            self.console.print()
            self.console.print("[step.done]ℹ This step is already complete. It will be skipped during installation.[/step.done]")
        self.console.print()
        self.console.print("[dim]Press Enter to return...[/dim]")
        try:
            self.console.input()
        except (KeyboardInterrupt, EOFError):
            pass