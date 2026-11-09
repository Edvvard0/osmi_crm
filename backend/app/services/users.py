import uuid
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import check_password_policy, hash_password
from app.core.types import _CTRL
from app.models import Location, Role, User, UserLocation
from app.schemas.user import UserCreate, UserPage, UserRead, UserUpdate
from app.services.audit import ClientInfo, diff, write_audit
from app.services.sessions import revoke_user_sessions, utcnow


async def location_ids_map(
    session: AsyncSession, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    result: dict[uuid.UUID, list[uuid.UUID]] = {uid: [] for uid in user_ids}
    if user_ids:
        rows = await session.execute(
            select(UserLocation.user_id, UserLocation.location_id)
            .where(UserLocation.user_id.in_(user_ids))
            .order_by(UserLocation.created_at, UserLocation.location_id)
        )
        for uid, lid in rows:
            result[uid].append(lid)
    return result


def to_read(user: User, location_ids: list[uuid.UUID]) -> UserRead:
    return UserRead(
        id=user.id,
        login=user.login,
        full_name=user.full_name,
        role=Role(user.role),
        is_active=user.is_active,
        location_ids=location_ids,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        telegram_linked=user.telegram_chat_id is not None,
        telegram_username=user.telegram_username,
    )


async def read_user(session: AsyncSession, user: User) -> UserRead:
    return to_read(user, (await location_ids_map(session, [user.id]))[user.id])


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_users(
    session: AsyncSession,
    *,
    search: str | None,
    role: Role | None,
    location_id: uuid.UUID | None,
    is_active: bool | None,
    limit: int,
    offset: int,
) -> UserPage:
    conds: list[Any] = []
    term = _CTRL.sub("", search or "").strip()  # NUL и др. управляющие символы ломают запрос
    if term:
        pattern = f"%{_like_escape(term)}%"
        conds.append(
            or_(
                User.full_name.ilike(pattern, escape="\\"),
                User.login.ilike(pattern, escape="\\"),
            )
        )
    if role is not None:
        conds.append(User.role == role.value)
    if is_active is not None:
        conds.append(User.is_active == is_active)
    if location_id is not None:
        conds.append(
            User.id.in_(select(UserLocation.user_id).where(UserLocation.location_id == location_id))
        )
    total = await session.scalar(select(func.count()).select_from(User).where(*conds)) or 0
    rows = (
        await session.scalars(
            select(User).where(*conds).order_by(User.full_name, User.id).limit(limit).offset(offset)
        )
    ).all()
    loc_map = await location_ids_map(session, [u.id for u in rows])
    return UserPage(items=[to_read(u, loc_map[u.id]) for u in rows], total=total)


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise AppError(404, "not_found")
    return user


async def _check_locations(session: AsyncSession, ids: list[uuid.UUID]) -> list[uuid.UUID]:
    unique = list(dict.fromkeys(ids))
    if unique:
        found = await session.scalar(
            select(func.count()).select_from(Location).where(Location.id.in_(unique))
        )
        if found != len(unique):
            raise AppError(422, "validation_error", {"location_ids": "unknown_location"})
    return unique


def _weak(field: str, password: str, login: str) -> None:
    reason = check_password_policy(password, login)
    if reason:
        raise AppError(422, "validation_error", {field: reason})


async def create_user(
    session: AsyncSession, actor: User, data: UserCreate, client: ClientInfo
) -> UserRead:
    _weak("password", data.password, data.login)
    loc_ids = await _check_locations(session, data.location_ids)
    user = User(
        login=data.login,
        full_name=data.full_name,
        role=data.role.value,
        password_hash=await hash_password(data.password),
        password_changed_at=utcnow(),
        created_by=actor.id,
    )
    session.add(user)
    await session.flush()
    session.add_all(UserLocation(user_id=user.id, location_id=lid) for lid in loc_ids)
    write_audit(
        session,
        action="create",
        entity_type="user",
        user_id=actor.id,
        entity_id=user.id,
        changes={
            "login": {"old": None, "new": user.login},
            "full_name": {"old": None, "new": user.full_name},
            "role": {"old": None, "new": user.role},
            "location_ids": {"old": [], "new": [str(i) for i in loc_ids]},
        },
        client=client,
    )
    await session.commit()
    return to_read(user, loc_ids)


async def update_user(
    session: AsyncSession,
    actor: User,
    user_id: uuid.UUID,
    data: UserUpdate,
    client: ClientInfo,
) -> UserRead:
    user = await session.get(User, user_id, with_for_update=True)
    if user is None:
        raise AppError(404, "not_found")
    patch = data.model_dump(exclude_unset=True)
    if user.id == actor.id and (
        patch.get("is_active") is False or ("role" in patch and patch["role"].value != user.role)
    ):
        # Руководитель не может заблокировать или понизить сам себя.
        raise AppError(422, "validation_error", {"_": "cannot_change_self"})

    old_locs = (await location_ids_map(session, [user.id]))[user.id]
    old: dict[str, Any] = {
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
        "location_ids": sorted(str(i) for i in old_locs),
    }
    revoke = False
    if "full_name" in patch:
        user.full_name = patch["full_name"]
    if "role" in patch:
        revoke = patch["role"].value != user.role
        user.role = patch["role"].value
    if "is_active" in patch:
        revoke = revoke or (user.is_active and not patch["is_active"])
        if patch["is_active"] and not user.is_active:
            user.failed_login_count = 0
            user.locked_until = None
        user.is_active = patch["is_active"]
    new_locs = old_locs
    if "location_ids" in patch:
        new_locs = await _check_locations(session, patch["location_ids"])
        await session.execute(delete(UserLocation).where(UserLocation.user_id == user.id))
        session.add_all(UserLocation(user_id=user.id, location_id=lid) for lid in new_locs)
    if revoke:
        await revoke_user_sessions(session, user.id)
    new: dict[str, Any] = {
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
        "location_ids": sorted(str(i) for i in new_locs),
    }
    changes = diff(old, new)
    if changes:
        write_audit(
            session,
            action="update",
            entity_type="user",
            user_id=actor.id,
            entity_id=user.id,
            changes=changes,
            client=client,
        )
    await session.commit()
    return to_read(user, new_locs)


async def reset_password(
    session: AsyncSession,
    actor: User,
    user_id: uuid.UUID,
    new_password: str,
    client: ClientInfo,
) -> None:
    user = await session.get(User, user_id, with_for_update=True)
    if user is None:
        raise AppError(404, "not_found")
    _weak("new_password", new_password, user.login)
    user.password_hash = await hash_password(new_password)
    user.password_changed_at = utcnow()
    user.failed_login_count = 0
    user.locked_until = None
    await revoke_user_sessions(session, user.id)
    write_audit(
        session,
        action="password_change",
        entity_type="user",
        user_id=actor.id,
        entity_id=user.id,
        changes={"reset_by_director": {"old": None, "new": True}},
        client=client,
    )
    await session.commit()
