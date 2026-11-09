import uuid
from datetime import datetime
from typing import Any, Literal

from app.schemas.common import Strict

AuditAction = Literal[
    "create",
    "update",
    "delete",
    "archive",
    "restore",
    "status_change",
    "refund",
    "login",
    "login_failed",
    "logout",
    "token_reuse",
    "password_change",
    "export",
    "revoke_session",
]


class UserRef(Strict):
    id: uuid.UUID
    full_name: str


class AuditLocation(Strict):
    id: uuid.UUID
    name: str
    timezone: str


class AuditEntry(Strict):
    id: int
    created_at: datetime
    user: UserRef | None
    action: AuditAction
    entity_type: str
    entity_id: uuid.UUID | None
    entity_label: str | None
    entity_path: str | None
    location: AuditLocation | None
    changes: dict[str, Any] | None
    ip: str | None
    user_agent: str | None


class AuditPage(Strict):
    items: list[AuditEntry]
    total: int


class ActionOption(Strict):
    value: AuditAction
    label: str


class EntityTypeOption(Strict):
    value: str
    label: str


class AuditMeta(Strict):
    actions: list[ActionOption]
    entity_types: list[EntityTypeOption]


class SessionRead(Strict):
    id: uuid.UUID
    created_at: datetime
    last_active_at: datetime
    ip: str | None
    user_agent: str | None
    device: str
    is_current: bool
