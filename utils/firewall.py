"""
Idempotent firewall and kernel tuning.

Design rules:
* never flush, reset or disable the system firewall;
* never disable IPv6 globally (that breaks unrelated services);
* only append rules that do not already exist;
* persist the complete current ruleset, so other rules survive reboots.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List

from core.config import InstallConfig
from core.exceptions import SystemError
from core.logger import get_logger

SYSCTL_PATH = Path("/etc/sysctl.d/99-openvpn-wizard.conf")
SYSCTL_MARKER = "# OpenVPN Wizard v2 managed sysctl settings"


def _run(cmd: List[str], timeout: int = 60) -> subprocess.CompletedProcess:
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
            fix_hint="Check system load and firewall state.",
        ) from exc


def detect_wan_interface() -> str:
    result = _run(["ip", "route", "show", "default"])
    for line in result.stdout.splitlines():
        if line.startswith("default"):
            parts = line.split()
            if "dev" in parts:
                idx = parts.index("dev")
                if idx + 1 < len(parts):
                    return parts[idx + 1]
    return "eth0"


def _ufw_active() -> bool:
    try:
        result = _run(["ufw", "status"])
    except SystemError:
        # Minimal images often do not ship ufw. iptables is handled separately.
        return False
    return result.returncode == 0 and "Status: active" in result.stdout


def _iptables_rule_exists(args: List[str]) -> bool:
    return _run(["iptables", "-C", *args]).returncode == 0


class FirewallManager:
    def __init__(self, config: InstallConfig):
        self.config = config
        self.logger = get_logger()
        self.iface = config.wan_interface or detect_wan_interface()

    # ── Public API ───────────────────────────────────────────────────────

    def apply(self) -> dict:
        actions = {"ufw": [], "iptables": [], "sysctl": [], "warnings": []}

        self._configure_sysctl(actions)
        self._open_public_port(actions)

        if self.config.free_tunnel:
            self._configure_nat(actions)
        else:
            self.logger.info(
                "Locked mode: no NAT/forwarding rules are added. Clients can "
                "only reach the VPN subnet and cannot use this VPS as an "
                "internet exit."
            )

        self._persist(actions)
        return actions

    def remove(self) -> None:
        """Remove only rules this installer would have added."""
        subnet = self.config.vpn_cidr
        iface = self.iface
        for args in (
            ["-t", "nat", "-D", "POSTROUTING", "-s", subnet, "-o", iface, "-j", "MASQUERADE"],
            ["-D", "FORWARD", "-i", "tun0", "-o", iface, "-j", "ACCEPT"],
            ["-D", "FORWARD", "-i", iface, "-o", "tun0", "-m", "conntrack",
             "--ctstate", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
        ):
            _run(["iptables", *args])
        if SYSCTL_PATH.exists():
            SYSCTL_PATH.unlink()
        # Do not globally lower ip_forward: another VPN or router may rely on
        # it. Removing the file stops it from being re-applied at boot.
        self._persist({"warnings": []})

    # ── Internals ────────────────────────────────────────────────────────

    def _configure_sysctl(self, actions: dict) -> None:
        lines = [
            SYSCTL_MARKER,
            "# VPN-related knobs. IPv6 is controlled by the explicit wizard choice.",
            "net.ipv4.ip_forward = 1",
            "net.core.default_qdisc = fq",
        ]
        if self.config.ipv6_enabled:
            lines.extend([
                "net.ipv6.conf.all.disable_ipv6 = 0",
                "net.ipv6.conf.default.disable_ipv6 = 0",
            ])
        else:
            lines.extend([
                "net.ipv6.conf.all.disable_ipv6 = 1",
                "net.ipv6.conf.default.disable_ipv6 = 1",
            ])
        # Enable BBR only when the kernel module is actually available.
        try:
            modprobe = _run(["modprobe", "tcp_bbr"])
            bbr_available = modprobe.returncode == 0
        except SystemError:
            bbr_available = False
        if bbr_available:
            lines.append("net.ipv4.tcp_congestion_control = bbr")
        else:
            actions["warnings"].append(
                "Kernel BBR module is unavailable; keeping the current TCP "
                "congestion control algorithm."
            )

        if self.config.free_tunnel:
            lines.extend([
                "net.core.rmem_max = 16777216",
                "net.core.wmem_max = 16777216",
            ])

        content = "\n".join(lines) + "\n"
        previous = SYSCTL_PATH.read_text() if SYSCTL_PATH.exists() else ""
        if previous != content:
            SYSCTL_PATH.parent.mkdir(parents=True, exist_ok=True)
            SYSCTL_PATH.write_text(content)
            os.chmod(SYSCTL_PATH, 0o644)
            actions["sysctl"].append(str(SYSCTL_PATH))
        # Apply only our file. Running `sysctl --system` would also apply
        # unrelated (possibly broken) files and is unnecessary.
        result = _run(["sysctl", "-p", str(SYSCTL_PATH)])
        if result.returncode != 0:
            raise SystemError(
                "Could not apply the VPN kernel settings.",
                command=f"sysctl -p {SYSCTL_PATH}",
                fix_hint=(result.stderr or "").strip(),
            )

    def _open_public_port(self, actions: dict) -> None:
        port = self.config.public_port
        proto = "udp" if self.config.vpn_proto == "udp" else "tcp"
        if _ufw_active():
            result = _run(["ufw", "allow", f"{port}/{proto}"])
            if result.returncode == 0:
                actions["ufw"].append(f"{port}/{proto}")
            else:
                actions["warnings"].append(
                    f"ufw refused to add {port}/{proto}: "
                    f"{(result.stderr or result.stdout).strip()}"
                )

        chain = "INPUT"
        args = ["-p", proto, "--dport", str(port), "-j", "ACCEPT"]
        exists = _run(["iptables", "-C", chain, *args]).returncode == 0
        if not exists:
            result = _run(["iptables", "-I", chain, "1", *args])
            if result.returncode != 0:
                raise SystemError(
                    f"Could not open {proto}/{port} in iptables.",
                    command=f"iptables -I {chain} 1 " + " ".join(args),
                    fix_hint=(result.stderr or "").strip(),
                )
            actions["iptables"].append(f"INPUT {proto}/{port}")

    def _configure_nat(self, actions: dict) -> None:
        subnet = self.config.vpn_cidr
        iface = self.iface
        nat = ["-t", "nat", "-A", "POSTROUTING", "-s", subnet, "-o", iface,
               "-j", "MASQUERADE"]
        if _run(["iptables", "-C", *nat]).returncode != 0:
            result = _run(["iptables", *nat])
            if result.returncode != 0:
                raise SystemError(
                    f"Could not add NAT rule for {subnet} via {iface}.",
                    command="iptables " + " ".join(nat),
                    fix_hint=(result.stderr or "").strip(),
                )
            actions["iptables"].append(f"NAT {subnet} -> {iface}")

        forward_rules = [
            ["-i", "tun0", "-o", iface, "-j", "ACCEPT"],
            ["-i", iface, "-o", "tun0", "-m", "conntrack",
             "--ctstate", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
        ]
        for rule in forward_rules:
            if _run(["iptables", "-C", "FORWARD", *rule]).returncode != 0:
                # Insert at the top so a default DROP from UFW or another
                # firewall cannot silently defeat VPN forwarding.
                result = _run(["iptables", "-I", "FORWARD", "1", *rule])
                if result.returncode != 0:
                    raise SystemError(
                        "Could not add VPN forwarding rule.",
                        command="iptables -I FORWARD 1 " + " ".join(rule),
                        fix_hint=(result.stderr or "").strip(),
                    )
                actions["iptables"].append("FORWARD " + " ".join(rule))

    def _persist(self, actions: dict) -> None:
        persistent = _run(["systemctl", "is-enabled", "netfilter-persistent"])
        if persistent.returncode == 0:
            result = _run(["netfilter-persistent", "save"])
            if result.returncode != 0:
                actions.setdefault("warnings", []).append(
                    "netfilter-persistent save failed; rules are active now "
                    "but may not survive a reboot."
                )
            return
        rules_dir = Path("/etc/iptables")
        if rules_dir.is_dir():
            result = _run(["bash", "-c", "iptables-save > /etc/iptables/rules.v4"])
            if result.returncode != 0:
                actions.setdefault("warnings", []).append(
                    "Could not persist iptables rules to /etc/iptables/rules.v4."
                )
        else:
            actions.setdefault("warnings", []).append(
                "No netfilter-persistent or /etc/iptables directory found; "
                "firewall rules are active but not persisted."
            )
