import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Response

from app.api.deps import Client, CurrentUser, Director, SessionDep
from app.core.errors import AppError
from app.core.ratelimit import RateLimiter
from app.schemas.audit import SessionRead
from app.services import user_sessions as svc

router = APIRouter(tags=["sessions"])

# 30 изменяющих запросов в минуту на пользователя.
_mutations = RateLimiter()
MUTATIONS_PER_MINUTE = 30

RefreshCookie = Annotated[str | None, Cookie(alias="refresh_token")]


def _limit(user_id: uuid.UUID) -> None:
    if not _mutations.allow(str(user_id), MUTATIONS_PER_MINUTE):
        raise AppError(429, "rate_limited")


@router.get("/auth/sessions", response_model=list[SessionRead])
async def list_sessions(
    user: CurrentUser, session: SessionDep, refresh_token: RefreshCookie = None
) -> list[SessionRead]:
    return await svc.list_sessions(session, user, refresh_token)


@router.post("/auth/sessions/revoke-others", status_code=204)
async def revoke_other_sessions(
    user: CurrentUser, session: SessionDep, client: Client, refresh_token: RefreshCookie = None
) -> Response:
    _limit(user.id)
    await svc.revoke_other_sessions(session, user, refresh_token, client)
    return Response(status_code=204)


@router.delete("/auth/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    client: Client,
    refresh_token: RefreshCookie = None,
) -> Response:
    _limit(user.id)
    await svc.revoke_session(session, user, session_id, refresh_token, client)
    return Response(status_code=204)


@router.post("/users/{user_id}/revoke-sessions", status_code=204)
async def revoke_user_sessions(
    user_id: uuid.UUID,
    actor: Director,
    session: SessionDep,
    client: Client,
    refresh_token: RefreshCookie = None,
) -> Response:
    await svc.revoke_all_user_sessions(session, actor, user_id, refresh_token, client)
    return Response(status_code=204)
