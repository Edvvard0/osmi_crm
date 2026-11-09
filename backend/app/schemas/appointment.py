import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from app.core.types import SafeText
from app.schemas.catalog import Department
from app.schemas.client import BlankToNone
from app.schemas.common import PatchBase, Strict

AppointmentStatus = Literal["scheduled", "confirmed", "arrived", "no_show", "cancelled"]
ServiceIds = Annotated[list[uuid.UUID], Field(max_length=50)]


class AppointmentCreate(BlankToNone, Strict):
    blank_fields = frozenset({"comment"})

    location_id: uuid.UUID
    client_id: uuid.UUID
    vehicle_id: uuid.UUID
    post_id: uuid.UUID | None = None
    department: Department
    start_at: AwareDatetime
    end_at: AwareDatetime
    service_ids: ServiceIds = []
    comment: SafeText(1000) | None = None  # type: ignore[valid-type]


class AppointmentUpdate(BlankToNone, PatchBase):
    blank_fields = frozenset({"comment"})
    nullable_fields = frozenset({"post_id", "comment"})

    post_id: uuid.UUID | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    department: Department | None = None
    service_ids: ServiceIds | None = None
    comment: SafeText(1000) | None = None  # type: ignore[valid-type]


class StatusChange(Strict):
    status: AppointmentStatus


class ServiceRef(Strict):
    id: uuid.UUID
    name: str


class ClientRef(Strict):
    id: uuid.UUID
    full_name: str
    phone: str


class VehicleRef(Strict):
    id: uuid.UUID
    make: str
    model: str
    plate_number: str | None


class AppointmentRead(Strict):
    id: uuid.UUID
    location_id: uuid.UUID
    client_id: uuid.UUID
    vehicle_id: uuid.UUID
    post_id: uuid.UUID | None
    department: Department
    start_at: datetime
    end_at: datetime
    status: AppointmentStatus
    comment: str | None
    service_ids: list[uuid.UUID]
    services: list[ServiceRef]
    client: ClientRef
    vehicle: VehicleRef
    work_order_id: uuid.UUID | None
    work_order_number: str | None = None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
