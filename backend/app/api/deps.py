"""Зависимости: текущий пользователь, проверка роли, список разрешённых точек."""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.models import Location, Role, User, UserLocation
from app.services.audit import ClientInfo, make_client_info

_bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if creds is None:
        raise AppError(401, "unauthorized")
    user_id = decode_access_token(creds.credentials)
    if user_id is None:
        raise AppError(401, "unauthorized")
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise AppError(401, "unauthorized")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: Role) -> Callable[..., Awaitable[User]]:
    async def dependency(user: CurrentUser) -> User:
        if user.role not in roles:
            raise AppError(403, "forbidden")
        return user

    return dependency


Director = Annotated[User, Depends(require_role(Role.director))]
# Клиенты и автомобили: менеджер и руководитель (механик — 403 до модуля 6).
Staff = Annotated[User, Depends(require_role(Role.manager, Role.director))]


async def get_allowed_location_ids(user: CurrentUser, session: SessionDep) -> list[uuid.UUID]:
    """Руководитель видит все точки, остальные — только привязанные к ним."""
    if user.role == Role.director:
        stmt = select(Location.id)
    else:
        stmt = select(UserLocation.location_id).where(UserLocation.user_id == user.id)
    return list(await session.scalars(stmt))


AllowedLocations = Annotated[list[uuid.UUID], Depends(get_allowed_location_ids)]


def get_client_info(request: Request) -> ClientInfo:
    host = request.client.host if request.client else None
    return make_client_info(host, request.headers.get("user-agent"))


Client = Annotated[ClientInfo, Depends(get_client_info)]
