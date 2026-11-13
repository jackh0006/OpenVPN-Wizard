#!/usr/bin/env python3
"""
OpenVPN Wizard v2 - hardened, non-destructive OpenVPN deployment.

Made by jackh0006 • jackh109867@gmail.com
MIT licensed. No telemetry, no tracking.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent))

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ui.theme import THEME
from core.config import (
    ClientSpec,
    InstallConfig,
    sanitize_cert_name,
    sanitize_profile_name,
    validate_config,
)
from core.detect import apply_existing_setup
from core.exceptions import InstallerError, format_error
from core.logger import get_log_path, setup_logger
from core.plan import build_plan
from core.secrets import generate_password
from core.state import InstallState, StateManager
from management.profile_gen import ProfileGenerator
from management.user_mgr import UserManager
from steps.client_profile import ClientProfileStep
from steps.haproxy import HAProxyStep
from steps.kernel_fw import KernelFWStep
from steps.openvpn import OpenVPNStep
from steps.packages import PackagesStep
from steps.pam import PAMStep
from steps.pki import PKIStep
from steps.services import ServicesStep
from steps.user_db import UserDBStep
from steps.xui import XUIStep
from ui.screens.confirm import ConfirmScreen
from ui.screens.goodbye import GoodbyeScreen
from ui.screens.manage import ManageScreen
from ui.screens.parameters import ParameterScreen
from ui.screens.privacy import PrivacyScreen
from ui.screens.progress import ProgressScreen
from ui.screens.success import SuccessScreen
from ui.screens.welcome import WelcomeScreen
from utils.download import serve_once
from validation.checklist import run_validation

VERSION = "2.1.0"

app = typer.Typer(
    name="vpn-installer",
    help="OpenVPN Wizard - hardened OpenVPN with optional HAProxy multiplexing.",
    add_completion=False,
    no_args_is_help=True,
)
console = Console(theme=THEME)


def _version_callback(value: bool) -> None:
    if value:
        try:
            from importlib.metadata import version as pkg_version
            v = pkg_version("vpn-installer")
        except Exception:
            v = VERSION
        console.print(f"[bold]vpn-installer[/bold] [primary]{v}[/primary]")
        console.print("[dim]Open source • no tracking • no telemetry[/dim]")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
):
    """OpenVPN Wizard - stealthy, non-destructive OpenVPN deployment."""


# ── Helpers ─────────────────────────────────────────────────────────────


def _print_error(exc: Exception) -> None:
    if isinstance(exc, InstallerError):
        console.print(Panel(format_error(exc, get_log_path()),
                            title="[error]Error[/error]", border_style="error"))
    else:
        console.print(Panel(
            f"[bold red]{exc}[/bold red]\n\nFull log: {get_log_path()}",
            title="[error]Error[/error]", border_style="error",
        ))


def _guard(coro) -> None:
    """Run a coroutine and present failures as actionable panels."""
    try:
        asyncio.run(coro)
    except InstallerError as exc:
        console.print(Panel(format_error(exc, get_log_path()),
                            title="[error]Installation stopped[/error]",
                            border_style="error"))
        raise typer.Exit(1)
    except KeyboardInterrupt:
        console.print("\n[warning]Interrupted. State was saved; resume with --resume.[/warning]")
        raise typer.Exit(130)
    except Exception as exc:  # last-resort readability
        console.print(Panel(
            f"[bold red]Unexpected error:[/bold red] {exc}\n\n"
            f"Full log: {get_log_path()}\n"
            "Nothing outside the installer's own managed files was removed.",
            title="[error]Error[/error]", border_style="error",
        ))
        raise typer.Exit(1)


def _make_users(prefix: str, count: int, password: Optional[str],
                auth_mode: str) -> List[ClientSpec]:
    names = [f"{prefix}-{i:02d}" for i in range(1, count + 1)] if count > 1 else [prefix]
    users = []
    for index, raw_name in enumerate(names):
        name = sanitize_profile_name(raw_name)
        username = sanitize_cert_name(name)
        pw = ""
        if auth_mode == "userpass":
            pw = password if (password and count == 1) else generate_password()
        users.append(ClientSpec(name=name, username=username, password=pw))
    return users


def _config_from_options(
    server_ip: str = "",
    domain: str = "",
    port: int = 443,
    proto: str = "tcp",
    auth_mode: str = "userpass",
    access_mode: str = "free",
    prefix: str = "MHH06",
    profiles: int = 3,
    users_raw: str = "",
    password: str = "",
    no_haproxy: bool = False,
    enable_vless: bool = False,
    domain1: str = "",
    domain2: str = "",
    reality_domain: str = "",
    admin_user: str = "admin",
    admin_pass: str = "",
    detect_existing: bool = True,
    ipv6_enabled: bool = False,
    tun_mtu: int = 1400,
    mssfix: int = 1360,
    sndbuf: int = 524288,
    rcvbuf: int = 524288,
    auth_digest: str = "SHA384",
    tls_min: str = "1.3",
    tls_max: str = "1.3",
    internal_port: int = 0,
    verify_client_cert: str = "require",
    duplicate_cn: bool = False,
) -> InstallConfig:
    from utils.system import get_public_ip
    server_ip = (server_ip or get_public_ip() or "").strip()
    if not server_ip:
        raise typer.BadParameter(
            "Could not detect the server IP. Provide --server-ip explicitly."
        )
    endpoint_mode = "domain" if domain else "ip"
    endpoint_host = domain.strip().lower() if domain else server_ip

    if users_raw:
        names = [part.strip() for part in users_raw.split(",") if part.strip()]
        if not names:
            raise typer.BadParameter("--users was empty.")
        users = []
        for index, raw in enumerate(names):
            name = sanitize_profile_name(raw)
            users.append(ClientSpec(
                name=name,
                username=sanitize_cert_name(name),
                password=(password if (password and len(names) == 1) else (
                    generate_password() if auth_mode == "userpass" else ""
                )),
            ))
    else:
        if password and profiles > 1:
            raise typer.BadParameter("Use --password only with a single profile, or omit it to auto-generate.")
        users = _make_users(prefix, profiles, password or None, auth_mode)

    config = InstallConfig(
        server_ip=server_ip,
        endpoint_mode=endpoint_mode,
        endpoint_host=endpoint_host,
        domain=domain.strip().lower(),
        vpn_proto=proto,
        public_port=port,
        auth_mode=auth_mode,
        access_mode=access_mode,
        profile_prefix=prefix,
        users=users,
        manage_haproxy=not no_haproxy,
        enable_vless=enable_vless,
        domain1=domain1,
        domain2=domain2,
        reality_domain=reality_domain,
        admin_user=admin_user,
        admin_pass=admin_pass or (generate_password() if enable_vless else ""),
        server_ip_confirmed=True,
        non_interactive=True,
        detect_existing=detect_existing,
        ipv6_enabled=ipv6_enabled,
        tun_mtu=tun_mtu,
        mssfix=mssfix,
        sndbuf=sndbuf,
        rcvbuf=rcvbuf,
        auth_digest=auth_digest,
        tls_min=tls_min,
        tls_max=tls_max,
        internal_port=internal_port,
        verify_client_cert=verify_client_cert,
        duplicate_cn=duplicate_cn,
    )
    if detect_existing:
        apply_existing_setup(config)
    problems = validate_config(config)
    if problems:
        raise typer.BadParameter(
            "Invalid configuration:\n" + "\n".join(f"  • {p}" for p in problems)
        )
    return config


def _config_with_db_users(config: InstallConfig) -> InstallConfig:
    """Use the database as the source of truth for users added via manage."""
    try:
        manager = UserManager(config)
        rows = manager.active_users()
        if rows:
            config.users = [
                ClientSpec(
                    name=row["name"],
                    username=row["username"],
                    password="",
                    cert_name=row.get("cert_name") or row["username"],
                )
                for row in rows
            ]
    except Exception:
        pass
    return config


# ── Installer orchestration ─────────────────────────────────────────────


class Installer:
    def __init__(self):
        self.config: Optional[InstallConfig] = None
        self.state: Optional[InstallState] = None
        self.state_manager = StateManager()
        self.logger = setup_logger()
        self.steps: list = []
        self.last_error: str = ""

    def build_steps(self, config: InstallConfig) -> list:
        steps = [("packages", "Install system packages", PackagesStep())]
        if config.use_haproxy:
            steps.append(("haproxy", "Add VPN listener to HAProxy", HAProxyStep()))
        if config.enable_vless:
            steps.append(("xui", "Deploy 3X-UI VLESS inbounds", XUIStep()))
        steps.append(("pki", "Create or reuse certificates", PKIStep()))
        if config.auth_mode == "userpass":
            steps.append(("pam", "Create VPN accounts", PAMStep()))
        steps += [
            ("openvpn", "Configure OpenVPN server", OpenVPNStep()),
            ("kernel_fw", "Open ports and tune the system", KernelFWStep()),
            ("services", "Start and verify services", ServicesStep()),
            ("client_profile", "Generate .ovpn profiles", ClientProfileStep()),
            ("user_db", "Record users in the database", UserDBStep()),
        ]
        return steps

    async def run_welcome(self) -> bool:
        return await WelcomeScreen(self.console).run()

    async def run_privacy(self) -> bool:
        return await PrivacyScreen(self.console).run()

    async def run_parameters(self) -> bool:
        result = await ParameterScreen(self.console).run()
        if not result:
            return False
        apply_existing_setup(result)
        self.config = result
        self.steps = self.build_steps(result)
        self.state = InstallState(config=result)
        self.state_manager.save(self.state)
        return True

    async def run_confirmation(self) -> bool:
        screen = ConfirmScreen(self.console, self.steps, self.config)
        return await screen.run()

    async def run_installation(self, already_done: set = None) -> bool:
        screen = ProgressScreen(
            self.console, self.steps, self.config, self.state,
            already_done=already_done or set(),
        )
        success = await screen.run()
        self.last_error = screen.last_error
        if success:
            self.state.completed = True
            self.state.install_done = True
            self.state_manager.save(self.state, redact_secrets=True)
        return success

    async def run_success(self):
        await SuccessScreen(self.console, self.config, self.state).run()

    async def run_management(self):
        if not self.config:
            return
        await ManageScreen(self.console, UserManager(self.config), self.config).run()

    async def run_goodbye(self):
        await GoodbyeScreen(self.console, self.config).run()

    async def run_validation(self) -> bool:
        if not self.config:
            return False
        console.print("\n[bold cyan]🔍 Running validation...[/bold cyan]\n")
        results = run_validation(self.config)
        for name, passed, details in results:
            status = "[green]✅ PASS[/green]" if passed else "[red]❌ FAIL[/red]"
            console.print(f"  {status} {name}")
            if details and not passed:
                console.print(f"    [dim]{details}[/dim]")
        passed_count = sum(1 for _, p, _ in results if p)
        console.print(f"\n[bold]{passed_count}/{len(results)} checks passed[/bold]")
        return passed_count == len(results)

    @property
    def console(self) -> Console:
        return console

    async def run_full(self, *, non_interactive: bool = False,
                       skip_validation: bool = False, resume: bool = False,
                       config: Optional[InstallConfig] = None,
                       assume_yes: bool = False) -> None:
        if resume:
            saved = self.state_manager.load()
            if saved and saved.config:
                self.state = saved
                self.config = saved.config
                self.steps = self.build_steps(self.config)
                console.print("[green]✓ Resumed from saved state[/green]")
            else:
                console.print("[yellow]No saved state found; starting normally.[/yellow]")

        if config:
            self.config = config
            self.steps = self.build_steps(config)
            self.state = InstallState(config=config)
            self.state.params_done = True
            self.state_manager.save(self.state)
        elif not self.config:
            if non_interactive:
                raise InstallerError(
                    "No configuration was supplied for a non-interactive install.",
                    code="VALIDATION_ERROR",
                    fix_hint=(
                        "Pass --server-ip and the other options, or use --resume "
                        "with an existing state file."
                    ),
                )
            if not await self.run_welcome():
                await self.run_goodbye()
                return
            if not await self.run_privacy():
                await self.run_goodbye()
                return
            if not await self.run_parameters():
                await self.run_goodbye()
                return

        if not non_interactive and not assume_yes:
            if not await self.run_confirmation():
                await self.run_goodbye()
                return
        else:
            self.state.confirm_done = True

        already_done = set()
        for step_id, _, step_obj in self.steps:
            try:
                if await step_obj.is_already_done(self.config):
                    already_done.add(step_id)
            except Exception:
                pass

        if not await self.run_installation(already_done=already_done):
            if self.last_error:
                console.print(Panel(self.last_error,
                                    title="[error]Installation stopped[/error]",
                                    border_style="error"))
            else:
                console.print("[red]Installation failed. The live system was rolled back where possible.[/red]")
            await self.run_goodbye()
            return

        if not skip_validation:
            await self.run_validation()

        await self.run_success()

        if not non_interactive and not assume_yes:
            if typer.confirm("\nOpen user management menu?", default=False):
                await self.run_management()

        await self.run_goodbye()


# ── Commands ────────────────────────────────────────────────────────────


@app.command()
def install(
    non_interactive: bool = typer.Option(False, "--non-interactive", "-n",
                                         help="No prompts; use the CLI options below."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Assume yes for confirmations."),
    skip_validation: bool = typer.Option(False, "--skip-validation"),
    resume: bool = typer.Option(False, "--resume", help="Resume a previously saved install."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Render everything to a directory; change nothing."),
    output: Path = typer.Option(Path("./vpn-plan"), "--output", "-o", help="Directory for --dry-run."),
    server_ip: str = typer.Option("", "--server-ip", help="Public IPv4/IPv6 address."),
    domain: str = typer.Option("", "--domain", help="Domain clients connect to."),
    port: int = typer.Option(443, "--port", help="Public port (1-65535)."),
    proto: str = typer.Option("tcp", "--proto", help="tcp or udp."),
    auth_mode: str = typer.Option("userpass", "--auth", help="userpass or cert."),
    access_mode: str = typer.Option("free", "--access", help="free or locked."),
    prefix: str = typer.Option("MHH06", "--prefix", help="Profile name prefix."),
    profiles: int = typer.Option(3, "--profiles", help="Number of unique profiles."),
    users: str = typer.Option("", "--users", help="Comma-separated profile names (overrides --profiles)."),
    password: str = typer.Option("", "--password", help="Password for a single profile only."),
    no_haproxy: bool = typer.Option(False, "--no-haproxy", help="Bind OpenVPN directly instead of via HAProxy."),
    enable_vless: bool = typer.Option(False, "--enable-vless", help="Advanced: multiplex VLESS/Reality on 443/TCP."),
    domain1: str = typer.Option("", "--domain1"),
    domain2: str = typer.Option("", "--domain2"),
    reality_domain: str = typer.Option("", "--reality-domain"),
    admin_user: str = typer.Option("admin", "--admin-user"),
    admin_pass: str = typer.Option("", "--admin-pass"),
    no_detect: bool = typer.Option(False, "--no-detect", help="Ignore an existing OpenVPN config."),
    enable_ipv6: bool = typer.Option(False, "--enable-ipv6", help="Keep host IPv6 enabled (default: disabled)."),
    tun_mtu: int = typer.Option(1400, "--tun-mtu"),
    mssfix: int = typer.Option(1360, "--mssfix"),
    sndbuf: int = typer.Option(524288, "--sndbuf"),
    rcvbuf: int = typer.Option(524288, "--rcvbuf"),
    auth_digest: str = typer.Option("SHA384", "--auth-digest"),
    tls_min: str = typer.Option("1.3", "--tls-min"),
    tls_max: str = typer.Option("1.3", "--tls-max"),
    internal_port: int = typer.Option(0, "--internal-port", help="Loopback port; 0 = auto-detect."),
    verify_client_cert: str = typer.Option("require", "--verify-client-cert"),
    duplicate_cn: bool = typer.Option(False, "--duplicate-cn"),
):
    """Run the installer (interactive by default)."""
    if dry_run:
        if non_interactive:
            config = _config_from_options(
                server_ip=server_ip, domain=domain, port=port, proto=proto,
                auth_mode=auth_mode, access_mode=access_mode, prefix=prefix,
                profiles=profiles, users_raw=users, password=password,
                no_haproxy=no_haproxy, enable_vless=enable_vless,
                domain1=domain1, domain2=domain2, reality_domain=reality_domain,
                admin_user=admin_user, admin_pass=admin_pass,
                detect_existing=not no_detect, ipv6_enabled=enable_ipv6,
                tun_mtu=tun_mtu, mssfix=mssfix, sndbuf=sndbuf, rcvbuf=rcvbuf,
                auth_digest=auth_digest, tls_min=tls_min, tls_max=tls_max,
                internal_port=internal_port, verify_client_cert=verify_client_cert,
                duplicate_cn=duplicate_cn,
            )
            result = build_plan(config, output)
            console.print(Panel(
                f"[bold]Rendered to:[/bold] {result['output_dir']}\n"
                f"[bold]Server:[/bold] {result['server_conf']}\n"
                f"[bold]Profiles:[/bold] {len(result['profiles'])}\n"
                + ("\n".join(f"  • {p}" for p in result["problems"])
                   if result["problems"] else "[success]✓ Validation passed[/success]"),
                title="[primary]Dry run[/primary]", border_style="primary",
            ))
            raise typer.Exit(1 if result["problems"] else 0)
        async def _interactive_plan():
            from ui.screens.parameters import ParameterScreen
            cfg = await ParameterScreen(console).run()
            if not cfg:
                return
            result = build_plan(cfg, output)
            console.print(Panel(
                f"[bold]Rendered to:[/bold] {result['output_dir']}\n"
                f"[bold]Profiles:[/bold] {len(result['profiles'])}",
                title="[primary]Dry run[/primary]", border_style="primary",
            ))
        _guard(_interactive_plan())
        return

    config = None
    if non_interactive and not resume:
        config = _config_from_options(
            server_ip=server_ip, domain=domain, port=port, proto=proto,
            auth_mode=auth_mode, access_mode=access_mode, prefix=prefix,
            profiles=profiles, users_raw=users, password=password,
            no_haproxy=no_haproxy, enable_vless=enable_vless,
            domain1=domain1, domain2=domain2, reality_domain=reality_domain,
            admin_user=admin_user, admin_pass=admin_pass,
            detect_existing=not no_detect, ipv6_enabled=enable_ipv6,
            tun_mtu=tun_mtu, mssfix=mssfix, sndbuf=sndbuf, rcvbuf=rcvbuf,
            auth_digest=auth_digest, tls_min=tls_min, tls_max=tls_max,
            internal_port=internal_port, verify_client_cert=verify_client_cert,
            duplicate_cn=duplicate_cn,
        )
    _guard(Installer().run_full(
        non_interactive=non_interactive or bool(config), skip_validation=skip_validation,
        resume=resume, config=config, assume_yes=yes,
    ))


@app.command()
def plan(
    output_dir: Path = typer.Option(Path("./vpn-plan"), "--output", "-o",
                                    help="Directory for rendered files."),
    server_ip: str = typer.Option("198.51.100.10", "--server-ip"),
    domain: str = typer.Option("", "--domain"),
    port: int = typer.Option(443, "--port"),
    proto: str = typer.Option("tcp", "--proto"),
    auth_mode: str = typer.Option("userpass", "--auth"),
    access_mode: str = typer.Option("free", "--access"),
    prefix: str = typer.Option("MHH06", "--prefix"),
    profiles: int = typer.Option(3, "--profiles"),
    users: str = typer.Option("", "--users"),
    no_haproxy: bool = typer.Option(False, "--no-haproxy"),
    enable_vless: bool = typer.Option(False, "--enable-vless"),
    domain1: str = typer.Option("", "--domain1"),
    domain2: str = typer.Option("", "--domain2"),
    reality_domain: str = typer.Option("", "--reality-domain"),
    no_detect: bool = typer.Option(False, "--no-detect"),
    enable_ipv6: bool = typer.Option(False, "--enable-ipv6"),
    tun_mtu: int = typer.Option(1400, "--tun-mtu"),
    mssfix: int = typer.Option(1360, "--mssfix"),
    sndbuf: int = typer.Option(524288, "--sndbuf"),
    rcvbuf: int = typer.Option(524288, "--rcvbuf"),
    auth_digest: str = typer.Option("SHA384", "--auth-digest"),
    tls_min: str = typer.Option("1.3", "--tls-min"),
    tls_max: str = typer.Option("1.3", "--tls-max"),
    internal_port: int = typer.Option(0, "--internal-port"),
    verify_client_cert: str = typer.Option("require", "--verify-client-cert"),
    duplicate_cn: bool = typer.Option(False, "--duplicate-cn"),
):
    """Render everything to a directory without changing the system (safe test)."""
    config = _config_from_options(
        server_ip=server_ip, domain=domain, port=port, proto=proto,
        auth_mode=auth_mode, access_mode=access_mode, prefix=prefix,
        profiles=profiles, users_raw=users, no_haproxy=no_haproxy,
        enable_vless=enable_vless, domain1=domain1, domain2=domain2,
        reality_domain=reality_domain, detect_existing=not no_detect,
        ipv6_enabled=enable_ipv6, tun_mtu=tun_mtu, mssfix=mssfix,
        sndbuf=sndbuf, rcvbuf=rcvbuf, auth_digest=auth_digest,
        tls_min=tls_min, tls_max=tls_max, internal_port=internal_port,
        verify_client_cert=verify_client_cert, duplicate_cn=duplicate_cn,
    )
    try:
        result = build_plan(config, output_dir)
    except Exception as exc:
        _print_error(exc)
        raise typer.Exit(1)
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("File", style="primary")
    table.add_column("Path")
    table.add_row("Plan directory", result["output_dir"])
    table.add_row("Server config", result["server_conf"])
    for profile in result["profiles"]:
        table.add_row("Client profile", profile)
    strategy = result.get("haproxy_strategy") or {}
    if result["haproxy_block"] and strategy.get("action") in {"append", "insert"}:
        table.add_row("HAProxy block", result["haproxy_block"])
    if strategy:
        table.add_row("HAProxy action", f"{strategy.get('action')}: {strategy.get('reason')}")
    console.print(Panel(table, title="[primary]Dry-run plan[/primary]",
                        border_style="primary"))
    if result["problems"]:
        console.print("[error]Validation problems:[/error]")
        for problem in result["problems"]:
            console.print(f"  • {problem}")
        raise typer.Exit(1)
    console.print("[success]✓ Plan validated. Nothing on the system was changed.[/success]")


@app.command()
def manage():
    """Open the user management menu."""
    installer = Installer()
    state = installer.state_manager.load()
    if not state or not state.config:
        console.print("[red]No installation found. Run 'vpn-installer install' first.[/red]")
        raise typer.Exit(1)
    installer.config = state.config
    installer.state = state
    _guard(installer.run_management())
    _guard(installer.run_goodbye())


@app.command()
def validate():
    """Run validation checks against the current installation."""
    installer = Installer()
    state = installer.state_manager.load()
    if not state or not state.config:
        console.print("[red]No installation found.[/red]")
        raise typer.Exit(1)
    installer.config = _config_with_db_users(state.config)
    try:
        ok = asyncio.run(installer.run_validation())
    except Exception as exc:
        _print_error(exc)
        raise typer.Exit(1)
    raise typer.Exit(0 if ok else 1)


@app.command()
def download(
    profile: str = typer.Argument("", help="Profile name (omit to list)."),
    serve: bool = typer.Option(False, "--serve", help="Start a one-time HTTPS download."),
    port: int = typer.Option(8443, "--port", help="HTTPS port for --serve."),
    ttl: int = typer.Option(300, "--ttl", help="Seconds before the one-time server expires."),
    host: str = typer.Option("", "--host", help="Hostname/IP to print in the one-time URL."),
    print_profile: bool = typer.Option(False, "--print", help="Print the profile to stdout."),
    scp: bool = typer.Option(False, "--scp", help="Print the scp command."),
):
    """List or deliver a client profile securely."""
    state = StateManager().load()
    if not state or not state.config:
        console.print("[red]No installation found.[/red]")
        raise typer.Exit(1)
    config = _config_with_db_users(state.config)
    if not profile:
        for user in config.users:
            console.print(f"  {user.name}  ({user.username})")
        return
    name = sanitize_profile_name(profile)
    user = next((u for u in config.users if u.name == name), None)
    if not user:
        console.print(f"[red]Profile {name!r} not found.[/red]")
        raise typer.Exit(1)
    path = Path(config.profiles_dir) / f"{name}.ovpn"
    try:
        if not path.exists():
            console.print("[yellow]Profile file is missing; regenerating...[/yellow]")
            path = ProfileGenerator(config).save(user)
    except Exception as exc:
        _print_error(exc)
        raise typer.Exit(1)
    if scp:
        console.print(f"scp root@{config.remote_host}:{path} ~/Downloads/")
        return
    if print_profile:
        print(path.read_text(), end="")
        return
    if serve:
        try:
            serve_once(path, port=port, ttl=ttl, public_host=host or config.remote_host)
        except KeyboardInterrupt:
            console.print("\n[dim]Download server stopped.[/dim]")
        except Exception as exc:
            _print_error(exc)
            raise typer.Exit(1)
        return
    console.print(Panel(
        f"[bold]Profile:[/bold] {path}\n\n"
        f"[bold]Download from your device:[/bold]\n"
        f"  scp root@{config.remote_host}:{path} ~/Downloads/\n\n"
        f"[bold]One-time HTTPS link:[/bold]\n"
        f"  sudo vpn-installer download {name} --serve\n\n"
        f"[dim]Or print it through SSH:[/dim]\n"
        f"  ssh root@{config.remote_host} 'vpn-installer download {name} --print' > {name}.ovpn",
        title="[primary]Download[/primary]", border_style="primary",
    ))


@app.command()
def doctor():
    """Diagnose common problems and print exact fixes."""
    from validation.doctor import run_doctor
    ok = run_doctor(console)
    raise typer.Exit(0 if ok else 1)


@app.command()
def uninstall(
    purge: bool = typer.Option(False, "--purge", help="Also delete certificates, profiles and the user database."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Do not ask for confirmation."),
):
    """Detach the VPN safely. Existing unrelated services are never modified."""
    state = StateManager().load()
    if not state or not state.config:
        console.print("[red]No installation found.[/red]")
        raise typer.Exit(1)
    config = state.config
    console.print(Panel(
        "[bold]This will:[/bold]\n"
        "• stop and disable the OpenVPN service\n"
        "• remove ONLY the OpenVPN Wizard block from HAProxy\n"
        "• remove ONLY the firewall rules it added\n"
        + ("• delete certificates, profiles and the user database (--purge)\n" if purge else
           "• keep certificates, profiles and the user database\n") +
        "\n[bold]It will NOT:[/bold] remove packages, wipe HAProxy, flush iptables, or touch other services.",
        title="[warning]Uninstall[/warning]", border_style="warning",
    ))
    if not yes and not typer.confirm("Continue?"):
        raise typer.Exit(0)

    _guard(_do_uninstall(config, purge))


async def _do_uninstall(config: InstallConfig, purge: bool) -> None:
    import shutil

    from steps.openvpn import OpenVPNStep
    from utils.firewall import FirewallManager
    from utils.haproxy import HAProxyManager

    service = OpenVPNStep.openvpn_service_name()
    console.print(f"Stopping {service}...")
    for action in ("stop", "disable"):
        import subprocess
        subprocess.run(["systemctl", action, service], capture_output=True, check=False)

    if config.use_haproxy:
        console.print("Removing the managed HAProxy block...")
        try:
            HAProxyManager(config).remove()
        except Exception as exc:
            console.print(f"[warning]HAProxy cleanup: {exc}[/warning]")

    console.print("Removing VPN firewall/NAT rules...")
    try:
        FirewallManager(config).remove()
    except Exception as exc:
        console.print(f"[warning]Firewall cleanup: {exc}[/warning]")

    dropin = Path("/etc/systemd/system/openvpn@.service.d/10-openvpn-wizard.conf")
    dropin.unlink(missing_ok=True)

    if purge:
        console.print("Removing installer-owned configuration and keys...")
        for path in (
            Path(config.openvpn_dir) / "server.conf",
            Path(config.openvpn_dir) / "ca.crt",
            Path(config.openvpn_dir) / "server.crt",
            Path(config.openvpn_dir) / "server.key",
            Path(config.openvpn_dir) / "ta.key",
            Path(config.openvpn_dir) / "crl.pem",
            Path(config.openvpn_dir) / "dh.pem",
            Path(config.openvpn_dir) / "clients",
            Path(config.openvpn_dir) / "pki",
            Path(config.user_db),
            Path(config.credentials_file),
        ):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        StateManager().clear()
    console.print("[success]✓ VPN detached. Other services and configs are untouched.[/success]")


@app.command()
def version():
    """Show version information."""
    console.print(Panel(
        f"[bold]OpenVPN Wizard[/bold]\nVersion: {VERSION}\n"
        "Made by jackh0006 • jackh109867@gmail.com\n\n"
        "Open source • No tracking • No telemetry",
        title="About", border_style="blue",
    ))


if __name__ == "__main__":
    app()
