from typing import ClassVar

from pydantic import BaseModel, ConfigDict, model_validator


class Strict(BaseModel):
    """Базовая схема: лишние поля запрещены (защита от mass assignment)."""

    model_config = ConfigDict(extra="forbid")


class PatchBase(Strict):
    """Схема частичного обновления: явный null допустим только для nullable-полей."""

    nullable_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _no_nulls(self) -> "PatchBase":
        for name in self.model_fields_set:
            if getattr(self, name) is None and name not in self.nullable_fields:
                raise ValueError("null_not_allowed")
        return self
