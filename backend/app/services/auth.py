import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import (
    check_password_policy,
    create_access_token,
    hash_password,
    hash_token,
    verify_dummy,
    verify_password,
)
from app.models import RefreshSession, User
from app.services.audit import ClientInfo, clean, write_audit
from app.services.sessions import issue_session, revoke_family, revoke_user_sessions, utcnow


async def _fail(
    session: AsyncSession,
    client: ClientInfo,
    login: str,
    reason: str,
    user: User | None,
    error: AppError,
) -> AppError:
    write_audit(
        session,
        action="login_failed",
        entity_type="user",
        entity_id=user.id if user else None,
        changes={"login": clean(login), "reason": reason},
        client=client,
    )
    await session.commit()
    return error


async def login(
    session: AsyncSession, login_name: str, password: str, client: ClientInfo
) -> tuple[User, str, int, str]:
    """Возвращает (user, access_token, expires_in, refresh_token)."""
    settings = get_settings()
    now = utcnow()
    user = await session.scalar(select(User).where(User.login == login_name).with_for_update())
    invalid = AppError(401, "invalid_credentials")
    locked = AppError(423, "account_locked")
    if user is None:
        await verify_dummy(password)
        raise await _fail(session, client, login_name, "unknown_login", None, invalid)
    if user.locked_until is not None:
        if user.locked_until > now:
            raise await _fail(session, client, login_name, "locked", user, locked)
        user.locked_until = None
        user.failed_login_count = 0
    if not await verify_password(user.password_hash, password):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.max_failed_logins:
            user.locked_until = now + timedelta(minutes=settings.lock_minutes)
            raise await _fail(session, client, login_name, "locked_out", user, locked)
        raise await _fail(session, client, login_name, "bad_password", user, invalid)
    if not user.is_active:
        raise await _fail(session, client, login_name, "inactive", user, invalid)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    refresh_token = issue_session(session, user.id, None, client)
    write_audit(
        session,
        action="login",
        entity_type="user",
        user_id=user.id,
        entity_id=user.id,
        client=client,
    )
    await session.commit()
    token, ttl = create_access_token(user.id)
    return user, token, ttl, refresh_token


async def refresh(
    session: AsyncSession, raw_token: str | None, client: ClientInfo
) -> tuple[User, str, int, str]:
    invalid = AppError(401, "invalid_token")
    if not raw_token:
        raise invalid
    rs = await session.scalar(
        select(RefreshSession)
        .where(RefreshSession.token_hash == hash_token(raw_token))
        .with_for_update()
    )
    if rs is None:
        raise invalid
    now = utcnow()
    if rs.revoked_at is not None:
        # Повторное использование уже ротированного токена: цепочка скомпрометирована.
        await revoke_family(session, rs.family_id)
        write_audit(
            session,
            action="token_reuse",
            entity_type="user",
            user_id=rs.user_id,
            entity_id=rs.user_id,
            client=client,
        )
        await session.commit()
        raise invalid
    user = await session.get(User, rs.user_id)
    if rs.expires_at <= now or user is None or not user.is_active:
        rs.revoked_at = now
        await session.commit()
        raise invalid
    rs.revoked_at = now
    new_raw = issue_session(session, user.id, rs.family_id, client)
    await session.commit()
    token, ttl = create_access_token(user.id)
    return user, token, ttl, new_raw


async def logout(session: AsyncSession, raw_token: str | None, client: ClientInfo) -> None:
    if not raw_token:
        return
    rs = await session.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == hash_token(raw_token))
    )
    if rs is None or rs.revoked_at is not None:
        return
    rs.revoked_at = utcnow()
    write_audit(
        session,
        action="logout",
        entity_type="user",
        user_id=rs.user_id,
        entity_id=rs.user_id,
        client=client,
    )
    await session.commit()


async def change_password(
    session: AsyncSession,
    user: User,
    raw_refresh: str | None,
    current: str,
    new: str,
    client: ClientInfo,
) -> None:
    if not await verify_password(user.password_hash, current):
        raise AppError(400, "invalid_current_password")
    reason = check_password_policy(new, user.login)
    if reason:
        raise AppError(422, "validation_error", {"new_password": reason})
    keep: uuid.UUID | None = None
    if raw_refresh:
        keep = await session.scalar(
            select(RefreshSession.id).where(
                RefreshSession.token_hash == hash_token(raw_refresh),
                RefreshSession.user_id == user.id,
                RefreshSession.revoked_at.is_(None),
            )
        )
    user.password_hash = await hash_password(new)
    user.password_changed_at = utcnow()
    await revoke_user_sessions(session, user.id, except_id=keep)
    write_audit(
        session,
        action="password_change",
        entity_type="user",
        user_id=user.id,
        entity_id=user.id,
        client=client,
    )
    await session.commit()
