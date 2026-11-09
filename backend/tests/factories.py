import uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import Location, Role, User, UserLocation

PASSWORD = "correct-horse-battery-1"


async def make_location(db: AsyncSession, name: str | None = None, **kw: object) -> Location:
    suffix = uuid.uuid4().hex[:8]
    loc = Location(
        name=name or f"Точка {suffix}",
        code=f"T{suffix.upper()}"[:10],
        address=kw.pop("address", "ул. Тестовая, 1"),
        **kw,
    )
    db.add(loc)
    await db.commit()
    return loc


async def make_user(
    db: AsyncSession,
    role: Role = Role.manager,
    login: str | None = None,
    password: str = PASSWORD,
    locations: list[Location] | None = None,
    is_active: bool = True,
) -> User:
    user = User(
        login=login or f"u{uuid.uuid4().hex[:10]}",
        full_name="Тестовый Сотрудник",
        role=role.value,
        password_hash=await hash_password(password),
        is_active=is_active,
    )
    db.add(user)
    await db.flush()
    db.add_all(UserLocation(user_id=user.id, location_id=loc.id) for loc in locations or [])
    await db.commit()
    return user


async def login(client: httpx.AsyncClient, user: User, password: str = PASSWORD) -> str:
    r = await client.post("/api/v1/auth/login", json={"login": user.login, "password": password})
    assert r.status_code == 200, r.text
    token: str = r.json()["access_token"]
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
