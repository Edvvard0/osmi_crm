"""Пароли (Argon2id), политика паролей, JWT access-токены, хеши refresh-токенов."""

import asyncio
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.common_passwords import COMMON_PASSWORDS
from app.core.config import get_settings

MIN_PASSWORD_LEN = 10
MAX_PASSWORD_LEN = 128


@lru_cache
def _hasher() -> PasswordHasher:
    if get_settings().env == "test":
        # В тестах облегчённые параметры, чтобы набор тестов не тормозил. В dev/prod — по умолчанию.
        return PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    return PasswordHasher()


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher().hash, password)


async def verify_password(password_hash: str, password: str) -> bool:
    def _verify() -> bool:
        try:
            return _hasher().verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False

    return await asyncio.to_thread(_verify)


@lru_cache
def _dummy_hash() -> str:
    return _hasher().hash(secrets.token_urlsafe(16))


async def verify_dummy(password: str) -> None:
    """Выравнивает время ответа для несуществующего логина."""
    await verify_password(_dummy_hash(), password)


def check_password_policy(password: str, login: str) -> str | None:
    """Возвращает код причины, если пароль слабый, иначе None."""
    if len(password) < MIN_PASSWORD_LEN:
        return "password_too_short"
    if len(password) > MAX_PASSWORD_LEN:
        return "password_too_long"
    low = password.lower()
    if low == login.lower():
        return "password_equals_login"
    if low in COMMON_PASSWORDS or len(set(low)) == 1:
        return "password_common"
    return None


def _jwt_key() -> bytes:
    raw = get_settings().secret_key.get_secret_value().encode()
    return hashlib.sha256(b"crm-jwt-v1:" + raw).digest()


def create_access_token(user_id: uuid.UUID) -> tuple[str, int]:
    ttl = get_settings().access_ttl_seconds
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "jti": uuid.uuid4().hex,
        "typ": "access",
    }
    return jwt.encode(payload, _jwt_key(), algorithm="HS256"), ttl


def decode_access_token(token: str) -> uuid.UUID | None:
    try:
        data = jwt.decode(
            token,
            _jwt_key(),
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "iat"]},
        )
        if data.get("typ") != "access":
            return None
        return uuid.UUID(str(data["sub"]))
    except (jwt.PyJWTError, ValueError):
        return None


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
