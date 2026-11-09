from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app import cli
from app.models import Location, Role, User, UserLocation

pytestmark = pytest.mark.integration


def _settings(password: str | None, prod: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        seed_director_password=SecretStr(password) if password is not None else None,
        is_prod=prod,
    )


async def test_seed_creates_and_is_idempotent(api, db, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(None))
    # чистая БД: в тестовой транзакции других точек и руководителя нет
    assert await cli.seed(db) == (True, True)
    assert await cli.seed(db) == (False, False)
    assert await db.scalar(select(func.count()).select_from(Location)) == 1
    director = await db.scalar(select(User).where(User.login == "director"))
    assert director.role == Role.director.value and director.is_active
    assert await db.scalar(select(func.count()).select_from(UserLocation)) == 1

    r = await api.post(
        "/api/v1/auth/login", json={"login": "director", "password": cli.DEV_PASSWORD}
    )
    assert r.status_code == 200 and r.json()["user"]["role"] == "director"


async def test_seed_uses_env_password_and_keeps_existing_director(api, db, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings("custom-long-passphrase-5"))
    await cli.seed(db)
    r = await api.post(
        "/api/v1/auth/login", json={"login": "director", "password": "custom-long-passphrase-5"}
    )
    assert r.status_code == 200
    # повторный seed с другим паролем существующего руководителя не перезаписывает
    monkeypatch.setattr(cli, "get_settings", lambda: _settings("different-passphrase-77"))
    assert await cli.seed(db) == (False, False)
    r = await api.post(
        "/api/v1/auth/login", json={"login": "director", "password": "custom-long-passphrase-5"}
    )
    assert r.status_code == 200


async def test_seed_refuses_in_prod_without_password(db, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(None, prod=True))
    with pytest.raises(cli.SeedError):
        await cli.seed(db)
    assert await db.scalar(select(func.count()).select_from(User)) == 0


@pytest.mark.parametrize("weak", ["short", "password123", "director"])
async def test_seed_refuses_weak_password(db, monkeypatch, weak):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(weak))
    with pytest.raises(cli.SeedError):
        await cli.seed(db)
    assert await db.scalar(select(func.count()).select_from(User)) == 0
