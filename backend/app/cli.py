"""CLI: `python -m app.cli seed` — руководитель и первая точка (идемпотентно)."""

import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import dispose_engine, get_engine
from app.core.security import check_password_policy, hash_password
from app.models import Location, Role, User, UserLocation
from app.services.audit import write_audit
from app.services.sessions import utcnow

DEV_PASSWORD = "demo-password-123"  # noqa: S105
DIRECTOR_LOGIN = "director"


class SeedError(Exception):
    pass


async def seed(session: AsyncSession) -> tuple[bool, bool]:
    """Возвращает (создана_точка, создан_руководитель)."""
    settings = get_settings()
    password = settings.seed_director_password
    if password is None:
        if settings.is_prod:
            raise SeedError("В ENV=prod задайте SEED_DIRECTOR_PASSWORD")
        raw = DEV_PASSWORD
    else:
        raw = password.get_secret_value()
    reason = check_password_policy(raw, DIRECTOR_LOGIN)
    if reason:
        raise SeedError(f"Пароль руководителя не проходит политику: {reason}")

    loc = await session.scalar(select(Location).order_by(Location.created_at).limit(1))
    loc_created = loc is None
    if loc is None:
        loc = Location(name="Основная точка", code="MAIN", address="Адрес не указан")
        session.add(loc)
        await session.flush()
        write_audit(
            session, action="create", entity_type="location", entity_id=loc.id, location_id=loc.id
        )

    director = await session.scalar(select(User).where(User.login == DIRECTOR_LOGIN))
    dir_created = director is None
    if director is None:
        director = User(
            login=DIRECTOR_LOGIN,
            full_name="Руководитель",
            role=Role.director.value,
            password_hash=await hash_password(raw),
            password_changed_at=utcnow(),
        )
        session.add(director)
        await session.flush()
        session.add(UserLocation(user_id=director.id, location_id=loc.id))
        write_audit(
            session,
            action="create",
            entity_type="user",
            entity_id=director.id,
            changes={"login": {"old": None, "new": DIRECTOR_LOGIN}},
        )
    await session.commit()
    return loc_created, dir_created


async def _run_seed() -> int:  # pragma: no cover
    try:
        async with AsyncSession(get_engine(), expire_on_commit=False) as session:
            loc_created, dir_created = await seed(session)
    except SeedError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    finally:
        await dispose_engine()
    print("Точка:", "создана" if loc_created else "уже есть")
    print(f"Руководитель {DIRECTOR_LOGIN}:", "создан" if dir_created else "уже есть")
    return 0


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(prog="app.cli")
    parser.add_subparsers(dest="command", required=True).add_parser("seed")
    parser.parse_args(argv)
    return asyncio.run(_run_seed())


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
