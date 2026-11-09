import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import ValidationError

from app.core import security
from app.core.ratelimit import RateLimiter
from app.schemas.location import LocationCreate, LocationUpdate
from app.schemas.user import UserCreate, UserUpdate


@pytest.mark.parametrize(
    "password,login,reason",
    [
        ("short1", "ivan", "password_too_short"),
        ("123456789", "ivan", "password_too_short"),
        ("password123", "ivan", "password_common"),
        ("QWERTYUIOP", "ivan", "password_common"),
        ("aaaaaaaaaaaa", "ivan", "password_common"),
        ("ivan.petrov-1", "ivan.petrov-1", "password_equals_login"),
        ("IVAN.PETROV-1", "ivan.petrov-1", "password_equals_login"),
        ("x" * 200, "ivan", "password_too_long"),
        ("correct-horse-battery-1", "ivan", None),
    ],
)
def test_password_policy(password, login, reason):
    assert security.check_password_policy(password, login) == reason


async def test_hash_and_verify():
    h = await security.hash_password("correct-horse-battery-1")
    assert h.startswith("$argon2id$")
    assert await security.verify_password(h, "correct-horse-battery-1")
    assert not await security.verify_password(h, "wrong-password-123")
    assert not await security.verify_password("not-a-hash", "whatever-123456")
    await security.verify_dummy("anything")


def test_access_token_roundtrip():
    uid = uuid.uuid4()
    token, ttl = security.create_access_token(uid)
    assert ttl == 900
    assert security.decode_access_token(token) == uid


def test_access_token_rejects_bad_tokens():
    uid = uuid.uuid4()
    key = security._jwt_key()
    now = datetime.now(UTC)
    good = {"sub": str(uid), "iat": now, "exp": now + timedelta(minutes=5), "typ": "access"}
    expired = {**good, "exp": now - timedelta(seconds=5)}
    assert security.decode_access_token(jwt.encode(expired, key, "HS256")) is None
    assert security.decode_access_token(jwt.encode(good, b"x" * 32, "HS256")) is None
    assert (
        security.decode_access_token(jwt.encode({**good, "typ": "refresh"}, key, "HS256")) is None
    )
    assert security.decode_access_token(jwt.encode({**good, "sub": "nope"}, key, "HS256")) is None
    no_exp = {k: v for k, v in good.items() if k != "exp"}
    assert security.decode_access_token(jwt.encode(no_exp, key, "HS256")) is None
    # alg=none и мусор
    assert security.decode_access_token(jwt.encode(good, None, "none")) is None
    assert security.decode_access_token("garbage") is None
    assert security.decode_access_token(jwt.encode(good, key, "HS256")) == uid


def test_refresh_token_hashing():
    t1, t2 = security.new_refresh_token(), security.new_refresh_token()
    assert t1 != t2 and len(t1) >= 60
    h = security.hash_token(t1)
    assert len(h) == 64 and t1 not in h and h == security.hash_token(t1)


def test_rate_limiter(monkeypatch):
    rl = RateLimiter()
    assert all(rl.allow("a", 3) for _ in range(3))
    assert not rl.allow("a", 3)
    assert rl.allow("b", 3)
    real = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: real + 61)
    assert rl.allow("a", 3)
    rl.reset()
    assert rl.allow("a", 1)


def test_schemas_forbid_extra_and_mass_assignment():
    with pytest.raises(ValidationError):
        UserCreate(login="ivan", full_name="Иван", role="manager", password="x", is_active=False)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        UserUpdate(login="other")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        LocationCreate(name="A", address="B", code="HACK")  # type: ignore[call-arg]


def test_patch_null_rules():
    with pytest.raises(ValidationError):
        UserUpdate(full_name=None)
    with pytest.raises(ValidationError):
        LocationUpdate(name=None)
    assert LocationUpdate(phone=None).model_dump(exclude_unset=True) == {"phone": None}
    with pytest.raises(ValidationError):
        LocationCreate(name="   ", address="адрес")
