from decimal import Decimal

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.types import VIN, Login, Money, Phone, PlateNumber, SafeText
from tests.security import payloads


class M(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: Phone | None = None
    plate: PlateNumber | None = None
    vin: VIN | None = None
    login: Login | None = None
    text: SafeText(200) | None = None  # type: ignore[valid-type]
    money: Money | None = None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("+7 (999) 123-45-67", "+79991234567"),
        ("89991234567", "+79991234567"),
        ("79991234567", "+79991234567"),
    ],
)
def test_phone_normalized(raw, expected):
    assert M(phone=raw).phone == expected


@pytest.mark.parametrize("raw", ["123", "+1 555 1234567", "abc", "+7999123456789"])
def test_phone_rejected(raw):
    with pytest.raises(ValidationError):
        M(phone=raw)


def test_plate_normalized_latin_to_cyrillic():
    assert M(plate="a 123 bc 77").plate == "А123ВС77"
    assert M(plate="К777КК199").plate == "К777КК199"


@pytest.mark.parametrize("raw", ["", "ABC", "Я123ЯЯ77", "А123ВС7"])
def test_plate_rejected(raw):
    with pytest.raises(ValidationError):
        M(plate=raw)


def test_vin():
    assert M(vin="xtA210930y2745992").vin == "XTA210930Y2745992"
    for bad in ["XTA21093OY2745992", "short", "I" * 17]:
        with pytest.raises(ValidationError):
            M(vin=bad)


def test_login():
    assert M(login=" Ivan.Petrov ").login == "ivan.petrov"
    for bad in ["ab", "a b", "иван", "x" * 33, "a;b"]:
        with pytest.raises(ValidationError):
            M(login=bad)


def test_money():
    assert M(money="10.50").money == Decimal("10.50")
    for bad in ["-1", "1.234", "1e30", "abc"]:
        with pytest.raises(ValidationError):
            M(money=bad)


def test_non_string_rejected():
    for field in ("phone", "plate", "vin", "login", "text"):
        with pytest.raises(ValidationError):
            M(**{field: {"$ne": 1}})
        with pytest.raises(ValidationError):
            M(**{field: 123})


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        M(unknown="x")


@pytest.mark.parametrize("payload", payloads.ALL)
@pytest.mark.parametrize("field", ["phone", "plate", "vin", "login", "text"])
def test_all_payloads_on_all_text_types(field, payload):
    try:
        out = getattr(M(**{field: payload}), field)
    except ValidationError:
        return
    assert "\x00" not in out and "<" not in out and ">" not in out
    assert len(out) <= 200 if field == "text" else True


@pytest.mark.parametrize("payload", payloads.MARKUP)
def test_markup_rejected_in_text(payload):
    with pytest.raises(ValidationError):
        M(text=payload)


def test_text_strips_control_chars():
    assert M(text="a\x00b\x1bc").text == "abc"
