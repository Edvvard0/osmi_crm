from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_token
from app.models import AuditLog, RefreshSession, Role, User
from tests.conftest import make_api_client
from tests.factories import PASSWORD, bearer, login, make_location, make_user

pytestmark = pytest.mark.integration

URL = "/api/v1/auth"


async def do_login(client, user, password=PASSWORD):
    return await client.post(f"{URL}/login", json={"login": user.login, "password": password})


async def audit_actions(db: AsyncSession) -> list[str]:
    return list(await db.scalars(select(AuditLog.action).order_by(AuditLog.id)))


async def test_login_success_shape_and_cookie(api, db):
    loc = await make_location(db)
    user = await make_user(db, Role.manager, locations=[loc])
    r = await do_login(api, user)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"access_token", "expires_in", "user"}
    assert body["expires_in"] == 900
    assert body["user"] == {
        "id": str(user.id),
        "login": user.login,
        "full_name": user.full_name,
        "role": "manager",
        "is_active": True,
        "location_ids": [str(loc.id)],
        "created_at": body["user"]["created_at"],
        "last_login_at": body["user"]["last_login_at"],
        "telegram_linked": False,
        "telegram_username": None,
    }
    assert "refresh_token" not in r.text
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("refresh_token=")
    for part in ("HttpOnly", "Secure", "SameSite=strict", "Path=/api/v1/auth"):
        assert part.lower() in cookie.lower()
    assert "login" in await audit_actions(db)


async def test_login_is_case_insensitive_and_trimmed(api, db):
    await make_user(db, login="ivan.petrov")
    r = await api.post(f"{URL}/login", json={"login": "  Ivan.Petrov ", "password": PASSWORD})
    assert r.status_code == 200


async def test_login_wrong_unknown_inactive_are_identical(api, db):
    user = await make_user(db)
    inactive = await make_user(db, is_active=False)
    wrong = await do_login(api, user, "wrong-password-123")
    unknown = await api.post(f"{URL}/login", json={"login": "nobody.here", "password": PASSWORD})
    off = await do_login(api, inactive)
    for r in (wrong, unknown, off):
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "invalid_credentials"
        assert "set-cookie" not in r.headers
    msgs = {r.json()["error"]["message"] for r in (wrong, unknown, off)}
    assert len(msgs) == 1
    assert (await audit_actions(db)).count("login_failed") == 3


async def test_lockout_after_five_failures(api, db):
    user = await make_user(db)
    codes = []
    for _ in range(5):
        r = await do_login(api, user, "wrong-password-123")
        codes.append((r.status_code, r.json()["error"]["code"]))
    assert codes[:4] == [(401, "invalid_credentials")] * 4
    assert codes[4] == (423, "account_locked")
    # даже верный пароль не пускает, пока блокировка действует
    r = await do_login(api, user)
    assert r.status_code == 423 and r.json()["error"]["code"] == "account_locked"

    # блокировка истекла -> вход разрешён, счётчик сброшен
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(locked_until=datetime.now(UTC) - timedelta(minutes=1))
    )
    await db.commit()
    assert (await do_login(api, user)).status_code == 200
    await db.refresh(user)
    assert user.failed_login_count == 0 and user.locked_until is None


async def test_success_resets_failed_counter(api, db):
    user = await make_user(db)
    for _ in range(4):
        await do_login(api, user, "wrong-password-123")
    assert (await do_login(api, user)).status_code == 200
    for _ in range(4):
        assert (await do_login(api, user, "wrong-password-123")).status_code == 401


async def test_login_rate_limit_per_ip(conn, db):
    user = await make_user(db)
    async with (
        make_api_client(conn, ip="198.51.100.1") as a,
        make_api_client(conn, ip="198.51.100.2") as b,
    ):
        ghost = {"login": "nobody.here", "password": "wrong-password-123"}
        codes = [(await a.post(f"{URL}/login", json=ghost)).status_code for _ in range(10)]
        assert 429 not in codes
        r = await do_login(a, user)
        assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
        # другой IP не затронут
        assert (await do_login(b, user)).status_code == 200


async def test_login_validation(api):
    for body in (
        {},
        {"login": "ivan"},
        {"login": "ivan", "password": ""},
        {"login": "ivan", "password": "x" * 129},
        {"login": "ivan", "password": "x", "extra": 1},
        {"login": 5, "password": "x"},
    ):
        r = await api.post(f"{URL}/login", json=body)
        assert r.status_code == 422, body
        assert r.json()["error"]["code"] == "validation_error"


async def test_me_and_bearer_validation(api, db):
    user = await make_user(db, Role.director)
    token = await login(api, user)
    r = await api.get(f"{URL}/me", headers=bearer(token))
    assert r.status_code == 200 and r.json()["login"] == user.login
    for headers in ({}, bearer("garbage"), {"Authorization": "Basic abc"}):
        r = await api.get(f"{URL}/me", headers=headers)
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


async def test_me_rejects_deactivated_user(api, db):
    user = await make_user(db)
    token = await login(api, user)
    await db.execute(update(User).where(User.id == user.id).values(is_active=False))
    await db.commit()
    assert (await api.get(f"{URL}/me", headers=bearer(token))).status_code == 401


# ---------------- refresh ----------------


async def test_refresh_rotates_token_and_stores_only_hash(api, db):
    user = await make_user(db)
    await do_login(api, user)
    old = api.cookies.get("refresh_token")
    assert old
    rows = (await db.scalars(select(RefreshSession))).all()
    assert [s.token_hash for s in rows] == [hash_token(old)]
    assert old not in {s.token_hash for s in rows}

    r2 = await api.post(f"{URL}/refresh")
    assert r2.status_code == 200
    assert set(r2.json()) == {"access_token", "expires_in", "user"}
    new = api.cookies.get("refresh_token")
    assert new and new != old
    assert (
        await api.get(f"{URL}/me", headers=bearer(r2.json()["access_token"]))
    ).status_code == 200

    db.expire_all()
    sessions = (await db.scalars(select(RefreshSession).order_by(RefreshSession.created_at))).all()
    assert len(sessions) == 2
    assert sessions[0].revoked_at is not None and sessions[1].revoked_at is None
    assert sessions[0].family_id == sessions[1].family_id


async def test_refresh_reuse_revokes_chain(api, db):
    user = await make_user(db)
    await do_login(api, user)
    old = api.cookies.get("refresh_token")
    assert (await api.post(f"{URL}/refresh")).status_code == 200
    newest = api.cookies.get("refresh_token")

    # злоумышленник предъявляет старый токен
    api.cookies.clear()
    api.cookies.set("refresh_token", old)
    r = await api.post(f"{URL}/refresh")
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"
    assert "refresh_token" in r.headers["set-cookie"]  # cookie очищается

    # легитимный (новейший) токен цепочки тоже больше не работает
    api.cookies.clear()
    api.cookies.set("refresh_token", newest)
    r = await api.post(f"{URL}/refresh")
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"
    db.expire_all()
    rows = (await db.scalars(select(RefreshSession))).all()
    assert all(s.revoked_at for s in rows)
    assert "token_reuse" in await audit_actions(db)


async def test_reuse_does_not_touch_other_families(api, db, conn):
    user = await make_user(db)
    await do_login(api, user)
    old = api.cookies.get("refresh_token")
    await api.post(f"{URL}/refresh")
    async with make_api_client(conn, ip="198.51.100.9") as other:
        await do_login(other, user)
        other_cookie = other.cookies.get("refresh_token")
        api.cookies.clear()
        api.cookies.set("refresh_token", old)
        assert (await api.post(f"{URL}/refresh")).status_code == 401
        assert (await other.post(f"{URL}/refresh")).status_code == 200
        assert other.cookies.get("refresh_token") != other_cookie


async def test_refresh_expired_unknown_missing(api, db):
    user = await make_user(db)
    assert (await api.post(f"{URL}/refresh")).status_code == 401  # нет cookie
    api.cookies.set("refresh_token", "unknown-token-value")
    r = await api.post(f"{URL}/refresh")
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"

    api.cookies.clear()
    await do_login(api, user)
    await db.execute(update(RefreshSession).values(expires_at=datetime.now(UTC) - timedelta(1)))
    await db.commit()
    r = await api.post(f"{URL}/refresh")
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"


async def test_refresh_for_deactivated_user(api, db):
    user = await make_user(db)
    await do_login(api, user)
    await db.execute(update(User).where(User.id == user.id).values(is_active=False))
    await db.commit()
    assert (await api.post(f"{URL}/refresh")).status_code == 401


# ---------------- logout ----------------


async def test_logout_revokes_session_and_clears_cookie(api, db):
    user = await make_user(db)
    await do_login(api, user)
    token = api.cookies.get("refresh_token")
    r = await api.post(f"{URL}/logout")
    assert r.status_code == 204
    assert "refresh_token=" in r.headers["set-cookie"] and "Max-Age=0" in r.headers["set-cookie"]
    api.cookies.set("refresh_token", token)
    assert (await api.post(f"{URL}/refresh")).status_code == 401
    assert "logout" in await audit_actions(db)


async def test_logout_without_cookie_is_ok(api):
    assert (await api.post(f"{URL}/logout")).status_code == 204


async def test_logout_twice_is_idempotent(api, db):
    user = await make_user(db)
    await do_login(api, user)
    token = api.cookies.get("refresh_token")
    await api.post(f"{URL}/logout")
    api.cookies.set("refresh_token", token)
    assert (await api.post(f"{URL}/logout")).status_code == 204


# ---------------- change-password ----------------


async def test_change_password_flow(api, db, conn):
    user = await make_user(db)
    token = await login(api, user)
    current_cookie = api.cookies.get("refresh_token")
    async with make_api_client(conn, ip="198.51.100.20") as other:
        await do_login(other, user)  # вторая сессия на другом устройстве

        new = "brand-new-passphrase-9"
        r = await api.post(
            f"{URL}/change-password",
            headers=bearer(token),
            json={"current_password": PASSWORD, "new_password": new},
        )
        assert r.status_code == 204

        assert (await other.post(f"{URL}/refresh")).status_code == 401  # другая сессия отозвана
        r = await api.post(f"{URL}/refresh")  # текущая жива
        assert r.status_code == 200 and api.cookies.get("refresh_token") != current_cookie

    api.cookies.clear()
    assert (await do_login(api, user, PASSWORD)).status_code == 401  # старый пароль не работает
    assert (await do_login(api, user, new)).status_code == 200
    assert "password_change" in await audit_actions(db)


async def test_change_password_wrong_current(api, db):
    user = await make_user(db)
    token = await login(api, user)
    r = await api.post(
        f"{URL}/change-password",
        headers=bearer(token),
        json={"current_password": "wrong-password-123", "new_password": "brand-new-passphrase-9"},
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_current_password"


@pytest.mark.parametrize(
    "new,reason",
    [
        ("short", "password_too_short"),
        ("password123", "password_common"),
        ("login.same.as", "password_equals_login"),
    ],
)
async def test_change_password_weak_new(api, db, new, reason):
    user = await make_user(db, login="login.same.as")
    token = await login(api, user)
    r = await api.post(
        f"{URL}/change-password",
        headers=bearer(token),
        json={"current_password": PASSWORD, "new_password": new},
    )
    assert r.status_code == 422
    assert r.json()["error"]["fields"] == {"new_password": reason}
    assert PASSWORD not in r.text and f'"{new}"' not in r.text


async def test_change_password_requires_auth(api):
    r = await api.post(
        f"{URL}/change-password", json={"current_password": "a", "new_password": "b"}
    )
    assert r.status_code == 401


async def test_secure_flag_follows_env(conn, db):
    """В dev cookie без Secure (для http://localhost), в остальных средах — с Secure."""
    from app.core.config import get_settings

    user = await make_user(db)
    async with make_api_client(conn) as c:
        get_settings().env = "dev"
        try:
            r = await do_login(c, user)
        finally:
            get_settings.cache_clear()
    assert "secure" not in r.headers["set-cookie"].lower()


async def test_db_state_has_no_plain_tokens(api, db):
    user = await make_user(db)
    await do_login(api, user)
    raw = api.cookies.get("refresh_token")
    dump = (await db.execute(text("SELECT token_hash FROM refresh_sessions"))).scalars().all()
    assert raw not in dump and all(len(h) == 64 for h in dump)
    assert isinstance(api, httpx.AsyncClient)
