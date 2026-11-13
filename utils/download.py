"""
Secure one-shot .ovpn delivery for phones and other devices.

The default delivery method is SSH/SCP, which adds no attack surface.  For
devices without an SSH client, ``vpn-installer download NAME --serve`` starts
a short-lived HTTPS server that:

* uses a fresh self-signed certificate generated in memory;
* requires a 256-bit random token in the URL;
* serves exactly one file and shuts down after the first download or TTL;
* never enables directory listing or caching.

Only one profile is exposed, never the profile directory.
"""

from __future__ import annotations

import hmac
import http.server
import ipaddress
import os
import secrets
import shutil
import socket
import ssl
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _make_self_signed(host: str, directory: Path) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, host or "openvpn-wizard"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OpenVPN Wizard one-time download"),
    ])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.ip_address(host))
                if _is_ip(host)
                else x509.DNSName(host or "openvpn-wizard")
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = directory / "cert.pem"
    key_path = directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    os.chmod(cert_path, 0o600)
    os.chmod(key_path, 0o600)
    return cert_path, key_path


def _lan_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("9.9.9.9", 53))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "0.0.0.0"


def serve_once(
    profile_path: Path,
    *,
    port: int = 8443,
    ttl: int = 300,
    bind: str = "0.0.0.0",
    public_host: Optional[str] = None,
) -> None:
    """Block while serving exactly one profile download over HTTPS."""
    profile_path = Path(profile_path)
    if not profile_path.is_file():
        raise FileNotFoundError(profile_path)

    token = secrets.token_urlsafe(32)
    download_name = profile_path.name
    state = {"served": False}
    lock = threading.Lock()

    cert_dir = Path(tempfile.mkdtemp(prefix="ovpn-download-"))
    try:
        cert_path, key_path = _make_self_signed(public_host or _lan_ip(), cert_dir)

        class Handler(http.server.BaseHTTPRequestHandler):
            server_version = "OpenVPNWizard/2.0"

            def log_message(self, fmt, *args):  # noqa: A003 - stdlib signature
                return

            def _deny(self, code: int = 404):
                self.send_error(code)

            def do_GET(self):  # noqa: N802 - stdlib API
                expected = f"/t/{token}/{download_name}"
                provided = self.path.split("?", 1)[0]
                if not hmac.compare_digest(provided.encode(), expected.encode()):
                    self._deny()
                    return
                with lock:
                    if state["served"]:
                        self._deny(410)
                        return
                    state["served"] = True
                data = profile_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/x-openvpn-profile")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{download_name}"')
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)
                threading.Thread(target=self.server.shutdown, daemon=True).start()

            def do_HEAD(self):  # noqa: N802
                self._deny()

        server = http.server.ThreadingHTTPServer((bind, port), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(cert_path), str(key_path))
        server.socket = context.wrap_socket(server.socket, server_side=True)

        def timeout():
            deadline = time.time() + ttl
            while time.time() < deadline:
                if state["served"]:
                    return
                time.sleep(1)
            server.shutdown()

        threading.Thread(target=timeout, daemon=True).start()

        host = public_host or _lan_ip()
        print("")
        print("  One-time HTTPS download (valid for %d seconds):" % ttl)
        print(f"  https://{host}:{port}/t/{token}/{download_name}")
        print("")
        print("  The URL works once. The server exits after the download or TTL.")
        print("  The certificate is self-signed; your device will ask you to confirm.")
        print("")
        server.serve_forever(poll_interval=0.5)
    finally:
        shutil.rmtree(cert_dir, ignore_errors=True)
