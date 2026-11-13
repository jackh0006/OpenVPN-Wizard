"""
Core configuration models for OpenVPN Wizard v2.

The installer is deliberately explicit about the four choices that decide how
the VPN behaves:

* endpoint   - a DNS name or a bare IP address used by clients
* transport  - TCP or UDP
* auth       - certificate + username/password, or certificate only
* access     - full tunnel ("free") or private-network-only ("locked")
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from typing import List, Optional

DEFAULT_VPN_SUBNET = "10.8.0.0"
DEFAULT_VPN_NETMASK = "255.255.255.0"
DEFAULT_DNS1 = "9.9.9.9"
DEFAULT_DNS2 = "149.112.112.112"

PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z]{2,63}$"
)
PASSWORD_SPECIALS = r"""!@#$%^&*()_+\-=\[\]{}|;:,.<>?/~`'" """

RESERVED_PROFILE_NAMES = {
    "con", "prn", "aux", "nul", "server", "ca", "crl", "ta",
}


@dataclass
class ClientSpec:
    """One human being / device that receives its own .ovpn profile."""

    name: str                      # Profile name shown in OpenVPN Connect
    username: str                  # Linux/PAM account and certificate CN
    password: str = ""             # Only used when auth_mode == "userpass"
    cert_name: str = ""            # Defaults to username

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        self.username = self.username.strip().lower()
        if not self.cert_name:
            self.cert_name = self.username

    @property
    def safe_cert_name(self) -> str:
        return sanitize_cert_name(self.cert_name or self.username)


@dataclass
class InstallConfig:
    """All settings required to build and deploy the VPN stack."""

    # ── Required identity ────────────────────────────────────────────────
    server_ip: str = ""
    endpoint_mode: str = "ip"          # "ip" | "domain"
    endpoint_host: str = ""            # What clients put in `remote`
    domain: str = ""                   # Only when endpoint_mode == "domain"

    # ── Transport ────────────────────────────────────────────────────────
    vpn_proto: str = "tcp"             # "tcp" | "udp"
    public_port: int = 443             # Port clients connect to
    internal_port: int = 0            # 0 = auto-detect existing, else 1194

    # ── Security policy ──────────────────────────────────────────────────
    auth_mode: str = "userpass"        # "userpass" | "cert"
    access_mode: str = "free"          # "free" | "locked"
    ipv6_enabled: bool = False         # False = disable host IPv6 + block clients

    # ── Profiles ─────────────────────────────────────────────────────────
    profile_prefix: str = "MHH06"
    users: List[ClientSpec] = field(default_factory=list)

    # ── Optional VLESS/Reality multiplexing (advanced, off by default) ───
    enable_vless: bool = False
    domain1: str = ""
    domain2: str = ""
    reality_domain: str = ""
    admin_user: str = "admin"
    admin_pass: str = ""

    # ── Network ──────────────────────────────────────────────────────────
    vpn_subnet: str = DEFAULT_VPN_SUBNET
    vpn_netmask: str = DEFAULT_VPN_NETMASK
    vpn_gateway: str = "10.8.0.1"
    dns1: str = DEFAULT_DNS1
    dns2: str = DEFAULT_DNS2
    max_clients: int = 128
    dh: str = "none"                    # "none" for ECDSA, path for RSA legacy PKI
    server_cert_cn: str = "server"      # detected from an existing certificate

    # ── Crypto / transport tuning (defaults match the working reference VPS) ──
    cipher: str = "AES-256-GCM"
    data_ciphers: str = "AES-256-GCM:CHACHA20-POLY1305:AES-128-GCM"
    auth_digest: str = "SHA384"         # SHA384 matches the reference profiles
    tls_min: str = "1.3"
    tls_max: str = "1.3"
    tls_ciphersuites: str = "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256"
    tls_cipher: str = (
        "TLS-ECDHE-ECDSA-WITH-AES-256-GCM-SHA384:"
        "TLS-ECDHE-RSA-WITH-AES-256-GCM-SHA384:"
        "TLS-ECDHE-ECDSA-WITH-CHACHA20-POLY1305-SHA256:"
        "TLS-ECDHE-RSA-WITH-CHACHA20-POLY1305-SHA256"
    )
    tun_mtu: int = 1400
    mssfix: int = 1360
    sndbuf: int = 524288
    rcvbuf: int = 524288
    verify_client_cert: str = "require" # require | optional | none
    duplicate_cn: bool = False

    # ── Runtime / paths ──────────────────────────────────────────────────
    openvpn_dir: str = "/etc/openvpn"
    pki_dir: str = "/etc/openvpn/pki"
    profiles_dir: str = "/etc/openvpn/clients"
    haproxy_cfg: str = "/etc/haproxy/haproxy.cfg"
    backup_dir: str = "/var/backups/vpn-installer"
    user_db: str = "/etc/openvpn/users.db"
    credentials_file: str = "/root/openvpn-wizard-credentials.txt"
    xui_db: str = "/etc/x-ui/x-ui.db"
    xui_cert: str = "/etc/x-ui/cert.pem"
    xui_key: str = "/etc/x-ui/key.pem"
    reality_key_path: str = "/etc/x-ui/reality_private.key"
    xui_inbound1_port: int = 10000      # VLESS-TLS, loopback only
    xui_tls2_port: int = 10004          # VLESS-TLS, loopback only
    xui_inbound2_port: int = 443        # VLESS-Reality, loopback only

    # ── Behaviour ────────────────────────────────────────────────────────
    manage_haproxy: bool = True
    detect_existing: bool = True
    wan_interface: str = ""
    server_ip_confirmed: bool = False
    non_interactive: bool = False
    haproxy_conflict_ok: bool = False   # Reserved for future integration mode

    def __post_init__(self) -> None:
        self.server_ip = (self.server_ip or "").strip()
        self.endpoint_mode = (self.endpoint_mode or "ip").strip().lower()
        self.domain = (self.domain or "").strip().lower().rstrip(".")
        self.endpoint_host = (self.endpoint_host or "").strip().lower().rstrip(".")
        self.vpn_proto = (self.vpn_proto or "tcp").strip().lower()
        self.auth_digest = (self.auth_digest or "SHA384").strip().upper()
        self.tls_min = str(self.tls_min or "1.3").strip()
        self.tls_max = str(self.tls_max or "").strip()
        self.auth_mode = (self.auth_mode or "userpass").strip().lower()
        self.access_mode = (self.access_mode or "free").strip().lower()
        self.profile_prefix = (self.profile_prefix or "MHH06").strip()
        self.domain1 = (self.domain1 or "").strip().lower().rstrip(".")
        self.domain2 = (self.domain2 or "").strip().lower().rstrip(".")
        self.reality_domain = (self.reality_domain or "").strip().lower().rstrip(".")
        self.admin_user = (self.admin_user or "admin").strip().lower()

        if not self.endpoint_host:
            self.endpoint_host = self.domain if self.endpoint_mode == "domain" else self.server_ip
        if self.endpoint_mode == "domain" and not self.domain and self.endpoint_host:
            self.domain = self.endpoint_host
        if not self.users and self.profile_prefix:
            # A single default profile keeps programmatic use simple.
            self.users = [
                ClientSpec(name=self.profile_prefix, username="vpnuser")
            ]
        if not self.credentials_file:
            self.credentials_file = "/root/openvpn-wizard-credentials.txt"

    # ── Derived values ───────────────────────────────────────────────────

    @property
    def remote_host(self) -> str:
        return self.endpoint_host or self.domain or self.server_ip

    @property
    def public_endpoint(self) -> str:
        return f"{self.remote_host}:{self.public_port}/{self.vpn_proto}"

    @property
    def use_haproxy(self) -> bool:
        """TCP traffic can be multiplexed. UDP is always bound directly."""
        return self.manage_haproxy and self.vpn_proto == "tcp"

    @property
    def behind_haproxy(self) -> bool:
        return self.use_haproxy

    @property
    def openvpn_bind_address(self) -> str:
        return "127.0.0.1" if self.behind_haproxy else "0.0.0.0"

    @property
    def openvpn_listen_port(self) -> int:
        if not self.behind_haproxy:
            return self.public_port
        return self.internal_port or 1194

    @property
    def haproxy_backend_port(self) -> int:
        return self.openvpn_listen_port

    @property
    def vpn_network(self) -> str:
        return self.vpn_subnet

    @property
    def vpn_cidr(self) -> str:
        return f"{self.vpn_subnet}/{ipaddress.IPv4Network(self.vpn_subnet + '/' + self.vpn_netmask, strict=False).prefixlen}"

    @property
    def free_tunnel(self) -> bool:
        return self.access_mode == "free"

    @property
    def requires_password(self) -> bool:
        return self.auth_mode == "userpass"

    # Backwards-compatible aliases used by older modules and saved state.
    @property
    def client_name(self) -> str:
        return self.users[0].name if self.users else self.profile_prefix

    @property
    def vpn_user(self) -> str:
        return self.users[0].username if self.users else "vpnuser"

    @property
    def vpn_pass(self) -> str:
        return self.users[0].password if self.users else ""

    @property
    def haproxy_port(self) -> int:
        return self.public_port

    def client_ovpn_path(self, name: Optional[str] = None) -> str:
        return f"{self.profiles_dir}/{sanitize_profile_name(name or self.client_name)}.ovpn"

    @property
    def web_ovpn_url(self) -> str:
        # Kept only for backwards compatibility. v2 never serves keys over HTTP.
        return ""

    def user_by_name(self, name: str) -> Optional[ClientSpec]:
        for user in self.users:
            if user.name == name:
                return user
        return None


# ── Validation helpers ──────────────────────────────────────────────────


def validate_ip(value: str) -> bool:
    """Validate an IPv4 or IPv6 address without ever touching the network."""
    try:
        ipaddress.ip_address((value or "").strip())
        return True
    except ValueError:
        return False


def validate_ipv4(value: str) -> bool:
    """The VPN listener is IPv4; reject IPv6 early with a clear message."""
    try:
        ipaddress.IPv4Address((value or "").strip())
        return True
    except ValueError:
        return False


def validate_hostname(value: str) -> bool:
    """Accept an FQDN, an IPv4 address, or an IPv6 address."""
    value = (value or "").strip().rstrip(".")
    if not value:
        return False
    if validate_ip(value):
        return True
    if value == "localhost":
        return True
    return bool(HOSTNAME_RE.match(value))


def validate_username(value: str) -> bool:
    # Usernames are stored lowercase; reject uppercase input so the UI and
    # CLI agree on exactly what will be created on the system.
    return bool(USERNAME_RE.match((value or "").strip()))


def validate_profile_name(value: str) -> bool:
    value = (value or "").strip()
    if not PROFILE_RE.match(value):
        return False
    return value.lower() not in RESERVED_PROFILE_NAMES


def validate_port(value: int | str) -> bool:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return False
    return 1 <= port <= 65535


def validate_password(password: str) -> tuple[bool, str]:
    """Return (valid, human readable reason)."""
    password = password or ""
    if len(password) < 12:
        return False, "Password must be at least 12 characters long."
    if len(password) > 256:
        return False, "Password must be at most 256 characters long."
    if "\n" in password or "\r" in password or ":" in password:
        return False, "Password must not contain newlines or ':' characters."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r"\d", password):
        return False, "Password must contain at least one digit."
    if not re.search(r"[^A-Za-z0-9]", password):
        return False, "Password must contain at least one symbol."
    return True, "Strong password"


def validate_transport(proto: str) -> bool:
    return (proto or "").lower() in {"tcp", "udp"}


def validate_auth_mode(mode: str) -> bool:
    return (mode or "").lower() in {"userpass", "cert"}


def validate_access_mode(mode: str) -> bool:
    return (mode or "").lower() in {"free", "locked"}


def sanitize_profile_name(name: str) -> str:
    """Turn arbitrary text into a safe single-component .ovpn filename."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "").strip()).strip(".-")
    cleaned = cleaned[:64] or "profile"
    if cleaned.lower() in RESERVED_PROFILE_NAMES:
        cleaned = f"client-{cleaned}"
    return cleaned


def sanitize_cert_name(name: str) -> str:
    """Certificate CNs must be simple, lowercase and filesystem safe."""
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", (name or "").strip().lower()).strip("-")
    return (cleaned[:64] or "client")


def validate_config(config: InstallConfig) -> List[str]:
    """Return a list of human-readable problems (empty means valid)."""
    problems: List[str] = []
    if not validate_ipv4(config.server_ip):
        problems.append("Server IP is missing or not a valid IPv4 address (IPv6 is not supported).")
    if config.endpoint_mode not in {"ip", "domain"}:
        problems.append("Endpoint mode must be 'ip' or 'domain'.")
    if config.endpoint_mode == "domain" and not validate_hostname(config.domain):
        problems.append("A valid domain name is required when using domain mode.")
    if not validate_hostname(config.endpoint_host):
        problems.append("The endpoint host (domain or IP) is invalid.")
    if config.endpoint_mode == "ip" and not validate_ipv4(config.endpoint_host):
        problems.append("The IP endpoint must be a valid IPv4 address.")
    if not validate_port(config.public_port):
        problems.append("The public port must be between 1 and 65535.")
    if config.internal_port and not validate_port(config.internal_port):
        problems.append("The internal loopback port must be between 1 and 65535.")
    if not validate_transport(config.vpn_proto):
        problems.append("Transport must be 'tcp' or 'udp'.")
    if not validate_auth_mode(config.auth_mode):
        problems.append("Authentication mode must be 'userpass' or 'cert'.")
    if not validate_access_mode(config.access_mode):
        problems.append("Access mode must be 'free' or 'locked'.")
    if config.auth_mode == "cert" and config.verify_client_cert != "require":
        problems.append("Certificate-only mode requires verify-client-cert=require.")
    if config.tls_min not in {"1.2", "1.3"} or config.tls_max not in {"1.2", "1.3"}:
        problems.append("TLS versions must be 1.2 or 1.3.")
    elif config.tls_max < config.tls_min:
        problems.append("tls_max must be greater than or equal to tls_min.")
    if config.auth_digest.upper() not in {"SHA256", "SHA384", "SHA512"}:
        problems.append("auth_digest must be SHA256, SHA384 or SHA512.")
    if not (576 <= config.tun_mtu <= 1500):
        problems.append("tun_mtu must be between 576 and 1500.")
    if not (500 <= config.mssfix <= 1460):
        problems.append("mssfix must be between 500 and 1460.")
    if config.sndbuf < 0 or config.rcvbuf < 0:
        problems.append("Socket buffers cannot be negative.")
    if config.verify_client_cert not in {"require", "optional", "none"}:
        problems.append("verify_client_cert must be require, optional or none.")
    if config.users and not config.users[0].name:
        problems.append("At least one client profile is required.")
    seen_names: set[str] = set()
    seen_users: set[str] = set()
    seen_certs: set[str] = set()
    for user in config.users:
        if not validate_profile_name(user.name):
            problems.append(f"Invalid profile name: {user.name!r}.")
        safe_name = sanitize_profile_name(user.name)
        if safe_name.lower() in seen_names:
            problems.append(f"Duplicate profile name: {user.name!r}.")
        seen_names.add(safe_name.lower())
        if not validate_username(user.username):
            problems.append(f"Invalid username for {user.name!r}: {user.username!r}.")
        if user.username in seen_users:
            problems.append(f"Duplicate username: {user.username!r}.")
        seen_users.add(user.username)
        cert_name = user.safe_cert_name
        if cert_name in seen_certs:
            problems.append(
                f"Two users would share the same certificate name: {cert_name!r}. "
                "Give each profile a different username."
            )
        seen_certs.add(cert_name)
        if config.auth_mode == "userpass":
            ok, reason = validate_password(user.password)
            if not ok:
                problems.append(f"{user.name}: {reason}")
    if config.enable_vless:
        if not validate_hostname(config.domain1):
            problems.append("VLESS requires a valid domain1.")
        if not validate_hostname(config.domain2):
            problems.append("VLESS requires a valid domain2.")
        if not validate_hostname(config.reality_domain):
            problems.append("VLESS requires a valid reality_domain.")
        if config.vpn_proto != "tcp":
            problems.append("VLESS multiplexing requires TCP (it shares the TCP listener).")
        if not config.use_haproxy:
            problems.append("VLESS multiplexing requires HAProxy (it needs SNI routing).")
    return problems


# Backwards-compatible aliases for v1 imports.
validate_fqdn = validate_hostname
validate_client_name = validate_profile_name
