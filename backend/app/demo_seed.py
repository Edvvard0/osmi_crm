"""Демо-данные для пустой CRM: всё создаётся только через HTTP API (как в работе пользователей).

Запуск: ``python -m app.demo_seed``. Переменные окружения:

- ``DEMO_API_URL`` — адрес API, по умолчанию ``http://127.0.0.1:8000/api/v1``;
- ``SEED_DIRECTOR_PASSWORD`` — пароль руководителя ``director`` (создан ``python -m app.cli seed``);
- ``DEMO_MANAGER_PASSWORD`` — пароль демо-менеджеров ``manager1`` и ``manager2``;
- ``DEMO_MECHANIC_PASSWORD`` — пароль демо-механиков ``mechanic1`` … ``mechanic4``.

Повторный запуск безопасен: если ``manager1`` уже есть, скрипт ничего не делает (код выхода 0).
Каждый пользователь входит один раз (лимит входов — 10 в минуту с одного IP), на 429 — ожидание
и повтор. Пароли нигде не печатаются.
"""

import os
import re
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.core.security import check_password_policy

DEFAULT_API_URL = "http://127.0.0.1:8000/api/v1"
DIRECTOR_LOGIN = "director"
MARKER_LOGIN = "manager1"  # по нему определяется, что демо-данные уже загружены

Json = dict[str, Any]

_VIN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
_RETRY_429_ATTEMPTS = 15
_RETRY_429_DELAY = 7.0  # секунд; окно лимитера входов — скользящие 60 секунд


class SeedError(RuntimeError):
    """Понятная ошибка для пользователя: печатается без трассировки."""


# ---------------- справочные данные ----------------

MANAGERS = [
    # логин, ФИО, индекс точки (0 — основная, 1 — вторая)
    ("manager1", "Григорьева Ирина Валерьевна", 0),
    ("manager2", "Захаров Роман Евгеньевич", 1),
]
MECHANICS = [
    ("mechanic1", "Белов Николай Иванович", 0),
    ("mechanic2", "Тарасов Владимир Олегович", 0),
    ("mechanic3", "Гусев Константин Андреевич", 1),
    ("mechanic4", "Комаров Артур Ринатович", 1),
]

SECOND_LOCATION = {
    "name": "Точка «Север»",
    "address": "г. Москва, Дмитровское ш., д. 98, стр. 2",
    "phone": "+74951234568",
}

POSTS = [
    # индекс точки, название, тип, отдел
    (0, "Подъёмник 1", "lift", "service"),
    (0, "Подъёмник 2", "lift", "service"),
    (0, "Пост диагностики", "diagnostics", "service"),
    (0, "Бокс детейлинга", "detailing_box", "detailing"),
    (0, "Мойка", "wash", "detailing"),
    (1, "Подъёмник 1", "lift", "service"),
    (1, "Бокс детейлинга", "detailing_box", "detailing"),
]

CATEGORIES = [
    # ключ, название, отдел
    ("to", "Техническое обслуживание", "service"),
    ("diag", "Диагностика", "service"),
    ("susp", "Ремонт ходовой части", "service"),
    ("tire", "Шиномонтаж", "service"),
    ("wash", "Мойка", "detailing"),
    ("polish", "Полировка и защита кузова", "detailing"),
    ("clean", "Химчистка", "detailing"),
]

SERVICES = [
    # категория, код, название, единица, цена, нормочасы, длительность (мин)
    ("to", "TO-OIL", "Замена масла и масляного фильтра", "pcs", "1500.00", "0.50", 30),
    ("to", "TO-15", "ТО-15 000 км (регламентное)", "pcs", "6500.00", "2.00", 120),
    ("to", "TO-PLUGS", "Замена свечей зажигания", "pcs", "1200.00", "0.60", 40),
    ("diag", "DIAG-COMP", "Компьютерная диагностика", "pcs", "1800.00", "0.50", 30),
    ("diag", "DIAG-SUSP", "Диагностика подвески", "pcs", "1200.00", "0.50", 30),
    ("susp", "SUSP-PADS", "Замена тормозных колодок (ось)", "pcs", "2200.00", "1.00", 60),
    ("susp", "SUSP-SHOCK", "Замена амортизатора", "pcs", "2800.00", "1.20", 75),
    ("susp", "SUSP-ALIGN", "Развал-схождение", "pcs", "2500.00", "1.00", 60),
    ("tire", "TIRE-SET", "Сезонная переобувка (4 колеса)", "set", "3200.00", "1.00", 60),
    ("tire", "TIRE-BAL", "Балансировка колеса", "pcs", "450.00", "0.20", 15),
    ("wash", "WASH-STD", "Комплексная мойка", "pcs", "1200.00", "0.50", 45),
    ("wash", "WASH-ENG", "Мойка двигателя", "pcs", "1500.00", "0.50", 30),
    ("polish", "POL-BODY", "Полировка кузова", "pcs", "18000.00", "8.00", 480),
    ("polish", "CER-COAT", "Керамическое покрытие кузова", "pcs", "35000.00", "10.00", 600),
    ("clean", "CLEAN-INT", "Химчистка салона", "pcs", "9500.00", "5.00", 300),
]
# Цены второй точки отличаются от базовых.
NORTH_PRICES = {"TO-OIL": "1400.00", "TIRE-SET": "3000.00", "WASH-STD": "1100.00"}

PARTS = [
    # ключ, артикул, название, бренд, единица, отдел, цена продажи, закупка
    ("oil", "OIL-5W30-4L", "Масло моторное 5W-30, 4 л", "Shell", "pcs", "service", "3900.00",
     "2900.00"),
    ("oil_filter", "FLT-OIL-01", "Фильтр масляный", "MANN", "pcs", "service", "650.00", "380.00"),
    ("air_filter", "FLT-AIR-01", "Фильтр воздушный", "MANN", "pcs", "service", "900.00", "540.00"),
    ("pads", "BRK-PAD-F", "Колодки тормозные передние", "Brembo", "set", "service", "3600.00",
     "2300.00"),
    ("shock", "SHK-FR-01", "Амортизатор передний", "KYB", "pcs", "service", "6200.00", "4100.00"),
    ("plugs", "SPK-PLUG-01", "Свеча зажигания", "NGK", "pcs", "service", "750.00", "420.00"),
    ("antifreeze", "AF-G12-5L", "Антифриз G12, 5 л", "Felix", "pcs", "service", "1600.00",
     "1050.00"),
    ("shampoo", "WSH-SHAMPOO", "Шампунь для бесконтактной мойки", "Koch Chemie", "l", "detailing",
     "450.00", "260.00"),
    ("paste", "POL-PASTE-01", "Полировальная паста", "3M", "pcs", "detailing", "2400.00",
     "1500.00"),
    ("ceramic", "CER-50ML", "Керамический состав, 50 мл", "Gyeon", "pcs", "detailing", "12000.00",
     "7800.00"),
]  # fmt: skip

# Приход на склад: ключ запчасти → количество (основная точка, вторая точка).
RECEIPTS = {
    "oil": ("20.000", "10.000"),
    "oil_filter": ("20.000", "10.000"),
    "air_filter": ("15.000", "6.000"),
    "pads": ("10.000", "6.000"),
    "shock": ("6.000", None),
    "plugs": ("4.000", None),
    "antifreeze": ("10.000", "4.000"),
    "shampoo": ("20.000", "10.000"),
    "paste": ("8.000", "4.000"),
    "ceramic": ("5.000", None),
}
MIN_QUANTITIES = {"oil": "6.000", "plugs": "8.000", "pads": "4.000"}

# ФИО, телефон, источник, скидка, компания, автомобили (марка, модель, год, номер, цвет, пробег).
CLIENTS: list[tuple[str, str, str, str, str | None, list[tuple[str, str, int, str, str, int]]]] = [
    ("Иванов Сергей Петрович", "+79161234501", "walk_in", "0", None,
     [("Lada", "Vesta", 2020, "А123ВС777", "Белый", 45200)]),
    ("Смирнова Анна Викторовна", "+79161234502", "online", "0", None,
     [("Kia", "Rio", 2019, "В456ЕК750", "Серебристый", 67800)]),
    ("Кузнецов Дмитрий Алексеевич", "+79161234503", "referral", "0", None,
     [("Toyota", "Camry", 2021, "Е789КМ777", "Чёрный", 38900)]),
    ("Попова Елена Игоревна", "+79161234504", "ads", "0", None,
     [("Hyundai", "Solaris", 2018, "К012МН199", "Красный", 98400)]),
    ("Васильев Андрей Николаевич", "+79161234505", "repeat", "5", None,
     [("Volkswagen", "Polo", 2017, "М345НО750", "Синий", 112300),
      ("Skoda", "Kodiaq", 2022, "Н678ОР777", "Серый", 21500)]),
    ("Петрова Ольга Сергеевна", "+79161234506", "online", "0", None,
     [("Renault", "Duster", 2019, "О901РС190", "Оранжевый", 76300)]),
    ("Соколов Максим Владимирович", "+79161234507", "referral", "0", None,
     [("BMW", "X5", 2020, "Р234СТ777", "Чёрный", 54100)]),
    ("Михайлова Татьяна Андреевна", "+79161234508", "walk_in", "0", None,
     [("Mazda", "CX-5", 2021, "С567ТУ750", "Белый", 33700)]),
    ("Новиков Алексей Дмитриевич", "+79161234509", "ads", "0", None,
     [("Nissan", "Qashqai", 2018, "Т890УХ199", "Серый", 88600)]),
    ("Фёдорова Наталья Олеговна", "+79161234510", "online", "0", None,
     [("Kia", "Sportage", 2023, "У123ХА777", "Зелёный", 12400)]),
    ("Морозов Игорь Валентинович", "+79161234511", "walk_in", "0", None,
     [("Lada", "Granta", 2016, "Х456АВ750", "Белый", 143200)]),
    ("Волкова Мария Александровна", "+79161234512", "repeat", "10", None,
     [("Mercedes-Benz", "E 200", 2019, "А789ВЕ777", "Чёрный", 61800)]),
    ("Алексеев Павел Юрьевич", "+79161234513", "referral", "0", None,
     [("Chery", "Tiggo 7 Pro", 2022, "В012ЕК199", "Серый", 27300)]),
    ("Лебедева Светлана Михайловна", "+79161234514", "ads", "0", None,
     [("Geely", "Coolray", 2023, "Е345КМ750", "Синий", 15900)]),
    ("Орлов Виктор Степанович", "+79161234515", "referral", "5", "ООО «ТрансЛогистик»",
     [("Ford", "Transit", 2019, "К678МН777", "Белый", 184500),
      ("Ford", "Transit", 2020, "М901НО777", "Белый", 156300)]),
]  # fmt: skip

# Начало VIN (код изготовителя) по марке.
WMI = {
    "Lada": "XTA", "Kia": "Z94", "Toyota": "JTN", "Hyundai": "Z94", "Volkswagen": "XW8",
    "Skoda": "TMB", "Renault": "X7L", "BMW": "WBA", "Mazda": "JMZ", "Nissan": "SJN",
    "Mercedes-Benz": "WDD", "Chery": "LVV", "Geely": "L6T", "Ford": "WF0",
}  # fmt: skip


def _vin(make: str, year: int, serial: int) -> str:
    vin = f"{WMI[make]}XB{year % 100:02d}K{serial:09d}"
    if not _VIN.fullmatch(vin):  # защита от опечаток в справочнике
        raise SeedError(f"Некорректный VIN в демо-данных: {vin}")
    return vin


# ---------------- клиент API ----------------


def _error_text(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error", {})
    except ValueError:
        return resp.text[:300]
    parts = [str(err.get("code") or ""), str(err.get("message") or "")]
    if err.get("fields"):
        parts.append(f"поля: {err['fields']}")
    if err.get("details"):
        parts.append(f"детали: {err['details']}")
    return "; ".join(p for p in parts if p)


class Api:
    """Тонкая обёртка над httpx: токены по логинам, повтор на 429, понятные ошибки."""

    def __init__(self, base_url: str) -> None:
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=60.0)
        self.tokens: dict[str, str] = {}
        self.logins = 0

    def close(self) -> None:
        self.http.close()

    def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        for _ in range(_RETRY_429_ATTEMPTS):
            try:
                resp = self.http.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                raise SeedError(f"API недоступно ({self.http.base_url}): {exc}") from exc
            if resp.status_code != 429:
                return resp
            print(f"  … лимит запросов ({method} {path}), ждём {_RETRY_429_DELAY:.0f} с")
            time.sleep(_RETRY_429_DELAY)
        raise SeedError(f"{method} {path}: лимит запросов не снимается")

    def login(self, login: str, password: str) -> None:
        if login in self.tokens:
            return
        resp = self._send("POST", "/auth/login", json={"login": login, "password": password})
        if resp.status_code != 200:
            raise SeedError(f"Вход «{login}» не удался ({resp.status_code}): {_error_text(resp)}")
        self.tokens[login] = resp.json()["access_token"]
        self.logins += 1

    def call(
        self,
        who: str,
        method: str,
        path: str,
        body: Json | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        resp = self._send(
            method,
            path,
            json=body,
            params=params,
            headers={"Authorization": f"Bearer {self.tokens[who]}"},
        )
        if resp.status_code >= 400:
            raise SeedError(f"{method} {path} от «{who}» → {resp.status_code}: {_error_text(resp)}")
        return resp.json() if resp.content else None

    def get(self, who: str, path: str, **params: str) -> Any:
        return self.call(who, "GET", path, params=params or None)

    def post(self, who: str, path: str, body: Json | None = None) -> Any:
        return self.call(who, "POST", path, body if body is not None else {})


# ---------------- сценарий ----------------


@dataclass
class Passwords:
    director: str
    manager: str
    mechanic: str


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SeedError(f"Не задана переменная окружения {name}")
    return value


def read_passwords() -> Passwords:
    pw = Passwords(
        director=_require_env("SEED_DIRECTOR_PASSWORD"),
        manager=_require_env("DEMO_MANAGER_PASSWORD"),
        mechanic=_require_env("DEMO_MECHANIC_PASSWORD"),
    )
    checks = [(pw.manager, login, "DEMO_MANAGER_PASSWORD") for login, _, _ in MANAGERS]
    checks += [(pw.mechanic, login, "DEMO_MECHANIC_PASSWORD") for login, _, _ in MECHANICS]
    for password, login, var in checks:
        problem = check_password_policy(password, login)
        if problem:
            raise SeedError(
                f"{var} не проходит политику паролей ({problem}): нужно не короче 10 символов, "
                "не равен логину, не из списка частых и не из одного повторяющегося символа"
            )
    return pw


class DemoSeed:
    def __init__(self, api: Api, pw: Passwords) -> None:
        self.api = api
        self.pw = pw
        self.stats: Counter[str] = Counter()
        self.locations: list[Json] = []
        self.users: dict[str, Json] = {}
        self.posts: dict[tuple[int, str], str] = {}
        self.services: dict[str, str] = {}
        self.parts: dict[str, str] = {}
        self.clients: list[Json] = []
        self.vehicles: list[list[Json]] = []
        self.orders: dict[str, Json] = {}
        self.tz = ZoneInfo("Europe/Moscow")
        self.today = date.today()

    # ---------- общее ----------

    def uid(self, login: str) -> str:
        return str(self.users[login]["id"])

    def loc(self, index: int) -> str:
        return str(self.locations[index]["id"])

    def at(self, day_offset: int, hhmm: str) -> datetime:
        hour, minute = (int(x) for x in hhmm.split(":"))
        day = self.today + timedelta(days=day_offset)
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=self.tz)

    # ---------- проверка и вход ----------

    def already_loaded(self) -> bool:
        self.api.login(DIRECTOR_LOGIN, self.pw.director)
        page = self.api.get(DIRECTOR_LOGIN, "/users", search=MARKER_LOGIN)
        return any(u["login"] == MARKER_LOGIN for u in page["items"])

    # ---------- точки и сотрудники ----------

    def setup_locations(self) -> None:
        existing: list[Json] = self.api.get(DIRECTOR_LOGIN, "/locations")
        if not existing:
            raise SeedError("Нет ни одной точки: сначала выполните `python -m app.cli seed`")
        main = next((x for x in existing if x.get("code") == "MAIN"), existing[0])
        second = next((x for x in existing if x["name"] == SECOND_LOCATION["name"]), None)
        if second is None:
            second = self.api.post(DIRECTOR_LOGIN, "/locations", dict(SECOND_LOCATION))
            self.stats["точек"] += 1
        self.locations = [main, second]
        self.tz = ZoneInfo(main["timezone"])
        self.today = datetime.now(self.tz).date()

    def setup_users(self) -> None:
        # manager1 — признак загруженных данных, поэтому создаётся последним среди сотрудников.
        people = [(*m, "mechanic") for m in MECHANICS] + [(*m, "manager") for m in MANAGERS[::-1]]
        for login, full_name, loc_index, role in people:
            password = self.pw.manager if role == "manager" else self.pw.mechanic
            self.users[login] = self.api.post(
                DIRECTOR_LOGIN,
                "/users",
                {
                    "login": login,
                    "full_name": full_name,
                    "role": role,
                    "password": password,
                    "location_ids": [self.loc(loc_index)],
                },
            )
            self.stats["сотрудников"] += 1
        # Каждый входит ровно один раз; дальше токены переиспользуются.
        for login, _, _ in MANAGERS:
            self.api.login(login, self.pw.manager)
        for login, _, _ in MECHANICS:
            self.api.login(login, self.pw.mechanic)

    # ---------- каталог и склад ----------

    def setup_catalog(self) -> None:
        d = DIRECTOR_LOGIN
        for loc_index, name, post_type, department in POSTS:
            post = self.api.post(
                d,
                f"/locations/{self.loc(loc_index)}/posts",
                {"name": name, "post_type": post_type, "department": department},
            )
            self.posts[(loc_index, name)] = post["id"]
            self.stats["постов"] += 1
        categories: dict[str, str] = {}
        for order, (key, name, department) in enumerate(CATEGORIES):
            cat = self.api.post(
                d,
                "/service-categories",
                {"name": name, "department": department, "sort_order": order * 10},
            )
            categories[key] = cat["id"]
            self.stats["категорий услуг"] += 1
        for cat_key, code, name, unit, price, hours, minutes in SERVICES:
            svc = self.api.post(
                d,
                "/services",
                {
                    "category_id": categories[cat_key],
                    "code": code,
                    "name": name,
                    "unit": unit,
                    "base_price": price,
                    "norm_hours": hours,
                    "duration_minutes": minutes,
                },
            )
            self.services[code] = svc["id"]
            self.stats["услуг"] += 1
        for code, price in NORTH_PRICES.items():
            self.api.call(
                d, "PUT", f"/services/{self.services[code]}/prices/{self.loc(1)}", {"price": price}
            )
        for key, sku, name, brand, unit, department, price, _ in PARTS:
            part = self.api.post(
                d,
                "/parts",
                {
                    "sku": sku,
                    "name": name,
                    "brand": brand,
                    "unit": unit,
                    "department": department,
                    "sale_price": price,
                },
            )
            self.parts[key] = part["id"]
            self.stats["запчастей в каталоге"] += 1

    def setup_stock(self) -> None:
        costs = {p[0]: p[7] for p in PARTS}
        for loc_index, supplier, doc in (
            (0, "ООО «АвтоДеталь»", "УТ-1024"),
            (1, "ООО «Запчасти Север»", "СВ-0312"),
        ):
            items = [
                {"part_id": self.parts[key], "quantity": qty[loc_index], "unit_cost": costs[key]}
                for key, qty in RECEIPTS.items()
                if qty[loc_index] is not None
            ]
            self.api.post(
                DIRECTOR_LOGIN,
                "/stock/receipts",
                {
                    "location_id": self.loc(loc_index),
                    "supplier": supplier,
                    "document_number": doc,
                    "items": items,
                },
            )
            self.stats["приходов на склад"] += 1
        for key, minimum in MIN_QUANTITIES.items():
            self.api.call(
                DIRECTOR_LOGIN,
                "PATCH",
                f"/stock/{self.parts[key]}",
                {"min_quantity": minimum},
                params={"location_id": self.loc(0)},
            )
        self.api.post(
            "manager1",
            "/stock/write-offs",
            {
                "location_id": self.loc(0),
                "reason": "Брак: повреждён корпус фильтра при вскрытии упаковки",
                "items": [{"part_id": self.parts["air_filter"], "quantity": "1.000"}],
            },
        )
        self.stats["списаний"] += 1

    # ---------- клиенты, авто, записи ----------

    def setup_clients(self) -> None:
        serial = 100_000
        for full_name, phone, source, discount, company, cars in CLIENTS:
            body: Json = {
                "client_type": "company" if company else "person",
                "full_name": full_name,
                "phone": phone,
                "source": source,
                "discount_percent": discount,
            }
            if company:
                body["company_name"] = company
                body["notes"] = "Корпоративный клиент, оплата по счёту"
            client = self.api.post("manager1", "/clients", body)
            self.clients.append(client)
            self.stats["клиентов"] += 1
            vehicles = []
            for make, model, year, plate, color, mileage in cars:
                serial += 7_919
                vehicles.append(
                    self.api.post(
                        "manager1",
                        f"/clients/{client['id']}/vehicles",
                        {
                            "make": make,
                            "model": model,
                            "year": year,
                            "vin": _vin(make, year, serial),
                            "plate_number": plate,
                            "color": color,
                            "mileage": mileage,
                        },
                    )
                )
                self.stats["автомобилей"] += 1
            self.vehicles.append(vehicles)

    def appointment(
        self,
        who: str,
        loc_index: int,
        client: int,
        post: str,
        department: str,
        day: int,
        start: str,
        end: str,
        services: list[str],
        comment: str | None = None,
        status: str | None = None,
        car: int = 0,
    ) -> Json:
        body: Json = {
            "location_id": self.loc(loc_index),
            "client_id": self.clients[client]["id"],
            "vehicle_id": self.vehicles[client][car]["id"],
            "post_id": self.posts[(loc_index, post)],
            "department": department,
            "start_at": self.at(day, start).isoformat(),
            "end_at": self.at(day, end).isoformat(),
            "service_ids": [self.services[c] for c in services],
        }
        if comment:
            body["comment"] = comment
        appt: Json = self.api.post(who, "/appointments", body)
        if status:
            appt = self.api.post(who, f"/appointments/{appt['id']}/status", {"status": status})
        self.stats["записей"] += 1
        return appt

    def setup_appointments(self) -> dict[str, Json]:
        m1, m2 = "manager1", "manager2"
        appts = {
            "qashqai_today": self.appointment(
                m1, 0, 8, "Подъёмник 1", "service", 0, "10:00", "12:00", ["TO-15"],
                "Плановое ТО, клиент ждёт в зоне отдыха", "confirmed",
            ),
        }  # fmt: skip
        self.appointment(m1, 0, 1, "Подъёмник 2", "service", 0, "16:00", "17:00", ["TO-OIL"],
                         "Позвонить за час до визита", "confirmed")  # fmt: skip
        self.appointment(m1, 0, 9, "Бокс детейлинга", "detailing", 0, "13:00", "15:00",
                         ["WASH-STD", "WASH-ENG"])  # fmt: skip
        self.appointment(m1, 0, 10, "Подъёмник 1", "service", 1, "09:00", "11:00", ["TO-15"],
                         status="confirmed")  # fmt: skip
        self.appointment(m1, 0, 3, "Пост диагностики", "service", 1, "11:00", "12:00",
                         ["DIAG-SUSP"], "Стук спереди справа на неровностях")  # fmt: skip
        self.appointment(m1, 0, 7, "Бокс детейлинга", "detailing", 1, "10:00", "18:00",
                         ["POL-BODY"], "Перед продажей автомобиля")  # fmt: skip
        self.appointment(m1, 0, 0, "Подъёмник 2", "service", 2, "12:00", "13:00", ["TIRE-SET"],
                         "Хранение шин у клиента")  # fmt: skip
        self.appointment(m1, 0, 6, "Подъёмник 1", "service", 2, "15:00", "16:00", ["DIAG-COMP"],
                         "Клиент перенёс визит", "cancelled")  # fmt: skip
        self.appointment(m1, 0, 5, "Подъёмник 1", "service", -1, "17:00", "18:00", ["TO-OIL"],
                         status="no_show")  # fmt: skip
        self.appointment(m2, 1, 12, "Подъёмник 1", "service", 3, "09:30", "10:30", ["TO-OIL"],
                         status="confirmed")  # fmt: skip
        self.appointment(m2, 1, 13, "Бокс детейлинга", "detailing", 0, "11:00", "12:00",
                         ["WASH-STD"], "Мойка перед поездкой", "confirmed")  # fmt: skip
        return appts

    # ---------- заказ-наряды ----------

    def order(self, who: str, order_id: str) -> Json:
        result: Json = self.api.get(who, f"/work-orders/{order_id}")
        return result

    def create_order(
        self,
        key: str,
        who: str,
        loc_index: int,
        client: int,
        works: list[tuple[str, str | None] | tuple[str, str | None, str]],
        complaint: str,
        car: int = 0,
        appointment_id: str | None = None,
        planned_hours: int | None = 6,
    ) -> Json:
        vehicle = self.vehicles[client][car]
        items: list[Json] = []
        for work in works:
            item: Json = {"service_id": self.services[work[0]]}
            if work[1]:
                item["mechanic_id"] = self.uid(work[1])
            if len(work) > 2:
                item["quantity"] = work[2]
            items.append(item)
        body: Json = {
            "location_id": self.loc(loc_index),
            "client_id": self.clients[client]["id"],
            "vehicle_id": vehicle["id"],
            "manager_id": self.uid(who),
            "mileage_in": vehicle["mileage"],
            "complaint": complaint,
            "items": items,
        }
        if appointment_id:
            body["appointment_id"] = appointment_id
        if planned_hours is not None:
            ready_at = datetime.now(self.tz).replace(minute=0, second=0, microsecond=0)
            body["planned_ready_at"] = (ready_at + timedelta(hours=planned_hours)).isoformat()
        created: Json = self.api.post(who, "/work-orders", body)
        self.orders[key] = created
        self.stats["заказ-нарядов"] += 1
        return created

    def status(self, who: str, order_id: str, status: str, **extra: str) -> Json:
        version = self.order(who, order_id)["version"]
        result: Json = self.api.post(
            who,
            f"/work-orders/{order_id}/status",
            {"version": version, "status": status, **extra},
        )
        return result

    def add_part(self, who: str, order_id: str, part: str, quantity: str) -> None:
        version = self.order(who, order_id)["version"]
        self.api.post(
            who,
            f"/work-orders/{order_id}/parts",
            {"version": version, "part_id": self.parts[part], "quantity": quantity},
        )

    def comment(self, who: str, order_id: str, text: str, internal: bool = True) -> None:
        self.api.post(
            who, f"/work-orders/{order_id}/comments", {"text": text, "is_internal": internal}
        )
        self.stats["комментариев"] += 1

    def item_ids(self, order: Json, mechanic: str | None = None) -> list[str]:
        return [
            str(i["id"])
            for i in order["items"]
            if mechanic is None or (i["mechanic"] and i["mechanic"]["id"] == self.uid(mechanic))
        ]

    def work(self, mechanic: str, item_id: str, comment: str | None = None) -> Json:
        """Механик берёт работу и завершает её (таймер в своём кабинете)."""
        self.api.post(mechanic, f"/mechanic/tasks/{item_id}/start", {})
        body: Json = {"comment": comment} if comment else {}
        result: Json = self.api.post(mechanic, f"/mechanic/tasks/{item_id}/finish", body)
        self.stats["работ выполнено механиками"] += 1
        return result

    def do_all(self, who: str, order_id: str, notes: dict[str, str] | None = None) -> None:
        """Заказ передаётся в работу, механики по очереди выполняют свои работы."""
        order = self.order(who, order_id)
        if order["status"] == "new":
            order = self.status(who, order_id, "in_progress")
        for item in order["items"]:
            mech = item["mechanic"]
            login = next(k for k, v in self.users.items() if v["id"] == mech["id"])
            self.work(login, str(item["id"]), (notes or {}).get(item["name"]))

    def pay(self, who: str, order_id: str, method: str, amount: str | None = None) -> None:
        due = amount or self.order(who, order_id)["balance_due"]
        self.api.post(
            who,
            f"/work-orders/{order_id}/payments",
            {
                "amount": due,
                "method": method,
                "client_request_id": str(uuid.uuid4()),
            },
        )
        self.stats["оплат"] += 1

    def finish_order(
        self, who: str, order_id: str, payments: list[tuple[str, str | None]], close: bool = True
    ) -> None:
        """Работы выполнены → контроль качества (автоматически) → готов → оплата → закрыт."""
        self.do_all(who, order_id)
        if self.order(who, order_id)["status"] != "quality_check":
            raise SeedError(f"Заказ {order_id} не перешёл на контроль качества")
        self.status(who, order_id, "ready", comment="Проверено мастером-приёмщиком")
        for method, amount in payments:
            self.pay(who, order_id, method, amount)
        if close:
            self.status(who, order_id, "closed")

    def setup_orders(self, appts: dict[str, Json]) -> None:
        m1, m2 = "manager1", "manager2"

        # --- Основная точка: закрытые и оплаченные ---
        o = self.create_order("closed_vesta", m1, 0, 0, [("TO-OIL", "mechanic1")],
                              "Плановая замена масла")  # fmt: skip
        self.add_part(m1, o["id"], "oil", "1.000")
        self.add_part(m1, o["id"], "oil_filter", "1.000")
        self.finish_order(m1, o["id"], [("cash", None)])
        self.api.post(
            m1,
            f"/vehicles/{self.vehicles[0][0]['id']}/recommendations",
            {
                "text": "Через 5 000 км заменить свечи зажигания",
                "priority": "low",
                "work_order_id": o["id"],
            },
        )
        self.stats["рекомендаций"] += 1

        o = self.create_order("closed_rio", m1, 0, 1,
                              [("DIAG-SUSP", "mechanic2"), ("SUSP-PADS", "mechanic2")],
                              "Скрип при торможении")  # fmt: skip
        self.add_part(m1, o["id"], "pads", "1.000")
        self.finish_order(m1, o["id"], [("card", None)])

        o = self.create_order("closed_transit", m1, 0, 14,
                              [("TIRE-SET", "mechanic1"), ("TIRE-BAL", "mechanic1", "4.00")],
                              "Сезонная замена шин на зимние")  # fmt: skip
        self.finish_order(m1, o["id"], [("transfer", None)])

        o = self.create_order("closed_mercedes", m1, 0, 11,
                              [("WASH-STD", "mechanic2"), ("CLEAN-INT", "mechanic2")],
                              "Химчистка салона после зимы")  # fmt: skip
        self.add_part(m1, o["id"], "shampoo", "2.000")
        total = Decimal(self.order(m1, o["id"])["balance_due"])
        half = (total / 2).quantize(Decimal("0.01"))
        self.finish_order(m1, o["id"], [("cash", f"{half:.2f}"), ("card", None)])

        # --- Готов к выдаче, частично оплачен ---
        o = self.create_order("ready_camry", m1, 0, 2, [("TO-15", "mechanic1")],
                              "ТО-15, проверить тормозную жидкость")  # fmt: skip
        self.add_part(m1, o["id"], "oil", "1.000")
        self.add_part(m1, o["id"], "oil_filter", "1.000")
        self.add_part(m1, o["id"], "air_filter", "1.000")
        self.pay(m1, o["id"], "cash", "5000.00")
        self.finish_order(m1, o["id"], [], close=False)

        # --- Контроль качества (автопереход после последней работы) ---
        o = self.create_order("qc_solaris", m1, 0, 3, [("SUSP-ALIGN", "mechanic2")],
                              "Уводит вправо")  # fmt: skip
        self.do_all(m1, o["id"])

        # --- Ожидает согласования: диагностика выполнена, нужен ответ клиента ---
        o = self.create_order("approval_mazda", m1, 0, 7, [("DIAG-COMP", "mechanic1")],
                              "Горит Check Engine")  # fmt: skip
        self.status(m1, o["id"], "diagnostics")
        item = self.item_ids(o)[0]
        self.work("mechanic1", item, "Ошибка P0301: пропуски воспламенения в 1-м цилиндре")
        self.api.post(
            "mechanic1",
            "/mechanic/recommendations",
            {
                "item_id": item,
                "text": "Заменить свечи зажигания и проверить катушку 1-го цилиндра",
                "priority": "high",
            },
        )
        self.stats["рекомендаций"] += 1
        version = self.order(m1, o["id"])["version"]
        self.api.call(
            m1,
            "PATCH",
            f"/work-orders/{o['id']}",
            {"version": version, "diagnosis": "Пропуски зажигания в 1-м цилиндре, износ свечей"},
        )
        self.status(m1, o["id"], "awaiting_approval", comment="Ждём согласия клиента на ремонт")

        # --- Отменён ---
        o = self.create_order("cancelled_granta", m1, 0, 10, [("DIAG-COMP", None)],
                              "Не заводится в мороз", planned_hours=None)  # fmt: skip
        self.status(m1, o["id"], "cancelled", cancel_reason="Клиент отказался от ремонта")

        # --- Ожидает запчасти: механик запросил то, чего нет на складе ---
        o = self.create_order("parts_duster", m1, 0, 5, [("SUSP-PADS", "mechanic2")],
                              "Замена задних колодок", planned_hours=48)  # fmt: skip
        self.status(m1, o["id"], "in_progress")
        item = self.item_ids(o)[0]
        self.api.post("mechanic2", f"/mechanic/tasks/{item}/start", {})
        self.api.post(
            "mechanic2",
            "/mechanic/part-requests",
            {
                "item_id": item,
                "description": "Колодки задние Renault Duster 4x4 — нет на складе",
                "quantity": "1.000",
            },
        )
        self.stats["заявок на запчасти"] += 1
        self.api.post("mechanic2", f"/mechanic/tasks/{item}/pause", {})
        self.status(m1, o["id"], "awaiting_parts", comment="Заказаны колодки у поставщика")

        # --- В работе: механик сейчас работает, заявка на запчасть одобрена и выдана ---
        o = self.create_order("work_polo", m1, 0, 4,
                              [("SUSP-SHOCK", "mechanic1", "2.00"), ("SUSP-ALIGN", "mechanic2")],
                              "Стук в передней подвеске")  # fmt: skip
        self.status(m1, o["id"], "in_progress")
        shock = self.item_ids(o, "mechanic1")[0]
        self.api.post("mechanic1", f"/mechanic/tasks/{shock}/start", {})
        request = self.api.post(
            "mechanic1",
            "/mechanic/part-requests",
            {"item_id": shock, "part_id": self.parts["shock"], "quantity": "2.000"},
        )
        self.stats["заявок на запчасти"] += 1
        self.api.post(m1, f"/part-requests/{request['id']}/approve", {})
        version = self.order(m1, o["id"])["version"]
        self.api.post(m1, f"/part-requests/{request['id']}/issue", {"version": version})
        self.api.post(
            "mechanic1",
            f"/mechanic/tasks/{shock}/comments",
            {"text": "Опорные подшипники в норме, пыльники требуют замены"},
        )
        self.stats["комментариев"] += 1
        self.comment(m1, o["id"], "Клиент просит позвонить перед дополнительными работами")

        # --- Диагностика идёт прямо сейчас ---
        o = self.create_order("diag_bmw", m1, 0, 6, [("DIAG-COMP", "mechanic2")],
                              "Плавают обороты на холостом ходу")  # fmt: skip
        self.status(m1, o["id"], "diagnostics")
        self.api.post("mechanic2", f"/mechanic/tasks/{self.item_ids(o)[0]}/start", {})

        # --- Новые ---
        self.create_order("new_qashqai", m1, 0, 8, [("TO-15", None)], "Плановое ТО по записи",
                          appointment_id=appts["qashqai_today"]["id"])  # fmt: skip
        o = self.create_order("new_sportage", m1, 0, 9, [("WASH-STD", None)],
                              "Мойка кузова и салона", planned_hours=3)  # fmt: skip
        self.comment(m1, o["id"], "Клиент оставил детское кресло в багажнике", internal=False)

        # --- Точка «Север» ---
        o = self.create_order("north_closed_tiggo", m2, 1, 12, [("TO-OIL", "mechanic3")],
                              "Замена масла")  # fmt: skip
        self.add_part(m2, o["id"], "oil", "1.000")
        self.add_part(m2, o["id"], "oil_filter", "1.000")
        self.finish_order(m2, o["id"], [("cash", None)])

        o = self.create_order("north_closed_coolray", m2, 1, 13,
                              [("WASH-STD", "mechanic4"), ("POL-BODY", "mechanic4")],
                              "Полировка после покупки")  # fmt: skip
        self.add_part(m2, o["id"], "paste", "1.000")
        self.finish_order(m2, o["id"], [("card", None)])

        o = self.create_order("north_ready_kodiaq", m2, 1, 4, [("TIRE-SET", "mechanic4")],
                              "Переобуть на зиму", car=1)  # fmt: skip
        self.finish_order(m2, o["id"], [], close=False)

        o = self.create_order("north_work_transit", m2, 1, 14, [("SUSP-PADS", "mechanic3")],
                              "Замена передних колодок", car=1)  # fmt: skip
        self.add_part(m2, o["id"], "pads", "1.000")
        self.status(m2, o["id"], "in_progress")
        self.api.post("mechanic3", f"/mechanic/tasks/{self.item_ids(o)[0]}/start", {})

        self.create_order("north_new_rio", m2, 1, 1, [("TO-OIL", None)],
                          "Повторный визит: замена масла")  # fmt: skip

    # ---------- касса и зарплата ----------

    def setup_expenses(self) -> None:
        categories: list[Json] = self.api.get(DIRECTOR_LOGIN, "/expense-categories")
        by_name = {c["name"]: c["id"] for c in categories if c["is_active"]}
        if not by_name:
            raise SeedError("Нет активных категорий расходов")

        def cat(name: str) -> str:
            return str(by_name.get(name) or next(iter(by_name.values())))

        month_start = self.today.replace(day=1)
        expenses = [
            ("director", 0, "Аренда", "150000.00", "transfer", month_start,
             "Аренда помещения за месяц"),
            ("director", 1, "Аренда", "90000.00", "transfer", month_start,
             "Аренда помещения за месяц"),
            ("director", 0, "Коммунальные услуги", "18300.00", "transfer",
             self.today - timedelta(days=5), "Электроэнергия и вода"),
            ("manager1", 0, "Расходные материалы", "4500.00", "cash", self.today,
             "Перчатки, ветошь, очиститель тормозов"),
            ("manager2", 1, "Расходные материалы", "2300.00", "card",
             self.today - timedelta(days=1), "Микрофибра и аппликаторы"),
        ]  # fmt: skip
        for who, loc_index, category, amount, method, day, text in expenses:
            self.api.post(
                who,
                "/expenses",
                {
                    "location_id": self.loc(loc_index),
                    "category_id": cat(category),
                    "amount": amount,
                    "method": method,
                    "expense_date": max(day, month_start).isoformat(),
                    "description": text,
                },
            )
            self.stats["расходов"] += 1

    def setup_payroll(self) -> None:
        month_start = self.today.replace(day=1)
        for login, _, _ in MECHANICS:
            self.api.post(
                DIRECTOR_LOGIN,
                "/payroll/schemes",
                {
                    "user_id": self.uid(login),
                    "scheme_type": "percent_of_works",
                    "percent": "40.00",
                    "valid_from": month_start.isoformat(),
                },
            )
            self.stats["схем зарплаты"] += 1
        for login, _, _ in MANAGERS:
            self.api.post(
                DIRECTOR_LOGIN,
                "/payroll/schemes",
                {
                    "user_id": self.uid(login),
                    "scheme_type": "fixed_plus_percent",
                    "fixed_monthly": "60000.00",
                    "percent": "2.00",
                    "valid_from": month_start.isoformat(),
                },
            )
            self.stats["схем зарплаты"] += 1
        month = month_start.strftime("%Y-%m")
        for login, amount, reason in (
            ("mechanic1", "5000.00", "Премия за качество работ"),
            ("mechanic3", "-1500.00", "Удержание за испорченный пыльник"),
        ):
            self.api.post(
                DIRECTOR_LOGIN,
                "/payroll/adjustments",
                {"user_id": self.uid(login), "month": month, "amount": amount, "reason": reason},
            )
            self.stats["корректировок зарплаты"] += 1

    # ---------- запуск ----------

    def run(self) -> None:
        steps = [
            ("Точки", self.setup_locations),
            ("Сотрудники", self.setup_users),
            ("Каталог", self.setup_catalog),
            ("Склад", self.setup_stock),
            ("Клиенты и автомобили", self.setup_clients),
        ]
        for title, step in steps:
            print(f"• {title}")
            step()
        print("• Записи")
        appts = self.setup_appointments()
        print("• Заказ-наряды")
        self.setup_orders(appts)
        print("• Расходы")
        self.setup_expenses()
        print("• Зарплата")
        self.setup_payroll()

    def summary(self) -> None:
        statuses = Counter(
            str(self.order(DIRECTOR_LOGIN, o["id"])["status"]) for o in self.orders.values()
        )
        print("\nДемо-данные загружены:")
        for name, count in self.stats.items():
            print(f"  {name}: {count}")
        print("  заказ-наряды по статусам: " + ", ".join(f"{k} — {v}" for k, v in statuses.items()))
        print("\nЛогины (пароли — из переменных окружения):")
        names = [loc["name"] for loc in self.locations]
        for login, full_name, loc_index in MANAGERS:
            print(
                f"  {login:<10} менеджер, {full_name}, {names[loc_index]} (DEMO_MANAGER_PASSWORD)"
            )
        for login, full_name, loc_index in MECHANICS:
            print(
                f"  {login:<10} механик, {full_name}, {names[loc_index]} (DEMO_MECHANIC_PASSWORD)"
            )
        print(f"  {DIRECTOR_LOGIN:<10} руководитель (SEED_DIRECTOR_PASSWORD)")


def main() -> int:
    try:
        passwords = read_passwords()
    except SeedError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    api = Api(os.environ.get("DEMO_API_URL") or DEFAULT_API_URL)
    try:
        seed = DemoSeed(api, passwords)
        if seed.already_loaded():
            print("Демо-данные уже загружены")
            return 0
        seed.run()
        seed.summary()
        print(f"\nВходов в API: {api.logins}")
        return 0
    except SeedError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    finally:
        api.close()


if __name__ == "__main__":
    sys.exit(main())
