"""Ограниченные типы для всех входных полей. Белые списки вместо чёрных."""

import re
from decimal import Decimal
from typing import Annotated, Any

from pydantic import AfterValidator, BeforeValidator, Field, StringConstraints

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PHONE = re.compile(r"^\+7\d{10}$")
_PLATE = re.compile(r"^[АВЕКМНОРСТУХ]\d{3}[АВЕКМНОРСТУХ]{2}\d{2,3}$")
_VIN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
_LOGIN = re.compile(r"^[a-z0-9._-]{3,32}$")
_LAT2CYR = str.maketrans("ABEKMHOPCTYX", "АВЕКМНОРСТУХ")


def _must_be_str(v: Any) -> str:
    if not isinstance(v, str):
        raise ValueError("not_a_string")
    return v


def _phone(v: str) -> str:
    digits = re.sub(r"[\s()\-]", "", v)
    if digits.startswith("8") and len(digits) == 11:
        digits = "+7" + digits[1:]
    elif digits.startswith("7") and len(digits) == 11:
        digits = "+" + digits
    if not _PHONE.fullmatch(digits):
        raise ValueError("invalid_phone")
    return digits


def _plate(v: str) -> str:
    s = re.sub(r"\s", "", v).upper().translate(_LAT2CYR)
    if not _PLATE.fullmatch(s):
        raise ValueError("invalid_plate")
    return s


def _vin(v: str) -> str:
    s = v.strip().upper()
    if not _VIN.fullmatch(s):
        raise ValueError("invalid_vin")
    return s


def _login(v: str) -> str:
    s = v.strip().lower()
    if not _LOGIN.fullmatch(s):
        raise ValueError("invalid_login")
    return s


def _clean_text(v: str) -> str:
    s = _CTRL.sub("", v).strip()
    # HTML-разметка в свободном тексте запрещена; вывод на фронте дополнительно экранируется React.
    if "<" in s or ">" in s:
        raise ValueError("markup_not_allowed")
    return s


def SafeText(max_len: int, min_len: int = 0) -> Any:  # noqa: N802
    return Annotated[
        str,
        BeforeValidator(_must_be_str),
        AfterValidator(_clean_text),
        StringConstraints(min_length=min_len, max_length=max_len),
    ]


Phone = Annotated[str, BeforeValidator(_must_be_str), AfterValidator(_phone)]
PlateNumber = Annotated[str, BeforeValidator(_must_be_str), AfterValidator(_plate)]
VIN = Annotated[str, BeforeValidator(_must_be_str), AfterValidator(_vin)]
Login = Annotated[str, BeforeValidator(_must_be_str), AfterValidator(_login)]
Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
