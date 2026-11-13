"""
Step: create PAM accounts for certificate + password authentication.

In certificate-only mode this step is a no-op.  When it runs, every VPN
account is created with a non-login shell and its password is sent to
``chpasswd`` over stdin (never through argv, so it never appears in process
listings or shell history).
"""

from __future__ import annotations

from typing import Callable

from core.config import InstallConfig
from core.exceptions import SystemError
from steps.base import BaseStep


class PAMStep(BaseStep):
    @property
    def name(self) -> str:
        return "pam"

    @property
    def display_name(self) -> str:
        return "Create VPN accounts"

    @property
    def description(self) -> str:
        return "Create one non-login PAM account per user (user/password mode only)"

    async def is_already_done(self, config: InstallConfig) -> bool:
        if config.auth_mode != "userpass":
            return True
        # Always re-apply passwords: the user may have edited them in the wizard,
        # and re-applying is idempotent and fast.
        return False

    async def execute(self, config: InstallConfig,
                      output_callback: Callable[[str], None] = None) -> bool:
        def log(msg: str):
            if output_callback:
                output_callback(msg)
            self.logger.info(msg)

        if config.auth_mode != "userpass":
            log("Certificate-only mode: no PAM accounts are created")
            return True

        for user in config.users:
            username = user.username
            if not user.password:
                raise SystemError(
                    f"No password configured for {user.name}",
                    fix_hint="Re-run the installer and provide a password, or use certificate-only mode.",
                )

            exists = self._run_cmd(["id", username], check=False).returncode == 0
            if not exists:
                log(f"Creating non-login account: {username}")
                result = self._run_cmd(
                    ["useradd", "--no-create-home", "--shell", "/usr/sbin/nologin", username],
                    check=False,
                )
                if result.returncode != 0:
                    raise SystemError(
                        f"Could not create user {username}: {(result.stderr or '').strip()}",
                        command=f"useradd {username}",
                        fix_hint="Check that the username is not already in use.",
                    )
            else:
                log(f"Updating password for existing account: {username}")

            result = self._run_cmd(
                ["chpasswd"], input_data=f"{username}:{user.password}\n", check=False,
            )
            if result.returncode != 0:
                raise SystemError(
                    f"Could not set the VPN password for {username}.",
                    command="chpasswd",
                    fix_hint=(result.stderr or "").strip(),
                )

            # Lock the Unix shell login while keeping PAM password auth usable.
            self._run_cmd(["usermod", "-s", "/usr/sbin/nologin", username], check=False)
            log(f"  ✓ {user.name} ({username}) is ready")

        return True

    async def rollback(self, config: InstallConfig, rollback_data: dict) -> bool:
        if config.auth_mode != "userpass":
            return True
        for user in config.users:
            self._run_cmd(["userdel", "-f", user.username], check=False)
        return True
