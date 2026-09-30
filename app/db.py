"""Database access. Thin SQLite wrapper: connection handling, money helpers,
audit logging. Deliberately no ORM - the schema is small and the team should be
able to read the SQL.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from . import config


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    schema = (config.BASE_DIR / "app" / "schema.sql").read_text(encoding="utf-8")
    with connect() as conn:
        conn.executescript(schema)
    _ensure_seed_users()


# ------------------------------------------------------------------ money
# Amounts are stored as integers in the minor unit (e.g. paise).
# 100 minor units == 1 major unit.
MINOR_PER_MAJOR = 100


def to_minor(major: float) -> int:
    return int(round(major * MINOR_PER_MAJOR))


def to_major(minor: int) -> float:
    return round(minor / MINOR_PER_MAJOR, 2)


# ------------------------------------------------------------------ auth
def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt, digest = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return secrets.compare_digest(candidate.hex(), digest)


def _ensure_seed_users() -> None:
    with connect() as conn:
        for username, role, password in (
            ("admin", config.ROLE_ADMIN, "admin123"),
            ("analyst", config.ROLE_ANALYST, "analyst123"),
            ("ciso", config.ROLE_EXEC, "ciso123"),
        ):
            row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO users (username, role, password_hash, created_at) VALUES (?,?,?,?)",
                    (username, role, hash_password(password), utcnow()),
                )


def create_session(conn: sqlite3.Connection, user_id: int) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now.timestamp() + config.SESSION_TTL_SECONDS
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
        (token, user_id, now.isoformat(timespec="seconds"),
         datetime.fromtimestamp(expires, timezone.utc).isoformat(timespec="seconds")),
    )
    return token, hashlib.sha256(token.encode()).hexdigest()


def user_for_token(conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    row = conn.execute(
        """SELECT u.id, u.username, u.role FROM sessions s
           JOIN users u ON u.id = s.user_id WHERE s.token = ?""",
        (token,),
    ).fetchone()
    if row is None:
        return None
    expires = conn.execute("SELECT expires_at FROM sessions WHERE token = ?", (token,)).fetchone()
    if expires and expires["expires_at"] < utcnow():
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        return None
    return row


def has_capability(role: str, capability: str) -> bool:
    return capability in config.CAPABILITIES.get(role, set())


# ------------------------------------------------------------------ audit
def audit(conn: sqlite3.Connection, action: str, *, entity: str | None = None,
          detail: dict[str, Any] | None = None, username: str | None = None,
          role: str | None = None, severity: str = "info") -> None:
    conn.execute(
        """INSERT INTO audit_events (ts, username, role, action, entity, detail_json, severity)
           VALUES (?,?,?,?,?,?,?)""",
        (utcnow(), username, role, action, entity,
         json.dumps(detail or {}, default=str), severity),
    )


# ------------------------------------------------------------------ helpers
def table_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"])


def last_load(conn: sqlite3.Connection, dataset_type: str) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT * FROM datasets WHERE dataset_type = ? AND status = 'committed'
           ORDER BY COALESCE(loaded_at, id) DESC LIMIT 1""",
        (dataset_type,),
    ).fetchone()


def age_days(timestamp: str | None) -> float | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - parsed).total_seconds() / 86400, 2)
