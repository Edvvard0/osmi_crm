# Контракт API модуля 9 — Касса: оплаты и расходы

Префикс `/api/v1`. Общие типы (`Money`, `SignedMoney`, `Page<T>`, `UserRef`), округление, оптимистическая блокировка, события, аудит, правила миграций — в «Общих соглашениях» файла `api-contract-m5.md`. Формат ошибок, `extra="forbid"`, `SafeText` — как в модуле 1. Заказ-наряды (`WorkOrder`) — модуль 5.

Деньги принимаются и выдаются **только на точке**; интеграции с эквайрингом и онлайн-кассами в проекте нет — система фиксирует факт оплаты, введённый сотрудником. Все суммы — `Money` (строка, 2 знака), в БД `amount` всегда положительна, знак определяет тип операции.

## Права
| Операция | director | manager | mechanic |
|---|---|---|---|
| `POST /work-orders/{id}/payments` (приём оплаты) | любая точка | заказы своих точек | 403 |
| `GET /work-orders/{id}/payments` | ✓ | заказы своих точек | 403 |
| `POST /payments/{id}/refund` (возврат) | ✓ | **403** | 403 |
| Закрытие неоплаченного заказа (`force_close`) | ✓ (с комментарием) | **403** | 403 |
| `GET /expense-categories` | ✓ | ✓ | 403 |
| `POST/PATCH /expense-categories` | ✓ | 403 | 403 |
| `POST /expenses` | ✓ (любая дата ≤ сегодня) | своя точка, дата за последние 4 дня включая сегодня | 403 |
| `GET /expenses` | ✓ | только свои точки | 403 |
| `POST /expenses/{id}/cancel` | ✓ | 403 | 403 |
| `GET /cash/report`, `GET /cash/operations` | ✓ | только свои точки | 403 |
| Чужая точка/заказ | — | 404 | — |

Механик денег, оплат и расходов не видит и не получает в ответах; суммы `paid_total`/`balance_due` в `GET /mechanic/*` отсутствуют (как в модуле 6).

## Типы
- `PaymentMethod` = `"cash"|"card"|"transfer"|"other"`. В диалоге приёма оплаты (MG-14) предлагаются первые три; `other` допустим в API и для расходов.
- `PaymentType` = `"payment"|"refund"`
- `Payment` = `{id, work_order_id, order_number: str, location_id, payment_type: PaymentType, amount: Money, method: PaymentMethod, paid_at: iso, refund_of_id: uuid|null, refundable: Money|null, comment: str|null, accepted_by: UserRef, created_at}`
  - `refundable` — для `payment`: `amount` минус сумма уже сделанных по нему возвратов; для `refund` — `null`.
- `ExpenseCategory` = `{id, name, is_active: bool}`
- `Expense` = `{id, location_id, category: {id, name}, amount: Money, method: PaymentMethod, expense_date: "YYYY-MM-DD", description: str|null, created_by: UserRef, created_at, cancelled_at: iso|null, cancelled_by: UserRef|null}`
- `CashOperation` = `{kind: "payment"|"refund"|"expense", id, at: iso, method: PaymentMethod, amount: Money, signed_amount: SignedMoney, order: {id, number}|null, category: {id, name}|null, comment: str|null, user: UserRef, is_cancelled: bool, refundable: Money|null}`
  - `at` — `paid_at` или `created_at` расхода; `signed_amount`: `+` для `payment`, `−` для `refund` и `expense`; `is_cancelled` — только для расходов; `refundable` — только для `payment`.
- `MethodTotals` = `{method: PaymentMethod, received: Money, refunded: Money, net: SignedMoney}` — всегда 4 строки в порядке `cash, card, transfer, other`.
- `CashReport` = `{location_id, date_from, date_to, timezone, payments: MethodTotals[], received_total: Money, refunded_total: Money, net_total: SignedMoney, expenses_by_method: {method, total: Money}[], expenses_by_category: {category: {id, name}, total: Money}[], expenses_total: Money, cash_balance: SignedMoney}`
  - `cash_balance` = `net` по `cash` минус расходы по `cash` за период (движение наличных; инкассация/начальный остаток в системе не ведутся — это остаток **за период**, а не сумма в кассе).
  - Отменённые расходы в итоги не входят. Дни считаются в часовом поясе точки: период `[date_from 00:00, date_to + 1 день 00:00)`.
- Расширения `WorkOrderListItem` / `WorkOrder` (модуль 5): `paid_total` = **чистая** оплата (платежи минус возвраты), `balance_due = max(total − paid_total, 0)`, `payment_status` обновляется сервером; `WorkOrder` += `refunded_total: Money` (сумма всех возвратов по заказу). Остальные поля не меняются.

## Статус оплаты заказа
Пересчитывается при каждом платеже/возврате и при каждом изменении `total` заказа (функция `recalc_payment_status(session, order)`, заглушка которой создана в модуле 5; модуль 9 заменяет тело). Колонки `work_orders.paid_total` и `payment_status` — денормализованные, обновляются в той же транзакции. Пусть `net = Σ payment − Σ refund`:
| Условие | `payment_status` |
|---|---|
| платежей не было | `unpaid` |
| платежи были, `net = 0`, возвраты были | `refunded` |
| `0 < net < total` | `partial` |
| `net >= total` и `net > 0` | `paid` |
| `total = 0`, платежей нет | `paid` (платить нечего) |
| `net = 0` при `total > 0` и возвратов нет | `unpaid` |

`recalc_payment_status` при `total < net` (после уменьшения скидкой, удаления позиции и т. п.) бросает `AppError(409, "total_below_paid", details={"total": "…", "paid_total": "…"})`; вызывающий сервис модуля 5 откатывает транзакцию. Для закрытого и отменённого заказа изменения состава запрещены (модуль 5), поэтому проверка касается только открытых заказов.

## Оплаты
- `POST /work-orders/{id}/payments` `{amount: Money, method: PaymentMethod, comment?: SafeText ≤500, client_request_id?: uuid}` → 201 `{payment: Payment, order: WorkOrder}`.
  - `amount > 0` (иначе 422 `fields.amount`), не больше `balance_due` → иначе 409 `overpayment` `details: {balance_due}`. Если `balance_due = 0` → 409 `nothing_to_pay`. Заказ `cancelled` → 409 `invalid_state`. В остальных статусах (включая `new` — предоплата, и `closed` — для заказов, закрытых принудительно) приём разрешён.
  - `paid_at` — серверное время; клиент его не передаёт. `accepted_by` — текущий пользователь, `location_id` — точка заказа.
  - Идемпотентность: повторный запрос с тем же `client_request_id` того же пользователя возвращает ранее созданный платёж (200 вместо 201) и ничего не создаёт.
  - Заказ блокируется `SELECT … FOR UPDATE` на время операции; `version` заказа **не увеличивается** и в теле не передаётся (оплаты не конфликтуют с редактированием состава).
  - Аудит: `create`, `entity_type = "payment"`, `changes` — `{amount, method, order_number}`.
- `GET /work-orders/{id}/payments` → `Payment[]` (сортировка по `paid_at`, платежи и возвраты вместе). Не пагинируется.

## Возврат
- `POST /payments/{id}/refund` `{amount?: Money, comment: SafeText 3..500, client_request_id?: uuid}` → 201 `{payment: Payment, order: WorkOrder}` — только `director`.
  - `{id}` — платёж типа `payment` (возврат возврата → 409 `invalid_state`). `amount` по умолчанию — `refundable` платежа; больше `refundable` → 409 `refund_exceeds_payment` `details: {refundable}`.
  - Способ возврата совпадает со способом исходного платежа (`method` копируется), `refund_of_id` = id платежа. `comment` (причина) обязателен.
  - Пересчитывает `paid_total`/`payment_status`. Статус заказа не меняется (в том числе у `closed`).
  - Публикуется событие `payment.refund` (`location_id`, `actor_id`; payload и получатели — `api-contract-m7.md`). Аудит: `action = "refund"`, `entity_type = "payment"`, `entity_id` = id возврата, `changes` — `{amount, refund_of_id, reason}`.

## Закрытие и отмена заказа (расширение модуля 5)
`POST /work-orders/{id}/status` дополняется необязательным полем `force_close: bool` (по умолчанию `false`).
| Ситуация | Ответ |
|---|---|
| Переход в `closed`, `payment_status = paid` | ✓ |
| Переход в `closed`, не оплачен, `force_close = false` | 409 `order_not_paid` `details: {balance_due}` |
| `force_close = true`, роль `director`, `comment` непустой (1..500) | ✓; в историю статусов и аудит пишется отметка «закрыт без полной оплаты» (`changes.forced = true`, остаток долга в `changes.balance_due`) |
| `force_close = true`, `comment` пуст | 422 `fields.comment` |
| `force_close = true`, роль `manager` | 403 `forbidden` |
| Переход в `cancelled` при `paid_total > 0` | 409 `has_payments` (сначала оформляется возврат директором) |
| Переход в `cancelled` при `paid_total = 0` (возвраты были) | ✓ |

Поле `force_close` при другом `status` игнорируется только если `false`; `true` при ином статусе → 422 `fields.force_close`.

## Расходы
- `GET /expense-categories?include_inactive=false` → `ExpenseCategory[]` (по имени). Менеджеру и директору. Начальное содержимое (seed в миграции): «Аренда», «Коммунальные услуги», «Расходные материалы», «Инструмент и оборудование», «Реклама», «Налоги и сборы», «Хозяйственные расходы», «Прочее».
- `POST /expense-categories` `{name: SafeText 1..100}` → 201; дубль имени (без учёта регистра) → 409 `unique_violation`. Только `director`.
- `PATCH /expense-categories/{id}` `{name?, is_active?}` → `ExpenseCategory`. Деактивированная категория недоступна для новых расходов, в прошлых сохраняется. Только `director`. Аудит `create/update`, `entity_type = "expense_category"`.
- `POST /expenses` `{location_id, category_id, amount: Money, method: PaymentMethod, expense_date: "YYYY-MM-DD", description?: SafeText ≤500}` → 201 `Expense`.
  - `amount > 0`; `expense_date` не в будущем (по поясу точки) → иначе 422 `fields.expense_date`; для `manager` — не раньше «сегодня − 3 суток» (иначе 422 `fields.expense_date`); категория активна (иначе 422 `fields.category_id`); для `manager` точка из своих (чужая → 404). Аудит: `create`, `entity_type = "expense"`.
- `GET /expenses?location_id=&category_id=&method=&date_from=&date_to=&include_cancelled=&limit=&offset=` → `Page<Expense>` с верхнеуровневым `total_amount: Money` (по отбору без отменённых). Менеджер без `location_id` видит все свои точки; `location_id` чужой → 404. Период ≤ 366 суток. Сортировка: `expense_date` убыв., `created_at` убыв.
- `POST /expenses/{id}/cancel` `{reason?: SafeText ≤500}` → `Expense` (ставит `cancelled_at/by`). Повторная отмена → 409 `invalid_state`. Только `director`. Редактирования расходов нет — «отмена и ввод заново». Аудит: `update` (`changes: {cancelled_at}`, причина в `changes.reason`).

## Кассовый отчёт и операции
- `GET /cash/report?location_id=&date_from=&date_to=` → `CashReport`. `location_id` обязателен (нет → 422 `fields.location_id`; чужая точка менеджера → 404). `date_from` по умолчанию — сегодня (по поясу точки), `date_to` по умолчанию = `date_from`; `date_to < date_from` или период > 92 суток → 422 `fields.date_to`. Платежи — по `paid_at`, расходы — по `expense_date`.
- `GET /cash/operations?location_id=&date_from=&date_to=&kind=&method=&limit=&offset=` → `Page<CashOperation>`; сортировка по `at` убыванию. Содержит платежи, возвраты и расходы (в том числе отменённые, с `is_cancelled = true`, в итоги не входят). Те же правила `location_id`/дат.
- Сверка: `received_total − refunded_total` отчёта равно сумме `signed_amount` операций типов `payment|refund` за тот же период; `expenses_total` — сумме модулей `signed_amount` неотменённых расходов (тесты должны проверять равенство).

## Правила и ошибки
| Правило | Ответ |
|---|---|
| Оплата больше остатка | 409 `overpayment`, `details: {balance_due}` |
| Нечего оплачивать | 409 `nothing_to_pay` |
| Оплата отменённого заказа | 409 `invalid_state` |
| Возврат больше доступного | 409 `refund_exceeds_payment`, `details: {refundable}` |
| Возврат без причины | 422 `fields.comment` |
| Возврат менеджером | 403 `forbidden` |
| Закрытие без полной оплаты | 409 `order_not_paid`, `details: {balance_due}` |
| Отмена заказа с оплатой | 409 `has_payments` |
| Итог заказа стал меньше оплаченного | 409 `total_below_paid`, `details: {total, paid_total}` |
| Расход: дата вне окна менеджера / в будущем | 422 `fields.expense_date` |
| Расход: неактивная категория | 422 `fields.category_id` |
| Чужая точка/заказ у менеджера | 404 |
| Повторная отмена расхода | 409 `invalid_state` |

Новые коды для `ERROR_MESSAGES`: `overpayment`, `nothing_to_pay`, `refund_exceeds_payment`, `order_not_paid`, `has_payments`, `total_below_paid` (последние три введены в модуле 5, фронтенд может добавить сразу). Для `overpayment` и подобных фронтенд подставляет суммы из `details` самостоятельно (форматирование — на клиенте).

## События
- `payment.refund` — при возврате (см. выше). `order.discount_alert` публикует модуль 5 (порог скидки читается через `get_setting("discount_alert_percent")`, модуль 9 его не затрагивает).

## Миграция `0009_cash`
- Таблицы (`docs/02-database-schema.md` §3.7): `payments`, `expense_categories`, `expenses`.
- Расширение `payments`: колонка `client_request_id uuid NULL` и `UNIQUE (accepted_by, client_request_id) WHERE client_request_id IS NOT NULL`; `CHECK (payment_type = 'refund' OR refund_of_id IS NULL)`, `CHECK (payment_type = 'payment' OR refund_of_id IS NOT NULL)`.
- Индексы: `payments(location_id, paid_at)`, `payments(work_order_id)`, `payments(refund_of_id)`, `expenses(location_id, expense_date)`; уникальный индекс `lower(name)` на `expense_categories`.
- Seed категорий расходов (см. выше) выполняется в `upgrade()` (идемпотентно, `ON CONFLICT DO NOTHING`).
- `work_orders.paid_total`, `work_orders.payment_status` созданы модулем 5 — миграция их не трогает.
- Права БД: `GRANT SELECT, INSERT, UPDATE, DELETE` на `expense_categories`, `expenses`; на `payments` — `GRANT SELECT, INSERT` (платежи и возвраты неизменяемы; `REVOKE UPDATE, DELETE, TRUNCATE` на `payments` для `crm_app`).
- Новых ролей и прав в таблицах нет.

## Зависимости
- Модуль 5 (заказы, колонки `paid_total`/`payment_status`, `recalc_payment_status`, статусная машина), модуль 1 (точки, пользователи, аудит). Событие `payment.refund` — через `events.publish` (модуль 7 подключается независимо).
- Потребители: модуль 10 (выручка/кассовые отчёты читают `payments`, `expenses`), модуль 11 (аудит возвратов, категории расходов в D-09).

## Что можно разрабатывать параллельно
- Backend: (а) оплаты/возврат/`recalc_payment_status` + изменения статусной машины; (б) расходы и категории — независимо; (в) кассовый отчёт и операции — после (а) и (б).
- Frontend: диалог оплаты, форма расхода, MG-13 — на MSW по этому контракту. Модули 7 и 8 независимы.

## Экраны фронтенда (по `docs/03-ui-screens.md`)
| Код | Маршрут | Роли | Содержание и состояния |
|---|---|---|---|
| MG-13 | `/cash` | `manager`, `director` | Селектор точки (`?location_id=`), дата (по умолчанию сегодня; период — для директора и менеджера через «Период»). Блоки: итоги по способам оплаты (4 строки `MethodTotals`), расходы (по категориям), остаток наличных за период; список `CashOperation` (оплаты, возвраты — отдельным цветом/знаком, расходы; отменённые зачёркнуты); фильтры по типу и способу. Кнопка «Расход» открывает форму расхода (категория, сумма, способ, дата, описание); у директора в строке расхода — «Отменить». У платежа директору доступно «Вернуть» (диалог: сумма ≤ `refundable`, причина обязательна). Состояния: загрузка — скелетон блоков; пусто — «Операций за выбранный день нет» (итоги нулевые); ошибка — баннер «Не удалось загрузить кассу» с «Повторить» |
| MG-14 | диалог в `/orders/:id` (MG-05) | `manager`, `director` | Показывает «К оплате» (`balance_due`), поле суммы (по умолчанию остаток), способ кнопками «Наличные / Карта / Перевод»; для наличных — поле «Получено» и расчёт сдачи (только на клиенте, на сервер не передаётся). Двойная отправка блокируется + `client_request_id`. Ошибки: `overpayment` («Сумма больше остатка к оплате: X ₽»), `nothing_to_pay`. После успеха карточка заказа обновляется (`paid_total`, `payment_status`) |
| (блок) | `/orders/:id` (MG-05) | `manager`, `director` | Блок «Оплаты» в правой колонке/вкладке: список `Payment` (дата, способ, сумма, кто принял; возвраты со знаком «−» и причиной), кнопка «Принять оплату» (неактивна при `balance_due = 0` или `cancelled`), директору — «Вернуть». Кнопка «Закрыть заказ» при неполной оплате: менеджеру — ошибка `order_not_paid` («Заказ не оплачен полностью»), директору — диалог «Закрыть без полной оплаты» с обязательным комментарием (`force_close`) |
| (список) | `/orders` (MG-04) | `manager`, `director` | Колонка/бейдж `payment_status` (Не оплачен / Частично / Оплачен / Возврат), фильтр `payment_status` уже есть в модуле 5 |
| D-09 (часть) | `/system-settings` | `director` | Раздел «Категории расходов» (список, добавить, переименовать, деактивировать) — экран целиком описан в `api-contract-m11.md` |
