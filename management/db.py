"""Shared SQLite schema helpers for the management database."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA = """
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
);
CREATE INDEX IF NOT EXISTS idx_users_name ON users(name);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o750)
    except OSError:
        pass
    conn = connect(path)
    try:
        cur = conn.cursor()
        cur.executescript(SCHEMA)
        existing = {row[1] for row in cur.execute("PRAGMA table_info(users)")}
        for column, ddl in (
            ("cert_name", "TEXT NOT NULL DEFAULT ''"),
            ("profile_path", "TEXT NOT NULL DEFAULT ''"),
            ("auth_mode", "TEXT NOT NULL DEFAULT 'userpass'"),
            ("access_mode", "TEXT NOT NULL DEFAULT 'free'"),
        ):
            if column not in existing:
                cur.execute(f"ALTER TABLE users ADD COLUMN {column} {ddl}")
        conn.commit()
    finally:
        conn.close()
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
