# Контракт API модуля 1 (источник истины для backend и frontend)

Префикс `/api/v1`. Ошибки — единый формат модуля 0 (`{"error":{"code","message","fields","request_id"}}`).
Access-токен (JWT, 15 мин) приходит в JSON и передаётся как `Authorization: Bearer`. Refresh-токен — только в cookie `refresh_token` (`HttpOnly; SameSite=Strict; Path=/api/v1/auth`; `Secure` — когда `ENV != dev`), в теле не возвращается.

## Типы
- `User` = `{id: uuid, login: str, full_name: str, role: "mechanic"|"manager"|"director", is_active: bool, location_ids: uuid[], created_at: iso}`
- `Location` = `{id: uuid, name: str, address: str, phone: str|null, is_active: bool}`
- `Page<T>` = `{items: T[], total: int}`

## Auth
| Метод и путь | Тело | Ответ | Ошибки (code → HTTP) |
|---|---|---|---|
| `POST /auth/login` | `{login, password}` | 200 `{access_token, expires_in, user: User}` + cookie | `invalid_credentials` 401 (одинаково для неверного логина/пароля/неактивного), `account_locked` 423 (после 5 неудач, 15 мин), `rate_limited` 429 (10/мин с IP) |
| `POST /auth/refresh` | — (cookie) | 200 как у login | `invalid_token` 401 (в т.ч. повторное использование → отзыв всех сессий) |
| `POST /auth/logout` | — | 204, cookie очищается | — |
| `POST /auth/change-password` | `{current_password, new_password}` | 204, остальные сессии отозваны | `invalid_current_password` 400, 422 `fields.new_password` (слабый: <10 символов, частый, равен логину) |
| `GET /auth/me` | — | `User` | `unauthorized` 401 |

## Locations (изменять — только director; читать — director все, остальные свои)
- `GET /locations` → `Location[]`
- `POST /locations` `{name, address, phone?}` → 201 `Location`
- `GET /locations/{id}` → `Location` (чужая точка → 404)
- `PATCH /locations/{id}` `{name?, address?, phone?, is_active?}` → `Location`
- Удаления нет (только `is_active=false`).

## Users (только director; остальным 403 `forbidden`)
- `GET /users?search=&role=&location_id=&is_active=&limit=50&offset=0` → `Page<User>`
- `POST /users` `{login, full_name, role, password, location_ids}` → 201 `User`; дубль логина → 409 `unique_violation`
- `GET /users/{id}` → `User`
- `PATCH /users/{id}` `{full_name?, role?, location_ids?, is_active?}` → `User` (смена роли/блокировка отзывают сессии)
- `POST /users/{id}/reset-password` `{new_password}` → 204 (сессии пользователя отозваны)

## Seed (dev)
`python -m app.cli seed` создаёт руководителя `director` и одну точку; пароль берётся из `SEED_DIRECTOR_PASSWORD` (по умолчанию в dev — `demo-password-123`), в `ENV=prod` без явной переменной команда отказывается работать.

## Валидация
Логин — `Login` из `app/core/types.py`; ФИО, адрес, название точки — `SafeText` (HTML вырезается `nh3`, `<`/`>` запрещены). Все схемы `extra="forbid"`.
