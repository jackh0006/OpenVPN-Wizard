"""
Management menu: add, revoke, change password, rename, rotate, export.
"""

from __future__ import annotations

import getpass

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from core.config import InstallConfig, validate_password
from core.secrets import generate_password
from management.user_mgr import UserManager
from ui.components import CreditsFooter, SectionHeader


class ManageScreen:
    def __init__(self, console: Console, user_mgr: UserManager, config: InstallConfig):
        self.console = console
        self.user_mgr = user_mgr
        self.config = config

    async def run(self):
        while True:
            self._show_menu()
            choice = await self._get_choice()
            if choice == "exit":
                return
            actions = {
                "add": self._add_user,
                "remove": self._remove_user,
                "change_pass": self._change_password,
                "rename": self._rename_user,
                "export": self._export_profile,
                "list": self._list_users,
                "rotate": self._rotate_keys,
                "download": self._download,
                "refresh": self._noop,
            }
            await actions[choice]()

    async def _noop(self):
        return

    def _show_menu(self):
        self.console.clear()
        self.console.print(SectionHeader(1, 2, "User management", "👥").render())
        users = self.user_mgr.list_users()
        table = Table(show_header=True, header_style="primary", box=None, padding=(0, 1))
        table.add_column("#", width=3, justify="right")
        table.add_column("Profile", width=22)
        table.add_column("Username", width=18)
        table.add_column("Auth", width=10)
        table.add_column("Status", width=12)
        for i, user in enumerate(users, 1):
            status = "[green]active[/green]" if not user.get("revoked") else "[red]revoked[/red]"
            table.add_row(str(i), user["name"], user["username"],
                          user.get("auth_mode", self.config.auth_mode), status)
        if not users:
            table.add_row("", "[dim](no users)[/dim]", "", "", "")
        self.console.print(Panel(table, title="[primary]Users[/primary]",
                                 border_style="primary"))

        self.console.print()
        self.console.print("[primary]1.[/primary] Add user")
        self.console.print("[primary]2.[/primary] Revoke/remove user")
        self.console.print("[primary]3.[/primary] Change password")
        self.console.print("[primary]4.[/primary] Rename profile")
        self.console.print("[primary]5.[/primary] Regenerate/export profile")
        self.console.print("[primary]6.[/primary] Detailed list")
        self.console.print("[primary]7.[/primary] Rotate certificate + key")
        self.console.print("[primary]8.[/primary] Show download command")
        self.console.print("[primary]9.[/primary] Refresh")
        self.console.print("[primary]b.[/primary] Back")
        self.console.print("[primary]q.[/primary] Exit")
        self.console.print()
        self.console.print(CreditsFooter.render())

    async def _get_choice(self):
        mapping = {
            "1": "add", "a": "add", "add": "add",
            "2": "remove", "r": "remove", "remove": "remove", "del": "remove",
            "3": "change_pass", "p": "change_pass", "pass": "change_pass",
            "4": "rename", "n": "rename",
            "5": "export", "e": "export",
            "6": "list", "l": "list", "ls": "list",
            "7": "rotate", "k": "rotate", "rotate": "rotate",
            "8": "download", "d": "download",
            "9": "refresh", "refresh": "refresh",
            "b": "exit", "back": "exit", "q": "exit", "quit": "exit", "exit": "exit",
        }
        while True:
            try:
                raw = self.console.input("\n[primary]Choice: [/primary]").strip().lower()
                if raw in mapping:
                    return mapping[raw]
                self.console.print("[error]Invalid choice.[/error]")
            except (KeyboardInterrupt, EOFError):
                return "exit"

    # ── Actions ──────────────────────────────────────────────────────────

    async def _add_user(self):
        self.console.print()
        self.console.print(Panel("[bold]Add a user[/bold]", border_style="primary"))
        name = Prompt.ask("[primary]Profile name[/primary] (e.g. MHH06-04)",
                          console=self.console).strip()
        if not name:
            return
        username = Prompt.ask("[primary]VPN username[/primary]",
                              default=name.lower().replace(".", ""),
                              console=self.console).strip().lower()
        password = None
        if self.config.auth_mode == "userpass":
            self.console.print("[primary]1[/primary] auto-generate  [primary]2[/primary] enter manually")
            choice = Prompt.ask("Choice", choices=["1", "2"], default="1",
                                console=self.console)
            if choice == "2":
                while True:
                    password = getpass.getpass("Password (min 12 chars): ")
                    ok, reason = validate_password(password)
                    if not ok:
                        self.console.print(f"[error]{reason}[/error]")
                        continue
                    if password != getpass.getpass("Confirm password: "):
                        self.console.print("[error]Passwords do not match.[/error]")
                        continue
                    break
            else:
                password = generate_password()
        try:
            with self.console.status("[primary]Creating certificate and profile...[/primary]"):
                path = self.user_mgr.add_user(name, username, password)
            self.console.print(f"[success]✓ User created:[/success] [path]{path}[/path]")
            if password:
                self.console.print(f"[primary]Password:[/primary] [key]{password}[/key]")
            self.console.print(f"[primary]Download:[/primary] [code]{self.user_mgr.download_command(name)}[/code]")
        except Exception as exc:
            self.console.print(f"[error]Could not add user: {exc}[/error]")
        await self._pause()

    def _select_user(self, prompt: str):
        users = self.user_mgr.active_users()
        if not users:
            self.console.print("[warning]No active users.[/warning]")
            return None
        self.console.print()
        self.console.print(f"[primary]{prompt}[/primary]")
        for i, user in enumerate(users, 1):
            self.console.print(f"  [primary]{i}.[/primary] {user['name']} ({user['username']})")
        raw = Prompt.ask("Number (Enter to cancel)", default="", console=self.console).strip()
        if not raw:
            return None
        try:
            return users[int(raw) - 1]
        except (ValueError, IndexError):
            self.console.print("[error]Invalid selection.[/error]")
            return None

    async def _remove_user(self):
        user = self._select_user("Revoke which user?")
        if not user:
            await self._pause()
            return
        if Confirm.ask(
            f"[warning]Revoke {user['name']}? Their certificate is revoked and "
            "their profile is deleted. Other users are unaffected.[/warning]",
            default=False, console=self.console,
        ):
            try:
                with self.console.status("[primary]Revoking...[/primary]"):
                    self.user_mgr.remove_user(user["name"])
                self.console.print("[success]✓ User revoked.[/success]")
            except Exception as exc:
                self.console.print(f"[error]Could not revoke: {exc}[/error]")
        await self._pause()

    async def _change_password(self):
        if self.config.auth_mode != "userpass":
            self.console.print("[warning]This install uses certificate-only authentication.[/warning]")
            await self._pause()
            return
        user = self._select_user("Change password for which user?")
        if not user:
            await self._pause()
            return
        while True:
            password = getpass.getpass("New password (min 12 chars): ")
            ok, reason = validate_password(password)
            if not ok:
                self.console.print(f"[error]{reason}[/error]")
                continue
            if password != getpass.getpass("Confirm password: "):
                self.console.print("[error]Passwords do not match.[/error]")
                continue
            break
        try:
            self.user_mgr.change_password(user["name"], password)
            self.console.print("[success]✓ Password changed.[/success]")
        except Exception as exc:
            self.console.print(f"[error]{exc}[/error]")
        await self._pause()

    async def _rename_user(self):
        user = self._select_user("Rename which profile?")
        if not user:
            await self._pause()
            return
        new_name = Prompt.ask("New profile name", default=user["name"],
                              console=self.console).strip()
        try:
            path = self.user_mgr.rename_user(user["name"], new_name)
            self.console.print(f"[success]✓ Renamed:[/success] [path]{path}[/path]")
        except Exception as exc:
            self.console.print(f"[error]{exc}[/error]")
        await self._pause()

    async def _export_profile(self):
        user = self._select_user("Regenerate which profile?")
        if not user:
            await self._pause()
            return
        try:
            path = self.user_mgr.export_profile(user["name"])
            self.console.print(f"[success]✓ Regenerated:[/success] [path]{path}[/path]")
            self.console.print(f"[primary]Download:[/primary] [code]{self.user_mgr.download_command(user['name'])}[/code]")
        except Exception as exc:
            self.console.print(f"[error]{exc}[/error]")
        await self._pause()

    async def _rotate_keys(self):
        user = self._select_user("Rotate certificate for which user?")
        if not user:
            await self._pause()
            return
        if not Confirm.ask(
            f"[warning]Issue a new key for {user['name']} and revoke the old one?[/warning]",
            default=False, console=self.console,
        ):
            await self._pause()
            return
        try:
            path = self.user_mgr.rotate_keys(user["name"])
            self.console.print(f"[success]✓ New key issued:[/success] [path]{path}[/path]")
        except Exception as exc:
            self.console.print(f"[error]{exc}[/error]")
        await self._pause()

    async def _download(self):
        user = self._select_user("Download which profile?")
        if not user:
            await self._pause()
            return
        name = user["name"]
        self.console.print(Panel(
            f"[bold]From your device:[/bold]\n"
            f"  [code]{self.user_mgr.download_command(name)}[/code]\n\n"
            f"[bold]One-time HTTPS link (for phones):[/bold]\n"
            f"  [code]sudo vpn-installer download {name} --serve[/code]\n\n"
            f"[bold]Print through SSH:[/bold]\n"
            f"  [code]ssh root@{self.config.remote_host} "
            f"'vpn-installer download {name} --print' > {name}.ovpn[/code]",
            title="[primary]Download[/primary]", border_style="primary",
        ))
        await self._pause()

    async def _list_users(self):
        users = self.user_mgr.list_users()
        table = Table(show_header=True, header_style="primary", box=None, padding=(0, 1))
        table.add_column("Profile", width=20)
        table.add_column("Username", width=18)
        table.add_column("Cert", width=22)
        table.add_column("Created", width=20)
        table.add_column("Revoked", width=8)
        for user in users:
            table.add_row(
                user["name"], user["username"],
                (user.get("cert_name") or "")[:22],
                (user.get("created_at") or "")[:19],
                "yes" if user.get("revoked") else "no",
            )
        self.console.print(Panel(table, title="[primary]All users[/primary]",
                                 border_style="primary"))
        await self._pause()

    async def _pause(self):
        self.console.print()
        self.console.print("[dim]Press Enter to continue...[/dim]")
        try:
            self.console.input()
        except (KeyboardInterrupt, EOFError):
            pass
