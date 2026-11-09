# Контракт API модуля 10 — Отчёты, аналитика, зарплата

Префикс `/api/v1`. Общие типы (`Money`, `SignedMoney`, `Hours`, `Qty2`, `Percent`, `Page<T>`, `UserRef`), округление, `events.publish`, `get_setting`, аудит, правила миграций — в «Общих соглашениях» файла `api-contract-m5.md`. Формат ошибок, `extra="forbid"`, `SafeText` — как в модуле 1. Ответы отчётов только читают данные модулей 5, 6, 8, 9; новых бизнес-данных модуль не создаёт, кроме схем оплаты и корректировок зарплаты.

## Права
| Операция | director | manager | mechanic |
|---|---|---|---|
| `GET /reports/dashboard` | ✓ (все точки или одна) | 403 | 403 |
| `GET /reports/{id}` и `/export` (выручка, услуги, механики, клиенты, склад, расходы, прибыль) | ✓ | 403 | 403 |
| `GET /reports/location-summary` | ✓ | только своя точка (чужая → 404) | 403 |
| `GET /dashboard/today` | ✓ | только своя точка | 403 |
| Зарплата: `GET /payroll*`, схемы и корректировки (все методы) | ✓ | 403 | 403 |
| `GET /me/earnings` | 403 | 403 | ✓ (только свои) |
| `GET /users/{id}/activity-heatmap`, `/activity-details` | любой сотрудник | механики, делящие с ним хотя бы одну точку; прочие, включая себя → 404 | только себя; прочие → 404 |

Менеджер не получает расходов, себестоимости, прибыли, зарплат и сведений других точек (`location-summary` намеренно без них). Механик не видит цен работ и скидок: в `GET /me/earnings` и в тепловой карте денег нет, а начисленная сумма — только итог.

## Общие правила отчётов
- **Период**: `date_from`, `date_to` — даты `YYYY-MM-DD` включительно; день определяется в часовом поясе **точки** (для набора из нескольких точек каждая считается по своему поясу). `date_to < date_from` или период > 366 суток → 422 `fields.date_to`; даты в будущем допустимы (дают нули). Значения по умолчанию: `date_to` — сегодня (APP_TIMEZONE), `date_from` — первое число месяца `date_to`.
- **Предыдущий период** (для сравнения) — столько же суток непосредственно перед `date_from`.
- **`location_id`** — необязателен для директора (все точки); неизвестная → 404. Менеджер: см. таблицу прав. Деактивированные точки в отчёт входят, если в них были данные.
- **Выручка** — сумма `work_orders.total` заказов в статусе `closed` с `closed_at` в периоде (по поясу точки заказа). Отменённые и открытые заказы не входят. Оплаты — отдельный показатель `cash_received` (чистые поступления из `payments`: платежи минус возвраты по `paid_at`). Эти два числа намеренно разные (сверка выручки дашборда с кассой выполняется по `cash_received`).
- **Работа заказа «учитывается»**, если её статус `done` и заказ `closed`; дата — `closed_at` заказа.
- **Чистая стоимость работы** (`item_net`) = `ROUND(item.total × (1 − order.discount_percent / 100), 2)` — основа зарплаты и отчёта «по механикам».
- Все суммы — `Money`/`SignedMoney`, проценты — `Percent` (строка, 2 знака), часы — `Hours`, счётчики — целые числа JSON внутри `Kpi`, но строки в ячейках таблиц (см. ниже).
- Расчёты — `Decimal`, `ROUND_HALF_UP`; деление на ноль даёт `null`, а не ошибку.

### Типы
- `Kpi` = `{kind: "money"|"count"|"percent", value: str, previous: str, delta: str|null}`
  - `value`/`previous`: `Money` для `money`, целое в виде строки для `count`, `Percent` для `percent`.
  - `delta` — изменение к предыдущему периоду: для `money` и `count` относительное, в процентах (`"12.50"`, `"-3.20"`), `null` при `previous = 0`; для `percent` — разность в процентных пунктах (`"-4.10"`).
- `LocationRef` = `{id, name}`.
- `ReportColumnKind` = `"text"|"money"|"hours"|"count"|"percent"|"date"`.
- `ReportColumn` = `{key, title, kind: ReportColumnKind}`
- `Report` = `{id: ReportId, title, date_from, date_to, location_id: uuid|null, columns: ReportColumn[], rows: object[], totals: object|null, chart: ReportChart|null, generated_at}`
  - `rows[i]` — объект `{<column.key>: str|null}`; значения всегда строки в формате `kind` (`Money`, `Hours`, целое, `Percent`, `YYYY-MM-DD`, текст) или `null`; дополнительно допускаются ссылочные ключи `*_id` (uuid) для переходов (`location_id`, `user_id`, `service_id`, `part_id`). Отдельной пагинации нет: строк не более 500 (превышение обрезается, `truncated` см. ниже).
  - `totals` — строка итогов по тем же ключам (или `null`, если итоги не имеют смысла).
  - `truncated: bool` — верхнеуровневое поле: `true`, если строки обрезаны лимитом.
- `ReportChart` = `{type: "line"|"bar", x: <column.key>, series: [{key: <column.key>, title}]}`
- `ReportId` = `"revenue"|"services"|"mechanics"|"clients"|"stock"|"expenses"|"profit"`

## Дашборд директора (D-01)
`GET /reports/dashboard?location_id=&date_from=&date_to=` → `Dashboard`:
```
{
  period: {date_from, date_to, previous_from, previous_to},
  location_id: uuid|null,
  kpis: {
    revenue: Kpi(money), cash_received: Kpi(money), orders_closed: Kpi(count),
    average_check: Kpi(money), post_load: Kpi(percent), detailing_share: Kpi(percent),
    conversion: Kpi(percent), new_clients: Kpi(count), repeat_clients: Kpi(count)
  },
  revenue_series: [{date, total: Money, by_location: [{location_id, total: Money}],
                    by_department: {service_works: Money, detailing_works: Money, parts: Money}}],
  locations: [{location: LocationRef, revenue: Money, orders_closed: int, average_check: Money,
               post_load: Percent, detailing_share: Percent}],
  top_services: [{service_id: uuid|null, name, quantity: Qty2, revenue: Money}],   // ≤ 10
  attention: {
    refunds:        {count: int, total: Money},
    big_discounts:  {count: int, threshold: Percent, items: AttentionOrder[]},      // ≤ 5
    overdue_orders: {count: int, items: AttentionOrder[]},                           // ≤ 5, текущее состояние
    low_stock:      {count: int, items: [{location: LocationRef, part: {id, sku, name}, quantity: str, min_quantity: str}]}  // ≤ 5, текущее состояние
  }
}
AttentionOrder = {id, number, location: LocationRef, value: str}   // value: % скидки либо planned_ready_at (iso)
```
Определения:
- `average_check` = `revenue / orders_closed` (0.00 при отсутствии заказов).
- `post_load` = занятые минуты постов / доступные минуты постов за период, ограниченный сегодняшним днём. Занятые — длительность записей со статусами `scheduled|confirmed|arrived` с `post_id`, начало в периоде; доступные — число активных постов × рабочие минуты точки (`work_start..work_end`) × число дней периода (до сегодня включительно). Больше 100 % не бывает (обрезается).
- `detailing_share` = `Σ item.total` по работам отдела `detailing` / `Σ item.total` по всем работам закрытых заказов (запчасти не учитываются).
- `conversion` = записей со статусом `arrived` / (`arrived` + `no_show`) среди записей периода (отменённые и ещё не наступившие не входят).
- `new_clients` — клиенты, у которых **первый** в сети закрытый заказ закрыт в периоде; `repeat_clients` — клиенты с закрытым заказом в периоде и с более ранним закрытым заказом.
- `by_department`: `service_works`/`detailing_works` — `Σ item.total` по отделу, `parts` — `Σ part.total`; значения **до скидки заказа**. Сумма трёх значений минус сумма скидок заказов (`discount_total`) равна `total` дня; отдельно скидки в рядах не передаются — для сверки служит отчёт `revenue`.
- `revenue_series` содержит каждый день периода (нули — явно); для периода > 92 суток точки группируются по неделям (`date` — понедельник недели), для > 366 суток период отклоняется.
- Блок `attention.refunds` — возвраты (`payment_type = refund`) за период; `big_discounts` — закрытые в периоде заказы со скидкой не ниже порога `get_setting("discount_alert_percent")`; остальные два блока показывают состояние «сейчас» независимо от периода.

## Сводка точки (MG-16)
`GET /reports/location-summary?location_id=&period=&date_from=&date_to=` → `LocationSummary`.
- `location_id` обязателен для менеджера (ровно своя; чужая → 404) и необязателен для директора (если не задан — первая по имени).
- `period`: `day` (сегодня), `week` (текущая неделя с понедельника), `month` (текущий месяц), `custom` (используются `date_from`/`date_to`); по умолчанию `day`. Для `day|week|month` границы вычисляются сервером по поясу точки.
- Ответ: `{location: LocationRef, date_from, date_to, revenue: Money, orders_closed: int, average_check: Money, post_load: Percent, series: [{date, revenue: Money, orders: int}], mechanics: [{user: UserRef, items_done: int, norm_hours: Hours, actual_hours: Hours, efficiency: Percent|null, works_amount: Money}]}`.
- Без расходов, себестоимости, прибыли и зарплат. `efficiency` = `norm_hours / actual_hours × 100` (`null` при `actual_hours = 0`); считается по работам, учтённым за период (определение выше).

## Сводка дня (MG-01, расширение)
`GET /dashboard/today?location_id=` → `DashboardToday`; менеджеру обязателен свой `location_id` (если у менеджера одна точка — можно опустить), директору — любая.
```
{ server_time, location: LocationRef, date,
  revenue_today: Money, cash_received_today: Money, orders_closed_today: int,
  orders_open: int, overdue: int, ready_for_pickup: int,
  appointments_today: int, post_load_today: Percent, low_stock_count: int,
  mechanics: [{user: UserRef, active_item: {item_id, name, order_number}|null,
               items_in_progress: int, items_done_today: int}] }
```
Счётчики `orders_open|overdue|ready_for_pickup|appointments_today` совпадают с `GET /work-orders/summary` модуля 5 и `GET /appointments` модуля 4 (источник тот же, расхождений быть не должно); `post_load_today` считается по правилу `post_load`. Это единственный запрос MG-01 после модуля 10; лента записей остаётся запросом `GET /appointments` модуля 4.

## Отчёты (D-02)
`GET /reports/{id}?location_id=&department=&date_from=&date_to=&…` → `Report`; параметр `department` (`service|detailing`) учитывается там, где указано. Неизвестный `id` → 404. Колонка `title` — русское название, используемое и в таблице, и в экспорте.

### `revenue` — выручка по точкам и отделам
Параметр `group_by=location|day|month` (по умолчанию `location`). Колонки: `group` (text; название точки либо дата), `orders_closed` (count), `service_works` (money), `detailing_works` (money), `parts` (money), `discounts` (money, положительное число — сумма скидок), `revenue` (money), `average_check` (money). Формула строки: `revenue = service_works + detailing_works + parts − discounts`. График: `bar` (по точкам) или `line` (по дням/месяцам) по `revenue`.

### `services` — по услугам
Строки — услуги (произвольные работы одной строкой «Прочие работы (вручную)», `service_id = null`). Колонки: `name`, `department` (text), `quantity` (count с двумя знаками), `orders` (count), `revenue` (money, `Σ item.total`), `share` (percent от суммы). Сортировка по `revenue` убыв., не более 200 строк. Параметр `department`.

### `mechanics` — по механикам
Колонки: `mechanic` (text, `user_id`), `locations` (text, названия через запятую), `items_done` (count), `norm_hours` (hours, `Σ norm_hours_total`), `actual_hours` (hours, `Σ actual_minutes / 60`), `efficiency` (percent, `norm_hours / actual_hours`), `works_amount` (money, `Σ item.total`), `net_amount` (money, `Σ item_net`). Параметры `department`, `location_id` (по точке заказа). Сортировка по `works_amount` убыв.

### `clients` — клиенты
Колонки по точке (`group_by=location`) либо по месяцу (`group_by=month`): `group`, `new_clients`, `repeat_clients`, `orders_closed`, `average_check` (money), `lapsed_clients` (count). Новый клиент относится к точке своего первого заказа. `lapsed_clients` — клиенты, у которых был закрытый заказ за 180–365 суток до `date_to`, но нет за последние 180 суток (показатель на конец периода).

### `stock` — склад (оборот, маржа)
Строки — запчасти точки/сети. Колонки: `part` (text, `part_id`), `sku` (text), `sold_quantity` (count с тремя знаками; позиции заказов, закрытых в периоде), `revenue` (money, `Σ part.total`), `cost` (money, `Σ quantity × unit_cost`), `margin` (money), `margin_percent` (percent), `received_value` (money, приходы периода по `stock_movements`), `stock_value` (money, текущая стоимость остатка — `quantity × avg_cost` на момент формирования). Запчасти без `part_id` (произвольные) в отчёт не входят. До 500 строк, сортировка по `revenue`.

### `expenses` — расходы
Параметр `group_by=category|location|month` (по умолчанию `category`). Колонки: `group` (text), `count` (count), `total` (money). Только неотменённые расходы (модуль 9) по `expense_date`. График `bar`.

### `profit` — прибыль (упрощённый P&L)
Периоды выравниваются по календарным месяцам: `date_from` — первое число месяца, `date_to` — последний день месяца (иначе 422 `fields.date_from` / `fields.date_to`). Строки — точки. Колонки: `group` (text), `revenue` (money), `parts_cost` (money, `Σ quantity × unit_cost` запчастей закрытых заказов; произвольные позиции без себестоимости считаются нулём), `payroll` (money, начисленная зарплата работников, привязанных к точке, за все месяцы периода — по правилам раздела «Зарплата»), `expenses` (money), `profit` (money со знаком = `revenue − parts_cost − payroll − expenses`), `margin_percent` (percent, `profit / revenue`). Итоговая строка суммирует точки. Окладные части и корректировки сотрудника с несколькими точками относятся к его первой по имени точке.

### Экспорт
`GET /reports/{id}/export?format=xlsx|csv&…` (те же параметры) → файл (`Content-Disposition: attachment; filename="report-<id>-<date_from>_<date_to>.<ext>"`). Правила:
- XLSX: один лист, заголовки из `columns[].title`, числовые колонки (`money|hours|count|percent`) — числами с форматом, остальные — строками; CSV: UTF-8 с BOM, разделитель `;`, десятичная точка заменяется запятой в числовых колонках.
- **Защита от формульных инъекций**: значения текстовых колонок, начинающиеся с `=`, `+`, `-`, `@`, табуляции или возврата каретки, получают префикс `'`; числовые колонки не изменяются.
- Лимит — 100 000 строк (для отчётов это недостижимо; лимит страхует экспорт ведомости и журнала). Частота — 10 экспортов в минуту на пользователя (429 `rate_limited`).
- Каждый экспорт пишется в аудит: `action = "export"`, `entity_type = "report"` (`payroll` для ведомости), `changes` — `{report_id|kind, format, date_from, date_to, location_id}`.

## Зарплата (D-03)
Расчёт **не хранится**: ведомость вычисляется по выполненным работам, схемам и корректировкам. Данные за закрытые периоды изменяются только вместе с исходными данными (поэтому правила схем ниже ограничивают ретроспективные изменения).

### Типы
- `PayrollSchemeType` = `"percent_of_works"|"per_norm_hour"|"fixed_plus_percent"|"fixed"`
- `PayrollScheme` = `{id, user: UserRef, scheme_type, percent: Percent|null, norm_hour_rate: Money|null, fixed_monthly: Money|null, department: Department|null, valid_from: "YYYY-MM-DD", valid_to: "YYYY-MM-DD"|null, is_current: bool, description: str, created_by: UserRef, created_at}`
  - `description` — читаемое описание на русском («40 % от работ», «500 ₽ за нормочас», «30 000 ₽ в месяц + 10 %»), формируется сервером.
  - `is_current` — действует сегодня (по APP_TIMEZONE).
- `PayrollAdjustment` = `{id, user: UserRef, month: "YYYY-MM", amount: SignedMoney, reason: str, created_by: UserRef, created_at}`
- `PayrollRow` = `{user: UserRef, locations: LocationRef[], scheme_summary: str, items_done: int, norm_hours: Hours, base_amount: Money, accrued: Money, adjustments_total: SignedMoney, total: SignedMoney, items_without_scheme: int}`
  - `base_amount` = `Σ item_net` учтённых работ; `accrued` — начислено по схеме (вместе с окладной частью); `total = accrued + adjustments_total`.
  - `scheme_summary` — описание действующих в месяце схем через « · » (или «Схема не задана»).
- `PayrollSheet` = `{month: "YYYY-MM", location_id: uuid|null, rows: PayrollRow[], totals: {items_done: int, norm_hours: Hours, base_amount: Money, accrued: Money, adjustments_total: SignedMoney, total: SignedMoney}}`
- `PayrollItemLine` = `{item_id, order: {id, number}, closed_at, name, department: Department, quantity: Qty2, norm_hours_total: Hours, item_net: Money, scheme_id: uuid|null, amount: Money}`
- `PayrollFixedLine` = `{scheme_id, days: int, days_in_month: int, amount: Money}`
- `PayrollDetail` = `{row: PayrollRow, items: PayrollItemLine[], fixed: PayrollFixedLine[], adjustments: PayrollAdjustment[], schemes: PayrollScheme[]}`

### Правила расчёта
1. **Что учитывается**: позиции заказов `closed`, статус позиции `done`, `mechanic_id` = сотрудник, `closed_at` заказа в месяце (по поясу точки заказа). Позиции без исполнителя не начисляются никому.
2. **Схема позиции**: схема сотрудника, действующая в дату закрытия заказа (`valid_from <= дата <= valid_to` или `valid_to IS NULL`), с `department` = отделу позиции; если такой нет — схема с `department = NULL`; если нет и её — позиция начисляется нулём и считается в `items_without_scheme`.
3. **Формулы позиции**: `percent_of_works` — `ROUND(item_net × percent / 100, 2)`; `per_norm_hour` — `ROUND(norm_hours_total × norm_hour_rate, 2)`; `fixed_plus_percent` — процентная часть как у `percent_of_works`; `fixed` — позиции не начисляются. Сумма по позициям — сумма округлённых значений.
4. **Оклад** (`fixed`, `fixed_plus_percent`; только схемы с `department = NULL`): за каждую схему, пересекающуюся с месяцем, `ROUND(fixed_monthly × дней_пересечения / дней_в_месяце, 2)` — вне зависимости от выполненных работ.
5. **Корректировки**: `Σ amount` записей `payroll_adjustments` за месяц (премии `+`, удержания `−`).
6. **Состав ведомости**: сотрудники с хотя бы одной учтённой позицией, схемой, пересекающей месяц, или корректировкой за месяц. Фильтр `location_id`: позиции — по точке заказа; сотрудники с окладом/корректировкой без позиций — по привязке `user_locations`.
7. Роли в ведомости не ограничены (оклад могут иметь менеджеры), но позиции начисляются только механикам.

### Эндпоинты (только `director`)
- `GET /payroll?month=YYYY-MM&location_id=` → `PayrollSheet`. `month` по умолчанию — текущий; будущий месяц → 422 `fields.month`.
- `GET /payroll/{user_id}?month=` → `PayrollDetail` (раскрытие строки). Сотрудник не найден → 404.
- `GET /payroll/export?month=&location_id=&format=xlsx|csv` → файл ведомости (колонки `PayrollRow`; правила экспорта выше).
- Схемы:
  - `GET /payroll/schemes?user_id=` → `PayrollScheme[]` (по `valid_from` убыв.).
  - `POST /payroll/schemes` `{user_id, scheme_type, percent?: Percent, norm_hour_rate?: Money, fixed_monthly?: Money, department?: Department|null, valid_from}` → 201 `PayrollScheme`.
    - Обязательные поля по типу: `percent_of_works` — `percent`; `per_norm_hour` — `norm_hour_rate`; `fixed_plus_percent` — `percent` и `fixed_monthly`; `fixed` — `fixed_monthly` и `department = null`. Лишние поля → 422 по этим ключам. Схемы с окладом (`fixed*`) допускают только `department = null`.
    - Если у сотрудника в той же области (`department` либо общая) есть **открытая** схема с `valid_from < новая.valid_from`, она закрывается: `valid_to = новая.valid_from − 1 день`. Любое иное пересечение интервалов (в том числе открытая схема с `valid_from >= новая.valid_from`) → 409 `scheme_overlap`. Схема с `department = NULL` и схема конкретного отдела могут действовать одновременно (приоритет у отдельной).
    - `valid_from` не раньше первого числа текущего месяца (APP_TIMEZONE) → иначе 422 `fields.valid_from` (чтобы задним числом не менялись закрытые месяцы); для первой схемы сотрудника ограничения нет (но не позже чем +366 дней).
    - Аудит: `create`, `entity_type = "payroll_scheme"`, `entity_id`, `changes`.
  - `PATCH /payroll/schemes/{id}` `{valid_to}` → `PayrollScheme` — только установка даты окончания (`valid_to >= valid_from` и не раньше первого числа текущего месяца, иначе 422 `fields.valid_to`); изменять тип и ставки нельзя (создаётся новая схема). Пересечение со следующей схемой → 409 `scheme_overlap`. Аудит `update`.
  - `DELETE /payroll/schemes/{id}` → 204 — только схема, которая начинается в будущем (`valid_from > сегодня`); иначе 409 `invalid_state`. Аудит `delete`.
- Корректировки:
  - `GET /payroll/adjustments?user_id=&month=` → `PayrollAdjustment[]` (по `created_at` убыв.; оба фильтра необязательны).
  - `POST /payroll/adjustments` `{user_id, month: "YYYY-MM", amount: SignedMoney, reason: SafeText 1..500}` → 201 `PayrollAdjustment`. `amount != 0` (иначе 422 `fields.amount`); `month` не в будущем (иначе 422 `fields.month`); сотрудник существует и активен. Редактирования и удаления нет — ошибка исправляется записью с обратным знаком. Аудит: `create`, `entity_type = "payroll_adjustment"`.

### Заработок механика (M-07)
`GET /me/earnings?month=YYYY-MM` (только `mechanic`) → `MyEarnings`:
```
{ month, accrued: Money, adjustments_total: SignedMoney, total: SignedMoney,
  items_done: int, norm_hours: Hours, actual_hours: Hours,
  adjustments: [{amount: SignedMoney, reason: str, created_at}],
  awaiting_close: {items_count: int, norm_hours: Hours},
  days: [{date, items: [{item_id, order: {id, number}, plate_number: str|null, name,
                         norm_hours_total: Hours, actual_minutes: int, finished_at}]}],
  server_time }
```
- `accrued` считается по тем же правилам (включая оклад); цен работ, `item_net`, скидок и ставок в ответе нет.
- `awaiting_close` — работы механика со статусом `done` в заказах, которые ещё не `closed` (в начисление пока не вошли).
- `days` — только учтённые работы, по дням `closed_at` (в поясе точки), по убыванию даты. Будущий месяц → 422 `fields.month`.

## Тепловая карта активности (D-05, MG-17, M-07)
### Эндпоинт
`GET /users/{id}/activity-heatmap?from=YYYY-MM-DD&to=YYYY-MM-DD` → `ActivityHeatmap`.
- `to` по умолчанию — сегодня, `from` — `to − 364 суток`. `to < from` или период > 366 дней (включительно) → 422 `fields.to`. Дни позже сегодняшнего (по поясу пользователя) в ответ не попадают.
- Права — см. таблицу выше; сотрудник вне доступа и несуществующий → 404 (без различия).
- Тип активности определяется ролью **просматриваемого**: `mechanic` → `kind = "hours"`, `manager|director` → `kind = "actions"`.

```
ActivityHeatmap = {
  user: UserRef, kind: "hours"|"actions", from, to, timezone: str, first_day: "YYYY-MM-DD",
  thresholds: [t1, t2, t3],          // числа: для hours — часы, для actions — действия
  days: [ActivityDay],               // каждый день периода (≤ сегодня), включая нулевые
  summary: {working_days: int, total_hours: Hours|null, total_actions: int|null,
            average_per_working_day: str, longest_streak_days: int}
}
ActivityDay = {date, minutes: int|null, hours: Hours|null, actions: int|null,
               works_count: int, level: 0|1|2|3|4, order_numbers: str[]}
```
- Для `hours` поля `actions = null`; для `actions` — `minutes = hours = null`.
- `first_day` — дата создания учётной записи (для серой «до приёма» области).
- `thresholds` берутся из `get_setting("heatmap_thresholds")` по `kind`; значения по умолчанию — в `api-contract-m11.md` (`hours: [2, 5, 8]`, `actions: [5, 15, 30]`).
- **Уровни**: 0 — активности нет; 1 — значение `<= t1`; 2 — `<= t2`; 3 — `<= t3`; 4 — выше `t3`. Для `hours` сравнение идёт по точной длительности (секунды / 3600), а не по округлённому `hours`.
- `summary`: `working_days` — число дней с уровнем ≥ 1; `total_hours` (`hours`) / `total_actions` (`actions`); `average_per_working_day` — строка с двумя знаками (часы) либо с одним (действия), `"0.00"`/`"0.0"` при отсутствии рабочих дней; `longest_streak_days` — наибольшая последовательность **подряд идущих календарных** дней с уровнем ≥ 1.
- `order_numbers` — до 10 номеров заказов дня (для подсказки), по убыванию активности; `works_count` — полное число (механик: различные позиции с интервалами в этот день; менеджер/директор: различные заказы, затронутые действиями).

### Источники и границы дней
- **Механик**: интервалы `work_logs` (модуль 6) — пауза не учитывается (между интервалами таймер не идёт); интервал, пересекающий полночь, делится между двумя днями; незавершённый интервал считается до `now()`. Границы дня — в часовом поясе **точки заказа** интервала. `timezone` ответа — пояс первой по имени точки сотрудника (информационно).
- **Менеджер/директор**: строки `audit_log` с `user_id` пользователя, кроме `action IN ('login', 'login_failed', 'logout', 'token_reuse', 'password_change')`. День — по поясу `audit_log.location_id` (если пусто — APP_TIMEZONE). `works_count` — различные `entity_id` типа `work_order`.
- Производительность: год по одному сотруднику < 200 мс (индексы `work_logs (mechanic_id, started_at)`, `audit_log (user_id, created_at DESC)`); отдельная таблица не создаётся.

### Детализация дня
`GET /users/{id}/activity-details?date_from=&date_to=` (те же права) → `ActivityDetails`; период ≤ 31 суток (иначе 422 `fields.date_to`), по умолчанию `date_from = date_to = сегодня`.
```
ActivityDetails = {user: UserRef, kind, days: [
  { date, total_minutes: int|null, actions: int|null, truncated: bool,
    entries: [ HoursEntry | ActionEntry ] } ]}          // days по убыванию даты, пустые дни не включаются
HoursEntry  = {order: {id, number}, plate_number: str|null, item_id, item_name, started_at, ended_at: iso|null, minutes: int}
ActionEntry = {at, action, entity_type, entity_id: uuid|null, label: str, order_number: str|null}
```
- В `entries` не более 200 записей на день (`truncated = true`, если обрезано); `minutes` в `HoursEntry` — часть интервала, попавшая в этот день.
- `label` — читаемое описание («Заказ MSK1-000123: смена статуса»); персональные данные клиентов и значения полей `changes` в `ActionEntry` не передаются.

## Ежедневная сводка директору
Задача `daily_summary` реестра воркера (`api-contract-m7.md`, раздел «Воркер»), запускается каждую минуту и срабатывает, когда текущее время в APP_TIMEZONE достигло `get_setting("daily_summary_time")` и сводка за сегодня ещё не отправлялась. Факт отправки хранится в памяти процесса воркера (последняя обработанная дата), а от дублей после перезапуска защищает уникальный `dedup_key` в `notification_outbox` (повторная вставка — no-op). Отдельного состояния в БД нет: таблица `system_settings` появляется только в миграции `0011`, а модуль 10 от неё не зависит. Значение `null` отключает сводку.
- Данные: по каждой активной точке — «сегодня» по её поясу: `revenue`, `orders_closed`, `orders_open`, `cash_received`.
- Публикуется **одно** событие `report.daily_summary` (`location_id = None`, `dedup_key = "report.daily_summary:{date}"`) с payload: `date`, `location_name = null`, `revenue`, `orders_closed`, `orders_open`, `cash_received` (суммы по сети) и `breakdown` — многострочная строка «Название точки: 125 000 ₽ · 14 заказов · касса 98 000 ₽».

## Правила и ошибки
| Правило | Ответ |
|---|---|
| Менеджер/механик обращается к отчётам директора | 403 `forbidden` |
| Менеджер: чужая точка | 404 |
| Период > лимита / `to < from` | 422 `fields.date_to` (для тепловой карты — `fields.to`) |
| Отчёт `profit` не по календарным месяцам | 422 `fields.date_from` / `fields.date_to` |
| Неизвестный отчёт | 404 |
| Схема пересекается с другой | 409 `scheme_overlap` |
| Удаление действующей/прошедшей схемы | 409 `invalid_state` |
| `valid_from`/`valid_to` в закрытом месяце | 422 `fields.valid_from` / `fields.valid_to` |
| Корректировка с нулевой суммой / будущий месяц | 422 `fields.amount` / `fields.month` |
| Слишком частый экспорт | 429 `rate_limited` |
| Карта чужого сотрудника | 404 |

Новый код для `ERROR_MESSAGES`: `scheme_overlap` («Для этого сотрудника на выбранные даты уже действует схема»).

## Аудит
`entity_type`: `payroll_scheme` (`create|update|delete`), `payroll_adjustment` (`create`), `report`/`payroll` (`export`). Действие `export` добавляется в общий список `action` (см. `api-contract-m11.md`). Просмотры отчётов не аудируются.

## Миграция `0010_reports_payroll`
- Таблицы (`docs/02-database-schema.md` §3.8): `payroll_schemes`, `payroll_adjustments`.
- `payroll_schemes`: все `CHECK` по схеме (диапазон процента, тип, отдел) и дополнительные — набор обязательных полей по `scheme_type`; exclusion-ограничение `EXCLUDE USING gist (user_id WITH =, (coalesce(department, '*')) WITH =, daterange(valid_from, valid_to, '[]') WITH &&)` (расширение `btree_gist` уже установлено).
- `payroll_adjustments`: `period_month date` (первое число месяца), `CHECK (amount <> 0)`.
- Индексы для отчётов (частичные/составные): `work_orders (location_id, closed_at) WHERE status = 'closed'`; `work_order_items (mechanic_id, finished_at) WHERE status = 'done'` (если не создан в `0005`); `payments (location_id, paid_at)` и `expenses (location_id, expense_date)` уже есть (`0009`); `work_logs (mechanic_id, started_at)` — `0006`; `audit_log (user_id, created_at DESC)` — `0001`. Материализованные представления не входят в контракт: если замеры (отчёт за год по 100 тыс. заказов < 2 с) потребуют, их добавляет этот же модуль без изменения форматов ответов.
- Права БД: `payroll_schemes` — `SELECT, INSERT, UPDATE, DELETE`; `payroll_adjustments` — `SELECT, INSERT` (записи неизменяемы).
- Новых прав доступа в таблицах нет.

## Зависимости
- Модули 5 (заказы), 6 (`work_logs`, `actual_minutes`), 8 (склад: отчёт `stock`, `low_stock`), 9 (платежи, расходы, возвраты), 4 (записи для `post_load`, `conversion`), 1 (аудит, пользователи), 7 (воркер и событие `report.daily_summary`), 11 (чтение `heatmap_thresholds`, `discount_alert_percent`, `daily_summary_time` через `get_setting`; до его выхода — значения по умолчанию из кода).
- Отчёты можно собирать по неполным данным: если модули 8–9 ещё не влиты, соответствующие показатели равны нулю, а отчёты `stock`, `expenses`, `profit` возвращают пустые таблицы.

## Что можно разрабатывать параллельно
- Backend: (а) тепловая карта (зависит только от `work_logs` и `audit_log`); (б) зарплата (схемы, корректировки, ведомость, `/me/earnings`); (в) дашборд и отчёты — независимо друг от друга по отчётам; (г) экспорт — после общего формата `Report`; (д) ежедневная сводка — после модуля 7.
- Frontend: общий компонент `ActivityHeatmap` пишется первым (его используют D-05, MG-17, M-07), остальные экраны — на MSW по этому контракту.

## Экраны фронтенда (по `docs/03-ui-screens.md`)
| Код | Маршрут | Роли | Содержание и состояния |
|---|---|---|---|
| D-01 | `/` (домашняя директора; до модуля 10 — MG-01) | `director` | Фильтры: точка, период (сегодня / неделя / месяц / свой). KPI-плитки с ▲/▼ (`Kpi.delta`), график выручки по дням (Recharts), таблица сравнения точек, топ-10 услуг, блок «Внимание». Загрузка — скелетон плиток; пусто — нули и «Нет данных за период»; ошибка — баннер с «Повторить». Переход в отчёты по клику на плитку |
| D-02 | `/reports` | `director` | Список отчётов слева (7 штук), параметры сверху (точка, период, отдел, `group_by`), результат таблицей и графиком, кнопки «XLSX» / «CSV». Отчёт «Прибыль» запрашивает целые месяцы. Пусто: «За выбранный период данных нет»; `truncated` → подпись «Показаны первые 500 строк» |
| D-03 | `/payroll` | `director` | Месяц (по умолчанию текущий), точка. Таблица `PayrollRow`; раскрытие строки — `PayrollDetail` (по заказам, окладная часть, корректировки, схемы). Кнопки «Премия / удержание» (диалог: сотрудник, месяц, сумма со знаком, причина), «Схема оплаты» (список и добавление, `scheme_overlap` → сообщение), «Экспорт ведомости». Предупреждение «Работ без схемы: N» по `items_without_scheme` |
| M-07 | `/earnings` | `mechanic` | Месяц (по умолчанию текущий). Крупно `accrued`/`total`; выполнено работ, нормочасы план/факт; премии и удержания; «Ожидают закрытия заказа»; блок «Мои рабочие дни» — `ActivityHeatmap` за 3 месяца с итогами; список работ по дням. Пусто: «В этом месяце завершённых работ пока нет» |
| MG-16 | `/location-report` | `manager` (и `director`) | Переключатель «День / Неделя / Месяц», выручка, заказов, средний чек, загрузка постов, график, таблица выработки механиков (имя — ссылка на MG-17). Без расходов и прибыли |
| MG-17 | `/mechanics/:id` | `manager` (механики своих точек; иначе экран 404), `director` | ФИО, точки, «Telegram подключён» (`User.telegram_linked`). `ActivityHeatmap` за 12 месяцев (или выбранный год) с итогами, под ним — список работ выбранного дня или периода (`activity-details`: заказ — ссылка, работа, время). Без зарплаты и данных учётной записи |
| D-05 (вкладка) | `/users/:id?tab=activity` | `director` | Вкладка «Активность» карточки сотрудника: `ActivityHeatmap` (`kind` определяется ролью просматриваемого), список действий/работ дня |
| MG-01 | `/` и `/today` (менеджер) | `manager` | Полная версия «Сегодня»: счётчики и показатели из `GET /dashboard/today` (выручка, касса, загрузка постов, механики и их активные работы) плюс лента записей модуля 4 |
| (общий) | компонент `ActivityHeatmap` | — | Свойства: `userId`, `from`, `to`, `variant: "desktop"|"mobile"`; 5 уровней цвета, подсказка «Вторник, 14 октября 2026 · 7 ч 20 мин · 3 работы» / «Нет активности», клик по дню открывает список за день, `aria-label` у каждой ячейки, стрелочная навигация, переключатель «Таблица», скелетон той же высоты; на mobile по умолчанию 3 месяца, ячейка 16 × 16 px |
