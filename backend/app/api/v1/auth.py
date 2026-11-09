from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response
from fastapi.responses import JSONResponse

from app.api.deps import Client, CurrentUser, SessionDep
from app.core.config import get_settings
from app.core.errors import AppError, error_response
from app.core.ratelimit import login_limiter
from app.models import User
from app.schemas.auth import ChangePassword, LoginRequest, TokenResponse
from app.schemas.user import UserRead
from app.services import auth as svc
from app.services.users import read_user

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE = "refresh_token"
COOKIE_PATH = "/api/v1/auth"


def _set_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.refresh_ttl_days * 86400,
        path=COOKIE_PATH,
        httponly=True,
        secure=settings.env != "dev",
        samesite="strict",
    )


def _clear_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        COOKIE,
        path=COOKIE_PATH,
        httponly=True,
        secure=settings.env != "dev",
        samesite="strict",
    )


async def _token_response(
    session: SessionDep, response: Response, user: User, access: str, ttl: int, refresh: str
) -> TokenResponse:
    _set_cookie(response, refresh)
    return TokenResponse(access_token=access, expires_in=ttl, user=await read_user(session, user))


@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest, response: Response, session: SessionDep, client: Client
) -> TokenResponse:
    if not login_limiter.allow(client.ip or "unknown", get_settings().login_per_minute):
        raise AppError(429, "rate_limited")
    user, access, ttl, refresh = await svc.login(session, data.login, data.password, client)
    return await _token_response(session, response, user, access, ttl, refresh)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    session: SessionDep,
    client: Client,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> TokenResponse | JSONResponse:
    try:
        user, access, ttl, new_refresh = await svc.refresh(session, refresh_token, client)
    except AppError as exc:
        # Негодный refresh-cookie больше не нужен браузеру.
        err = error_response(exc.status, exc.code, request, exc.fields)
        _clear_cookie(err)
        return err
    return await _token_response(session, response, user, access, ttl, new_refresh)


@router.post("/logout", status_code=204)
async def logout(
    session: SessionDep,
    client: Client,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> Response:
    await svc.logout(session, refresh_token, client)
    resp = Response(status_code=204)
    _clear_cookie(resp)
    return resp


@router.post("/change-password", status_code=204)
async def change_password(
    data: ChangePassword,
    user: CurrentUser,
    session: SessionDep,
    client: Client,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> Response:
    await svc.change_password(
        session, user, refresh_token, data.current_password, data.new_password, client
    )
    return Response(status_code=204)


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser, session: SessionDep) -> UserRead:
    return await read_user(session, user)
