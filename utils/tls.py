"""
TLS certificate acquisition for the optional VLESS/TLS listener.

Preference order:
1. an existing certificate that is valid for at least 30 days and covers
   the requested names is reused;
2. Let's Encrypt via certbot HTTP-01 (standalone), when DNS points at this
   server and port 80 is free;
3. a self-signed ECDSA certificate with proper SANs (always works, but the
   client must accept it).

Nothing is overwritten unless the existing certificate is unusable.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Iterable, List

from core.config import InstallConfig
from core.logger import get_logger


def _run(cmd: List[str], timeout: int = 300) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


def _cert_covers(cert_path: Path, names: Iterable[str]) -> bool:
    if not cert_path.exists():
        return False
    result = _run(["openssl", "x509", "-in", str(cert_path), "-noout", "-checkend", "2592000"])
    if result.returncode != 0:
        return False
    text = _run(["openssl", "x509", "-in", str(cert_path), "-noout", "-ext", "subjectAltName"]).stdout
    return all(name in text for name in names)


def _dns_points_here(domain: str, server_ip: str) -> bool:
    try:
        return socket.gethostbyname(domain) == server_ip
    except OSError:
        return False


def _port_free(port: int = 80) -> bool:
    result = _run(["ss", "-ltnH", f"sport = :{port}"])
    return result.returncode == 0 and not result.stdout.strip()


def _letsencrypt(config: InstallConfig, domains: List[str],
                 cert_path: Path, key_path: Path) -> bool:
    if not shutil.which("certbot"):
        return False
    if not all(_dns_points_here(d, config.server_ip) for d in domains):
        get_logger().warning(
            "Skipping Let's Encrypt: %s does not resolve to %s",
            ", ".join(domains), config.server_ip,
        )
        return False
    if not _port_free(80):
        get_logger().warning("Skipping Let's Encrypt: TCP/80 is already in use")
        return False

    name = "openvpn-wizard"
    cmd = [
        "certbot", "certonly", "--standalone", "--non-interactive",
        "--agree-tos", "--register-unsafely-without-email",
        "--cert-name", name, "--preferred-challenges", "http-01",
    ]
    for domain in domains:
        cmd += ["-d", domain]
    result = _run(cmd, timeout=300)
    live = Path("/etc/letsencrypt/live") / name
    if result.returncode != 0 or not (live / "fullchain.pem").exists():
        get_logger().warning("Let's Encrypt failed: %s",
                             (result.stderr or result.stdout)[-800:])
        return False

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(live / "fullchain.pem", cert_path)
    shutil.copy2(live / "privkey.pem", key_path)
    os.chmod(cert_path, 0o644)
    os.chmod(key_path, 0o600)

    hook_dir = Path("/etc/letsencrypt/renewal-hooks/deploy")
    hook_dir.mkdir(parents=True, exist_ok=True)
    hook = hook_dir / "openvpn-wizard.sh"
    hook.write_text(
        "#!/bin/sh\n"
        f"cp {live}/fullchain.pem {cert_path}\n"
        f"cp {live}/privkey.pem {key_path}\n"
        "chmod 644 " + str(cert_path) + "\n"
        "chmod 600 " + str(key_path) + "\n"
        "systemctl restart x-ui 2>/dev/null || true\n"
    )
    os.chmod(hook, 0o755)
    return True


def _self_signed(domains: List[str], cert_path: Path, key_path: Path) -> None:
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    san = ",".join(f"DNS:{d}" for d in domains)
    cmd = [
        "openssl", "req", "-x509", "-newkey", "ec",
        "-pkeyopt", "ec_paramgen_curve:secp384r1", "-nodes",
        "-days", "825", "-keyout", str(key_path), "-out", str(cert_path),
        "-subj", f"/CN={domains[0]}", "-addext", f"subjectAltName={san}",
    ]
    result = _run(cmd)
    if result.returncode != 0:
        raise RuntimeError(
            "Could not generate a self-signed certificate: "
            + (result.stderr or result.stdout)[-500:]
        )
    os.chmod(cert_path, 0o644)
    os.chmod(key_path, 0o600)


def ensure_certificate(config: InstallConfig, domains: List[str],
                       cert_path: str, key_path: str) -> str:
    """Ensure a usable certificate exists. Returns the source used."""
    domains = [d for d in domains if d]
    if not domains:
        raise ValueError("At least one domain is required for a TLS certificate.")
    cert = Path(cert_path)
    key = Path(key_path)

    if cert.exists() and key.exists() and _cert_covers(cert, domains):
        get_logger().info("Reusing existing TLS certificate: %s", cert)
        return "existing"

    if _letsencrypt(config, domains, cert, key):
        get_logger().info("Obtained a Let's Encrypt certificate for %s", ", ".join(domains))
        return "letsencrypt"

    get_logger().warning(
        "Using a self-signed certificate for %s. Clients will need to accept "
        "it once (or use the certificate-only OpenVPN profiles, which are separate).",
        ", ".join(domains),
    )
    _self_signed(domains, cert, key)
    return "self-signed"
