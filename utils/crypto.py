"""Compatibility crypto helpers.

Password hashing now lives in :mod:`core.secrets` because Python 3.13 removed
the stdlib ``crypt`` module.  The X25519 helpers are still used by the
optional VLESS/Reality step.
"""

from __future__ import annotations

import hashlib
import secrets

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from core.secrets import hash_password


def generate_password_hash(password: str, method: str = "pbkdf2_sha256") -> str:
    return hash_password(password)


def generate_x25519_key() -> tuple[str, str]:
    private_key = X25519PrivateKey.generate()
    public_key = private_key.public_key()
    priv_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv_bytes.hex(), pub_bytes.hex()


def generate_short_id(length: int = 8) -> str:
    return secrets.token_hex(max(1, length // 2))


def generate_uuid() -> str:
    return secrets.token_hex(16)


def hash_data(data: str, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    digest.update(data.encode())
    return digest.hexdigest()
