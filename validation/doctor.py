"""`vpn-installer doctor` - explain what is wrong and how to fix it."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path
from typing import List

from rich.console import Console
from rich.table import Table

from core.config import InstallConfig
from core.render import validate_client_profile
from core.state import StateManager


class Result:
    def __init__(self, name: str, ok: bool, details: str = "", fix: str = "",
                 warning: bool = False):
        self.name = name
        self.ok = ok
        self.details = details
        self.fix = fix
        self.warning = warning


def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(cmd, 127, "", "command unavailable")


def _tcp(port: int, host: str) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            return sock.connect_ex((host, port)) == 0
    except OSError:
        return False


def run_doctor(console: Console) -> bool:
    results: List[Result] = []

    results.append(Result(
        "Root privileges",
        os.geteuid() == 0,
        "running as root" if os.geteuid() == 0 else f"uid {os.geteuid()}",
        "Run with sudo for full checks: sudo vpn-installer doctor",
        warning=True,
    ))

    os_release = Path("/etc/os-release")
    if os_release.exists():
        text = os_release.read_text(errors="ignore")
        supported = ("Ubuntu" in text or "Debian" in text)
        results.append(Result("Operating system", supported,
                              "Ubuntu/Debian detected" if supported else "unsupported distro",
                              "This installer targets Ubuntu 22.04/24.04 and Debian 12."))

    for binary, fix, extra_path in (
        ("openvpn", "apt-get install -y openvpn", None),
        ("openssl", "apt-get install -y openssl", None),
        ("iptables", "apt-get install -y iptables", None),
        ("ss", "apt-get install -y iproute2", None),
        ("easyrsa", "apt-get install -y easy-rsa", "/usr/share/easy-rsa/easyrsa"),
    ):
        path = shutil.which(binary)
        if not path and extra_path and Path(extra_path).exists():
            path = extra_path
        results.append(Result(f"Command: {binary}", bool(path), path or "not found", fix))

    state = StateManager().load()
    config = state.config if state else None
    if not config:
        results.append(Result(
            "Installation state", False, "no state file",
            "Run 'sudo vpn-installer install' first.",
        ))
    else:
        results.extend(_check_config(config))

    # Print
    table = Table(show_header=True, header_style="primary", box=None, padding=(0, 1))
    table.add_column("", width=3)
    table.add_column("Check", width=34)
    table.add_column("Details")
    failures = 0
    for result in results:
        if result.ok:
            icon = "[green]✓[/green]"
        elif result.warning:
            icon = "[yellow]![/yellow]"
        else:
            icon = "[red]✗[/red]"
            failures += 1
        table.add_row(icon, result.name, result.details)
    console.print(table)

    fixes = [r for r in results if not r.ok and r.fix]
    if fixes:
        console.print("\n[bold]Suggested fixes:[/bold]")
        for result in fixes:
            console.print(f"  [primary]{result.name}:[/primary] {result.fix}")

    console.print(
        "\n[success]✓ No blocking problems found.[/success]" if failures == 0
        else f"\n[error]{failures} blocking problem(s) found.[/error]"
    )
    return failures == 0


def _check_config(config: InstallConfig) -> List[Result]:
    results: List[Result] = []
    from steps.openvpn import OpenVPNStep

    service = OpenVPNStep.openvpn_service_name()
    active = _run(["systemctl", "is-active", service]).stdout.strip() == "active"
    results.append(Result(
        f"Service {service}", active, "active" if active else "not active",
        f"journalctl -u {service} -n 100 --no-pager; systemctl restart {service}",
    ))

    if config.use_haproxy:
        active = _run(["systemctl", "is-active", "haproxy"]).stdout.strip() == "active"
        results.append(Result("Service haproxy", active, "active" if active else "not active",
                              "journalctl -u haproxy -n 100 --no-pager"))
        check = _run(["haproxy", "-c", "-f", config.haproxy_cfg])
        results.append(Result(
            "HAProxy config syntax", check.returncode == 0,
            "valid" if check.returncode == 0 else (check.stderr or check.stdout)[-500:],
            f"haproxy -c -f {config.haproxy_cfg}",
        ))
        if not _tcp(config.public_port, "127.0.0.1"):
            results.append(Result(
                f"Public listener TCP/{config.public_port}", False,
                "nothing is listening",
                f"ss -ltnp | grep :{config.public_port}",
            ))
        if not _tcp(config.internal_port, "127.0.0.1"):
            results.append(Result(
                f"OpenVPN loopback TCP/{config.internal_port}", False,
                "nothing is listening",
                "Check the OpenVPN journal and the managed HAProxy block.",
            ))
    else:
        if config.vpn_proto == "udp":
            out = _run(["ss", "-lunH", f"sport = :{config.public_port}"]).stdout.strip()
        else:
            out = _run(["ss", "-ltnH", f"sport = :{config.public_port}"]).stdout.strip()
        results.append(Result(
            f"Public listener {config.vpn_proto.upper()}/{config.public_port}",
            bool(out), out.splitlines()[0] if out else "nothing is listening",
            f"ss -ltnup | grep :{config.public_port}",
        ))

    conf = Path(config.openvpn_dir) / "server.conf"
    results.append(Result(
        "OpenVPN server config", conf.exists(),
        str(conf) if conf.exists() else "missing",
        "Re-run the installer (it re-renders this file).",
    ))
    if conf.exists():
        content = conf.read_text(errors="ignore")
        results.append(Result(
            "TLS-crypt + AEAD",
            "tls-crypt" in content and "AES-256-GCM" in content,
            "present" if "tls-crypt" in content else "missing",
            "Re-run the installer.",
        ))
        if config.auth_mode == "userpass":
            results.append(Result(
                "PAM plugin", "openvpn-plugin-auth-pam.so" in content,
                "configured" if "openvpn-plugin-auth-pam.so" in content else "missing",
                "apt-get install -y openvpn; re-run the installer.",
            ))

    pki = Path(config.pki_dir)
    for label, path in (
        ("CA certificate", pki / "ca.crt"),
        ("Server certificate", pki / "issued" / "server.crt"),
        ("Server key", pki / "private" / "server.key"),
        ("TLS-crypt key", pki / "ta.key"),
        ("CRL", pki / "crl.pem"),
    ):
        results.append(Result(label, path.exists(), str(path) if path.exists() else "missing",
                              "Re-run the PKI step or restore from backup."))

    for user in config.users:
        cert = pki / "issued" / f"{user.safe_cert_name}.crt"
        key = pki / "private" / f"{user.safe_cert_name}.key"
        ok = cert.exists() and key.exists()
        if ok:
            a = _run(["openssl", "x509", "-in", str(cert), "-noout", "-pubkey"]).stdout
            b = _run(["openssl", "pkey", "-in", str(key), "-pubout"]).stdout
            ok = bool(a.strip()) and a.strip() == b.strip()
        results.append(Result(
            f"Certificate/key: {user.name}", ok,
            "match" if ok else "missing or mismatched",
            "Run: sudo vpn-installer manage -> export/rotate this user.",
        ))

        profile = Path(config.profiles_dir) / f"{user.name}.ovpn"
        if profile.exists():
            problems = validate_client_profile(profile.read_text(errors="ignore"))
            mode = oct(profile.stat().st_mode & 0o777)
            results.append(Result(
                f"Profile: {user.name}", not problems and mode == "0o600",
                f"mode {mode}" + (f"; {', '.join(problems)}" if problems else ""),
                "Regenerate from manage -> export profile; expected mode 600.",
            ))
        else:
            results.append(Result(
                f"Profile: {user.name}", False, "missing",
                "sudo vpn-installer manage -> export profile",
            ))

    if config.free_tunnel:
        forward = Path("/proc/sys/net/ipv4/ip_forward").read_text().strip()
        results.append(Result("IPv4 forwarding", forward == "1", f"ip_forward={forward}",
                              "Re-run the installer (firewall step)."))
        nat = _run(["iptables", "-t", "nat", "-S", "POSTROUTING"]).stdout
        results.append(Result(
            "NAT masquerade", config.vpn_subnet in nat and "MASQUERADE" in nat,
            "present" if "MASQUERADE" in nat else "missing",
            "Re-run the installer; locked mode intentionally omits NAT.",
        ))

    return results
