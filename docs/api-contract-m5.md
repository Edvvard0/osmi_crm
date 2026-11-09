# Контракт API модуля 5 — заказ-наряды

Префикс `/api/v1`. Формат ошибок, авторизация, `extra="forbid"`, `SafeText` — как в модуле 1. Время — ISO 8601 с поясом точки (как в модуле 4). Доступ: `manager` (только свои точки; чужая точка и чужой объект → 404) и `director` (все точки). `mechanic` → 403 `forbidden` на всех эндпоинтах этого файла (его срез заказов — `/mechanic/*` в модуле 6).

Этот файл также задаёт **общие соглашения модулей 5–12**. Остальные контракты (`api-contract-m6.md` … `m12.md`) ссылаются на раздел «Общие соглашения» отсюда и не повторяют его.

## Общие соглашения (модули 5–12)

### Общие типы
Все числа с десятичной частью передаются **строками**; числа JSON для денег, часов и количеств не используются ни во входе, ни в выходе. Лишние знаки после запятой на входе → 422 (не округляются молча).

| Тип | Формат | Пример | Где |
|---|---|---|---|
| `Money` | строка, 2 знака, `>= 0`, максимум `9999999999.99` | `"1500.00"` | суммы, цены |
| `SignedMoney` | то же, но допускается знак `-` | `"-250.00"` | корректировки, дельты |
| `Hours` | строка, 2 знака, `>= 0` | `"1.50"` | нормочасы, часы |
| `Qty2` | строка, 2 знака, `> 0` | `"2.00"` | количество работ |
| `Qty3` | строка, 3 знака, `> 0` | `"0.500"` | количество запчастей |
| `SignedQty3` | то же со знаком | `"-1.000"` | движения склада |
| `Percent` | строка, 2 знака, `0..100` | `"10.00"` | скидки, проценты |
| `Page<T>` | `{items: T[], total: int}` | | списки с пагинацией (`limit` 1..200, по умолчанию 50; `offset >= 0`) |
| `UserRef` | `{id, full_name}` | | краткая ссылка на сотрудника |
| `ClientRef` | `{id, full_name, phone}` | | |
| `VehicleRef` | `{id, make, model, plate_number: str\|null}` | | |

Исключение для существующего кода: `Client.discount_percent` (модуль 2) остаётся числом JSON; в новых типах скидки — `Percent` (строка). При копировании скидки клиента в заказ сервер приводит число к `Percent`.

Перечисления:
- `WorkOrderStatus` = `"new"|"diagnostics"|"awaiting_approval"|"in_progress"|"awaiting_parts"|"quality_check"|"ready"|"closed"|"cancelled"`
- `WorkOrderDepartment` = `"service"|"detailing"|"mixed"`
- `ItemStatus` = `"pending"|"in_progress"|"paused"|"done"|"cancelled"`
- `PaymentStatus` = `"unpaid"|"partial"|"paid"|"refunded"`
- `Department` = `"service"|"detailing"` (как в модуле 3)

### Округление
Все денежные расчёты — `Decimal`, режим `ROUND_HALF_UP`, округление до копеек на каждой строке (формулы — в разделе «Расчёт сумм»). Клиент итоги не присылает.

### Оптимистическая блокировка
Изменяющие запросы по заказу несут `version` в теле (`{"version": 7, ...}`), кроме явно отмеченных. Несовпадение → **409 `version_conflict`**, `details: {"current_version": "9"}`. Каждый успешный запрос менеджера/директора, изменивший шапку, состав, статус или суммы заказа, увеличивает `version` на 1 и возвращает полный `WorkOrder` с новым `version`. Операции, которые версию **не** увеличивают: таймер механика (модуль 6), оплаты и возвраты (модуль 9), комментарии. Код `conflict` (общий 409 модуля 1) для этих случаев не используется; `version_conflict` — новый код, его надо добавить в `ERROR_MESSAGES` на фронтенде (общий текст «Данные изменил другой сотрудник» с кнопкой «Обновить»).

### Доменные события (заглушка до модуля 7)
Файл `backend/app/services/events.py`, создаётся **модулем 5**:
```python
async def publish(session, event_type: str, payload: dict[str, str | int | None], *,
                  location_id: UUID | None, actor_id: UUID | None,
                  target_user_id: UUID | None = None, dedup_key: str | None = None) -> None: ...
```
В модуле 5 тело функции пустое (no-op). Сервисы модулей 4–6 и 8–10 вызывают её сразу в нужных местах (в той же транзакции, что и бизнес-изменение). Модуль 7 заменяет тело на запись в `notification_outbox` (правила получателей, ключи дедупликации и состав `payload` каждого события — в `api-contract-m7.md`, раздел «Каталог событий»). Вызывающий код менять не требуется. `location_id = None` допустим для событий без точки (`user.locked`, `report.daily_summary`). `dedup_key` — необязательная база ключа дедупликации (модуль 7 дописывает к ней получателя). Значения `payload` — только строки/числа/`null` (UUID и даты — строками ISO).

### Настройки (аксессор до модуля 11)
Файлы `backend/app/core/settings_defaults.py` (словарь `ключ → значение по умолчанию`, значения и допустимые диапазоны — в `api-contract-m11.md`, раздел «Настройки») и `backend/app/services/settings.py` с `async def get_setting(session, key) -> Any` создаются **модулем 5**. До модуля 11 функция возвращает значение по умолчанию из кода; модуль 11 добавляет чтение из таблицы `system_settings` (кэш в процессе с TTL ≤ 10 с). Потребители (скидочный порог в модуле 5, пороги тепловой карты в модуле 10, время сводки) всегда вызывают `get_setting`, а не читают константы.

### Коды ошибок (новые), общие
| Код | HTTP | Когда |
|---|---|---|
| `version_conflict` | 409 | `version` в теле не равна текущей |
| `invalid_state` | 409 | объект в состоянии, где операция недопустима (уже есть в модуле 4) |
| `invalid_transition` | 409 | недопустимый переход статуса (уже есть в модуле 4) |

Остальные коды вводит модуль, который их использует; каждый перечислен в таблице «Правила и ошибки» своего файла. Фронтенд добавляет каждый код в `ERROR_MESSAGES` (русский текст без технических деталей). `details` — всегда словарь строка→строка.

### Аудит
Во всех модулях изменения пишутся в `audit_log` через `write_audit` (`app/services/audit.py`). Допустимые `action`: `create`, `update`, `delete`, `archive`, `restore`, `status_change`, `refund`, `login`, `login_failed`, `logout`, `token_reuse`, `password_change` (расширенный список — в `api-contract-m11.md`). `changes` — по `diff(old, new)`; секреты в `changes` не попадают.

### Миграции Alembic
- Ревизии резервируются **безусловно**: `0005` — модуль 5, `0006` — 6, … `0012` — 12. Файлы-заглушки `backend/migrations/versions/0005_work_orders.py … 0012_hardening.py` уже лежат в репозитории (`revision = "0005"`, `down_revision = "0004"` и дальше цепочкой `0005 → 0006 → … → 0012`, тела `upgrade/downgrade` пустые).
- Агент модуля N заполняет **только** `upgrade()`/`downgrade()` и docstring файла `00NN_*.py`; `revision` и `down_revision` в нём не меняет.
- Исключение (единственное): миграции модуля 4 (`appointments`, `appointment_services`) на момент написания не существует. Агент модуля 4 обязан создать `0004a_appointments.py` с `revision = "0004a"`, `down_revision = "0004"` и **один раз** изменить `down_revision` заглушки `0005` на `"0004a"`. Итоговая цепочка: `0001 → 0002 → 0003 → 0004 → 0004a → 0005 → … → 0012`. После любого merge `alembic heads` должен показывать ровно одну голову (проверка — в тестах миграций).
- Внешние ключи на таблицы более поздних модулей добавляет миграция модуля, в котором появляется целевая таблица (`docs/02-database-schema.md`, раздел 5).
- Роли БД: миграции выполняет отдельная роль; `crm_app` получает права на новые таблицы через `GRANT SELECT, INSERT, UPDATE, DELETE` в миграции (для `stock_movements` и `audit_log` — без `UPDATE/DELETE`).

## Расширения сущностей предыдущих модулей

| Сущность | Расширение | Модуль |
|---|---|---|
| `Appointment` (модуль 4) | `work_order_id: uuid\|null` (уже в контракте м4) теперь заполняется; новое поле `work_order_number: str\|null` | 5 |
| `Client` (модуль 2) — в `GET /clients` и `GET /clients/{id}` | `orders_count: int`, `total_spent: Money`, `average_check: Money`, `last_visit_at: iso\|null` — по закрытым заказам клиента (`status = closed`) во всех точках; `last_visit_at` = максимум `closed_at`; `average_check = total_spent / orders_count` (`"0.00"` при нуле) | 5 |
| `Vehicle` (модуль 2) | без изменений; история — `GET /vehicles/{id}/work-orders` | 5 |

Статистика клиента — агрегаты по всей сети (клиенты общие для точек, как в модуле 2); отдельные заказы чужой точки менеджеру не отдаются. Фильтр `GET /clients` по новым полям не добавляется; сортировка — по-прежнему на усмотрение модуля 2.

## Права
| Действие | director | manager | mechanic |
|---|---|---|---|
| Список, карточка, доска, счётчики заказов | все точки | свои точки | 403 |
| Создание, правка шапки, состав, статусы, отмена | ✓ | ✓ (свои точки) | 403 |
| Комментарии: чтение и запись | ✓ | ✓ | 403 (в модуле 6 — свои заказы) |
| Изменить цену каталожной услуги/запчасти в строке (`unit_price` отличается от каталожной) | ✓ | 403 `forbidden` | 403 |
| Задать цену произвольной работы/запчасти | ✓ | ✓ | 403 |
| Поле `WorkOrderPart.unit_cost` (себестоимость) | значение | всегда `null` | — |
| Печатные формы | ✓ | ✓ | 403 |

Менеджер видит заказы всех своих точек одновременно; `location_id` в списках необязателен, но если задан и это чужая точка — 404.

## Типы
- `WorkOrderItem` = `{id, service_id: uuid|null, name, department: Department, quantity: Qty2, unit_price: Money, discount_percent: Percent, total: Money, norm_hours: Hours, norm_hours_total: Hours, mechanic: UserRef|null, status: ItemStatus, started_at: iso|null, finished_at: iso|null, actual_minutes: int, sort_order: int}`
  - `norm_hours` — на единицу, `norm_hours_total = norm_hours × quantity`. `actual_minutes` — сумма интервалов `work_logs` (до модуля 6 всегда `0`).
- `WorkOrderPart` = `{id, part_id: uuid|null, name, sku: str|null, unit: str|null, quantity: Qty3, unit_price: Money, total: Money, unit_cost: Money|null, in_stock: SignedQty3|null, added_by: UserRef, created_at}`
  - `unit` — единица из справочника (`pcs|l|ml|kg|g|m|set`), `null` для произвольной позиции. `in_stock` — остаток запчасти на складе точки заказа (после модуля 8; до него и для произвольных позиций — `null`).
- `WorkOrderListItem` = `{id, number, location_id, status, department: WorkOrderDepartment, created_at, planned_ready_at: iso|null, is_overdue: bool, mileage_in: int|null, client: ClientRef, vehicle: VehicleRef, manager: UserRef, mechanics: UserRef[], items_count: int, items_done_count: int, works_total, parts_total, discount_total, total, paid_total, balance_due, payment_status: PaymentStatus, version: int}`
  - все суммы — `Money`; `mechanics` — уникальные исполнители неотменённых работ; `items_count/items_done_count` считаются по неотменённым работам; `balance_due = max(total − paid_total, 0)`.
  - `is_overdue = planned_ready_at < now() AND status ∉ {ready, closed, cancelled}`.
- `WorkOrder` = `WorkOrderListItem` + `{client: ClientRef + {discount_percent: number}, vehicle: {id, make, model, year: int|null, plate_number: str|null, vin: str|null, color: str|null, mileage: int|null}, complaint: str|null, intake_notes: str|null, diagnosis: str|null, discount_percent: Percent, started_at: iso|null, ready_at: iso|null, closed_at: iso|null, cancel_reason: str|null, appointment_id: uuid|null, items: WorkOrderItem[], parts: WorkOrderPart[], allowed_transitions: WorkOrderStatus[], updated_at}`
  - `items` отсортированы по `sort_order`, затем `created_at`; в ответ входят и отменённые (`status = cancelled`), UI их приглушает.
  - `allowed_transitions` — статусы, в которые разрешён переход из текущего (по таблице переходов, без проверки содержимого: `ready`/`closed` могут быть отклонены с `items_not_done`/`order_not_paid`).
- `StatusHistoryEntry` = `{id, from_status: WorkOrderStatus|null, to_status: WorkOrderStatus, changed_by: UserRef, comment: str|null, created_at}`
- `WorkOrderComment` = `{id, item_id: uuid|null, author: UserRef & {role}, text, is_internal: bool, created_at}`
- `OrderBoard` = `{columns: {status: WorkOrderStatus, total: int, items: WorkOrderListItem[]}[]}`
- `OrderSummary` = `{in_progress: int, awaiting_parts: int, ready: int, overdue: int, open_total: int}`

## Заказ-наряды
- `GET /work-orders` → `Page<WorkOrderListItem>`
  - Фильтры: `location_id=`, `status=` (можно несколько через запятую), `department=service|detailing|mixed`, `manager_id=`, `mechanic_id=` (есть неотменённая работа этого механика), `client_id=`, `vehicle_id=`, `payment_status=`, `overdue=true`, `date_from=`, `date_to=` (`YYYY-MM-DD` включительно по `created_at` в поясе точки; диапазон не более 366 дней), `search=` (номер заказа, госномер, VIN, ФИО/название клиента, последние цифры телефона; `%` и `_` экранируются), `sort=created_at|planned_ready_at|number|total|status` (по умолчанию `created_at`), `order=asc|desc` (по умолчанию `desc`), `limit`, `offset`.
  - Менеджер без `location_id` получает заказы всех своих точек; директор — всех.
- `GET /work-orders/board?location_id=&department=&manager_id=&mechanic_id=&overdue=` → `OrderBoard` (для канбана MG-04). Колонки — все статусы кроме `cancelled` в порядке жизненного цикла; в каждой не более 100 карточек (сортировка: `planned_ready_at` по возрастанию, пустые в конце; затем `created_at`), `total` — полное число. Колонка `closed` содержит заказы, закрытые за последние 7 дней. `location_id` обязателен для менеджера с несколькими точками (иначе 422 `fields.location_id`), необязателен для директора.
- `GET /work-orders/summary?location_id=` → `OrderSummary` (счётчики MG-01). `location_id` — как у доски. `open_total` — все заказы вне `closed/cancelled`.
- `POST /work-orders` — создание → 201 `WorkOrder`, статус `new`, `version = 1`.
  Тело: `{location_id, client_id, vehicle_id, appointment_id?, department?, manager_id?, mileage_in?, complaint?, intake_notes?, planned_ready_at?, discount_percent?, items?: NewItem[]}`, где `NewItem` — тело `POST …/items` без `version` (см. ниже).
  - `appointment_id`: создание из записи. Запись должна быть своей точки заказа, в статусе `scheduled|confirmed|arrived`, без заказа. `client_id`/`vehicle_id` обязаны совпасть с записью (или отсутствовать — тогда подставляются); `department` — из записи; если `items` не переданы, позиции создаются из услуг записи (`appointment.service_ids`, `quantity = 1.00`, цена каталога с учётом цены точки). В той же транзакции запись получает `status = arrived` (если ещё не `arrived`) и `work_order_id`.
  - `department` без позиций и без записи — по умолчанию `service`; после появления позиций отдел заказа всегда вычисляется (см. «Правила»).
  - `manager_id` по умолчанию текущий пользователь; должен быть `manager|director` с доступом к точке (иначе 422 `fields.manager_id`).
  - `discount_percent` по умолчанию = скидка клиента (`Client.discount_percent`).
  - `mileage_in` > текущего `Vehicle.mileage` → пробег авто обновляется (и пишется в аудит авто).
  - Номер: `<Location.code>-<6 цифр>`, например `MSK1-000123`, атомарно из `location_counters` (`INSERT … ON CONFLICT DO NOTHING`, затем `UPDATE … RETURNING`) в той же транзакции; пропусков при откате нет.
- `GET /work-orders/{id}` → `WorkOrder`
- `PATCH /work-orders/{id}` `{version, mileage_in?, complaint?, intake_notes?, diagnosis?, planned_ready_at?, discount_percent?, manager_id?, vehicle_id?}` → `WorkOrder`
  - `null` очищает поле, где оно допускает `null` (`mileage_in`, `complaint`, `intake_notes`, `diagnosis`, `planned_ready_at`).
  - `vehicle_id` (должно принадлежать клиенту заказа) меняется только в статусах `new|diagnostics|awaiting_approval`, иначе 409 `invalid_state`.
  - Любые изменения в статусах `closed|cancelled` → 409 `invalid_state`.
  - Изменение `discount_percent` пересчитывает суммы; результат ниже уже принятой оплаты → 409 `total_below_paid` (модуль 9; до него проверки нет).
  - Изменение `planned_ready_at` публикует событие `work_item.updated` каждому назначенному механику (неотменённые, незавершённые работы).
  - Если после изменения `discount_percent` (заказа или любой строки) максимальная скидка превышает `get_setting("discount_alert_percent")`, публикуется `order.discount_alert` (один раз на каждое изменение, когда значение выросло).
- `POST /work-orders/{id}/status` `{version, status, comment?, cancel_reason?}` → `WorkOrder` — смена статуса (также для перетаскивания в канбане). Правила — в разделе «Статусы».
- `GET /work-orders/{id}/history` → `StatusHistoryEntry[]` (по возрастанию времени)
- `POST /work-orders/{id}/duplicate` `{}` → 201 `WorkOrder` — новый заказ с теми же клиентом, авто, точкой, отделом, жалобой; статус `new`; копируются неотменённые работы (без механика, статус `pending`, цена каталожных — актуальная, произвольных — прежняя) и скидка заказа; запчасти, пробег, диагноз и комментарии не копируются; менеджер — текущий пользователь.

### Работы (позиции)
Тело создания `NewItem` (используется в `POST /work-orders` и `POST …/items`): либо `{service_id, quantity?, discount_percent?, mechanic_id?, unit_price?}` (каталожная), либо `{name, department, unit_price, quantity?, discount_percent?, norm_hours?, mechanic_id?}` (произвольная). `quantity` по умолчанию `"1.00"`, `discount_percent` — `"0.00"`.
- Каталожная работа: `name`, `department`, `norm_hours` берутся из услуги (снимок), `unit_price` — **эффективная цена услуги для точки заказа** (цена точки, иначе базовая), определяется сервером. Если клиент передал `unit_price` и он отличается от каталожной — для `manager` 403 `forbidden`, для `director` принимается. Передача `norm_hours` для каталожной → 422 `fields.norm_hours`. Услуга должна быть активной (`is_active`), иначе 422 `fields.service_id`.
- Произвольная работа: `name` (≤ 200, `SafeText`), `department`, `unit_price`, `norm_hours` (по умолчанию `"0.00"`).
- Эндпоинты:
  - `POST /work-orders/{id}/items` `{version, …NewItem}` → 201 `WorkOrder` (ответ — полный заказ, новая позиция в `items`). В статусе `ready` → 409 `invalid_state`. Если заказ в `awaiting_approval`, добавление допустимо.
  - `PATCH /work-orders/{id}/items/{item_id}` `{version, quantity?, discount_percent?, mechanic_id?, name?, unit_price?, norm_hours?, sort_order?}` → `WorkOrder`. `quantity`, `unit_price`, `name`, `norm_hours`, `discount_percent` меняются только при `status = pending`, иначе 409 `item_started`. `mechanic_id` (`null` — снять) меняется, пока у позиции нет открытого интервала таймера, иначе 409 `item_active`; для `done|cancelled` → 409 `invalid_state`. `name/norm_hours` — только у произвольных работ (у каталожных 422 соответствующего поля). Цена каталожной позиции — только `director`.
  - `DELETE /work-orders/{id}/items/{item_id}?version=` → `WorkOrder`. Только `pending` без интервалов таймера; иначе 409 `item_started` (используйте отмену).
  - `POST /work-orders/{id}/items/{item_id}/cancel` `{version}` → `WorkOrder`. Из `pending|in_progress|paused`; открытый интервал таймера закрывается сервером; из `done` → 409 `invalid_state` (сначала вернуть в работу через `reopen`, модуль 6). Отменённая строка исключается из сумм.
  - `POST /work-orders/{id}/items/{item_id}/complete` `{version}` → `WorkOrder`. Ручное завершение менеджером (механик не вёл таймер в приложении): из `pending|in_progress|paused` → `done`, `finished_at = now()`, `started_at` ставится, если пусто; открытый интервал закрывается. Нужен назначенный механик, иначе 422 `fields.mechanic_id` (нужен для зарплаты). `actual_minutes` не меняется (остаётся суммой интервалов). Если после этого все неотменённые позиции `done` и заказ `in_progress` → автопереход в `quality_check` (общая функция сервиса `on_item_done(order)`, её же вызывает модуль 6) с записью в историю (`comment: "Все работы выполнены"`). Событие в Telegram от ручного завершения не публикуется.
- Назначение/смена механика (в `NewItem` или `PATCH`) публикует `work_item.assigned` (`target_user_id` — новый механик); снятие и повторное назначение того же — нет. Механик должен быть `role = mechanic`, активен и привязан к точке заказа, иначе 422 `fields.mechanic_id`.

### Запчасти и материалы
Тело создания: либо `{part_id, quantity, unit_price?, part_request_id?}` (из справочника), либо `{name, quantity, unit_price}` (произвольная/запчасть клиента; склад не затрагивается).
- Из справочника: `name`, `sku`, `unit` — снимок; `unit_price` по умолчанию `Part.sale_price`; отличие от `sale_price` — только `director` (иначе 403 `forbidden`). Запчасть должна быть активна, иначе 422 `fields.part_id`. `quantity` — `Qty3`.
- `part_request_id` (заявка механика, модуль 6): заявка должна принадлежать этому заказу и иметь статус `new|approved`; после добавления становится `issued` (`handled_by/at` заполняются). Несоответствие → 422 `fields.part_request_id`. Без модуля 6 поле не используется.
- Эндпоинты:
  - `POST /work-orders/{id}/parts` `{version, …}` → 201 `WorkOrder`
  - `PATCH /work-orders/{id}/parts/{part_row_id}` `{version, quantity?, unit_price?, name?}` → `WorkOrder` (`name` — только у произвольных; цена каталожной — только `director`)
  - `DELETE /work-orders/{id}/parts/{part_row_id}?version=` → `WorkOrder`
- Складские эффекты (**модуль 8**; в модуле 5 их нет): добавление позиции с `part_id` создаёт движение `issue_to_order` и заполняет `stock_movement_id` и `unit_cost`; изменение количества = возврат и новая выдача; удаление позиции и отмена заказа → `return_from_order`; нехватка остатка → 409 `insufficient_stock`. Сервис заказов вызывает единую точку входа `stock_service.issue_for_order / return_for_order`, которая в модуле 5 — заглушка без действий. Контракт модуля 8 описывает её сигнатуру.
- Изменение запчастей в статусах `closed|cancelled` → 409 `invalid_state`. Для `ready` разрешено (корректировка перед оплатой).

### Комментарии
- `GET /work-orders/{id}/comments?is_internal=` → `WorkOrderComment[]` (по возрастанию времени)
- `POST /work-orders/{id}/comments` `{text, item_id?, is_internal?}` → 201 `WorkOrderComment`. `text` 1..2000 (`SafeText`); `is_internal` по умолчанию `true` (комментарий «для клиента» — `false`, попадает в примечания заказ-наряда при печати); `item_id` — позиция этого заказа. Комментарии неизменяемы и неудаляемы. `version` не требуется и не изменяется. Комментарий с `item_id` у позиции с назначенным механиком публикует `work_item.updated` этому механику; комментарии в закрытом/отменённом заказе разрешены.

### Печатные формы
- `GET /work-orders/{id}/print/work-order` → `application/pdf` (заказ-наряд: номер, дата, клиент, авто, пробег, жалоба, состояние при приёме, работы с ценами и скидками, запчасти, итоги, срок, подписи сторон, комментарии `is_internal = false`)
- `GET /work-orders/{id}/print/act` → `application/pdf` (акт выполненных работ: только неотменённые работы со статусом `done` и запчасти; итоги). Доступен в статусах `ready|closed`, иначе 409 `invalid_state`.
- Ответ — тело PDF с `Content-Disposition: inline; filename="<number>-order.pdf"` / `-act.pdf`. Ошибки приходят обычным JSON, поэтому фронтенд скачивает PDF через общий `api()` как `Blob`, а не прямой ссылкой (нужен `Authorization`). Шаблоны — Jinja2 с `autoescape=True`, WeasyPrint; пользовательские данные только переменными. Заголовок документа — название и адрес точки (`Location`); реквизитов юрлица в системе нет.

### История клиента и авто
- `GET /clients/{id}/work-orders?status=&limit=&offset=` → `Page<WorkOrderListItem>`; `GET /vehicles/{id}/work-orders?…` → то же (для MG-09, MG-10; сортировка — `created_at` по убыванию). Менеджер видит только заказы своих точек (`total` тоже по ним); клиент/авто несуществующие или архивные — 200 для чтения истории архивного, 404 для несуществующего.

## Статусы
Разрешённые переходы (всё остальное → 409 `invalid_transition`):

| Из | В |
|---|---|
| `new` | `diagnostics`, `in_progress`, `cancelled` |
| `diagnostics` | `awaiting_approval`, `in_progress`, `cancelled` |
| `awaiting_approval` | `in_progress`, `diagnostics`, `cancelled` |
| `in_progress` | `awaiting_parts`, `quality_check`, `cancelled` |
| `awaiting_parts` | `in_progress`, `cancelled` |
| `quality_check` | `in_progress`, `ready`, `cancelled` |
| `ready` | `in_progress` (доработка), `closed`, `cancelled` |
| `closed`, `cancelled` | — (финальные) |

Условия:
| Условие | Ответ |
|---|---|
| Переход в `in_progress`, `quality_check`, `ready`, `closed` требует хотя бы одну неотменённую работу | иначе 409 `order_empty` |
| Переход в `ready` требует, чтобы все неотменённые работы были `done` | иначе 409 `items_not_done`, `details: {"pending_count": "2"}` |
| Переход в `cancelled` требует `cancel_reason` (1..500, `SafeText`) | иначе 422 `fields.cancel_reason` |
| Переход в `closed` — условия оплаты (модуль 9): заказ оплачен полностью или `force_close` | 409 `order_not_paid` (м9) |
| Переход в `cancelled` при чистых платежах (оплаты минус возвраты) больше нуля | 409 `has_payments` (м9) |
| Переход из статуса `ready` в `in_progress` | позиции остаются `done`; новые работы можно добавлять после перехода |

Побочные эффекты перехода (в одной транзакции): если после перехода статус заказа не `diagnostics|in_progress` — открытые интервалы таймера его работ закрываются, позиции `in_progress` становятся `paused` (вызов `timers.pause_all(order)`; реализует модуль 6); запись в `work_order_status_history` (`from_status`, `to_status`, `changed_by`, `comment`), `audit_log` (`action = status_change`, `entity_type = work_order`), отметки времени: `started_at` — первый вход в `in_progress` (или `diagnostics`, если раньше), `ready_at` — вход в `ready`, `closed_at` — вход в `closed`; при отмене все неотменённые работы получают `cancelled` (открытые интервалы таймера закрываются), запчасти возвращаются на склад (модуль 8); событий Telegram переходы статуса не создают (клиентских уведомлений нет; событие `work_order.ready_for_check` публикует модуль 6 при автопереходе в `quality_check` после завершения работы механиком). Автопереход `in_progress → quality_check` (последняя работа выполнена) пишет в историю `changed_by` = исполнитель/менеджер, выполнивший завершение, и `comment` «Все работы выполнены».

## Расчёт сумм
Пересчитываются сервером при любом изменении работ, запчастей, скидки (формулы фиксированы, чтобы тесты сходились):
- `item.total = round(quantity × unit_price × (1 − item.discount_percent / 100), 2)`; отменённые строки имеют `total` как обычно, но в суммы не входят.
- `works_total = Σ item.total` по неотменённым работам.
- `parts_total = Σ round(quantity × unit_price, 2)` по запчастям (`part.total` — это значение).
- `discount_total = round((works_total + parts_total) × discount_percent / 100, 2)` — скидка заказа применяется ко всей сумме (работы и запчасти); скидка строки работы — отдельная и уже входит в `item.total`.
- `total = works_total + parts_total − discount_total`.
- `balance_due = max(total − paid_total, 0)`. `paid_total` и `payment_status` ведёт модуль 9; в модуле 5 они всегда `"0.00"` и `unpaid`. Если `total` изменился, `payment_status` пересчитывается тем же кодом модуля 9 (хук `recalc_payment_status(order)` — заглушка в модуле 5).
- `norm_hours_total` позиции — `norm_hours × quantity` (без округления более двух знаков, `ROUND_HALF_UP`).

## Отдел заказа
`department` вычисляется по неотменённым работам: все `service` → `service`, все `detailing` → `detailing`, иначе `mixed`; без неотменённых работ сохраняется прежнее значение. Клиент `department` после создания не меняет.

## Правила и ошибки
| Правило | Ответ |
|---|---|
| `client_id`, `vehicle_id` существуют, не в архиве; `vehicle_id` принадлежит `client_id` | иначе 422 `fields.vehicle_id` / `fields.client_id` |
| `location_id` — своя точка (чужая → 404); для `manager` обязателен | иначе 404 / 422 |
| Версия не совпала | 409 `version_conflict` |
| Операция над `closed|cancelled` (кроме комментариев и чтения) | 409 `invalid_state` |
| Запись для заказа уже связана с заказом | 409 `appointment_has_order`, `details: {"work_order_id": "…", "work_order_number": "MSK1-000123"}` |
| Запись `no_show|cancelled` или другой точки/клиента/авто | 409 `invalid_state` (статус) / 422 `fields.appointment_id` (несовпадение) |
| Правка начатой позиции (`quantity`, цена, имя, норма, скидка) | 409 `item_started` |
| Смена механика при открытом интервале таймера | 409 `item_active` |
| Переход без активных работ | 409 `order_empty` |
| Переход в `ready` с невыполненными работами | 409 `items_not_done` |
| Недопустимый переход | 409 `invalid_transition` |
| Цена каталожной позиции изменена менеджером | 403 `forbidden` |
| `planned_ready_at` ранее момента создания минус 5 минут (при создании) | 422 `fields.planned_ready_at` |
| Скидка вне `0..100` / больше двух знаков | 422 `fields.discount_percent` |
| Нехватка остатка (модуль 8) | 409 `insufficient_stock` |
| Итог стал меньше оплаченного (модуль 9) | 409 `total_below_paid` |

Новые коды для `ERROR_MESSAGES`: `version_conflict`, `order_empty`, `items_not_done`, `item_started`, `item_active`, `appointment_has_order`; коды `total_below_paid`, `order_not_paid`, `has_payments`, `insufficient_stock` вводятся модулями 8–9, но фронтенд может добавить их сразу. Тексты `SafeText` — `complaint`, `intake_notes`, `diagnosis` ≤ 2000/2000/4000; `comment` статуса ≤ 500.

Аудит (`entity_type`): `work_order` (`create`, `update`, `status_change`), `work_order_item` (`create`, `update`, `delete`, `status_change` для `cancel/complete`), `work_order_part` (`create`, `update`, `delete`), `work_order_comment` (`create`); во всех — `location_id` заказа, `entity_id` строки; в `changes` строки заказа также пишется `work_order_id`.

## Миграция `0005_work_orders`
- Таблицы: `location_counters`, `work_orders`, `work_order_items`, `work_order_parts`, `work_order_status_history`, `work_order_comments` — по `docs/02-database-schema.md` §3.5 (все CHECK, индексы и значения по умолчанию оттуда).
- `ALTER TABLE appointments ADD CONSTRAINT appointments_work_order_id_fkey FOREIGN KEY (work_order_id) REFERENCES work_orders(id)` (колонка и уникальный индекс созданы миграцией модуля 4).
- `work_order_parts.stock_movement_id` создаётся **без** внешнего ключа (FK добавляет миграция `0008`).
- `location_counters` — строки создаются лениво (первый заказ точки); начальное заполнение не нужно.
- Права БД: `GRANT SELECT, INSERT, UPDATE, DELETE` на все шесть таблиц роли `crm_app`; в `work_order_status_history` и `work_order_comments` разрешены только `SELECT, INSERT`.
- Новых прав доступа (ролей) нет: используется матрица из раздела «Права».

## Зависимости
- Модуль 4 (записи; Appointment, миграция `0004a`), модуль 3 (услуги, цены точек, запчасти), модуль 2 (клиенты, авто), модуль 1 (пользователи, точки, аудит).
- Создаёт для следующих модулей: `events.publish` (заглушка), `get_setting`, `on_item_done`, `recalc_payment_status` (заглушка), `stock_service` (заглушка), `timers` (заглушка: `pause_all(order)`, `close_open_log(item)`, `has_open_log(item) -> False`; таблицы `work_logs` до модуля 6 нет, модуль 6 заменяет реализацию).

## Что можно разрабатывать параллельно
- Backend и frontend модуля 5 — по этому контракту независимо (frontend на MSW-моках).
- Модули 6, 8, 9 стартуют после merge миграции `0005` (таблицы заказов нужны для внешних ключей), но их контракты можно реализовывать параллельно с модулем 5 на копии схемы.
- Печатные формы (PDF-шаблоны) независимы от остального backend: отдельный агент.
- Расширение `Client` статистикой — отдельная небольшая задача на стыке с модулем 2.

## Экраны фронтенда (по `docs/03-ui-screens.md`)
Роли: `manager`, `director`. Для `mechanic` маршруты недоступны (редирект на `/`). Во всех: загрузка — скелетон; ошибка — блок «Не удалось загрузить» с кнопкой «Повторить» и кодом обращения; 404 → C-03; 409 `version_conflict` → диалог «Данные изменил другой сотрудник» → «Обновить» (перезапрос заказа).

| Код | Маршрут | Содержание и состояния |
|---|---|---|
| MG-04 | `/orders` | Переключатель «Таблица / Канбан» (запоминается в `localStorage`). Таблица: номер, дата, госномер, клиент, отдел, статус, механики, сумма, оплата, срок (просрочка красным), пагинация. Канбан: колонки из `GET /work-orders/board`, перетаскивание = `POST /status` (недопустимые колонки не принимают карточку по `allowed_transitions`; при ошибке карточка возвращается и показывается сообщение). Фильтры: статус, отдел, механик, период, «только просроченные», поиск; «сохранённые фильтры» — в `localStorage` по имени. Пусто: «Заказов пока нет» + кнопка «Новый заказ». Mobile: карточки вместо таблицы, канбан скрыт |
| MG-05 | `/orders/:id` | Шапка (номер, отдел, степпер статуса, клиент — телефон ссылкой `tel:`, авто, пробег, срок), вкладки «Работы», «Запчасти» (колонка «Остаток» — `in_stock`, «—» если `null`), «Комментарии» (внутренние / для клиента), «История». Правая липкая панель сумм и кнопок: «Следующий статус», «Принять оплату» (диалог MG-14 из модуля 9; до него кнопки нет), «Печать» (→ `/orders/:id/print`), меню «⋯» (Отменить с причиной, Дублировать). Работы: добавление поиском по каталогу (`GET /services?location_id=`) или «Произвольная работа»; редактирование количества/скидки/механика inline; для начатых строк поля заблокированы с подсказкой; «Завершить вручную», «Отменить строку». Цену каталожной строки редактирует только директор (у менеджера поле только для чтения). Состояния: пустые «Работ пока нет», «Запчастей нет»; заказ `closed|cancelled` — только чтение |
| MG-06 | `/orders/new` (`?appointment_id=`, `?client_id=&vehicle_id=`) | Мастер в одной форме: клиент (поиск, создание — формы модуля 2) → авто → пробег, жалоба, состояние при приёме → работы и механики → срок готовности. Из записи — клиент, авто, услуги подставляются и заблокированы для смены. Ошибка `appointment_has_order` → переход к существующему заказу (`/orders/:id`). Кнопка «Создать заказ» в карточке записи (календарь, модуль 4) ведёт сюда с `appointment_id` |
| MG-07 | `/orders/:id/print` (`?form=order|act`) | Предпросмотр PDF во встроенном просмотрщике (`blob:` URL), кнопки «Печать», «Скачать», переключатель формы; «Акт» недоступен до статуса «Готов». Состояния: загрузка, ошибка с «Повторить» |
| MG-01 | `/` (главная менеджера), `/today` | Частично: строка счётчиков из `GET /work-orders/summary` («в работе», «ждут запчасти», «готовы к выдаче», «просрочены» — клик ведёт в `/orders?status=…`) и лента записей на сегодня (`GET /appointments`, модуль 4) с кнопками «Приехал» → «Создать заказ». Блоки «Загрузка постов» и «Требует внимания» — модуль 10 (до него не отображаются). Пусто: «На сегодня записей нет» |
| — | `/clients/:id`, `/vehicles/:id` | Вкладка/блок «История заказов» (`GET /clients/{id}/work-orders`, `GET /vehicles/{id}/work-orders`) и итоги клиента (визитов, сумма, средний чек) — дополнение экранов MG-09, MG-10; в список клиентов (MG-08) добавляются колонки «Визитов», «Сумма», «Последний визит» |

Навигация: пункт «Заказ-наряды» сайдбара и «Заказы» нижней панели менеджера/директора → `/orders`. Домашний маршрут `/`: `mechanic` → M-01 (модуль 6), `manager` → MG-01, `director` → D-01 (модуль 10; до него — MG-01).
