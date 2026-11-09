"""Журнал действий: только добавление. Пароли и токены в changes не попадают."""

import ipaddress
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog

_CTRL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class ClientInfo:
    ip: str | None = None
    user_agent: str | None = None


def make_client_info(host: str | None, user_agent: str | None) -> ClientInfo:
    ip: str | None = None
    if host:
        try:
            ip = str(ipaddress.ip_address(host))
        except ValueError:
            ip = None
    ua = _CTRL.sub("", user_agent)[:255] if user_agent else None
    return ClientInfo(ip=ip, user_agent=ua)


def clean(value: str, limit: int = 64) -> str:
    return _CTRL.sub("", value)[:limit]


def diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    return {k: {"old": old.get(k), "new": v} for k, v in new.items() if old.get(k) != v}


def write_audit(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    user_id: uuid.UUID | None = None,
    entity_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    changes: dict[str, Any] | None = None,
    client: ClientInfo | None = None,
) -> None:
    client = client or ClientInfo()
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            location_id=location_id,
            changes=changes,
            ip=client.ip,
            user_agent=client.user_agent,
        )
    )
