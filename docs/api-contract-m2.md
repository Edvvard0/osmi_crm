# Контракт API модуля 2 — клиенты и автомобили

Префикс `/api/v1`. Формат ошибок и авторизация — как в `api-contract-m1.md`. Доступ: `manager` и `director` (клиенты общие для всех точек); `mechanic` → 403 `forbidden` (его ограниченный просмотр появится в модуле 6).

## Типы
- `Client` = `{id, client_type: "person"|"company", full_name, company_name: str|null, inn: str|null, phone, phone_extra: str|null, email: str|null, source: "walk_in"|"referral"|"online"|"ads"|"repeat"|"other"|null, discount_percent: number (0..100), notes: str|null, vehicles_count: int, created_at, archived_at: iso|null}`
- `Vehicle` = `{id, client_id, make, model, year: int|null, vin: str|null, plate_number: str|null, color: str|null, mileage: int|null, notes: str|null, created_at, archived_at: iso|null}`
- `Page<T>` = `{items: T[], total: int}`
- `SearchHit` = `{type: "client"|"vehicle", id, title, subtitle, client_id}` (для клиента `title` — ФИО, `subtitle` — телефон; для авто `title` — «Марка Модель», `subtitle` — госномер)

Телефон принимается в любом формате, хранится и отдаётся как E.164 (`+79991234567`). Госномер: верхний регистр, латиница→кириллица (как в `PlateNumber`). VIN: 17 символов без I, O, Q. Текстовые поля — `SafeText`.

## Клиенты
- `GET /clients?search=&client_type=&source=&archived=false&limit=50&offset=0` → `Page<Client>` (search по ФИО, телефону — в т.ч. по последним цифрам, названию компании, госномеру и VIN авто)
- `POST /clients` `{client_type, full_name, company_name?, inn?, phone, phone_extra?, email?, source?, discount_percent?, notes?}` → 201 `Client`. Дубль телефона → 409 `duplicate_phone` с `fields`-подсказкой и `existing_id` внутри `error.details`: `{"error":{"code":"duplicate_phone","details":{"existing_id":"…","existing_name":"…"}}}`
- `GET /clients/{id}` → `Client` + `vehicles: Vehicle[]` (неархивные)
- `PATCH /clients/{id}` — любые поля создания → `Client`
- `POST /clients/{id}/archive` и `POST /clients/{id}/restore` → `Client`

## Автомобили
- `GET /clients/{id}/vehicles` → `Vehicle[]`
- `POST /clients/{id}/vehicles` `{make, model, year?, vin?, plate_number?, color?, mileage?, notes?}` → 201 `Vehicle`. Дубль VIN → 409 `duplicate_vin` с `details.existing_vehicle_id`, `details.existing_client_id`
- `GET /vehicles/{id}` → `Vehicle` + `client: {id, full_name, phone}`
- `PATCH /vehicles/{id}` → `Vehicle`; `POST /vehicles/{id}/archive`, `/restore`

## Глобальный поиск
- `GET /search?q=&limit=10` → `SearchHit[]` (клиенты и авто; минимум 2 символа, иначе 422)
