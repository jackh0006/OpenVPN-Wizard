"""Post-install validation, driven entirely by the chosen configuration."""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path
from typing import List, Tuple

from core.config import InstallConfig
from core.logger import get_logger
from core.render import validate_client_profile
from steps.openvpn import OpenVPNStep


def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


def _tcp(port: int, host: str) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(2)
            return sock.connect_ex((host, port)) == 0
    except OSError:
        return False


def run_validation(config: InstallConfig) -> List[Tuple[str, bool, str]]:
    logger = get_logger()
    checks = [
        (f"OpenVPN service ({OpenVPNStep.openvpn_service_name()})", _service_active, {}),
        ("OpenVPN server config exists", _server_conf_exists, {}),
        ("OpenVPN config uses TLS-crypt + AEAD", _server_crypto, {}),
        ("MTU, MSS and buffers are configured", _server_tuning, {}),
        ("CRL is valid", _crl_valid, {}),
        ("IPv4 forwarding", _ip_forward, {}),
        ("IPv6 policy", _ipv6_policy, {}),
        ("Client profiles exist and validate", _profiles_valid, {}),
        ("Profile permissions are 600", _profile_perms, {}),
        ("Certificate/key pairs match", _key_pairs, {}),
    ]

    if config.use_haproxy:
        checks += [
            ("HAProxy service active", _haproxy_active, {}),
            ("HAProxy config syntax", _haproxy_syntax, {}),
            (f"Public TCP/{config.public_port} listening", _public_tcp, {}),
            (f"OpenVPN loopback TCP/{config.haproxy_backend_port}", _loopback_tcp, {}),
        ]
    else:
        if config.vpn_proto == "udp":
            checks.append((f"Public UDP/{config.public_port} listening", _public_udp, {}))
        else:
            checks.append((f"Public TCP/{config.public_port} listening", _public_tcp, {}))

    if config.free_tunnel:
        checks.append(("NAT masquerade rule", _nat_rule, {}))
    else:
        checks.append(("Locked mode has no redirect-gateway", _locked_profile, {}))

    results = []
    for name, fn, kwargs in checks:
        try:
            passed, details = fn(config, **kwargs)
        except Exception as exc:
            passed, details = False, f"check error: {exc}"
        results.append((name, passed, details))
        logger.info("Validation: %s - %s", name, "PASS" if passed else "FAIL")
    return results


def _service_active(config, **_) -> Tuple[bool, str]:
    name = OpenVPNStep.openvpn_service_name()
    out = _run(["systemctl", "is-active", name]).stdout.strip()
    return out == "active", out or "inactive"


def _server_conf_exists(config, **_) -> Tuple[bool, str]:
    path = Path(config.openvpn_dir) / "server.conf"
    return path.exists(), str(path)


def _server_crypto(config, **_) -> Tuple[bool, str]:
    path = Path(config.openvpn_dir) / "server.conf"
    if not path.exists():
        return False, "server.conf missing"
    text = path.read_text(errors="ignore")
    needed = ["tls-crypt", "AES-256-GCM", "remote-cert-tls client", "verify-client-cert require"]
    missing = [n for n in needed if n not in text]
    return not missing, "ok" if not missing else f"missing: {', '.join(missing)}"


def _server_tuning(config, **_) -> Tuple[bool, str]:
    path = Path(config.openvpn_dir) / "server.conf"
    if not path.exists():
        return False, "server.conf missing"
    text = path.read_text(errors="ignore")
    required = {
        "tun-mtu": str(config.tun_mtu),
        "mssfix": str(config.mssfix),
        "sndbuf": str(config.sndbuf),
        "rcvbuf": str(config.rcvbuf),
    }
    missing = [key for key, value in required.items()
               if f"{key} {value}" not in text]
    return not missing, "ok" if not missing else "missing: " + ", ".join(missing)


def _crl_valid(config, **_) -> Tuple[bool, str]:
    for path in (Path(config.pki_dir) / "crl.pem", Path(config.openvpn_dir) / "crl.pem"):
        if path.exists() and "BEGIN X509 CRL" in path.read_text(errors="ignore"):
            return True, str(path)
    return False, "no valid CRL found"


def _ip_forward(config, **_) -> Tuple[bool, str]:
    if not config.free_tunnel:
        return True, "not required in locked mode"
    value = Path("/proc/sys/net/ipv4/ip_forward").read_text().strip()
    return value == "1", f"ip_forward={value}"


def _ipv6_policy(config, **_) -> Tuple[bool, str]:
    path = Path("/proc/sys/net/ipv6/conf/all/disable_ipv6")
    if not path.exists():
        return True, "IPv6 not present in this kernel"
    value = path.read_text().strip()
    if config.ipv6_enabled:
        return value == "0", f"host IPv6 disabled={value} (expected 0)"
    return value == "1", f"host IPv6 disabled={value} (expected 1)"


def _profiles_valid(config, **_) -> Tuple[bool, str]:
    missing, invalid = [], []
    for user in config.users:
        path = Path(config.profiles_dir) / f"{user.name}.ovpn"
        if not path.exists():
            missing.append(user.name)
            continue
        problems = validate_client_profile(path.read_text(errors="ignore"))
        if problems:
            invalid.append(f"{user.name}: {', '.join(problems)}")
    if missing:
        return False, "missing: " + ", ".join(missing)
    if invalid:
        return False, "; ".join(invalid)
    return True, f"{len(config.users)} profile(s) valid"


def _profile_perms(config, **_) -> Tuple[bool, str]:
    bad = []
    for user in config.users:
        path = Path(config.profiles_dir) / f"{user.name}.ovpn"
        if path.exists() and oct(path.stat().st_mode & 0o777) != "0o600":
            bad.append(f"{user.name}={oct(path.stat().st_mode & 0o777)}")
    return not bad, "all 600" if not bad else ", ".join(bad)


def _key_pairs(config, **_) -> Tuple[bool, str]:
    pki = Path(config.pki_dir)
    bad = []
    for user in config.users:
        cert = pki / "issued" / f"{user.safe_cert_name}.crt"
        key = pki / "private" / f"{user.safe_cert_name}.key"
        if not (cert.exists() and key.exists()):
            bad.append(f"{user.name}: missing")
            continue
        a = _run(["openssl", "x509", "-in", str(cert), "-noout", "-pubkey"]).stdout.strip()
        b = _run(["openssl", "pkey", "-in", str(key), "-pubout"]).stdout.strip()
        if not a or a != b:
            bad.append(f"{user.name}: mismatch")
    return not bad, "ok" if not bad else "; ".join(bad)


def _haproxy_active(config, **_) -> Tuple[bool, str]:
    out = _run(["systemctl", "is-active", "haproxy"]).stdout.strip()
    return out == "active", out or "inactive"


def _haproxy_syntax(config, **_) -> Tuple[bool, str]:
    result = _run(["haproxy", "-c", "-f", config.haproxy_cfg])
    return result.returncode == 0, (result.stderr or result.stdout or "ok").strip()[-500:]


def _public_tcp(config, **_) -> Tuple[bool, str]:
    ok = _tcp(config.public_port, "127.0.0.1")
    return ok, f"TCP/{config.public_port} {'open' if ok else 'closed'}"


def _loopback_tcp(config, **_) -> Tuple[bool, str]:
    ok = _tcp(config.haproxy_backend_port, "127.0.0.1")
    return ok, f"127.0.0.1:{config.haproxy_backend_port} {'open' if ok else 'closed'}"


def _public_udp(config, **_) -> Tuple[bool, str]:
    out = _run(["ss", "-lunH", f"sport = :{config.public_port}"]).stdout.strip()
    return bool(out), out.splitlines()[0] if out else "not listening"


def _nat_rule(config, **_) -> Tuple[bool, str]:
    out = _run(["iptables", "-t", "nat", "-S", "POSTROUTING"]).stdout
    ok = config.vpn_subnet in out and "MASQUERADE" in out
    return ok, "present" if ok else "missing"


def _locked_profile(config, **_) -> Tuple[bool, str]:
    for user in config.users:
        path = Path(config.profiles_dir) / f"{user.name}.ovpn"
        if not path.exists():
            return False, f"{user.name}: profile missing"
        text = path.read_text(errors="ignore")
        if "route-nopull" not in text or 'pull-filter ignore "redirect-gateway"' not in text:
            return False, f"{user.name}: locked-mode directives missing"
    return True, "all profiles are locked"
