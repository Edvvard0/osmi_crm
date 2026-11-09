import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import Director, SessionDep
from app.schemas.audit import AuditEntry, AuditMeta, AuditPage
from app.services import audit_read as svc

router = APIRouter(prefix="/audit-log", tags=["audit-log"])


@router.get("", response_model=AuditPage)
async def list_audit_log(
    _: Director,
    session: SessionDep,
    date_from: date | None = None,
    date_to: date | None = None,
    user_id: Annotated[str | None, Query(max_length=40)] = None,
    action: Annotated[str | None, Query(max_length=400)] = None,
    entity_type: Annotated[str | None, Query(max_length=800)] = None,
    entity_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditPage:
    return await svc.list_audit(
        session,
        date_from=date_from,
        date_to=date_to,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        location_id=location_id,
        limit=limit,
        offset=offset,
    )


@router.get("/meta", response_model=AuditMeta)
async def audit_meta(_: Director) -> AuditMeta:
    return svc.audit_meta()


@router.get("/{entry_id}", response_model=AuditEntry)
async def get_audit_entry(entry_id: int, _: Director, session: SessionDep) -> AuditEntry:
    return await svc.get_audit_entry(session, entry_id)
