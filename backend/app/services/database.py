from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from threading import Lock

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = BASE_DIR / "downloads" / "app.sqlite3"
FALLBACK_DB_PATH = Path(tempfile.gettempdir()) / "free-video-downloader" / "app.sqlite3"

_INIT_LOCK = Lock()
_INITIALIZED_PATHS: set[str] = set()


def database_path() -> Path:
    configured = os.getenv("FVD_DB_PATH", "").strip()
    if configured:
        return Path(configured)
    try:
        DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        return DEFAULT_DB_PATH
    except OSError:
        return FALLBACK_DB_PATH


def init_db() -> None:
    path = database_path()
    path_key = str(path.resolve())
    with _INIT_LOCK:
        if path_key in _INITIALIZED_PATHS:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    display_name TEXT,
                    avatar_url TEXT,
                    is_vip INTEGER NOT NULL DEFAULT 0,
                    vip_activated_at TEXT,
                    stripe_customer_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS payments (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    stripe_price_id TEXT,
                    stripe_checkout_session_id TEXT UNIQUE,
                    stripe_payment_intent_id TEXT,
                    amount_total INTEGER,
                    currency TEXT,
                    status TEXT NOT NULL,
                    checkout_url TEXT,
                    expires_at INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS stripe_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    processed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS email_codes (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    code TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            payment_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(payments)").fetchall()
            }
            if "stripe_price_id" not in payment_columns:
                conn.execute("ALTER TABLE payments ADD COLUMN stripe_price_id TEXT")
            if "amount_total" not in payment_columns:
                conn.execute("ALTER TABLE payments ADD COLUMN amount_total INTEGER")
            if "currency" not in payment_columns:
                conn.execute("ALTER TABLE payments ADD COLUMN currency TEXT")
            user_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()
            }
            if "display_name" not in user_columns:
                conn.execute("ALTER TABLE users ADD COLUMN display_name TEXT")
            if "avatar_url" not in user_columns:
                conn.execute("ALTER TABLE users ADD COLUMN avatar_url TEXT")
        _INITIALIZED_PATHS.add(path_key)


def get_connection() -> sqlite3.Connection:
    init_db()
    conn = sqlite3.connect(database_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
