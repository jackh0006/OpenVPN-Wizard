"""Password generation and hashing helpers.

Python 3.13 removed the stdlib ``crypt`` module, so v1's password hashing
crashes on modern systems.  This module uses PBKDF2-HMAC-SHA256 from
``hashlib`` and stores a self-describing string.  The PAM password itself is
set with ``chpasswd``; the hash is only for the installer's own database.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import string

PBKDF2_ITERATIONS = 600_000
_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{},.?"


def generate_password(length: int = 24) -> str:
    """Generate a strong password that always satisfies validate_password()."""
    length = max(16, min(length, 128))
    while True:
        # Guarantee each required class, then fill with random characters.
        chars = [
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.ascii_uppercase),
            secrets.choice(string.digits),
            secrets.choice("!@#$%^&*()-_=+[]{},.?"),
        ]
        chars.extend(secrets.choice(_ALPHABET) for _ in range(length - len(chars)))
        secrets.SystemRandom().shuffle(chars)
        password = "".join(chars)
        if "\n" not in password and "\r" not in password:
            return password


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS,
                  salt: bytes | None = None) -> str:
    """Return ``pbkdf2_sha256$iterations$salt_b64$hash_b64``."""
    if not password:
        return ""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time verification of a stored hash."""
    if not password or not encoded:
        return False
    try:
        scheme, iterations, salt_b64, hash_b64 = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def generate_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)
