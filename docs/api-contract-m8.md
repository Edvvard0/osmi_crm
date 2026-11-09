# Контракт API модуля 8 — Склад

Префикс `/api/v1`. Общие типы (`Money`, `Qty3`, `SignedQty3`, `Page<T>`, `UserRef`), округление, `events.publish`, аудит, правила миграций — в «Общих соглашениях» файла `api-contract-m5.md`. Формат ошибок, `extra="forbid"`, `SafeText` — как в модуле 1. Справочник запчастей (`Part`) — модуль 3, остатки и движения — этот модуль.

Склад ведётся **по точкам**: остаток запчасти принадлежит паре (точка, запчасть). Единица измерения, артикул, цена продажи берутся из `Part`. Механик к складу доступа не имеет (для заявок есть `GET /mechanic/parts` модуля 6).

## Права
| Операция | director | manager | mechanic |
|---|---|---|---|
| `GET /stock`, `GET /stock/{part_id}`, `GET /stock/movements` | любая точка | только свои точки (чужая → 404) | 403 |
| `PATCH /stock/{part_id}` (минимальный остаток) | ✓ | ✓ (своя точка) | 403 |
| `POST /stock/receipts` (приход) | ✓ | ✓ (своя точка) | 403 |
| `POST /stock/write-offs` (списание) | ✓ | ✓ (своя точка) | 403 |
| `POST /stock/transfers` (перемещение между точками) | ✓ | 403 | 403 |
| `POST /stock/inventory/commit` (инвентаризация) | ✓ | ✓ (своя точка) | 403 |
| `POST /stock/movements/{id}/reverse` (сторно) | ✓ | ✓ (движения своей точки, не старше 7 суток) | 403 |
| Себестоимость (`avg_cost`, `unit_cost`) в ответах | ✓ | ✓ | — |

Менеджер видит себестоимость собственной точки (это складской учёт, не прайс); механик остатков и себестоимости не видит нигде. `sale_price` — как в модуле 3. Выдача/возврат со склада происходит автоматически из заказ-нарядов (модуль 5) и от имени пользователя, который изменил заказ; отдельных эндпоинтов выдачи нет (кроме `POST /part-requests/{id}/issue` модуля 6, который идёт через тот же сервис).

## Типы
- `StockBalance` = `{location_id, part: PartBrief, quantity: Qty3|"0.000", min_quantity: Qty3|"0.000", avg_cost: Money, stock_value: Money, is_low: bool, updated_at: iso|null}`
  - `quantity` и `min_quantity` — строки с 3 знаками; допускается `"0.000"` (в отличие от `Qty3` движений).
  - `stock_value` = `ROUND(quantity × avg_cost, 2)`.
  - `is_low` = `min_quantity > 0 AND quantity < min_quantity`.
  - Строки для запчастей без записи остатка (`scope=all`) приходят с нулями, `updated_at = null`.
- `PartBrief` = `{id, sku, name, brand: str|null, barcode: str|null, unit, department, sale_price: Money, is_active: bool}` (поля `Part` модуля 3).
- `StockMovementType` = `"receipt"|"issue_to_order"|"return_from_order"|"write_off"|"transfer_out"|"transfer_in"|"adjustment"`
- `StockMovement` = `{id, location_id, part: {id, sku, name, unit}, movement_type, quantity: SignedQty3, unit_cost: Money, total: SignedMoney, balance_after: Qty3|"0.000", work_order: {id, number}|null, related_movement_id: uuid|null, reversed: bool, supplier: str|null, document_number: str|null, reason: str|null, created_by: UserRef, created_at}`
  - `total` = `ROUND(quantity × unit_cost, 2)`; `balance_after` — остаток после движения (хранится в строке, см. миграцию); `reversed = true`, если на это движение уже есть сторно.
- `StockReceiptLine` = `{part_id, quantity: Qty3, unit_cost: Money}`
- `StockWriteOffLine` = `{part_id, quantity: Qty3}`
- `StockTransferLine` = `{part_id, quantity: Qty3}`
- `InventoryLine` = `{part_id, expected_quantity: Qty3|"0.000", actual_quantity: Qty3|"0.000"}`

## Остатки
- `GET /stock?location_id=&search=&department=&scope=&sort=&order=&limit=&offset=` → `Page<StockBalance>` с дополнительным полем ответа верхнего уровня `totals: {positions: int, low_count: int, stock_value: Money}` (по всему отбору, а не по странице). Ответ: `{items, total, totals}`.
  - `location_id` **обязателен** для обоих ролей (нет → 422 `fields.location_id`; чужая точка менеджера → 404).
  - `search` — подстрока по `name`, `sku`, `brand`, `barcode` (триграммы); точное совпадение со `barcode` ранжируется первым (для сканера в MG-12).
  - `scope`: `stocked` (по умолчанию — есть строка остатка с `quantity > 0` или `min_quantity > 0`), `low` (только `is_low`), `all` (все активные запчасти справочника, `LEFT JOIN`).
  - `sort`: `name` (по умолчанию) | `sku` | `quantity` | `stock_value`; `order`: `asc|desc`. Неизвестное значение → 422.
- `GET /stock/{part_id}?location_id=` → `StockBalance` (200 и нули, если запчасть есть в справочнике, а остатка нет; 404 — если запчасти нет или точка недоступна).
- `PATCH /stock/{part_id}?location_id=` `{min_quantity: Qty3|"0.000"}` → `StockBalance`. Создаёт строку остатка, если её нет. Аудит `update` (`entity_type = "stock_balance"`, `entity_id` = `part_id`, `location_id`).

## Движения
- `GET /stock/movements?location_id=&part_id=&movement_type=&work_order_id=&date_from=&date_to=&limit=&offset=` → `Page<StockMovement>`; сортировка по `created_at` убыванию, затем `id`. `location_id` обязателен (как выше). Даты — `YYYY-MM-DD` в поясе точки, период ≤ 366 суток (иначе 422 `fields.date_to`). Для карточки позиции фронтенд передаёт `part_id`.

### Приход
`POST /stock/receipts` `{location_id, supplier?: SafeText ≤200, document_number?: SafeText ≤50, items: StockReceiptLine[1..100]}` → 201 `{movements: StockMovement[]}`.
- Одна строка запроса → одно движение `receipt` на позицию. Повтор `part_id` в `items` → 422 `fields.items` (складывать количества нужно на клиенте).
- Запчасть должна существовать и быть активной (иначе 422 `fields.items`).
- Пересчёт средней себестоимости: `new_avg = ROUND((q_old × avg_old + q_in × cost_in) / (q_old + q_in), 2)`; при `q_old = 0` `new_avg = cost_in`.
- `unit_cost` в движении — цена закупки строки. Аудит: одна запись `create` на приход (`entity_type = "stock_receipt"`, `entity_id` = id первого движения, `changes` — `{items: n, document_number}`), движения не дублируются в аудите.

### Списание
`POST /stock/write-offs` `{location_id, reason: SafeText 3..500, items: StockWriteOffLine[1..100]}` → 201 `{movements: StockMovement[]}`.
- Движения `write_off` с отрицательным `quantity`, `unit_cost` = текущая `avg_cost`; `avg_cost` не меняется.
- Нехватка остатка → 409 `insufficient_stock` (транзакция откатывается целиком).
- Может вызвать событие `stock.low` (ниже).

### Перемещение между точками (только директор)
`POST /stock/transfers` `{from_location_id, to_location_id, comment?: SafeText ≤500, items: StockTransferLine[1..100]}` → 201 `{out: StockMovement[], in: StockMovement[]}`.
- Точки должны различаться (иначе 422 `fields.to_location_id`) и быть активными.
- На каждую позицию создаются **два движения в одной транзакции**: `transfer_out` в исходной точке (по её `avg_cost`) и `transfer_in` в целевой с тем же `unit_cost` и `related_movement_id` = id `transfer_out`. Целевая `avg_cost` пересчитывается как при приходе. `reason` = `comment`.
- Нехватка в исходной точке → 409 `insufficient_stock`. Событие `stock.low` — для исходной точки.
- Аудит: `create`, `entity_type = "stock_transfer"`, `location_id` = исходная точка, `changes` — `{to_location_id, items: n}`.

### Инвентаризация
Фронтенд собирает таблицу «ожидаемое/фактическое» на странице (на основе `GET /stock?scope=stocked`), расхождения вычисляет сам; сервер принимает только позиции с изменениями.

`POST /stock/inventory/commit` `{location_id, comment?: SafeText ≤500, items: InventoryLine[1..500]}` → 201 `{movements: StockMovement[], skipped: int}`.
- Для каждой строки сервер под блокировкой сравнивает `expected_quantity` (то, что видел пользователь) с текущим остатком. Если не равны → 409 `stock_changed` `details: {"part_id": "…"}` (первая из изменившихся), ничего не записывается; пользователь перезагружает инвентаризацию.
- Если `actual_quantity` = текущему остатку — строка пропускается (`skipped += 1`). Иначе создаётся `adjustment` с `quantity = actual − current` (со знаком), `unit_cost` = `avg_cost`, `reason` = `comment` или `"Инвентаризация"`. `avg_cost` не меняется. Если фактический остаток больше и `avg_cost = 0` — допускается, себестоимость не определена; `unit_cost = "0.00"`.
- `actual_quantity` не может быть отрицательным (422 `fields.items`); повтор `part_id` → 422.
- Аудит: одна запись `create`, `entity_type = "stock_inventory"`, `changes` — `{adjusted: n, skipped: m}`.

### Сторно
`POST /stock/movements/{id}/reverse` `{reason: SafeText 3..500}` → 201 `StockMovement` (создаваемое обратное движение).
- Допустимо только для `receipt`, `write_off`, `adjustment`. Для `issue_to_order`/`return_from_order` — 409 `invalid_state` (они исправляются в заказе), для `transfer_*` — 409 `invalid_state` (делается обратным перемещением директором).
- Создаётся `adjustment` с обратным знаком, тем же `unit_cost`, `related_movement_id` = исходное, `reason`. Уже сторнированное → 409 `already_reversed`. Если обратное движение вывело бы остаток ниже нуля → 409 `insufficient_stock`.
- Для сторно прихода `avg_cost` не откатывается (остаётся текущей); движение лишь компенсирует количество.
- Менеджер — только для своей точки и для движений не старше 7 суток (иначе 403 `forbidden`).

## Правила учёта
- **Запрет отрицательного остатка**: `CHECK (quantity >= 0)` в БД и блокировка. Все изменения остатка идут через единый сервис `stock_service` в той же транзакции, что и движение.
- **Блокировки**: перед изменением строки выполняется `SELECT … FROM stock_balances WHERE (location_id, part_id) IN (…) ORDER BY location_id, part_id FOR UPDATE`; отсутствующие строки предварительно создаются `INSERT … ON CONFLICT DO NOTHING`. Один порядок блокировок для всех операций исключает взаимоблокировки; конкурентное списание последней единицы даёт ровно один успех, второй получает 409 `insufficient_stock`.
- **Себестоимость (средняя взвешенная)**: любое движение с положительным количеством (приход, возврат, `transfer_in`, положительная корректировка) пересчитывает `avg_cost` формулой прихода; отрицательные движения используют текущую `avg_cost` и её не меняют. Возврат из заказа идёт по `unit_cost` исходной выдачи.
- **Неизменяемость**: `stock_movements` — только `INSERT`; для роли `crm_app` `UPDATE/DELETE/TRUNCATE` отозваны (миграция). Исправление — обратным движением.
- **`balance_after`** фиксируется в строке движения в момент записи (под той же блокировкой).
- **Событие низкого остатка**: если после отрицательного движения (выдача, списание, `transfer_out`, отрицательная корректировка) остаток стал `< min_quantity` при `min_quantity > 0`, а до движения был `>= min_quantity`, публикуется `stock.low` (`location_id` точки, `actor_id`, payload и получатели — в `api-contract-m7.md`, ключей дедупликации нет: повторное событие возможно только после нового пересечения порога).

## Интеграция с заказ-нарядами (модуль 5) и заявками (модуль 6)
Модуль 8 **заменяет заглушки** в `backend/app/services/stock_service.py` (создана модулем 5):
```python
@dataclass(frozen=True)
class IssueResult:
    movement_id: UUID
    unit_cost: Decimal            # средняя себестоимость на момент выдачи

async def issue_for_order(session, *, order, part_id: UUID, quantity: Decimal,
                          actor_id: UUID) -> IssueResult | None: ...
async def return_for_order(session, *, order, part_row,
                           actor_id: UUID) -> None: ...
async def stock_for_parts(session, *, location_id: UUID,
                          part_ids: Collection[UUID]) -> dict[UUID, Decimal]: ...
```
- `issue_for_order` создаёт `issue_to_order` (количество со знаком «−», `work_order_id = order.id`, `unit_cost = avg_cost`) и под блокировкой проверяет остаток; нехватка → `AppError(409, "insufficient_stock", details={"part_id", "available", "requested"})`. Возвращает `None` (без движения), если `part_id` отсутствует (произвольная позиция).
- `return_for_order` по `part_row.stock_movement_id`: создаёт `return_from_order` на `part_row.quantity` с `unit_cost` исходного движения и `related_movement_id` = исходное; если `stock_movement_id` пуст — ничего не делает. Идемпотентно по движению (повторный вызов для уже возвращённой строки — no-op).
- `stock_for_parts` — одним запросом возвращает остатки для заполнения `WorkOrderPart.in_stock` и `PartRequestFull.part.in_stock` (после модуля 8 вместо `null`).
- Сервис заказов (модуль 5) вызывает:
  - добавление позиции с `part_id` (включая выдачу по заявке) → `issue_for_order`, значения `movement_id`/`unit_cost` записываются в `work_order_parts.stock_movement_id`/`unit_cost`;
  - изменение `quantity` позиции → `return_for_order` (старое) + `issue_for_order` (новое количество), `stock_movement_id`/`unit_cost` обновляются; изменение только цены склад не затрагивает;
  - удаление позиции → `return_for_order`;
  - переход заказа в `cancelled` → `return_for_order` для всех позиций со `stock_movement_id` (в порядке `part_id`);
  - закрытие заказа и любые другие переходы склад не затрагивают.
- Все вызовы идут в одной транзакции с изменением заказа; при `insufficient_stock` откатывается вся операция, `version` заказа не меняется.
- `WorkOrderPart.unit_cost` (себестоимость выдачи) заполняется из движения и по-прежнему видно **только `director`** (для менеджера всегда `null`, как в модуле 5; права модуля 5 не меняются). Остатки и `avg_cost` в самом складе менеджер своей точки видит.

Поле в `WorkOrderPart`/`PartRequestFull` `in_stock` — остаток на точке заказа (`SignedQty3`, фактически `>= 0`), для произвольных позиций `null`.

## Правила и ошибки
| Правило | Ответ |
|---|---|
| `location_id` отсутствует/недоступен | 422 `fields.location_id` / 404 |
| Запчасть не найдена или неактивна в строках | 422 `fields.items` |
| Повтор `part_id` в одной операции | 422 `fields.items` |
| Нехватка остатка | 409 `insufficient_stock`, `details: {part_id, available, requested}` (значения — строки `Qty3`) |
| Фактический остаток изменился после загрузки инвентаризации | 409 `stock_changed`, `details: {part_id}` |
| Сторно уже выполнено | 409 `already_reversed` |
| Сторно недопустимого типа | 409 `invalid_state` |
| Перемещение в ту же точку | 422 `fields.to_location_id` |
| Менеджер: перемещение | 403 `forbidden` |
| Менеджер: сторно старше 7 суток | 403 `forbidden` |
| Механик | 403 `forbidden` |

Новые коды для `ERROR_MESSAGES`: `insufficient_stock` (с подстановкой названия и «доступно N» из `details` — фронтенд собирает текст сам), `stock_changed`, `already_reversed`.

### Аудит
`entity_type`: `stock_balance` (`update`), `stock_receipt`, `stock_transfer`, `stock_inventory` (`create`), `stock_movement` (`create` для списания и сторно: `entity_id` = id движения; движения заказов отдельно не аудируются — они отражены в аудите заказа и в самой таблице движений).

## Миграция `0008_stock`
- Таблицы (`docs/02-database-schema.md` §3.6): `stock_balances` (PK `(location_id, part_id)`, `CHECK (quantity >= 0)`, `CHECK (min_quantity >= 0)`), `stock_movements`.
- Расширение `stock_movements` относительно схемы: колонка `balance_after numeric(12,3) NOT NULL` (остаток после движения), `CHECK (movement_type IN (…7 типов…))`, `CHECK (quantity <> 0)`. Индексы: `(location_id, part_id, created_at DESC)`, `(work_order_id)`, `(related_movement_id)`, `(location_id, created_at DESC)`; частичный `UNIQUE (related_movement_id) WHERE movement_type = 'adjustment' AND related_movement_id IS NOT NULL` — защита от двойного сторно.
- FK `work_order_parts.stock_movement_id → stock_movements(id)` (колонка создана в `0005` без FK; уникальный индекс уже есть).
- Права: `GRANT SELECT, INSERT, UPDATE, DELETE` на `stock_balances`; на `stock_movements` — `GRANT SELECT, INSERT`, плюс `REVOKE UPDATE, DELETE, TRUNCATE` (идемпотентно).
- Триггер/ограничение «движения неизменяемы» поверх прав (по желанию агента модуля): `BEFORE UPDATE OR DELETE` на `stock_movements` с `RAISE EXCEPTION`.
- Индекс `GIN (name gin_trgm_ops)`, `(sku gin_trgm_ops)` на `parts` уже создан в модуле 3.
- Новых ролей нет; новых прав в `permissions` нет (права — по ролям в таблице выше).

## Зависимости
- Модуль 5 (заказы, `stock_service`-заглушка, `work_order_parts.stock_movement_id`), модуль 3 (`Part`), модуль 1 (точки, доступ). Модуль 6 (`PartRequestFull.in_stock`, выдача по заявке) — только через тот же сервис. Событие `stock.low` — через `events.publish`; модуль 7 подключается независимо.
- Модуль 10 читает `stock_balances` и `stock_movements` для отчёта по складу; модуль 9 не связан.

## Что можно разрабатывать параллельно
- Backend: (а) `stock_service` + остатки/движения/сторно; (б) приход/списание/перемещение/инвентаризация — после (а); (в) подключение к заказам (замена заглушек) и расчёт `in_stock`.
- Frontend: экраны MG-11/MG-12 на MSW по этому контракту — независимо от backend; вкладка «Заявки механиков» использует `PartRequestsPanel` из модуля 6.
- Модуль 9 и модуль 7 — полностью независимы.

## Экраны фронтенда (по `docs/03-ui-screens.md`)
| Код | Маршрут | Роли | Содержание и состояния |
|---|---|---|---|
| MG-11 | `/stock` (вкладки `/stock`, `/stock/movements`, `/stock/requests`, `/stock/inventory`) | `manager`, `director` | Селектор точки (менеджер — из своих; director — любая; значение в URL `?location_id=`). **Остатки**: таблица (артикул, название, ед., остаток, минимум, средняя себестоимость, стоимость), дефицит (`is_low`) красным текстом, поиск, фильтр «Только дефицит», итоги `totals`. Кнопки «Приход» (→ MG-12) и «Списание» (диалог: позиции, причина). Директору — «Переместить». **Движения**: лента с фильтрами тип/период/запчасть, ссылка на заказ, «Сторно» с причиной. **Заявки механиков**: `PartRequestsPanel` (модуль 6), бейдж новых. **Инвентаризация**: загрузить остатки → ввести фактические → подсветить расхождения → «Провести» (подтверждение, итог «скорректировано N, без изменений M»); при `stock_changed` — «Остатки изменились, обновите страницу». Пусто: «На складе пока ничего нет» / «Движений нет». Загрузка — скелетон таблицы. Ошибка — баннер с «Повторить». Доступ механика → редирект на `/` |
| MG-12 | `/stock/receipt` | `manager`, `director` | Шапка: точка, поставщик, номер накладной. Таблица позиций: поиск по артикулу/названию/штрихкоду (поле принимает ввод сканера: Enter → точное совпадение по `barcode` добавляет строку или увеличивает количество), количество, цена закупки, сумма строки; итог документа. «Провести приход» неактивна без строк; ошибки полей `items` подсвечивают строки. После успеха — переход на `/stock` и уведомление «Приход проведён» |
| (карточка) | `/stock/:partId?location_id=` | `manager`, `director` | Остаток, минимум (редактируемый), средняя себестоимость, цена продажи, история движений позиции (`GET /stock/movements?part_id=`). Ссылка из таблицы остатков. Пусто: «Движений по позиции нет» |
| (расширения) | `/orders/:id` (MG-05) | `manager`, `director` | В таблице запчастей — остаток на точке (`in_stock`, красным, если меньше количества); ошибка `insufficient_stock` показывается под строкой («Недостаточно на складе: нужно N, доступно M») |
