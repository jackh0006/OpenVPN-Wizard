"""
Guided parameter collection.

Every decision that changes how the VPN behaves is asked explicitly:
server IP, endpoint (domain or IP), port, TCP or UDP, authentication,
locked or free access, profile names, and how many unique profiles to make.
"""

from __future__ import annotations

import getpass

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from core.config import (
    ClientSpec,
    InstallConfig,
    sanitize_cert_name,
    sanitize_profile_name,
    validate_config,
    validate_hostname,
    validate_ipv4,
    validate_password,
    validate_port,
    validate_profile_name,
    validate_username,
)
from core.secrets import generate_password
from ui.components import CreditsFooter, SectionHeader
from ui.theme import get_console
from utils.system import get_public_ip


class ParameterScreen:
    def __init__(self, console: Console = None):
        self.console = console or get_console()

    async def run(self) -> InstallConfig | None:
        try:
            return await self._run()
        except (KeyboardInterrupt, EOFError):
            self.console.print("\n[dim]Cancelled. Nothing was changed.[/dim]")
            return None

    async def _run(self) -> InstallConfig | None:
        self.console.clear()
        self.console.print(SectionHeader(2, 6, "Configuration", "⚙️").render())
        self.console.print(
            Panel(
                "[bold]Every choice below is applied explicitly.[/bold]\n"
                "[dim]Defaults are safe. Press Ctrl+C at any time to abort without changes.[/dim]",
                border_style="primary", padding=(0, 2),
            )
        )

        detected = get_public_ip() or ""
        server_ip = self._ask(
            "Server public IP address",
            default=detected,
            validator=validate_ipv4,
            error="Enter a valid IPv4 or IPv6 address.",
        )

        self.console.print()
        self.console.print("[primary]How should clients reach the server?[/primary]")
        self.console.print("  [primary]1.[/primary] Domain name (recommended; needs DNS → server IP)")
        self.console.print("  [primary]2.[/primary] IP address only")
        endpoint_choice = Prompt.ask("Choice", choices=["1", "2"], default="2",
                                     console=self.console)
        domain = ""
        if endpoint_choice == "1":
            domain = self._ask(
                "Domain name (e.g. vpn.example.com)",
                validator=validate_hostname,
                error="Enter a valid fully qualified domain name.",
            ).lower()
            endpoint_host = domain
            mode = "domain"
        else:
            endpoint_host = server_ip
            mode = "ip"

        port = self._ask_int(
            "Public port (443 looks like HTTPS and works through most firewalls)",
            default="443",
        )

        self.console.print()
        proto = Prompt.ask(
            "Transport protocol",
            choices=["tcp", "udp"],
            default="tcp",
            console=self.console,
        )

        self.console.print()
        self.console.print("[primary]Authentication[/primary]")
        self.console.print("  [primary]1.[/primary] Unique certificate + username/password (2 factors, recommended)")
        self.console.print("  [primary]2.[/primary] Unique certificate only (no password prompt)")
        auth_choice = Prompt.ask("Choice", choices=["1", "2"], default="1",
                                 console=self.console)
        auth_mode = "userpass" if auth_choice == "1" else "cert"

        self.console.print()
        self.console.print("[primary]Access policy[/primary]")
        self.console.print("  [primary]1.[/primary] Free: route all internet traffic through the VPN")
        self.console.print("  [primary]2.[/primary] Locked: only reach the private VPN network (no internet exit)")
        access_choice = Prompt.ask("Choice", choices=["1", "2"], default="1",
                                   console=self.console)
        access_mode = "free" if access_choice == "1" else "locked"

        self.console.print()
        prefix = self._ask(
            "Profile name prefix (used for the .ovpn file names)",
            default="MHH06",
            validator=validate_profile_name,
            error="Use letters, digits, dot, dash or underscore (max 64).",
        )
        count = self._ask_int("How many unique profiles/users?", default="3", minimum=1, maximum=50)

        users = self._collect_users(prefix, count, auth_mode)

        use_haproxy = True
        if proto == "tcp":
            self.console.print()
            use_haproxy = Confirm.ask(
                "Add the VPN to HAProxy's existing config (non-destructive, recommended)?",
                default=True, console=self.console,
            )

        enable_vless = False
        domain1 = domain2 = reality_domain = ""
        admin_user, admin_pass = "admin", ""
        if proto == "tcp" and port == 443 and use_haproxy:
            self.console.print()
            enable_vless = Confirm.ask(
                "Also multiplex VLESS/Reality on the same 443 listener? (advanced, off by default)",
                default=False, console=self.console,
            )
            if enable_vless:
                domain1 = self._ask("VLESS domain 1", validator=validate_hostname,
                                    error="Invalid domain.").lower()
                domain2 = self._ask("VLESS domain 2", validator=validate_hostname,
                                    error="Invalid domain.").lower()
                reality_domain = self._ask(
                    "Reality disguise domain (e.g. www.cloudflare.com)",
                    validator=validate_hostname, error="Invalid domain.",
                ).lower()
                admin_user = self._ask("3X-UI admin username", default="admin",
                                       validator=validate_username,
                                       error="Lowercase letters/digits only.").lower()
                admin_pass = generate_password()
                self.console.print(
                    f"[success]3X-UI admin password generated:[/success] [key]{admin_pass}[/key]"
                )

        config = InstallConfig(
            server_ip=server_ip,
            endpoint_mode=mode,
            endpoint_host=endpoint_host,
            domain=domain,
            vpn_proto=proto,
            public_port=port,
            auth_mode=auth_mode,
            access_mode=access_mode,
            profile_prefix=prefix,
            users=users,
            manage_haproxy=use_haproxy,
            enable_vless=enable_vless,
            domain1=domain1,
            domain2=domain2,
            reality_domain=reality_domain,
            admin_user=admin_user,
            admin_pass=admin_pass,
            server_ip_confirmed=True,
        )

        while True:
            self._review(config)
            action = Prompt.ask(
                "[primary]Action[/primary] [c]ontinue, [e]dit users, [r]estart, [q]uit",
                choices=["c", "e", "r", "q"], default="c", console=self.console,
            )
            if action == "c":
                problems = validate_config(config)
                if problems:
                    self.console.print(Panel(
                        "\n".join(f"• {p}" for p in problems),
                        title="[error]Please fix[/error]", border_style="error",
                    ))
                    continue
                return config
            if action == "e":
                users = self._collect_users(prefix, len(config.users), auth_mode)
                config.users = users
            elif action == "r":
                return await self._run()
            else:
                return None

    # ── Helpers ──────────────────────────────────────────────────────────

    def _ask(self, label: str, default: str = "", validator=None,
             error: str = "Invalid value.") -> str:
        while True:
            value = Prompt.ask(f"[primary]{label}[/primary]", default=default,
                               console=self.console).strip()
            if validator is None or validator(value):
                return value
            self.console.print(f"[error]{error}[/error]")

    def _ask_int(self, label: str, default: str, minimum: int = 1,
                 maximum: int = 65535) -> int:
        while True:
            raw = Prompt.ask(f"[primary]{label}[/primary]", default=default,
                             console=self.console).strip()
            if validate_port(raw) and minimum <= int(raw) <= maximum:
                return int(raw)
            self.console.print(f"[error]Enter a number between {minimum} and {maximum}.[/error]")

    def _collect_users(self, prefix: str, count: int, auth_mode: str) -> list[ClientSpec]:
        users: list[ClientSpec] = []
        used_names: set[str] = set()
        used_users: set[str] = set()
        for index in range(1, count + 1):
            self.console.print()
            self.console.print(f"[primary]Profile {index} of {count}[/primary]")
            default_name = f"{prefix}-{index:02d}" if count > 1 else prefix
            while True:
                name = Prompt.ask("  Display/file name", default=default_name,
                                  console=self.console).strip()
                name = sanitize_profile_name(name)
                if not validate_profile_name(name):
                    self.console.print("  [error]Invalid profile name.[/error]")
                    continue
                if name in used_names:
                    self.console.print("  [error]That name is already used in this batch.[/error]")
                    continue
                break
            used_names.add(name)

            default_user = sanitize_cert_name(name)
            while True:
                username = Prompt.ask("  VPN username", default=default_user,
                                      console=self.console).strip().lower()
                if not validate_username(username):
                    self.console.print("  [error]Use lowercase letters, digits, '-' or '_'.[/error]")
                    continue
                if username in used_users:
                    self.console.print("  [error]That username is already used in this batch.[/error]")
                    continue
                break
            used_users.add(username)

            password = ""
            if auth_mode == "userpass":
                self.console.print(
                    "  Password: [primary]1[/primary] auto-generate strong  "
                    "[primary]2[/primary] enter manually"
                )
                choice = Prompt.ask("  Choice", choices=["1", "2"], default="1",
                                    console=self.console)
                if choice == "1":
                    password = generate_password()
                    self.console.print(f"  [success]Generated:[/success] [key]{password}[/key]")
                else:
                    while True:
                        password = getpass.getpass("  Password (min 12 chars): ")
                        ok, reason = validate_password(password)
                        if not ok:
                            self.console.print(f"  [error]{reason}[/error]")
                            continue
                        if password != getpass.getpass("  Confirm password: "):
                            self.console.print("  [error]Passwords do not match.[/error]")
                            continue
                        break
            users.append(ClientSpec(name=name, username=username, password=password))
        return users

    def _review(self, config: InstallConfig) -> None:
        self.console.clear()
        self.console.print(SectionHeader(2, 6, "Review", "🔎").render())
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Setting", style="primary", width=24)
        table.add_column("Value")
        table.add_row("Server IP", config.server_ip)
        table.add_row("Endpoint", f"{config.remote_host} ({config.endpoint_mode})")
        table.add_row("Public port", f"{config.public_port}/{config.vpn_proto}")
        table.add_row("Transport", config.vpn_proto.upper())
        table.add_row("Authentication", "certificate + password" if config.auth_mode == "userpass"
                      else "certificate only")
        table.add_row("Access", "free (full tunnel)" if config.free_tunnel else "locked (VPN network only)")
        table.add_row("HAProxy", "yes (managed block)" if config.use_haproxy else "no (direct bind)")
        table.add_row("VLESS multiplex", "yes" if config.enable_vless else "no")
        self.console.print(Panel(table, border_style="primary"))

        users = Table(show_header=True, header_style="primary", box=None, padding=(0, 1))
        users.add_column("#", width=3)
        users.add_column("Profile", width=22)
        users.add_column("Username", width=18)
        users.add_column("Password", width=28)
        for i, user in enumerate(config.users, 1):
            shown = user.password if config.auth_mode == "userpass" else "(certificate only)"
            users.add_row(str(i), user.name, user.username, shown)
        self.console.print(users)
        if config.auth_mode == "userpass":
            self.console.print(
                "[warning]Passwords are shown here and written to a root-only file "
                "after install. They are never served over HTTP.[/warning]"
            )
        self.console.print()
        self.console.print(CreditsFooter.render())
