import uuid

from app.core.types import Phone, SafeText
from app.schemas.common import PatchBase, Strict


class LocationCreate(Strict):
    name: SafeText(100, 1)  # type: ignore[valid-type]
    address: SafeText(255, 1)  # type: ignore[valid-type]
    phone: Phone | None = None


class LocationUpdate(PatchBase):
    nullable_fields = frozenset({"phone"})

    name: SafeText(100, 1) | None = None  # type: ignore[valid-type]
    address: SafeText(255, 1) | None = None  # type: ignore[valid-type]
    phone: Phone | None = None
    is_active: bool | None = None


class LocationRead(Strict):
    id: uuid.UUID
    name: str
    address: str
    phone: str | None
    is_active: bool
