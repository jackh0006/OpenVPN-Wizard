"""
User management: add, revoke, rename, change password, rotate keys, export.

All operations are idempotent where possible and always regenerate a valid,
validated .ovpn profile.  Certificate operations use the system Easy-RSA
against the same PKI directory as the installer.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from core.config import (
    ClientSpec,
    InstallConfig,
    sanitize_cert_name,
    sanitize_profile_name,
    validate_password,
    validate_profile_name,
    validate_username,
)
from core.logger import get_logger
from core.secrets import generate_password, hash_password
from management import db as user_db
from management.profile_gen import ProfileGenerator
from steps.openvpn import OpenVPNStep


class UserManager:
    def __init__(self, config: InstallConfig):
        self.config = config
        self.logger = get_logger()
        self.db_path = Path(config.user_db)
        self.pki_dir = Path(config.pki_dir)
        self.profiles_dir = Path(config.profiles_dir)
        user_db.init_db(self.db_path)

    # ── Read ─────────────────────────────────────────────────────────────

    def list_users(self) -> List[Dict]:
        if not self.db_path.exists():
            return []
        conn = user_db.connect(self.db_path)
        try:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM users ORDER BY created_at DESC, id DESC"
            )]
        finally:
            conn.close()

    def get_user(self, name: str) -> Optional[Dict]:
        for user in self.list_users():
            if user["name"] == name:
                return user
        return None

    def active_users(self) -> List[Dict]:
        return [u for u in self.list_users() if not u.get("revoked")]

    # ── Create ───────────────────────────────────────────────────────────

    def add_user(self, name: str, username: str,
                 password: Optional[str] = None) -> Path:
        name = sanitize_profile_name(name)
        username = (username or name).strip().lower()
        if not validate_profile_name(name):
            raise ValueError("Invalid profile name. Use letters, digits, dot, dash or underscore.")
        if not validate_username(username):
            raise ValueError("Invalid username. Use lowercase letters, digits, '_' or '-' (max 32).")
        if self.get_user(name):
            raise ValueError(f"A profile named {name!r} already exists.")

        for existing in self.list_users():
            if existing["username"] == username:
                raise ValueError(f"Username {username!r} is already used by {existing['name']!r}.")
            if (existing.get("cert_name") or existing["username"]) == sanitize_cert_name(username):
                raise ValueError(
                    f"Certificate name {sanitize_cert_name(username)!r} is already "
                    f"used by {existing['name']!r}. Choose a different username."
                )

        if self.config.auth_mode == "userpass":
            password = password or generate_password()
            ok, reason = validate_password(password)
            if not ok:
                raise ValueError(reason)
        else:
            password = ""

        cert_name = sanitize_cert_name(username)
        self._issue_certificate(cert_name)
        self._create_or_update_pam(username, password)

        spec = ClientSpec(name=name, username=username, password=password,
                          cert_name=cert_name)
        profile = ProfileGenerator(self.config).save(spec, self.profiles_dir)

        conn = user_db.connect(self.db_path)
        try:
            conn.execute("""
                INSERT INTO users
                    (name, username, password_hash, cert_name, cert_serial,
                     auth_mode, access_mode, profile_path, revoked)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                name, username,
                hash_password(password) if password else "",
                cert_name, self._cert_serial(cert_name),
                self.config.auth_mode, self.config.access_mode, str(profile),
            ))
            conn.commit()
        finally:
            conn.close()

        self.logger.info("Added user %s (%s)", name, username)
        return profile

    # ── Modify ───────────────────────────────────────────────────────────

    def change_password(self, name: str, new_password: str) -> None:
        user = self._require(name)
        if self.config.auth_mode != "userpass":
            raise ValueError("This installation uses certificate-only authentication.")
        ok, reason = validate_password(new_password)
        if not ok:
            raise ValueError(reason)
        self._create_or_update_pam(user["username"], new_password)
        conn = user_db.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE users SET password_hash=? WHERE name=?",
                (hash_password(new_password), name),
            )
            conn.commit()
        finally:
            conn.close()
        self.logger.info("Changed password for %s", name)

    def rename_user(self, old_name: str, new_name: str) -> Path:
        user = self._require(old_name)
        new_name = sanitize_profile_name(new_name)
        if not validate_profile_name(new_name):
            raise ValueError("Invalid new profile name.")
        if new_name == old_name:
            return Path(user.get("profile_path") or "")
        if self.get_user(new_name):
            raise ValueError(f"A profile named {new_name!r} already exists.")

        spec = ClientSpec(
            name=new_name,
            username=user["username"],
            password="",
            cert_name=user.get("cert_name") or user["username"],
        )
        new_path = ProfileGenerator(self.config).save(spec, self.profiles_dir)
        old_path = self.profiles_dir / f"{sanitize_profile_name(old_name)}.ovpn"
        old_path.unlink(missing_ok=True)

        conn = user_db.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE users SET name=?, profile_path=? WHERE name=?",
                (new_name, str(new_path), old_name),
            )
            conn.commit()
        finally:
            conn.close()
        self.logger.info("Renamed %s -> %s", old_name, new_name)
        return new_path

    def rotate_keys(self, name: str) -> Path:
        """Issue a new certificate/key pair and revoke the old one."""
        user = self._require(name)
        cert_name = user.get("cert_name") or user["username"]
        self._revoke_certificate(cert_name)
        # Easy-RSA cannot reuse a revoked CN; issue a fresh unique CN.
        new_cert = sanitize_cert_name(f"{cert_name}-{secrets.token_hex(4)}")
        self._issue_certificate(new_cert)
        spec = ClientSpec(
            name=user["name"], username=user["username"],
            password="", cert_name=new_cert,
        )
        profile = ProfileGenerator(self.config).save(spec, self.profiles_dir)
        conn = user_db.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE users SET cert_name=?, cert_serial=?, profile_path=? WHERE name=?",
                (new_cert, self._cert_serial(new_cert), str(profile), name),
            )
            conn.commit()
        finally:
            conn.close()
        self.logger.info("Rotated keys for %s", name)
        return profile

    # ── Revoke / delete ──────────────────────────────────────────────────

    def remove_user(self, name: str) -> None:
        user = self._require(name)
        cert_name = user.get("cert_name") or user["username"]
        self._revoke_certificate(cert_name)

        # Remove the PAM account only if no other active profile shares it.
        others = [
            u for u in self.active_users()
            if u["username"] == user["username"] and u["name"] != name
        ]
        if not others and self.config.auth_mode == "userpass":
            subprocess.run(["userdel", "-f", user["username"]],
                           capture_output=True, text=True, check=False)

        conn = user_db.connect(self.db_path)
        try:
            conn.execute("UPDATE users SET revoked=1 WHERE name=?", (name,))
            conn.commit()
        finally:
            conn.close()

        (self.profiles_dir / f"{sanitize_profile_name(name)}.ovpn").unlink(missing_ok=True)
        self.logger.info("Revoked user %s", name)

    def export_profile(self, name: str) -> Path:
        user = self._require(name)
        spec = ClientSpec(
            name=user["name"], username=user["username"], password="",
            cert_name=user.get("cert_name") or user["username"],
        )
        path = ProfileGenerator(self.config).save(spec, self.profiles_dir)
        conn = user_db.connect(self.db_path)
        try:
            conn.execute("UPDATE users SET profile_path=? WHERE name=?", (str(path), name))
            conn.commit()
        finally:
            conn.close()
        return path

    def download_command(self, name: str) -> str:
        host = self.config.remote_host
        return (
            f"scp root@{host}:{self.profiles_dir}/"
            f"{sanitize_profile_name(name)}.ovpn ~/Downloads/"
        )

    # ── Internals ────────────────────────────────────────────────────────

    def _require(self, name: str) -> Dict:
        user = self.get_user(name)
        if not user:
            raise ValueError(f"User {name!r} not found.")
        return user

    def _easyrsa(self, args: list) -> subprocess.CompletedProcess:
        binary = "/usr/share/easy-rsa/easyrsa"
        if not Path(binary).exists():
            found = shutil.which("easyrsa")
            if not found:
                raise RuntimeError("easy-rsa is not installed (apt-get install -y easy-rsa)")
            binary = found
        env = dict(os.environ)
        env.update({
            "EASYRSA_BATCH": "1",
            "EASYRSA_PKI": str(self.pki_dir),
        })
        if (self.pki_dir / "vars").exists():
            env["EASYRSA_VARS_FILE"] = str(self.pki_dir / "vars")
        result = subprocess.run([binary, *args], capture_output=True, text=True,
                                env=env, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"Easy-RSA failed: {' '.join(args)}\n"
                f"{(result.stderr or result.stdout)[-1500:]}"
            )
        return result

    def _sanitize_vars(self) -> None:
        vars_file = self.pki_dir / "vars"
        if not vars_file.exists():
            return
        lines = [
            line for line in vars_file.read_text().splitlines()
            if not line.strip().startswith("set_var EASYRSA_REQ_CN")
        ]
        vars_file.write_text("\n".join(lines) + "\n")

    def _issue_certificate(self, cert_name: str) -> None:
        self._sanitize_vars()
        crt = self.pki_dir / "issued" / f"{cert_name}.crt"
        key = self.pki_dir / "private" / f"{cert_name}.key"
        if crt.exists() and key.exists():
            return
        if crt.exists() != key.exists():
            raise RuntimeError(
                f"Incomplete certificate material for {cert_name!r}: "
                f"{'certificate exists' if crt.exists() else 'key exists'} "
                "without its pair. Move the orphaned file aside and retry."
            )
        self._easyrsa(["--batch", "build-client-full", cert_name, "nopass"])

    def _revoke_certificate(self, cert_name: str) -> None:
        crt = self.pki_dir / "issued" / f"{cert_name}.crt"
        if crt.exists():
            result = subprocess.run(
                ["openssl", "x509", "-in", str(crt), "-noout", "-serial"],
                capture_output=True, text=True, check=False,
            )
            if result.returncode == 0:
                self._easyrsa(["--batch", "revoke", cert_name])
        self._easyrsa(["gen-crl"])
        shutil.copy2(self.pki_dir / "crl.pem", Path(self.config.openvpn_dir) / "crl.pem")
        os.chmod(Path(self.config.openvpn_dir) / "crl.pem", 0o644)
        self._reload_openvpn()

    def _create_or_update_pam(self, username: str, password: str) -> None:
        if self.config.auth_mode != "userpass" or not password:
            return
        exists = subprocess.run(["id", username], capture_output=True, text=True,
                                check=False).returncode == 0
        if not exists:
            result = subprocess.run(
                ["useradd", "--no-create-home", "--shell", "/usr/sbin/nologin", username],
                capture_output=True, text=True, check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Could not create user {username}: {result.stderr.strip()}")
        result = subprocess.run(
            ["chpasswd"], input=f"{username}:{password}\n", text=True,
            capture_output=True, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Could not set password for {username}: {result.stderr.strip()}")

    def _cert_serial(self, cert_name: str) -> str:
        cert = self.pki_dir / "issued" / f"{cert_name}.crt"
        result = subprocess.run(
            ["openssl", "x509", "-in", str(cert), "-noout", "-serial"],
            capture_output=True, text=True, check=False,
        )
        return result.stdout.strip().replace("serial=", "") if result.returncode == 0 else ""

    def _reload_openvpn(self) -> None:
        service = OpenVPNStep.openvpn_service_name()
        subprocess.run(["systemctl", "reload-or-restart", service],
                       capture_output=True, text=True, check=False)
