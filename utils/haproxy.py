"""
Non-destructive HAProxy integration.

Three cases are handled:

1. **No listener on the target port** — append a marked standalone frontend and
   backend. Existing config is untouched.
2. **An existing TCP frontend already binds the port** — if it already routes
   to the OpenVPN loopback port, reuse it and change nothing. Otherwise insert
   one marked `use_backend … if !{ req_ssl_hello_type 1 }` rule so non-TLS
   OpenVPN traffic reaches the VPN while every existing SNI route stays intact.
3. **A conflicting HTTP frontend or an ambiguous multi-bind** — refuse and
   explain exactly how to proceed.

Every write is backed up, validated with ``haproxy -c``, and restored on
failure. Removal deletes only the marked blocks/routes this installer added.
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
ROUTE_BEGIN = "# >>> openvpn-wizard route (v2) >>>"
ROUTE_END = "# <<< openvpn-wizard route (v2) <<<"
BACKEND_BEGIN = "# >>> openvpn-wizard backend (v2) >>>"
BACKEND_END = "# <<< openvpn-wizard backend (v2) <<<"

_BLOCK_RE = re.compile(
    r"^# >>> openvpn-wizard managed block.*?^# <<< openvpn-wizard managed block <<<[ \t]*\n?",
    re.MULTILINE | re.DOTALL,
)
_ROUTE_RE = re.compile(
    r"^# >>> openvpn-wizard route \(v2\) >>>.*?^# <<< openvpn-wizard route \(v2\) <<<[ \t]*\n?",
    re.MULTILINE | re.DOTALL,
)
_BACKEND_RE = re.compile(
    r"^# >>> openvpn-wizard backend \(v2\) >>>.*?^# <<< openvpn-wizard backend \(v2\) <<<[ \t]*\n?",
    re.MULTILINE | re.DOTALL,
)
_BIND_RE = re.compile(r"^\s*bind\s+(.+)$", re.IGNORECASE)
_SECTION_RE = re.compile(
    r"^\s*(global|defaults|frontend|backend|listen|peers|resolvers|ring|"
    r"log-forward|program|http-errors|cache|userlist|mailers)\b",
    re.IGNORECASE,
)
_DEFAULT_BACKEND_RE = re.compile(r"^\s*default_backend\s+(\S+)", re.IGNORECASE)
_USE_BACKEND_RE = re.compile(r"^\s*use_backend\s+(\S+)(?:\s+(.*))?$", re.IGNORECASE)
_MODE_RE = re.compile(r"^\s*mode\s+(tcp|http)\b", re.IGNORECASE)
_SERVER_RE = re.compile(r"^\s*server\s+\S+\s+([^\s]+)", re.IGNORECASE)

MINIMAL_BASE = """# Minimal HAProxy configuration created by OpenVPN Wizard.
# Only this file and the managed blocks below are touched.
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
class Section:
    kind: str
    name: str
    start: int
    end: int
    body: List[str] = field(default_factory=list)


@dataclass
class FrontendInfo(Section):
    binds: List[int] = field(default_factory=list)
    mode: str = "tcp"
    default_backend: str = ""
    use_backends: List[Tuple[str, str]] = field(default_factory=list)
    has_inspect: bool = False

    @property
    def routes_to_plain_tcp(self) -> bool:
        for target, condition in self.use_backends:
            if "req_ssl_hello_type" in condition and "!" in condition:
                return True
        return False


@dataclass
class BackendInfo(Section):
    servers: List[Tuple[str, int]] = field(default_factory=list)
    mode: str = "tcp"


@dataclass
class ApplyResult:
    changed: bool
    migrated_v1: bool = False
    backup: Optional[str] = None
    reloaded: bool = False
    block_created: bool = False
    reused_existing: bool = False
    inserted_route: bool = False
    warnings: List[str] = field(default_factory=list)


# ── Pure helpers (unit tested) ──────────────────────────────────────────


def strip_managed_block(text: str) -> Tuple[str, bool]:
    match = _BLOCK_RE.search(text)
    if not match:
        return text, False
    cleaned = text[: match.start()] + text[match.end():]
    return cleaned.rstrip() + "\n", True


def strip_all_wizard_blocks(text: str) -> Tuple[str, bool]:
    found = False
    for pattern in (_BLOCK_RE, _ROUTE_RE, _BACKEND_RE):
        new_text, changed = pattern.subn("", text)
        if changed:
            found = True
            text = new_text
    return text.rstrip() + "\n", found


def _extract_ports(bind_value: str) -> List[int]:
    ports: List[int] = []
    for token in re.split(r"[\s,]+", bind_value.strip()):
        token = token.strip()
        if not token or token.startswith("#"):
            continue
        if not re.search(r"\d", token):
            continue
        candidate = token.rstrip(",")
        if candidate.startswith("["):
            match = re.search(r"\]:(\d+)$", candidate)
        else:
            match = re.search(r":(\d+)$", candidate)
        if match:
            ports.append(int(match.group(1)))
        elif candidate.isdigit():
            ports.append(int(candidate))
    return ports


def _lines_outside_block(text: str):
    clean, _ = strip_managed_block(text)
    for number, line in enumerate(clean.splitlines(), 1):
        yield number, line


def find_port_conflicts(text: str, port: int) -> List[Tuple[int, str]]:
    conflicts: List[Tuple[int, str]] = []
    clean, _ = strip_managed_block(text)
    in_managed_route = False
    for number, line in enumerate(clean.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(ROUTE_BEGIN) or stripped.startswith(BACKEND_BEGIN):
            in_managed_route = True
            continue
        if stripped.startswith(ROUTE_END) or stripped.startswith(BACKEND_END):
            in_managed_route = False
            continue
        if in_managed_route or not stripped or stripped.startswith("#"):
            continue
        match = _BIND_RE.match(line)
        if match and port in _extract_ports(match.group(1)):
            conflicts.append((number, stripped))
    return conflicts


def is_v1_managed(text: str) -> bool:
    markers = ("frontend ovpn_tcp", "backend openvpn_tcp", "frontend https_in")
    return all(marker in text for marker in markers)


def merge_managed_block(text: str, block: str) -> Tuple[str, bool]:
    if _BLOCK_RE.search(text):
        new_text = _BLOCK_RE.sub(lambda _match: block.rstrip() + "\n", text)
        return new_text, False
    base = text.rstrip() + "\n\n" if text.strip() else ""
    return base + block.rstrip() + "\n", True


def parse_config(text: str) -> Tuple[List[FrontendInfo], List[BackendInfo]]:
    """Parse frontend/backend sections, effective modes and bind ports."""
    lines = text.splitlines()
    defaults_mode = "tcp"
    frontends: List[FrontendInfo] = []
    backends: List[BackendInfo] = []

    # Find defaults mode first (the last defaults block wins).
    for line in lines:
        match = _MODE_RE.match(line)
        if match:
            defaults_mode = match.group(1).lower()

    index = 0
    while index < len(lines):
        match = _SECTION_RE.match(lines[index])
        if not match:
            index += 1
            continue
        kind = match.group(1).lower()
        if kind == "defaults":
            # Update the effective mode for sections that follow.
            block = _collect_section(lines, index)
            for body_line in block.body:
                mode_match = _MODE_RE.match(body_line)
                if mode_match:
                    defaults_mode = mode_match.group(1).lower()
            index = block.end
            continue
        if kind not in {"frontend", "backend", "listen"}:
            index += 1
            continue
        block = _collect_section(lines, index)
        name = _section_name(lines[index], kind)
        if kind in {"frontend", "listen"}:
            fe = FrontendInfo(kind=kind, name=name, start=block.start,
                              end=block.end, body=block.body, mode=defaults_mode)
            for body_line in block.body:
                bind = _BIND_RE.match(body_line)
                if bind:
                    fe.binds.extend(_extract_ports(bind.group(1)))
                mode = _MODE_RE.match(body_line)
                if mode:
                    fe.mode = mode.group(1).lower()
                default = _DEFAULT_BACKEND_RE.match(body_line)
                if default:
                    fe.default_backend = default.group(1)
                use = _USE_BACKEND_RE.match(body_line)
                if use:
                    fe.use_backends.append((use.group(1), use.group(2) or ""))
                if "inspect-delay" in body_line:
                    fe.has_inspect = True
            frontends.append(fe)
        if kind in {"backend", "listen"}:
            be = BackendInfo(kind=kind, name=name, start=block.start,
                             end=block.end, body=block.body, mode=defaults_mode)
            for body_line in block.body:
                mode = _MODE_RE.match(body_line)
                if mode:
                    be.mode = mode.group(1).lower()
                server = _SERVER_RE.match(body_line)
                if server:
                    hostport = server.group(1)
                    if hostport.startswith("["):
                        host, _, port_text = hostport.rpartition("]:")
                        host = host + "]"
                    else:
                        host, _, port_text = hostport.rpartition(":")
                    if port_text.isdigit():
                        be.servers.append((host, int(port_text)))
            backends.append(be)
        index = block.end
    return frontends, backends


def _collect_section(lines: List[str], start: int) -> Section:
    index = start + 1
    kind_match = _SECTION_RE.match(lines[start])
    kind = kind_match.group(1).lower() if kind_match else "other"
    name = _section_name(lines[start], kind)
    body: List[str] = []
    while index < len(lines) and not _SECTION_RE.match(lines[index]):
        body.append(lines[index])
        index += 1
    return Section(kind=kind, name=name, start=start, end=index, body=body)


def _section_name(line: str, kind: str) -> str:
    parts = line.strip().split()
    return parts[1] if len(parts) > 1 else kind


def _backend_reaches_port(backends: List[BackendInfo], name: str, port: int) -> bool:
    for backend in backends:
        if backend.name != name:
            continue
        for host, server_port in backend.servers:
            if server_port == port and host in {"127.0.0.1", "localhost", "::1"}:
                return True
    return False


def _frontend_reuses_openvpn(frontend: FrontendInfo, backends: List[BackendInfo],
                             port: int) -> bool:
    candidates = []
    if frontend.default_backend:
        candidates.append(frontend.default_backend)
    candidates.extend(name for name, _ in frontend.use_backends)
    return any(_backend_reaches_port(backends, name, port) for name in candidates)


def _insert_route(text: str, frontend: FrontendInfo, backend_name: str,
                  need_inspect: bool) -> str:
    lines = text.splitlines()
    route = [ROUTE_BEGIN,
             f"    use_backend {backend_name} if !{{ req_ssl_hello_type 1 }}"]
    if need_inspect:
        route[1:1] = [
            "    tcp-request inspect-delay 2s",
            "    tcp-request content accept if { req_ssl_hello_type 1 }",
        ]
    route.append(ROUTE_END)

    # Insert before default_backend, otherwise at the end of the section.
    insert_at = None
    for idx in range(frontend.start + 1, frontend.end):
        if _DEFAULT_BACKEND_RE.match(lines[idx]):
            insert_at = idx
            break
    if insert_at is None:
        insert_at = frontend.end
    lines[insert_at:insert_at] = route
    return "\n".join(lines) + "\n"


def _backend_block(config: InstallConfig, name: str = "ovpn_wizard_openvpn") -> str:
    port = config.haproxy_backend_port
    return (
        f"{BACKEND_BEGIN}\n"
        f"backend {name}\n"
        "    mode tcp\n"
        f"    timeout connect 5s\n"
        f"    timeout server 1h\n"
        f"    server openvpn 127.0.0.1:{port}\n"
        f"{BACKEND_END}\n"
    )


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


# ── Manager ─────────────────────────────────────────────────────────────


class HAProxyManager:
    def __init__(self, config: InstallConfig):
        self.config = config
        self.logger = get_logger()
        self.cfg_path = Path(config.haproxy_cfg)
        self.backup_dir = Path(config.backup_dir)

    def apply(self) -> ApplyResult:
        if not self.config.use_haproxy:
            return ApplyResult(changed=False)

        self._check_other_process_on_port()
        existing = self.cfg_path.read_text(encoding="utf-8") if self.cfg_path.exists() else ""
        migrated = False

        # Migrate only the exact v1 layout (which bound 443 twice and could not
        # be safely edited).
        if is_v1_managed(existing):
            self.logger.warning(
                "Detected the exact OpenVPN Wizard v1 HAProxy layout. Backing it "
                "up and migrating to the additive v2 layout."
            )
            self._backup(existing, suffix="v1-migration")
            existing = MINIMAL_BASE
            migrated = True

        if not existing.strip():
            existing = MINIMAL_BASE

        frontends, backends = parse_config(existing)
        on_port = [f for f in frontends if self.config.public_port in f.binds]

        changed = False
        backup = None
        reused = False
        inserted = False

        if len(on_port) > 1:
            details = ", ".join(f.name for f in on_port)
            raise HAProxyConflictError(
                f"Multiple HAProxy frontends bind port {self.config.public_port} "
                f"({details}); refusing to guess which one owns the traffic.",
                fix_hint=(
                    "Nothing was changed. Choose a different --port, or remove "
                    "the duplicate frontend manually, then re-run."
                ),
            )

        if len(on_port) == 1:
            frontend = on_port[0]
            if frontend.mode == "http":
                raise HAProxyConflictError(
                    f"HAProxy frontend '{frontend.name}' binds port "
                    f"{self.config.public_port} in HTTP mode. Raw OpenVPN TCP "
                    "cannot pass through an HTTP frontend.",
                    fix_hint=(
                        "Nothing was changed. Use a different --port, or change "
                        "that frontend to 'mode tcp' yourself."
                    ),
                )
            if _frontend_reuses_openvpn(frontend, backends,
                                        self.config.haproxy_backend_port):
                self.logger.info(
                    "HAProxy frontend '%s' already routes port %s to OpenVPN "
                    "127.0.0.1:%s; leaving HAProxy unchanged.",
                    frontend.name, self.config.public_port,
                    self.config.haproxy_backend_port,
                )
                reused = True
            else:
                backend_name = "ovpn_wizard_openvpn"
                existing_backend = next(
                    (b for b in backends if b.name == backend_name), None
                )
                if existing_backend is not None and not (
                    existing_backend.mode == "tcp"
                    and _backend_reaches_port(
                        [existing_backend], backend_name,
                        self.config.haproxy_backend_port,
                    )
                ):
                    backend_name = (
                        f"ovpn_wizard_openvpn_{self.config.haproxy_backend_port}"
                    )
                    existing_backend = next(
                        (b for b in backends if b.name == backend_name), None
                    )
                text = existing
                if existing_backend is None:
                    text = text.rstrip() + "\n\n" + _backend_block(
                        self.config, backend_name
                    )
                need_inspect = not frontend.has_inspect
                text = _insert_route(text, frontend, backend_name, need_inspect)
                existing = text
                changed = True
                inserted = True
        else:
            # No existing listener on this port: append the standalone block.
            block = render_haproxy_block(self.config)
            new_text, created = merge_managed_block(existing, block)
            if new_text != existing:
                existing = new_text
                changed = True
            if not created and not changed:
                self.logger.info("HAProxy managed block is already up to date")
                return ApplyResult(changed=False, reloaded=self._is_active())

        if not changed:
            return ApplyResult(changed=False, reloaded=self._is_active(),
                               reused_existing=reused)

        backup = self._backup(
            self.cfg_path.read_text(encoding="utf-8") if self.cfg_path.exists() else "",
            suffix="pre-apply",
        )
        self._write_atomic(existing)
        problems = self._validate()
        if problems:
            if backup:
                shutil.copy2(backup, self.cfg_path)
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
            "HAProxy: %s at %s (backup: %s)",
            "inserted an additive VPN route" if inserted else "updated the VPN block",
            self.cfg_path, backup or "none",
        )
        return ApplyResult(
            changed=True, migrated_v1=migrated,
            backup=str(backup) if backup else None, reloaded=reloaded,
            block_created=not inserted and changed, reused_existing=reused,
            inserted_route=inserted,
        )


    def describe(self) -> dict:
        """Read-only description of what apply() would do."""
        if not self.config.use_haproxy:
            return {"action": "none", "reason": "HAProxy not used"}
        if not self.cfg_path.exists():
            return {"action": "append", "reason": "no existing HAProxy config"}
        existing = self.cfg_path.read_text(encoding="utf-8")
        frontends, backends = parse_config(existing)
        on_port = [f for f in frontends if self.config.public_port in f.binds]
        if len(on_port) > 1:
            return {"action": "conflict", "reason": "multiple frontends bind the port",
                    "frontends": [f.name for f in on_port]}
        if not on_port:
            return {"action": "append", "reason": "no listener on the target port"}
        frontend = on_port[0]
        if frontend.mode == "http":
            return {"action": "conflict", "reason": "target frontend is HTTP mode",
                    "frontend": frontend.name}
        if _frontend_reuses_openvpn(frontend, backends,
                                    self.config.haproxy_backend_port):
            return {"action": "reuse", "reason": "existing route already points to OpenVPN",
                    "frontend": frontend.name,
                    "backend_port": self.config.haproxy_backend_port}
        return {"action": "insert", "reason": "add one non-TLS route to the existing frontend",
                "frontend": frontend.name,
                "backend_port": self.config.haproxy_backend_port}

    def remove(self) -> bool:
        if not self.cfg_path.exists():
            return False
        text = self.cfg_path.read_text(encoding="utf-8")
        clean, found = strip_all_wizard_blocks(text)
        if not found:
            return False
        backup = self._backup(text, suffix="pre-remove")
        self._write_atomic(clean)
        problems = self._validate()
        if problems:
            if backup:
                shutil.copy2(backup, self.cfg_path)
            raise HAProxyConflictError(
                "Removing the VPN blocks left an invalid HAProxy config; restored it.\n"
                + problems
            )
        self._reload_or_restore(backup)
        self.logger.info("Removed only OpenVPN Wizard blocks from %s", self.cfg_path)
        return True

    # ── Internals ────────────────────────────────────────────────────────

    def _check_other_process_on_port(self) -> None:
        try:
            result = _run(["ss", "-ltnpH", f"sport = :{self.config.public_port}"])
        except SystemError:
            return
        output = (result.stdout or "").strip()
        if not output or "haproxy" in output:
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
