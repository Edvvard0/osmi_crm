import uuid
from datetime import datetime

from pydantic import Field

from app.core.types import Login, SafeText
from app.models.enums import Role
from app.schemas.common import PatchBase, Strict

Password = Field(min_length=1, max_length=128)


class UserRead(Strict):
    id: uuid.UUID
    login: str
    full_name: str
    role: Role
    is_active: bool
    location_ids: list[uuid.UUID]
    created_at: datetime


class UserPage(Strict):
    items: list[UserRead]
    total: int


class UserCreate(Strict):
    login: Login
    full_name: SafeText(150, 1)  # type: ignore[valid-type]
    role: Role
    password: str = Password
    location_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


class UserUpdate(PatchBase):
    full_name: SafeText(150, 1) | None = None  # type: ignore[valid-type]
    role: Role | None = None
    location_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class ResetPassword(Strict):
    new_password: str = Password
