"""Сессии пользователя = «семьи» refresh-токенов (`family_id`): список, завершение, очистка."""

import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import hash_token
from app.models import RefreshSession, User
from app.schemas.audit import SessionRead
from app.services.audit import ClientInfo, write_audit
from app.services.sessions import utcnow
from app.services.settings import get_setting

# ---------- устройство из user_agent (простой разбор без внешних сервисов) ----------

_BROWSERS: list[tuple[str, str]] = [
    (r"\bEdgA?/|\bEdge/|\bEdgiOS/", "Edge"),
    (r"\bOPR/|\bOpera\b", "Opera"),
    (r"YaBrowser/", "Яндекс Браузер"),
    (r"SamsungBrowser/", "Samsung Internet"),
    (r"Firefox/|FxiOS/", "Firefox"),
    (r"Chrome/|CriOS/|Chromium/", "Chrome"),
    (r"Safari/", "Safari"),
]
_SYSTEMS: list[tuple[str, str]] = [
    (r"iPhone", "iPhone"),
    (r"iPad", "iPad"),
    (r"Android", "Android"),
    (r"Windows", "Windows"),
    (r"Mac OS X|Macintosh", "macOS"),
    (r"CrOS", "ChromeOS"),
    (r"Linux|X11", "Linux"),
]


def describe_device(user_agent: str | None) -> str:
    if not user_agent:
        return "Неизвестное устройство"
    browser = next((name for pat, name in _BROWSERS if re.search(pat, user_agent)), None)
    system = next((name for pat, name in _SYSTEMS if re.search(pat, user_agent)), None)
    parts = [p for p in (browser, system) if p]
    return " · ".join(parts) if parts else "Неизвестное устройство"


# ---------- текущая сессия ----------


async def current_family(
    session: AsyncSession, user_id: uuid.UUID, raw_token: str | None
) -> uuid.UUID | None:
    """Семья токена из cookie текущего запроса (только действующего и своего)."""
    if not raw_token:
        return None
    return await session.scalar(
        select(RefreshSession.family_id).where(
            RefreshSession.token_hash == hash_token(raw_token),
            RefreshSession.user_id == user_id,
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > utcnow(),
        )
    )


def _active_families(user_id: uuid.UUID) -> Select[Any]:
    return select(RefreshSession.family_id).where(
        RefreshSession.user_id == user_id,
        RefreshSession.revoked_at.is_(None),
        RefreshSession.expires_at > utcnow(),
    )


async def list_sessions(
    session: AsyncSession, user: User, raw_token: str | None
) -> list[SessionRead]:
    current = await current_family(session, user.id, raw_token)
    active = _active_families(user.id)
    spans = (
        await session.execute(
            select(
                RefreshSession.family_id,
                func.min(RefreshSession.created_at),
                func.max(RefreshSession.created_at),
            )
            .where(RefreshSession.user_id == user.id, RefreshSession.family_id.in_(active))
            .group_by(RefreshSession.family_id)
        )
    ).all()
    latest = {
        fam: (ip, ua)
        for fam, ip, ua in (
            await session.execute(
                select(RefreshSession.family_id, RefreshSession.ip, RefreshSession.user_agent)
                .where(RefreshSession.user_id == user.id, RefreshSession.family_id.in_(active))
                .ext(distinct_on(RefreshSession.family_id))
                .order_by(
                    RefreshSession.family_id,
                    RefreshSession.created_at.desc(),
                    RefreshSession.expires_at.desc(),
                )
            )
        ).all()
    }
    items = []
    for fam, first, last in spans:
        ip, ua = latest.get(fam, (None, None))
        items.append(
            SessionRead(
                id=fam,
                created_at=first,
                last_active_at=last,
                ip=str(ip) if ip is not None else None,
                user_agent=ua,
                device=describe_device(ua),
                is_current=fam == current,
            )
        )
    items.sort(key=lambda s: (not s.is_current, -s.last_active_at.timestamp()))
    return items


# ---------- завершение ----------


async def _revoke(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    family_id: uuid.UUID | None = None,
    except_family: uuid.UUID | None = None,
) -> int:
    """Отзывает действующие токены; возвращает число завершённых сессий (семей)."""
    stmt = update(RefreshSession).where(
        RefreshSession.user_id == user_id,
        RefreshSession.revoked_at.is_(None),
        RefreshSession.expires_at > utcnow(),
    )
    if family_id is not None:
        stmt = stmt.where(RefreshSession.family_id == family_id)
    if except_family is not None:
        stmt = stmt.where(RefreshSession.family_id != except_family)
    rows = await session.execute(
        stmt.values(revoked_at=utcnow()).returning(RefreshSession.family_id)
    )
    return len({r[0] for r in rows})


async def revoke_session(
    session: AsyncSession,
    user: User,
    family_id: uuid.UUID,
    raw_token: str | None,
    client: ClientInfo,
) -> None:
    exists = await session.scalar(
        select(RefreshSession.id)
        .where(RefreshSession.user_id == user.id, RefreshSession.family_id == family_id)
        .limit(1)
    )
    if exists is None:
        raise AppError(404, "not_found")
    if family_id == await current_family(session, user.id, raw_token):
        raise AppError(409, "invalid_state")
    # Идемпотентно: у уже завершённой сессии отзывать нечего и аудит не пишется.
    if await _revoke(session, user.id, family_id=family_id):
        write_audit(
            session,
            action="revoke_session",
            entity_type="session",
            user_id=user.id,
            entity_id=family_id,
            client=client,
        )
    await session.commit()


async def revoke_other_sessions(
    session: AsyncSession, user: User, raw_token: str | None, client: ClientInfo
) -> None:
    current = await current_family(session, user.id, raw_token)
    if current is None:
        raise AppError(401, "invalid_token")
    count = await _revoke(session, user.id, except_family=current)
    write_audit(
        session,
        action="revoke_session",
        entity_type="session",
        user_id=user.id,
        changes={"count": count},
        client=client,
    )
    await session.commit()


async def revoke_all_user_sessions(
    session: AsyncSession,
    actor: User,
    target_id: uuid.UUID,
    raw_token: str | None,
    client: ClientInfo,
) -> None:
    target = await session.get(User, target_id)
    if target is None:
        raise AppError(404, "not_found")
    keep: uuid.UUID | None = None
    if target.id == actor.id:
        # Своя текущая сессия сохраняется. Cookie refresh_token ходит только на /api/v1/auth,
        # поэтому без неё сохраняем самую свежую по активности сессию.
        keep = await current_family(session, actor.id, raw_token)
        if keep is None:
            keep = await session.scalar(
                select(RefreshSession.family_id)
                .where(
                    RefreshSession.user_id == actor.id,
                    RefreshSession.revoked_at.is_(None),
                    RefreshSession.expires_at > utcnow(),
                )
                .order_by(RefreshSession.created_at.desc())
                .limit(1)
            )
    count = await _revoke(session, target.id, except_family=keep)
    write_audit(
        session,
        action="revoke_session",
        entity_type="user",
        user_id=actor.id,
        entity_id=target.id,
        changes={"count": count},
        client=client,
    )
    await session.commit()


# ---------- очистка (задача воркера session_cleanup, 03:45 APP_TIMEZONE) ----------


async def session_cleanup(session: AsyncSession, now: datetime | None = None) -> int:
    """Удаляет refresh_sessions с `expires_at`/`revoked_at` старше `session_retention_days`."""
    days = int(await get_setting(session, "session_retention_days"))
    border = (now or utcnow()) - timedelta(days=days)
    result = await session.execute(
        delete(RefreshSession)
        .where(or_(RefreshSession.expires_at < border, RefreshSession.revoked_at < border))
        .returning(RefreshSession.id)
    )
    deleted = len(result.all())
    await session.commit()
    return deleted
