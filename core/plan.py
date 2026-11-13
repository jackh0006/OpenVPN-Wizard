"""
Dry-run planner: render every file into a directory without touching the
system.  This is what ``vpn-installer plan`` uses and what CI tests exercise.

It creates a throwaway PKI with the same algorithms as the real installer so
the rendered server config and client profiles can be validated for real
(certificate/key matching, required blocks, paths, etc.).
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from core.config import InstallConfig
from core.render import render_haproxy_block, render_server_conf, validate_rendered_server
from management.profile_gen import ProfileGenerator


def _key():
    return ec.generate_private_key(ec.SECP384R1())


def _name(cn: str) -> x509.Name:
    return x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OpenVPN Wizard Plan"),
    ])


def _write_key(path: Path, key) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    os.chmod(path, 0o600)


def _write_cert(path: Path, cert) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    os.chmod(path, 0o644)


def _issue(ca_cert, ca_key, cn: str, *, client: bool):
    key = _key()
    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(cn))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    )
    if client:
        builder = builder.add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False
        )
    else:
        builder = builder.add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
    return key, builder.sign(ca_key, hashes.SHA384())


def _ta_key() -> str:
    """OpenVPN static key: 2048 random bits, formatted like openvpn --genkey."""
    lines = ["#", "# 2048 bit OpenVPN static key", "#",
             "-----BEGIN OpenVPN Static key V1-----"]
    lines += [secrets.token_hex(16) for _ in range(16)]
    lines += ["-----END OpenVPN Static key V1-----", ""]
    return "\n".join(lines)


def build_plan(config: InstallConfig, output_dir: Path) -> dict:
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pki = output_dir / "pki"
    openvpn = output_dir
    clients = output_dir / "clients"
    for directory in (pki, pki / "issued", pki / "private", clients):
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700 if directory.name == "private" else 0o750)

    ca_key = _key()
    now = datetime.now(timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(_name("OpenVPN-Wizard-CA"))
        .issuer_name(_name("OpenVPN-Wizard-CA"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False,
                key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=True, crl_sign=True,
                encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA384())
    )
    _write_key(pki / "private" / "ca.key", ca_key)
    _write_cert(pki / "ca.crt", ca_cert)

    server_key, server_cert = _issue(ca_cert, ca_key, "server", client=False)
    _write_key(pki / "private" / "server.key", server_key)
    _write_cert(pki / "issued" / "server.crt", server_cert)

    for user in config.users:
        key, cert = _issue(ca_cert, ca_key, user.safe_cert_name, client=True)
        _write_key(pki / "private" / f"{user.safe_cert_name}.key", key)
        _write_cert(pki / "issued" / f"{user.safe_cert_name}.crt", cert)

    (pki / "ta.key").write_text(_ta_key())
    os.chmod(pki / "ta.key", 0o600)

    crl = (
        x509.CertificateRevocationListBuilder()
        .issuer_name(ca_cert.subject)
        .last_update(now - timedelta(minutes=5))
        .next_update(now + timedelta(days=180))
        .sign(ca_key, hashes.SHA384())
    )
    (pki / "crl.pem").write_bytes(crl.public_bytes(serialization.Encoding.PEM))
    os.chmod(pki / "crl.pem", 0o644)

    # Point the plan config at the dry-run directory. The throwaway server
    # certificate is always CN=server, so client pinning must match it.
    config.server_cert_cn = "server"
    config.pki_dir = str(pki)
    config.openvpn_dir = str(openvpn)
    config.profiles_dir = str(clients)
    config.credentials_file = str(output_dir / "credentials.txt")
    config.dh = "none"

    mapping = {
        "ca.crt": pki / "ca.crt",
        "server.crt": pki / "issued" / "server.crt",
        "server.key": pki / "private" / "server.key",
        "ta.key": pki / "ta.key",
        "crl.pem": pki / "crl.pem",
    }
    for name, src in mapping.items():
        if src.exists():
            (openvpn / name).write_bytes(src.read_bytes())
            os.chmod(openvpn / name,
                     0o600 if name.endswith(".key") or name == "ta.key" else 0o644)

    server_conf = render_server_conf(config, pam_plugin="/usr/lib/x86_64-linux-gnu/openvpn/plugins/openvpn-plugin-auth-pam.so")
    (output_dir / "server.conf").write_text(server_conf)
    os.chmod(output_dir / "server.conf", 0o600)
    problems = validate_rendered_server(server_conf, config)

    profiles = ProfileGenerator(config).save_all(clients)
    haproxy_block = ""
    haproxy_strategy = {}
    if config.use_haproxy:
        try:
            from utils.haproxy import HAProxyManager
            haproxy_strategy = HAProxyManager(config).describe()
        except Exception as exc:
            haproxy_strategy = {"action": "unknown", "reason": str(exc)}
        (output_dir / "haproxy-strategy.txt").write_text(
            "\n".join(f"{key}: {value}" for key, value in haproxy_strategy.items()) + "\n"
        )
        if haproxy_strategy.get("action") in {"append", "insert"}:
            haproxy_block = render_haproxy_block(config)
            (output_dir / "haproxy-block.cfg").write_text(haproxy_block)
            os.chmod(output_dir / "haproxy-block.cfg", 0o644)
        else:
            (output_dir / "haproxy-block.cfg").write_text(
                "# No HAProxy change is required.\n"
                f"# Action: {haproxy_strategy.get('action')}\n"
                f"# Reason: {haproxy_strategy.get('reason')}\n"
            )

    readme = _readme(config, output_dir)
    (output_dir / "README.txt").write_text(readme)

    return {
        "output_dir": str(output_dir),
        "server_conf": str(output_dir / "server.conf"),
        "profiles": [str(p) for p in profiles],
        "haproxy_block": str(output_dir / "haproxy-block.cfg") if haproxy_block else "",
        "haproxy_strategy": haproxy_strategy,
        "problems": problems,
    }


def _readme(config: InstallConfig, output_dir: Path) -> str:
    user = config.users[0].name if config.users else "profile"
    return f"""OpenVPN Wizard v2 - dry-run plan
================================

Generated: {datetime.now(timezone.utc).isoformat()}
Endpoint:  {config.remote_host}:{config.public_port}/{config.vpn_proto}
Auth:      {config.auth_mode}
Access:    {config.access_mode}

This directory contains exactly what the installer would write, but nothing
on the system was changed. Files:

  server.conf                 OpenVPN server configuration
  clients/*.ovpn              one profile per user
  haproxy-block.cfg           append-only HAProxy block (not applied)
  pki/                        throwaway certificates used for this plan only

To inspect a client profile:

  openvpn --config {output_dir}/clients/{user}.ovpn --show-ciphers

If the plan looks right, run the real installer as root:

  sudo vpn-installer install

Delete this directory when finished; it contains throwaway private keys.
"""
