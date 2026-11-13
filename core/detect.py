"""
Detect an existing, working OpenVPN setup and preserve its behaviour.

This is what makes upgrades safe.  On a server that already has a working
``/etc/openvpn/server.conf`` we read the transport port, crypto parameters,
MTU/socket buffers, verification mode and certificate CN.  Those become the
defaults for the new configuration, so existing profiles keep working and the
HAProxy backend keeps pointing at the right loopback port.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional

from core.config import InstallConfig
from core.logger import get_logger

DEFAULT_OPENVPN_CONF = Path("/etc/openvpn/server.conf")


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="ignore")
    except OSError:
        return ""


def _first(text: str, key: str) -> Optional[str]:
    match = re.search(rf"^\s*{re.escape(key)}\s+(.+?)\s*$", text, re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip()


def _push_value(text: str, key: str) -> Optional[str]:
    match = re.search(rf'^\s*push\s+"{re.escape(key)}\s+([^"]+)"', text, re.MULTILINE)
    return match.group(1).strip() if match else None


def _cert_cn(cert_path: Path) -> Optional[str]:
    if not cert_path.exists() or not shutil.which("openssl"):
        return None
    result = subprocess.run(
        ["openssl", "x509", "-in", str(cert_path), "-noout", "-subject"],
        capture_output=True, text=True, check=False,
    )
    match = re.search(r"CN\s*=\s*([^,/]+)", result.stdout)
    return match.group(1).strip() if match else None


def detect_openvpn_config(path: str | Path | None = None) -> Dict:
    """Return only the settings that are present in the file."""
    path = Path(path or DEFAULT_OPENVPN_CONF)
    text = _read(path)
    if not text.strip():
        return {}
    out: Dict = {"path": str(path)}

    port = _first(text, "port")
    if port and port.isdigit():
        out["port"] = int(port)
    proto = (_first(text, "proto") or "").lower()
    if proto.startswith("tcp"):
        out["proto"] = "tcp"
    elif proto.startswith("udp"):
        out["proto"] = "udp"

    for key, field_name in (
        ("cipher", "cipher"),
        ("auth", "auth_digest"),
        ("data-ciphers", "data_ciphers"),
        ("tls-version-min", "tls_min"),
        ("tls-version-max", "tls_max"),
        ("tls-ciphersuites", "tls_ciphersuites"),
        ("tls-cipher", "tls_cipher"),
        ("tun-mtu", "tun_mtu"),
        ("mssfix", "mssfix"),
        ("sndbuf", "sndbuf"),
        ("rcvbuf", "rcvbuf"),
        ("verify-client-cert", "verify_client_cert"),
    ):
        value = _first(text, key)
        if value is None:
            continue
        if field_name in {"tun_mtu", "mssfix", "sndbuf", "rcvbuf"}:
            # Values such as "0" or "1400" are common.
            number = re.match(r"^-?\d+", value)
            if number:
                out[field_name] = int(number.group(0))
        else:
            out[field_name] = value.split()[0]
    if re.search(r"^\s*duplicate-cn\s*$", text, re.MULTILINE):
        out["duplicate_cn"] = True

    server = _first(text, "server")
    if server:
        parts = server.split()
        if len(parts) >= 2:
            out["vpn_subnet"] = parts[0]
            out["vpn_netmask"] = parts[1]

    cert = _first(text, "cert")
    if cert:
        cn = _cert_cn(Path(cert))
        if cn:
            out["server_cert_cn"] = cn
            out["cert_path"] = cert

    # Values that are pushed to clients are a better source when the local
    # directive is absent (the reference server pushes MTU and buffers).
    for key, field_name in (
        ("tun-mtu", "tun_mtu"), ("mssfix", "mssfix"),
        ("sndbuf", "sndbuf"), ("rcvbuf", "rcvbuf"),
    ):
        if field_name not in out:
            value = _push_value(text, key)
            if value:
                number = re.match(r"^-?\d+", value)
                if number:
                    out[field_name] = int(number.group(0))

    return out


def apply_existing_setup(config: InstallConfig) -> Dict:
    """Merge detected values into ``config`` and return what was found."""
    if not config.detect_existing:
        return {}
    detected = detect_openvpn_config()
    if not detected:
        return {}

    log = get_logger()
    if detected.get("port") and not config.internal_port:
        config.internal_port = int(detected["port"])
    for field in (
        "cipher", "data_ciphers", "auth_digest", "tls_min", "tls_max",
        "tls_ciphersuites", "tls_cipher", "tun_mtu", "mssfix", "sndbuf",
        "rcvbuf", "verify_client_cert", "duplicate_cn", "vpn_subnet",
        "vpn_netmask", "server_cert_cn",
    ):
        if field in detected:
            setattr(config, field, detected[field])

    # Certificate-only mode cannot safely run without certificate checks.
    if config.auth_mode == "cert" and config.verify_client_cert != "require":
        config.verify_client_cert = "require"
        log.warning(
            "Existing server had verify-client-cert=%s; certificate-only mode "
            "requires 'require', so it was raised for security.",
            detected.get("verify_client_cert"),
        )

    log.info(
        "Detected existing OpenVPN config: port %s, auth %s, TLS %s-%s, "
        "MTU %s, mssfix %s, buffers %s/%s, cert CN %s",
        config.openvpn_listen_port, config.auth_digest, config.tls_min,
        config.tls_max, config.tun_mtu, config.mssfix, config.sndbuf,
        config.rcvbuf, config.server_cert_cn,
    )
    return detected
