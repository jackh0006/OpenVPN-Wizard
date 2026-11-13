"""
Step: record users in the local SQLite database (hashes only, never keys).

The database is used by the management UI.  It intentionally does NOT store
private keys or plaintext passwords: keys live only in the PKI directory and
profiles, and passwords are stored as PBKDF2 hashes.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Callable

from core.config import InstallConfig
from core.secrets import hash_password
from steps.base import BaseStep


class UserDBStep(BaseStep):
    @property
    def name(self) -> str:
        return "user_db"

    @property
    def display_name(self) -> str:
        return "Record users in the database"

    @property
    def description(self) -> str:
        return "SQLite metadata for management (password hashes only)"

    async def is_already_done(self, config: InstallConfig) -> bool:
        return False

    async def execute(self, config: InstallConfig,
                      output_callback: Callable[[str], None] = None) -> bool:
        def log(msg: str):
            if output_callback:
                output_callback(msg)
            self.logger.info(msg)

        db_path = Path(config.user_db)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(db_path.parent, 0o750)
        except OSError:
            pass

        log("Initialising user database...")
        self._init_db(db_path)

        for user in config.users:
            serial = self._cert_serial(config, user.safe_cert_name)
            self._upsert(db_path, config, user, serial)
            log(f"  ✓ {user.name} ({user.username}) recorded")

        try:
            os.chmod(db_path, 0o600)
        except OSError:
            pass
        log("User records saved")
        return True

    def _init_db(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL DEFAULT '',
                    cert_name TEXT NOT NULL DEFAULT '',
                    cert_serial TEXT NOT NULL DEFAULT '',
                    auth_mode TEXT NOT NULL DEFAULT 'userpass',
                    access_mode TEXT NOT NULL DEFAULT 'free',
                    profile_path TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    revoked BOOLEAN DEFAULT 0
                )
            """)
            # Add columns introduced in v2 to an existing v1 database.
            existing = {row[1] for row in cur.execute("PRAGMA table_info(users)")}
            for column, ddl in (
                ("cert_name", "TEXT NOT NULL DEFAULT ''"),
                ("profile_path", "TEXT NOT NULL DEFAULT ''"),
                ("auth_mode", "TEXT NOT NULL DEFAULT 'userpass'"),
                ("access_mode", "TEXT NOT NULL DEFAULT 'free'"),
            ):
                if column not in existing:
                    cur.execute(f"ALTER TABLE users ADD COLUMN {column} {ddl}")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_name ON users(name)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
            conn.commit()
        finally:
            conn.close()

    def _cert_serial(self, config: InstallConfig, cert_name: str) -> str:
        cert = Path(config.pki_dir) / "issued" / f"{cert_name}.crt"
        result = self._run_cmd(
            ["openssl", "x509", "-in", str(cert), "-noout", "-serial"], check=False
        )
        return result.stdout.strip().replace("serial=", "") if result.returncode == 0 else ""

    def _upsert(self, db_path: Path, config: InstallConfig, user, serial: str) -> None:
        password_hash = hash_password(user.password) if config.auth_mode == "userpass" else ""
        profile = str(Path(config.profiles_dir) / f"{user.name}.ovpn")
        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO users
                    (name, username, password_hash, cert_name, cert_serial,
                     auth_mode, access_mode, profile_path, revoked)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(name) DO UPDATE SET
                    username=excluded.username,
                    password_hash=excluded.password_hash,
                    cert_name=excluded.cert_name,
                    cert_serial=excluded.cert_serial,
                    auth_mode=excluded.auth_mode,
                    access_mode=excluded.access_mode,
                    profile_path=excluded.profile_path,
                    revoked=0
            """, (
                user.name, user.username, password_hash, user.safe_cert_name,
                serial, config.auth_mode, config.access_mode, profile,
            ))
            conn.commit()
        finally:
            conn.close()

    async def rollback(self, config: InstallConfig, rollback_data: dict) -> bool:
        db_path = Path(config.user_db)
        if not db_path.exists():
            return True
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "UPDATE users SET revoked=1 WHERE name IN (%s)"
                % ",".join("?" for _ in config.users),
                [u.name for u in config.users],
            )
            conn.commit()
        finally:
            conn.close()
        return True
