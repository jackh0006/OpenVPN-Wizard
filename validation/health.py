"""Service health checks used by the UI and doctor command."""

from __future__ import annotations

import subprocess
from typing import Dict, List

from core.config import InstallConfig
from steps.openvpn import OpenVPNStep


def check_service_health(service: str) -> Dict:
    result = subprocess.run(
        ["systemctl", "status", service, "--no-pager"],
        capture_output=True, text=True, check=False,
    )
    active = result.returncode == 0 and "active (running)" in result.stdout
    return {
        "service": service,
        "active": active,
        "status": "running" if active else "stopped",
        "details": (result.stdout or result.stderr)[:500],
    }


def check_all_services(config: InstallConfig) -> List[Dict]:
    services = [OpenVPNStep.openvpn_service_name()]
    if config.use_haproxy:
        services.append("haproxy")
    if config.enable_vless:
        services.append("x-ui")
    return [check_service_health(service) for service in services]


def get_service_logs(service: str, lines: int = 50) -> str:
    result = subprocess.run(
        ["journalctl", "-u", service, "-n", str(lines), "--no-pager"],
        capture_output=True, text=True, check=False,
    )
    return result.stdout if result.returncode == 0 else result.stderr
