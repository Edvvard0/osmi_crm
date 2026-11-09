# Контракт API модуля 4 — запись (календарь)

Префикс `/api/v1`. Ошибки и авторизация — как в модуле 1. Время — ISO 8601 с часовым поясом (`2026-11-10T10:00:00+03:00`); в БД хранится UTC, наружу отдаётся в поясе точки. Доступ: `manager` (только свои точки; чужая точка → 404) и `director`; `mechanic` → 403 `forbidden`.

## Изменение в Locations (расширение модуля 1)
`Location` дополняется полями только для чтения у всех ролей и для изменения у director:
`code: str`, `timezone: str` (IANA, например `Europe/Moscow`), `work_start: "HH:MM"`, `work_end: "HH:MM"` (`work_end > work_start`).
- `PATCH /locations/{id}` принимает дополнительно `timezone?` (проверяется по списку IANA, иначе 422), `work_start?`, `work_end?`.
- `POST /locations` принимает те же поля необязательно (по умолчанию `Europe/Moscow`, `09:00`, `21:00`); `code` генерируется автоматически, как сейчас.

## Типы
- `AppointmentStatus` = `"scheduled"|"confirmed"|"arrived"|"no_show"|"cancelled"`
- `Appointment` = `{id, location_id, client_id, vehicle_id, post_id: uuid|null, department: "service"|"detailing", start_at, end_at, status, comment: str|null, service_ids: uuid[], services: {id, name}[], client: {id, full_name, phone}, vehicle: {id, make, model, plate_number: str|null}, work_order_id: uuid|null, created_by: uuid, created_at, updated_at}`
  (`work_order_id` всегда `null` до модуля 5.)

## Эндпоинты
- `GET /appointments?location_id=&date_from=&date_to=&post_id=&department=&status=&client_id=` → `Appointment[]` (без пагинации, по возрастанию `start_at`)
  - `location_id`, `date_from`, `date_to` — обязательны; даты `YYYY-MM-DD` включительно, трактуются в часовом поясе точки; диапазон не более 31 дня, иначе 422.
- `POST /appointments` `{location_id, client_id, vehicle_id, post_id?, department, start_at, end_at, service_ids?, comment?}` → 201 `Appointment`, статус `scheduled`.
- `GET /appointments/{id}` → `Appointment`
- `PATCH /appointments/{id}` `{post_id?, start_at?, end_at?, department?, service_ids?, comment?}` → `Appointment` — перенос и изменение длительности (`start_at` и `end_at` передаются вместе). Для статусов `no_show`, `cancelled`, `arrived` → 409 `invalid_state`.
- `POST /appointments/{id}/status` `{status}` → `Appointment`. Разрешённые переходы: `scheduled → confirmed | arrived | no_show | cancelled`; `confirmed → arrived | no_show | cancelled`. Остальное → 409 `invalid_transition`. Конечные статусы: `arrived`, `no_show`, `cancelled`. Запись в конечном статусе не занимает пост (освобождает слот).

Быстрое создание клиента и авто из формы записи: фронтенд последовательно вызывает существующие `POST /clients` и `POST /clients/{id}/vehicles` (модуль 2), затем `POST /appointments`.

## Правила и ошибки
| Правило | Ответ |
|---|---|
| `vehicle_id` принадлежит `client_id`, оба не в архиве | иначе 422 `fields.vehicle_id` |
| `post_id` принадлежит `location_id`, активен, его `department` равен `department` записи | иначе 422 `fields.post_id` |
| `service_ids` — активные услуги; их отдел совпадает с `department` | иначе 422 `fields.service_ids` |
| Длительность от 15 минут до 12 часов, `start_at` и `end_at` кратны 5 минутам | иначе 422 `fields.end_at` / `fields.start_at` |
| Запись целиком в рабочих часах точки и в пределах одних суток (в поясе точки) | иначе 422 `outside_working_hours` |
| Пост занят (пересечение интервалов `[start, end)` со статусами `scheduled/confirmed/arrived`) | 409 `post_busy`, `details: {conflict_id, start_at, end_at}`; гарантируется exclusion constraint в БД, при гонке выигрывает одна запись |
| Запись без поста (`post_id = null`) | допустима, пересечения не проверяются |
| Недопустимый переход статуса | 409 `invalid_transition` |
| Правка записи в конечном статусе | 409 `invalid_state` |

Текстовые поля — `SafeText` (`comment` до 1000 символов). Схемы `extra="forbid"`. Изменения пишутся в `audit_log`.
