from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from sqlite3 import IntegrityError, Row

from app.services.database import get_connection

AUTH_COOKIE_NAME = "fvd_session"
AUTH_ALGORITHM = "HS256"
SESSION_TTL_DAYS = 30
PBKDF2_ITERATIONS = 260_000


class AuthError(RuntimeError):
    pass


class DuplicateEmail(AuthError):
    pass


@dataclass(frozen=True)
class UserRecord:
    id: str
    email: str
    password_hash: str
    display_name: str | None
    avatar_url: str | None
    is_vip: bool
    vip_activated_at: str | None
    stripe_customer_id: str | None
    created_at: str
    updated_at: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _auth_secret() -> str:
    return os.getenv("AUTH_SECRET_KEY", "dev-only-change-me-please")


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _pwdlib_hasher():
    try:
        from pwdlib import PasswordHash  # type: ignore
    except ModuleNotFoundError:
        return None
    return PasswordHash.recommended()


def _hash_password_pbkdf2(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def hash_password(password: str) -> str:
    hasher = _pwdlib_hasher()
    if hasher is not None:
        return hasher.hash(password)
    return _hash_password_pbkdf2(password)


def _verify_pbkdf2(password: str, encoded: str) -> bool:
    try:
        _, iterations, salt_b64, digest_b64 = encoded.split("$", 3)
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def verify_password(password: str, encoded: str) -> bool:
    if encoded.startswith("pbkdf2_sha256$"):
        return _verify_pbkdf2(password, encoded)
    hasher = _pwdlib_hasher()
    if hasher is None:
        return False
    try:
        return bool(hasher.verify(password, encoded))
    except Exception:
        return False


def _row_to_user(row: Row | None) -> UserRecord | None:
    if row is None:
        return None
    return UserRecord(
        id=str(row["id"]),
        email=str(row["email"]),
        password_hash=str(row["password_hash"]),
        display_name=row["display_name"],
        avatar_url=row["avatar_url"],
        is_vip=bool(row["is_vip"]),
        vip_activated_at=row["vip_activated_at"],
        stripe_customer_id=row["stripe_customer_id"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def create_user(email: str, password: str) -> UserRecord:
    normalized = _normalize_email(email)
    user_id = uuid4().hex
    now = _now_iso()
    default_name = normalized.split("@", 1)[0][:32] or "用户"
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (id, email, password_hash, display_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, normalized, hash_password(password), default_name, now, now),
            )
    except IntegrityError as exc:
        raise DuplicateEmail("该邮箱已注册") from exc
    user = get_user_by_id(user_id)
    if user is None:
        raise AuthError("用户创建失败")
    return user


def get_user_by_email(email: str) -> UserRecord | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (_normalize_email(email),)).fetchone()
    return _row_to_user(row)


def get_user_by_id(user_id: str) -> UserRecord | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_user(row)


def authenticate_user(email: str, password: str) -> UserRecord | None:
    user = get_user_by_email(email)
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def update_profile(user_id: str, display_name: str | None) -> UserRecord | None:
    cleaned_name = (display_name or "").strip()[:32] or None
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE users
            SET display_name = COALESCE(?, display_name),
                updated_at = ?
            WHERE id = ?
            """,
            (cleaned_name, _now_iso(), user_id),
        )
    return get_user_by_id(user_id)


def update_avatar(user_id: str, avatar_url: str | None) -> UserRecord | None:
    cleaned_avatar = (avatar_url or "").strip()[:500] or None
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE users
            SET avatar_url = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (cleaned_avatar, _now_iso(), user_id),
        )
    return get_user_by_id(user_id)


def create_session_token(user_id: str) -> str:
    session_id = uuid4().hex
    expires_at = _now() + timedelta(days=SESSION_TTL_DAYS)
    now = _now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO sessions (id, user_id, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, user_id, expires_at.isoformat(), now),
        )
    return jwt.encode(
        {"sub": user_id, "sid": session_id, "exp": expires_at},
        _auth_secret(),
        algorithm=AUTH_ALGORITHM,
    )


def revoke_session(session_id: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE sessions SET revoked_at = ? WHERE id = ?", (_now_iso(), session_id))


def user_from_token(token: str | None) -> UserRecord | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, _auth_secret(), algorithms=[AUTH_ALGORITHM])
        user_id = str(payload.get("sub") or "")
        session_id = str(payload.get("sid") or "")
    except jwt.PyJWTError:
        return None
    if not user_id or not session_id:
        return None
    with get_connection() as conn:
        session = conn.execute(
            """
            SELECT * FROM sessions
            WHERE id = ? AND user_id = ? AND revoked_at IS NULL AND expires_at > ?
            """,
            (session_id, user_id, _now_iso()),
        ).fetchone()
    if session is None:
        return None
    return get_user_by_id(user_id)


def session_id_from_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, _auth_secret(), algorithms=[AUTH_ALGORITHM])
    except jwt.PyJWTError:
        return None
    sid = payload.get("sid")
    return str(sid) if sid else None


def activate_vip(user_id: str, stripe_customer_id: str | None = None) -> UserRecord | None:
    now = _now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE users
            SET is_vip = 1,
                vip_activated_at = COALESCE(vip_activated_at, ?),
                stripe_customer_id = COALESCE(?, stripe_customer_id),
                updated_at = ?
            WHERE id = ?
            """,
            (now, stripe_customer_id, now, user_id),
        )
    return get_user_by_id(user_id)


def deactivate_vip(user_id: str) -> UserRecord | None:
    now = _now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE users
            SET is_vip = 0,
                vip_activated_at = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (now, user_id),
        )
    return get_user_by_id(user_id)


def check_and_increment_daily_ai_usage(user_id: str) -> bool:
    """Try to consume one daily AI usage. Returns True if allowed, False if limit reached."""
    today = _now().strftime("%Y-%m-%d")
    now = _now_iso()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT count FROM daily_ai_usage WHERE user_id = ? AND usage_date = ?",
            (user_id, today),
        ).fetchone()
        if row is not None and row["count"] >= 2:
            return False
        if row is None:
            conn.execute(
                "INSERT INTO daily_ai_usage (id, user_id, usage_date, count, updated_at) VALUES (?, ?, ?, 1, ?)",
                (uuid4().hex, user_id, today, now),
            )
        else:
            conn.execute(
                "UPDATE daily_ai_usage SET count = count + 1, updated_at = ? WHERE user_id = ? AND usage_date = ?",
                (now, user_id, today),
            )
    return True


def get_daily_ai_remaining(user_id: str) -> int:
    """Return remaining free AI uses for today (0-2)."""
    today = _now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        row = conn.execute(
            "SELECT count FROM daily_ai_usage WHERE user_id = ? AND usage_date = ?",
            (user_id, today),
        ).fetchone()
    used = row["count"] if row else 0
    return max(0, 2 - used)
