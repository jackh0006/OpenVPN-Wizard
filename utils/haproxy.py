"""
Non-destructive HAProxy integration.

The wizard NEVER rewrites or deletes unrelated HAProxy configuration.  It
appends a clearly marked, self-contained block at the end of
``/etc/haproxy/haproxy.cfg`` (or replaces only that block on later runs).
Every change is backed up first and validated with ``haproxy -c`` before it
is put live; a failed validation automatically restores the previous file.

Only one frontend can bind a given TCP port, so we refuse to touch a config
in which some *other* frontend already owns the requested port.  That is
reported as an actionable conflict instead of silently breaking it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from core.config import InstallConfig
from core.exceptions import (
    HAProxyConflictError,
    PortConflictError,
    ServiceError,
    SystemError,
)
from core.logger import get_logger
from core.render import render_haproxy_block

BEGIN_MARKER = "# >>> openvpn-wizard managed block"
END_MARKER = "# <<< openvpn-wizard managed block <<<"
_BLOCK_RE = re.compile(
    r"^# >>> openvpn-wizard managed block.*?^# <<< openvpn-wizard managed block <<<\s*$",
    re.MULTILINE | re.DOTALL,
)
_BIND_RE = re.compile(r"^\s*bind\s+(.+)$", re.IGNORECASE)
_SECTION_RE = re.compile(
    r"^\s*(global|defaults|frontend|backend|listen|peers|resolvers|ring|"
    r"log-forward|program|http-errors|cache|userlist|mailers)\b",
    re.IGNORECASE,
)

MINIMAL_BASE = """# Minimal HAProxy configuration created by OpenVPN Wizard.
# Only this file and the managed block below are touched.
global
    log /dev/log local0
    maxconn 4096
    daemon
    user haproxy
    group haproxy

defaults
    log global
    mode tcp
    option dontlognull
    timeout connect 5s
    timeout client 1h
    timeout server 1h
"""


@dataclass
class ApplyResult:
    changed: bool
    migrated_v1: bool = False
    backup: Optional[str] = None
    reloaded: bool = False
    block_created: bool = False
    warnings: List[str] = field(default_factory=list)


def strip_managed_block(text: str) -> Tuple[str, bool]:
    """Remove our marked block, preserving every other byte."""
    match = _BLOCK_RE.search(text)
    if not match:
        return text, False
    cleaned = text[: match.start()] + text[match.end():]
    # Keep the file tidy without touching other content.
    cleaned = cleaned.rstrip() + "\n"
    return cleaned, True


def _lines_outside_block(text: str):
    clean, _ = strip_managed_block(text)
    for number, line in enumerate(clean.splitlines(), 1):
        yield number, line


def _extract_ports(bind_value: str) -> List[int]:
    ports: List[int] = []
    # HAProxy allows comma-separated address lists, optional SSL params.
    for token in re.split(r"[\s,]+", bind_value.strip()):
        token = token.strip()
        if not token or token.startswith("#"):
            continue
        # Strip parameters such as "ssl", "crt", "alpn" and quoted strings.
        if not re.search(r"\d", token):
            continue
        candidate = token.rstrip(",")
        if candidate.startswith("["):  # [::]:443
            match = re.search(r"\]:(\d+)$", candidate)
        else:
            match = re.search(r":(\d+)$", candidate)
        if match:
            ports.append(int(match.group(1)))
        elif candidate.isdigit():
            ports.append(int(candidate))
    return ports


def find_port_conflicts(text: str, port: int) -> List[Tuple[int, str]]:
    """Return (line_number, line) for binds of ``port`` outside our block."""
    conflicts: List[Tuple[int, str]] = []
    for number, line in _lines_outside_block(text):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _BIND_RE.match(line)
        if not match:
            continue
        if port in _extract_ports(match.group(1)):
            conflicts.append((number, stripped))
    return conflicts


def is_v1_managed(text: str) -> bool:
    """Detect the exact config shape written by the old v1 installer."""
    markers = ("frontend ovpn_tcp", "backend openvpn_tcp", "frontend https_in")
    return all(marker in text for marker in markers)


def merge_managed_block(text: str, block: str) -> Tuple[str, bool]:
    """Replace our block, or append one. Returns (new_text, created)."""
    if _BLOCK_RE.search(text):
        new_text = _BLOCK_RE.sub(lambda _match: block.rstrip() + "\n", text)
        return new_text, False
    base = text.rstrip() + "\n\n" if text.strip() else ""
    return base + block.rstrip() + "\n", True


def _run(cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise SystemError(
            f"Required command not found: {cmd[0]}",
            command=" ".join(cmd),
            fix_hint=f"Install it with: apt-get install -y {cmd[0]}",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise SystemError(
            f"Command timed out: {' '.join(cmd)}",
            command=" ".join(cmd),
            fix_hint="Check system load and whether the service is stuck.",
        ) from exc


class HAProxyManager:
    def __init__(self, config: InstallConfig):
        self.config = config
        self.logger = get_logger()
        self.cfg_path = Path(config.haproxy_cfg)
        self.backup_dir = Path(config.backup_dir)

    # ── Public API ───────────────────────────────────────────────────────

    def apply(self) -> ApplyResult:
        if not self.config.use_haproxy:
            return ApplyResult(changed=False)

        self._check_other_process_on_port()

        existing = self.cfg_path.read_text(encoding="utf-8") if self.cfg_path.exists() else ""
        conflicts = find_port_conflicts(existing, self.config.public_port)
        migrated = False

        if conflicts:
            if is_v1_managed(existing):
                self.logger.warning(
                    "Detected an HAProxy config generated by OpenVPN Wizard v1. "
                    "It binds port %s twice (which is why it often fails to start). "
                    "Backing it up and migrating to the v2 managed layout.",
                    self.config.public_port,
                )
                self._backup(existing, suffix="v1-migration")
                existing = MINIMAL_BASE
                migrated = True
            else:
                details = "\n".join(f"  line {n}: {line}" for n, line in conflicts)
                raise HAProxyConflictError(
                    "The existing HAProxy configuration already binds port "
                    f"{self.config.public_port}. Refusing to break it:\n{details}",
                    fix_hint=(
                        "Paths forward (nothing was changed):\n"
                        f"  1. Re-run with --port <free-port> (e.g. 8443)\n"
                        "  2. Remove/rename the conflicting frontend yourself, then re-run\n"
                        "  3. Use UDP with --proto udp (UDP does not use HAProxy)\n"
                        "Tip: 'sudo ss -ltnp | grep :%d' shows the owner." % self.config.public_port
                    ),
                )

        block = render_haproxy_block(self.config)
        new_text, created = merge_managed_block(
            existing if existing.strip() else MINIMAL_BASE, block
        )
        if new_text == existing and not created:
            self.logger.info("HAProxy managed block is already up to date")
            return ApplyResult(changed=False, reloaded=self._is_active())

        backup = None
        if self.cfg_path.exists():
            backup = self._backup(existing, suffix="pre-apply")

        self._write_atomic(new_text)
        problems = self._validate()
        if problems:
            if backup:
                shutil.copy2(backup, self.cfg_path)
                self.logger.error("Restored previous HAProxy config after failed validation")
            else:
                self.cfg_path.unlink(missing_ok=True)
            raise HAProxyConflictError(
                "HAProxy rejected the merged configuration; the previous file "
                "was restored untouched.\n" + problems,
                fix_hint=(
                    "The existing config may already contain errors. Run "
                    f"'haproxy -c -f {self.cfg_path}' to see them, fix them, "
                    "then re-run. Your original file is still in place."
                ),
            )

        reloaded = self._reload_or_restore(backup)
        self.logger.info(
            "HAProxy: %s managed block at %s (backup: %s)",
            "added" if created else "updated", self.cfg_path, backup or "none",
        )
        return ApplyResult(
            changed=True,
            migrated_v1=migrated,
            backup=str(backup) if backup else None,
            reloaded=reloaded,
            block_created=created,
        )

    def remove(self) -> bool:
        """Remove only our managed block. Returns True if anything changed."""
        if not self.cfg_path.exists():
            return False
        text = self.cfg_path.read_text(encoding="utf-8")
        clean, found = strip_managed_block(text)
        if not found:
            return False
        backup = self._backup(text, suffix="pre-remove")
        self._write_atomic(clean)
        problems = self._validate()
        if problems:
            if backup:
                shutil.copy2(backup, self.cfg_path)
            raise HAProxyConflictError(
                "Removing the VPN block left an invalid HAProxy config; restored it.\n"
                + problems
            )
        self._reload_or_restore(backup)
        self.logger.info("Removed the OpenVPN Wizard block from %s", self.cfg_path)
        return True

    # ── Internals ────────────────────────────────────────────────────────

    def _check_other_process_on_port(self) -> None:
        """Warn/fail if a non-HAProxy process already owns the public port."""
        try:
            result = _run(["ss", "-ltnpH", f"sport = :{self.config.public_port}"])
        except SystemError:
            return
        output = (result.stdout or "").strip()
        if not output:
            return
        if "haproxy" in output:
            # Existing HAProxy binds are handled by the config merge logic.
            return
        raise PortConflictError(
            self.config.public_port,
            owner=output.splitlines()[0].strip(),
            fix_hint=(
                f"Another service is already listening on TCP {self.config.public_port}. "
                "The installer will not stop or reconfigure it. Choose another port "
                "with --port, or free the port yourself and re-run."
            ),
        )

    def _backup(self, content: str, suffix: str) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = self.backup_dir / f"haproxy.cfg.{suffix}.{stamp}"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def _write_atomic(self, content: str) -> None:
        self.cfg_path.parent.mkdir(parents=True, exist_ok=True)
        mode = 0o644
        if self.cfg_path.exists():
            mode = self.cfg_path.stat().st_mode & 0o777
        tmp = self.cfg_path.with_name(self.cfg_path.name + ".vpn-wizard.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        if self.cfg_path.exists():
            shutil.copystat(self.cfg_path, tmp)
        os.replace(tmp, self.cfg_path)
        os.chmod(self.cfg_path, mode)

    def _validate(self) -> str:
        _run(["haproxy", "-v"])
        result = _run(["haproxy", "-c", "-f", str(self.cfg_path)])
        if result.returncode == 0:
            return ""
        return (result.stderr or result.stdout or "unknown HAProxy error").strip()

    def _is_active(self) -> bool:
        result = _run(["systemctl", "is-active", "haproxy"])
        return result.returncode == 0 and result.stdout.strip() == "active"

    def _reload_or_restore(self, backup: Optional[Path]) -> bool:
        result = _run(["systemctl", "reload-or-restart", "haproxy"])
        if result.returncode == 0 and self._is_active():
            return True
        if backup:
            shutil.copy2(backup, self.cfg_path)
            _run(["systemctl", "reload-or-restart", "haproxy"])
        raise ServiceError(
            "HAProxy did not come back after loading the merged config. "
            "The previous configuration was restored.",
            service="haproxy",
            fix_hint=(
                "Check 'journalctl -u haproxy -n 100 --no-pager'. The most "
                "common causes are another process on the port or a syntax "
                "error in pre-existing config."
            ),
        )
