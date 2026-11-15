"""Read-only network inspection for safe, conflict-aware setup."""

from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class PortStatus:
    port: int
    tcp_owner: str = ""
    udp_owner: str = ""

    @property
    def available(self) -> bool:
        return not self.tcp_owner and not self.udp_owner

    @property
    def description(self) -> str:
        owners = ", ".join(x for x in (self.tcp_owner, self.udp_owner) if x)
        return "free for TCP and UDP" if not owners else f"already used by {owners}"


def _listeners(protocol: str, port: int) -> str:
    flag = "-ltnpH" if protocol == "tcp" else "-lunpH"
    try:
        result = subprocess.run(
            ["ss", flag, f"sport = :{port}"], capture_output=True, text=True, timeout=3, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return "; ".join(line.strip() for line in result.stdout.splitlines() if line.strip())


def inspect_port(port: int) -> PortStatus:
    return PortStatus(port, _listeners("tcp", port), _listeners("udp", port))


def suggested_ports(limit: int = 3) -> List[int]:
    result: List[int] = []
    for port in (443, 8443, 9443, 10443, 4443, 2053, 2083, 2087, 2096, 1194):
        if inspect_port(port).available:
            result.append(port)
        if len(result) >= limit:
            break
    return result


def domain_addresses(domain: str) -> List[str]:
    try:
        rows = socket.getaddrinfo(domain, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    return sorted({row[4][0] for row in rows})


def domain_points_to(domain: str, server_ip: str) -> Tuple[bool, List[str]]:
    addresses = domain_addresses(domain)
    return server_ip in addresses, addresses


# Backwards-compatible helpers.
def check_port(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def get_listening_ports() -> List[Tuple[str, int, str]]:
    ports: List[Tuple[str, int, str]] = []
    try:
        result = subprocess.run(
            ["ss", "-ltnupH"], capture_output=True, text=True, timeout=3, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ports
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 5 or ":" not in fields[3]:
            continue
        try:
            ports.append(
                (
                    fields[0].lower(),
                    int(fields[3].rsplit(":", 1)[1]),
                    fields[-1] if "users:" in line else "",
                )
            )
        except ValueError:
            continue
    return ports


def is_port_in_use(port: int, host: str = "0.0.0.0") -> bool:
    return not inspect_port(port).available


def get_default_gateway_interface() -> str:
    try:
        result = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            parts = line.split()
            if line.startswith("default") and "dev" in parts:
                return parts[parts.index("dev") + 1]
    except (FileNotFoundError, IndexError):
        pass
    return "eth0"
