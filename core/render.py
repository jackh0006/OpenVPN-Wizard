"""Template rendering and PEM handling shared by install and management."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from core.config import InstallConfig
from core.exceptions import CryptoError
from core.logger import get_logger

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        # Plain-text OpenVPN/HAProxy config, not HTML. Autoescaping would
        # corrupt PEM blocks and config syntax.  # nosec B701
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_template(name: str, **context) -> str:
    template = _env().get_template(name)
    return template.render(**context)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def extract_pem(text: str, label: str) -> str:
    """Return exactly one PEM block, dropping OpenSSL's textual dump.

    Older installers embedded the output of ``openssl x509 -text`` before the
    actual certificate.  That is tolerated by OpenVPN but is not standard and
    bloats profiles.  This extracts only the PEM block.
    """
    pattern = re.compile(
        rf"-----BEGIN {re.escape(label)}-----.*?-----END {re.escape(label)}-----",
        re.DOTALL,
    )
    match = pattern.search(text or "")
    if not match:
        raise CryptoError(
            f"Missing PEM block: {label}",
            operation="extract_pem",
            fix_hint=(
                "The certificate/key file is incomplete or not PEM encoded. "
                "Regenerate it with Easy-RSA, or restore it from backup."
            ),
        )
    return match.group(0).strip() + "\n"


def read_pem(path: str | Path, label: str) -> str:
    try:
        return extract_pem(Path(path).read_text(encoding="utf-8"), label)
    except FileNotFoundError as exc:
        raise CryptoError(
            f"Required file not found: {path}",
            operation="read_pem",
            fix_hint="Re-run the PKI step or restore the file from backup.",
        ) from exc


def read_private_key(path: str | Path) -> str:
    """Read a key regardless of PKCS#8 / EC / RSA PEM label."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CryptoError(
            f"Required key not found: {path}",
            operation="read_private_key",
            fix_hint="Re-run the PKI step or restore the key from backup.",
        ) from exc
    for label in ("PRIVATE KEY", "EC PRIVATE KEY", "RSA PRIVATE KEY"):
        try:
            return extract_pem(text, label)
        except CryptoError:
            continue
    raise CryptoError(
        f"No PEM private key found in {path}",
        operation="read_private_key",
        fix_hint="Regenerate the certificate/key pair with Easy-RSA.",
    )


def render_server_conf(config: InstallConfig, pam_plugin: Optional[str] = None) -> str:
    return render_template(
        "openvpn_server.conf.j2",
        config=config,
        pam_plugin=pam_plugin or "",
        generated_at=utc_now(),
    )


def render_haproxy_block(config: InstallConfig) -> str:
    return render_template(
        "haproxy_block.cfg.j2",
        config=config,
        generated_at=utc_now(),
    )


def validate_rendered_server(conf: str, config: InstallConfig, log=None) -> list[str]:
    """Static validation used before touching the live service."""
    log = log or get_logger()
    problems: list[str] = []
    required = [
        "dev tun",
        "topology subnet",
        "tls-crypt",
        "remote-cert-tls client",
        f"verify-client-cert {config.verify_client_cert}",
        "server ",
    ]
    for needle in required:
        if needle not in conf:
            problems.append(f"missing directive: {needle}")
    if config.auth_mode == "userpass" and "openvpn-plugin-auth-pam.so" not in conf:
        problems.append("missing PAM plugin for user/password authentication")
    if config.auth_mode == "cert" and "openvpn-plugin-auth-pam.so" in conf:
        problems.append("PAM plugin must not be enabled in certificate-only mode")
    if "comp-lzo" in conf or "\ncompress " in conf:
        problems.append("compression must not be enabled")
    for setting in ("tun-mtu", "mssfix", "sndbuf", "rcvbuf", "auth",
                    "cipher", "data-ciphers", "tls-version-min"):
        if f"\n{setting} " not in "\n" + conf:
            problems.append(f"missing tuning directive: {setting}")
    if config.free_tunnel and 'push "redirect-gateway' not in conf:
        problems.append("free tunnel is missing redirect-gateway")
    if not config.free_tunnel and 'push "redirect-gateway' in conf:
        problems.append("locked mode must not push redirect-gateway")

    for line in conf.splitlines():
        if len(line) > 256:
            problems.append("option line exceeds OpenVPN's 256-character limit")
            break

    for directive in ("ca", "cert", "key", "tls-crypt", "crl-verify"):
        match = re.search(rf"^{directive}\s+(\S+)$", conf, re.MULTILINE)
        if match and not Path(match.group(1)).exists():
            problems.append(f"{directive} file does not exist: {match.group(1)}")
    dh_match = re.search(r"^dh\s+(\S+)$", conf, re.MULTILINE)
    if dh_match and dh_match.group(1) != "none" and not Path(dh_match.group(1)).exists():
        problems.append(f"dh file does not exist: {dh_match.group(1)}")

    for problem in problems:
        log.error("Server config validation: %s", problem)
    return problems


def validate_client_profile(content: str) -> list[str]:
    problems: list[str] = []
    for block in ("<ca>", "</ca>", "<cert>", "</cert>", "<key>", "</key>",
                  "<tls-crypt>", "</tls-crypt>"):
        if block not in content:
            problems.append(f"missing block: {block}")
    if not re.search(r"^remote\s+\S+\s+\d+$", content, re.MULTILINE):
        problems.append("missing or malformed remote line")
    if "-----BEGIN CERTIFICATE-----" not in content:
        problems.append("missing certificate PEM")
    if "-----BEGIN" not in content:
        problems.append("missing key PEM")
    if re.search(r"^key-direction\b", content, re.MULTILINE):
        problems.append("key-direction is invalid with tls-crypt")
    if re.search(r"^comp-lzo\b|^compress\b", content, re.MULTILINE):
        problems.append("compression must not be enabled")
    if content.count("<tls-crypt>") != 1:
        problems.append("tls-crypt block must appear exactly once")
    for line in content.splitlines():
        # Inline PEM lines are long by nature; only check option lines.
        if line.startswith("-----") or not line or line.startswith("#"):
            continue
        if len(line) > 256:
            problems.append("option line exceeds OpenVPN's 256-character limit")
            break
    return problems
