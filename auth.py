"""
Permanent player identity: registration, login, JWT sessions, SMS password reset.

Environment variables required:
  JWT_SECRET          — random secret for signing tokens (required)
  TWILIO_ACCOUNT_SID  — Twilio account SID (required for SMS reset)
  TWILIO_AUTH_TOKEN   — Twilio auth token (required for SMS reset)
  TWILIO_FROM_NUMBER  — Twilio phone number in E.164 format, e.g. +15551234567
  APP_BASE_URL        — public base URL, e.g. https://mishmish-game.fly.dev
                        (used to build the reset link; defaults to http://localhost:8000)
"""

import os
import uuid
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiosqlite
import bcrypt
import jwt

DB_PATH = os.environ.get("DB_PATH", "mishmish.db")
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 90
RESET_TOKEN_EXPIRE_MINUTES = 30
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000").rstrip("/")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          TEXT PRIMARY KEY,
                username    TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                phone       TEXT,
                created_at  TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reset_tokens (
                token       TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL,
                expires_at  TEXT NOT NULL,
                used        INTEGER DEFAULT 0
            )
        """)
        await db.commit()


# ---------------------------------------------------------------------------
# User operations
# ---------------------------------------------------------------------------

async def get_user_by_username(username: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_user_by_id(user_id: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_user_by_phone(phone: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE phone = ?", (phone,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def create_user(username: str, password: str, phone: Optional[str] = None) -> dict:
    """Create a new user. Raises ValueError on duplicate username."""
    user_id = uuid.uuid4().hex
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO users (id, username, password_hash, phone, created_at) VALUES (?,?,?,?,?)",
                (user_id, username, pw_hash, phone, created_at),
            )
            await db.commit()
        except aiosqlite.IntegrityError:
            raise ValueError("Username already taken")
    return {"id": user_id, "username": username, "phone": phone}


async def verify_password(username: str, password: str) -> Optional[dict]:
    """Return user dict if credentials are valid, else None."""
    user = await get_user_by_username(username)
    if not user:
        return None
    if bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return user
    return None


async def update_password(user_id: str, new_password: str):
    pw_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?", (pw_hash, user_id)
        )
        await db.commit()


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_token(user_id: str, username: str) -> str:
    payload = {
        "sub": user_id,
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Return payload dict or None if invalid/expired."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


# ---------------------------------------------------------------------------
# Password reset tokens
# ---------------------------------------------------------------------------

async def create_reset_token(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)
    ).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        # Invalidate any existing unused tokens for this user
        await db.execute(
            "UPDATE reset_tokens SET used = 1 WHERE user_id = ? AND used = 0", (user_id,)
        )
        await db.execute(
            "INSERT INTO reset_tokens (token, user_id, expires_at) VALUES (?,?,?)",
            (token, user_id, expires_at),
        )
        await db.commit()
    return token


async def consume_reset_token(token: str) -> Optional[str]:
    """
    Validate a reset token. Returns user_id if valid and unused, else None.
    Marks the token as used.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM reset_tokens WHERE token = ? AND used = 0", (token,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        expires_at = datetime.fromisoformat(row["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            return None
        await db.execute(
            "UPDATE reset_tokens SET used = 1 WHERE token = ?", (token,)
        )
        await db.commit()
        return row["user_id"]


# ---------------------------------------------------------------------------
# SMS via Twilio
# ---------------------------------------------------------------------------

def _twilio_client():
    from twilio.rest import Client  # lazy import so server starts without config
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth = os.environ.get("TWILIO_AUTH_TOKEN")
    if not sid or not auth:
        raise RuntimeError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set")
    return Client(sid, auth)


def _twilio_from():
    num = os.environ.get("TWILIO_FROM_NUMBER")
    if not num:
        raise RuntimeError("TWILIO_FROM_NUMBER must be set")
    return num


def normalize_phone(raw: str) -> str:
    """Strip non-digit chars, then prepend +1 if 10 digits (US default)."""
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    # Return as-is with a leading + if it doesn't already have one
    return raw if raw.startswith("+") else f"+{raw}"


async def send_reset_sms(phone: str, reset_token: str):
    """Send a password-reset link via Twilio SMS."""
    link = f"{APP_BASE_URL}/reset-password?token={reset_token}"
    body = f"Mish Mish password reset — tap the link (expires in {RESET_TOKEN_EXPIRE_MINUTES} min):\n{link}"
    client = _twilio_client()
    # Twilio's REST client is sync; run in executor to avoid blocking
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: client.messages.create(to=phone, from_=_twilio_from(), body=body),
    )
