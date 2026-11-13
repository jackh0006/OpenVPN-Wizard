"""Single source of truth for generating standard OpenVPN client profiles."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from core.config import ClientSpec, InstallConfig, sanitize_profile_name
from core.exceptions import CryptoError
from core.logger import get_logger
from core.render import (
    read_pem,
    read_private_key,
    render_template,
    utc_now,
    validate_client_profile,
)


class ProfileGenerator:
    """Render, validate and save .ovpn files for individual users."""

    def __init__(self, config: InstallConfig, pki_dir: Optional[Path] = None):
        self.config = config
        self.pki_dir = Path(pki_dir or config.pki_dir)
        self.logger = get_logger()

    # ── Public API ───────────────────────────────────────────────────────

    def generate(self, user: ClientSpec) -> str:
        cert_name = user.safe_cert_name
        ca_crt = read_pem(self.pki_dir / "ca.crt", "CERTIFICATE")
        client_crt = read_pem(self.pki_dir / "issued" / f"{cert_name}.crt", "CERTIFICATE")
        client_key = read_private_key(self.pki_dir / "private" / f"{cert_name}.key")
        ta_key = read_pem(self.pki_dir / "ta.key", "OpenVPN Static key V1")

        self._assert_key_matches_cert(client_crt, client_key, user)

        content = render_template(
            "client.ovpn.j2",
            config=self.config,
            profile_name=sanitize_profile_name(user.name),
            generated_at=utc_now(),
            ca_crt=ca_crt,
            client_crt=client_crt,
            client_key=client_key,
            ta_key=ta_key,
        )

        problems = validate_client_profile(content)
        if problems:
            raise CryptoError(
                "Generated client profile is invalid: " + "; ".join(problems),
                operation="generate_profile",
                fix_hint="This is a bug in the installer. Run 'vpn-installer doctor'.",
            )
        return content

    def save(self, user: ClientSpec, directory: Optional[Path] = None) -> Path:
        directory = Path(directory or self.config.profiles_dir)
        directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass

        content = self.generate(user)
        path = directory / f"{sanitize_profile_name(user.name)}.ovpn"
        tmp = path.with_suffix(".ovpn.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
        self.logger.info("Saved client profile: %s", path)
        return path

    def save_all(self, directory: Optional[Path] = None) -> list[Path]:
        return [self.save(user, directory) for user in self.config.users]

    # ── Validation ───────────────────────────────────────────────────────

    def _assert_key_matches_cert(self, cert_pem: str, key_pem: str,
                                 user: ClientSpec) -> None:
        try:
            cert = x509.load_pem_x509_certificate(cert_pem.encode())
            key = serialization.load_pem_private_key(key_pem.encode(), password=None)
            cert_pub = cert.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            key_pub = key.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        except Exception as exc:
            raise CryptoError(
                f"Could not parse certificate/key for {user.name}: {exc}",
                operation="verify_key_pair",
                fix_hint="Regenerate this user's certificate with Easy-RSA.",
            ) from exc
        if cert_pub != key_pub:
            raise CryptoError(
                f"Certificate and private key do not match for {user.name}",
                operation="verify_key_pair",
                fix_hint=(
                    "This profile would never connect. Regenerate the user's "
                    "certificate and key together (manage -> export profile)."
                ),
            )
