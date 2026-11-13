"""
Custom exception hierarchy with actionable, human-friendly messages.
"""

from __future__ import annotations


class InstallerError(Exception):
    """Base exception for all installer errors."""

    def __init__(self, message: str, code: str = "INSTALLER_ERROR",
                 fix_hint: str = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.fix_hint = fix_hint


class UserInputError(InstallerError):
    def __init__(self, message: str, field: str = None, fix_hint: str = None):
        super().__init__(message, "USER_INPUT_ERROR", fix_hint)
        self.field = field


class ValidationError(InstallerError):
    def __init__(self, message: str, field: str = None, fix_hint: str = None):
        super().__init__(message, "VALIDATION_ERROR", fix_hint)
        self.field = field


class SystemError(InstallerError):
    def __init__(self, message: str, command: str = None, fix_hint: str = None):
        super().__init__(message, "SYSTEM_ERROR", fix_hint)
        self.command = command


class NetworkError(InstallerError):
    def __init__(self, message: str, url: str = None, fix_hint: str = None):
        super().__init__(message, "NETWORK_ERROR", fix_hint)
        self.url = url


class ConfigError(InstallerError):
    def __init__(self, message: str, file: str = None, fix_hint: str = None):
        super().__init__(message, "CONFIG_ERROR", fix_hint)
        self.file = file


class ServiceError(InstallerError):
    def __init__(self, message: str, service: str = None, fix_hint: str = None):
        super().__init__(message, "SERVICE_ERROR", fix_hint)
        self.service = service


class CryptoError(InstallerError):
    def __init__(self, message: str, operation: str = None, fix_hint: str = None):
        super().__init__(message, "CRYPTO_ERROR", fix_hint)
        self.operation = operation


class RollbackError(InstallerError):
    def __init__(self, message: str, step: str = None, fix_hint: str = None):
        super().__init__(message, "ROLLBACK_ERROR", fix_hint)
        self.step = step


class StateError(InstallerError):
    def __init__(self, message: str, fix_hint: str = None):
        super().__init__(message, "STATE_ERROR", fix_hint)


class UserAbortError(InstallerError):
    def __init__(self, message: str = "Installation aborted by user"):
        super().__init__(message, "USER_ABORT", "Run the installer again to continue")


class PortConflictError(InstallerError):
    """A public port is already owned by another service."""

    def __init__(self, port: int, owner: str = "", fix_hint: str = None):
        detail = f"Port {port} is already in use"
        if owner:
            detail += f" by: {owner}"
        super().__init__(
            detail,
            "PORT_CONFLICT",
            fix_hint or (
                f"Stop/disable the process using port {port}, or choose a "
                "different port with --port. The installer never kills or "
                "reconfigures unrelated services."
            ),
        )
        self.port = port


class HAProxyConflictError(InstallerError):
    """The existing HAProxy configuration already binds the target port."""

    def __init__(self, message: str, fix_hint: str = None):
        super().__init__(message, "HAPROXY_CONFLICT", fix_hint)


class PKIError(InstallerError):
    def __init__(self, message: str, fix_hint: str = None):
        super().__init__(message, "PKI_ERROR", fix_hint)


ERROR_TITLES = {
    "USER_INPUT_ERROR": "Input Error",
    "VALIDATION_ERROR": "Validation Failed",
    "SYSTEM_ERROR": "System Error",
    "NETWORK_ERROR": "Network Error",
    "CONFIG_ERROR": "Configuration Error",
    "SERVICE_ERROR": "Service Error",
    "CRYPTO_ERROR": "Cryptography Error",
    "ROLLBACK_ERROR": "Rollback Failed",
    "STATE_ERROR": "State Error",
    "USER_ABORT": "Aborted",
    "PORT_CONFLICT": "Port Conflict",
    "HAPROXY_CONFLICT": "HAProxy Configuration Conflict",
    "PKI_ERROR": "Certificate Error",
    "INSTALLER_ERROR": "Installation Error",
}


def format_error(error: InstallerError, log_path: str = "") -> str:
    """Format an installer error for a Rich panel."""
    title = ERROR_TITLES.get(error.code, "Error")
    lines = [
        f"[bold red]❌ {title} ({error.code})[/bold red]",
        "",
        f"[bold]What happened:[/bold] {error.message}",
    ]
    if getattr(error, "fix_hint", None):
        lines.append(f"[bold]How to fix:[/bold] {error.fix_hint}")
    if log_path:
        lines.append(f"[bold]Full log:[/bold] {log_path}")
    lines.append(
        "[dim]Nothing outside this installer's own managed files was removed. "
        "Re-run with --verbose for more detail.[/dim]"
    )
    return "\n".join(lines)
