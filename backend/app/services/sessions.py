"""Refresh-сессии: выпуск, ротация, отзыв."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.ids import new_id
from app.core.security import hash_token, new_refresh_token
from app.models import RefreshSession
from app.services.audit import ClientInfo


def utcnow() -> datetime:
    return datetime.now(UTC)


def issue_session(
    session: AsyncSession, user_id: uuid.UUID, family_id: uuid.UUID | None, client: ClientInfo
) -> str:
    """Создаёт сессию и возвращает сам refresh-токен (в БД попадает только SHA-256)."""
    raw = new_refresh_token()
    session.add(
        RefreshSession(
            user_id=user_id,
            token_hash=hash_token(raw),
            family_id=family_id or new_id(),
            user_agent=client.user_agent,
            ip=client.ip,
            expires_at=utcnow() + timedelta(days=get_settings().refresh_ttl_days),
        )
    )
    return raw


async def revoke_user_sessions(
    session: AsyncSession, user_id: uuid.UUID, except_id: uuid.UUID | None = None
) -> None:
    stmt = update(RefreshSession).where(
        RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None)
    )
    if except_id is not None:
        stmt = stmt.where(RefreshSession.id != except_id)
    await session.execute(stmt.values(revoked_at=utcnow()))


async def revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshSession)
        .where(RefreshSession.family_id == family_id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
