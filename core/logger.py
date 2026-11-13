"""
Structured logging with a persistent, rotated log file.

Every install writes to ``/var/log/vpn-installer/install.log`` when running as
root (or a per-user state directory otherwise).  Log lines that could contain
credentials are redacted before they reach disk.
"""

from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler

_SECRET_PATTERNS = [
    re.compile(r"(?i)(password\s*[=:]\s*)\S+"),
    re.compile(r"(?i)(passwd\s*[=:]\s*)\S+"),
    re.compile(r"(?i)(--pass(?:word)?\s+)\S+"),
    re.compile(r"(?i)(auth-user-pass\s+)\S+"),
]


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        for pattern in _SECRET_PATTERNS:
            message = pattern.sub(r"\1[redacted]", message)
        record.msg = message
        record.args = ()
        return True


def default_log_path() -> Path:
    if os.geteuid() == 0:
        return Path("/var/log/vpn-installer/install.log")
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return state_home / "vpn-installer" / "install.log"


def setup_logger(
    name: str = "vpn-installer",
    level: int = logging.INFO,
    log_file: Optional[str] = None,
) -> logging.Logger:
    """Configure and return the installer logger (idempotent)."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    logger.handlers.clear()

    console_handler = RichHandler(
        console=Console(stderr=True),
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
    )
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))
    logger.addHandler(console_handler)

    path = Path(log_file) if log_file else default_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o750)
        file_handler = RotatingFileHandler(
            path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        file_handler.addFilter(_RedactFilter())
        logger.addHandler(file_handler)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        logger.log_path = str(path)  # type: ignore[attr-defined]
    except OSError as exc:
        logger.warning("Could not open log file %s: %s", path, exc)

    return logger


def get_logger(name: str = "vpn-installer") -> logging.Logger:
    return logging.getLogger(name)


def get_log_path() -> str:
    logger = get_logger()
    return getattr(logger, "log_path", str(default_log_path()))


class StepLogger:
    """Context manager that logs the start/end of an installation step."""

    def __init__(self, step_name: str, logger: Optional[logging.Logger] = None):
        self.step_name = step_name
        self.logger = logger or get_logger()
        self.start_time = None

    def __enter__(self):
        import time
        self.start_time = time.time()
        self.logger.info("[bold cyan]▶ Starting:[/bold cyan] %s", self.step_name)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        import time
        elapsed = time.time() - self.start_time
        if exc_type:
            self.logger.error(
                "[bold red]✗ Failed:[/bold red] %s (%.1fs) - %s",
                self.step_name, elapsed, exc_val,
            )
        else:
            self.logger.info(
                "[bold green]✓ Completed:[/bold green] %s (%.1fs)",
                self.step_name, elapsed,
            )
        return False

    def info(self, msg: str):
        self.logger.info("  %s", msg)

    def warning(self, msg: str):
        self.logger.warning("  [yellow]⚠[/yellow] %s", msg)

    def error(self, msg: str):
        self.logger.error("  [red]✗[/red] %s", msg)

    def debug(self, msg: str):
        self.logger.debug("  %s", msg)


def log_command(cmd: list, logger: Optional[logging.Logger] = None):
    log = logger or get_logger()
    log.debug("$ %s", " ".join(str(c) for c in cmd))


def log_output(output: str, logger: Optional[logging.Logger] = None,
               level: int = logging.DEBUG):
    log = logger or get_logger()
    for line in (output or "").strip().split("\n"):
        if line.strip():
            log.log(level, "  └─> %s", line)
