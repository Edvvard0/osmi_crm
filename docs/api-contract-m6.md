# Контракт API модуля 6 — рабочее место механика

Префикс `/api/v1`. Общие типы (`Money`, `Qty3`, `Page<T>`, `UserRef`, `VehicleRef`, перечисления `ItemStatus`, `WorkOrderStatus`), оптимистическая блокировка `version`, заглушки `events.publish` / `timers`, нумерация миграций и правила аудита — в разделе «Общие соглашения» файла `api-contract-m5.md`. Формат ошибок и авторизация — как в модуле 1, `extra="forbid"`, текстовые поля — `SafeText`.

Модуль добавляет:
1. срез `/mechanic/*` — только для роли `mechanic`: свои задачи, таймер, заявки на запчасти, рекомендации, комментарии;
2. эндпоинты менеджера/директора для заявок на запчасти, рекомендаций и возврата выполненной работы в исполнение.

**Принципы доступа механика.** Механик видит и меняет только позиции заказов (`work_order_items`), у которых `mechanic_id` — он сам, и только в точках, к которым он привязан. Чужая позиция, позиция чужой точки, несуществующий `item_id` → одинаково 404. Цены, суммы, скидки, контакты клиента (телефон, ФИО, email) механику **никогда** не отдаются: типы этого модуля их не содержат. `manager` и `director` на `/mechanic/*` получают 403 `forbidden`.

## Права
| Ресурс | director | manager | mechanic |
|---|---|---|---|
| `GET/POST /mechanic/*` | 403 | 403 | ✓ (только свои позиции) |
| `GET /part-requests`, `approve`, `reject`, `issue` | все точки | свои точки | 403 |
| `POST /work-orders/{id}/items/{item_id}/reopen` | ✓ | ✓ (свои точки) | 403 |
| `GET/POST /vehicles/{id}/recommendations`, `PATCH /recommendations/{id}` | ✓ | ✓ | 403 |
| Цена в `issue` отличается от каталожной | ✓ | 403 | — |

## Типы
- `TaskVehicle` = `{id, make, model, year: int|null, plate_number: str|null, color: str|null}`
- `MechanicTask` = `{item_id, order_id, order_number, order_status: WorkOrderStatus, department: Department, name, quantity: Qty2, norm_hours: Hours, status: ItemStatus, worked_seconds: int, running_since: iso|null, vehicle: TaskVehicle, planned_ready_at: iso|null, is_overdue: bool, can_start: bool, finished_at: iso|null}`
  - `norm_hours` — **нормочасы всей строки** (`norm_hours × quantity`), `worked_seconds` — суммарное время по закрытым интервалам плюс текущий открытый (на момент ответа); `running_since` — начало открытого интервала (только у `in_progress`), иначе `null`.
  - `can_start = true`, если позиция `pending|paused` и заказ в статусе `diagnostics|in_progress`. Другая активная работа механика `can_start` не отключает (ошибка возникает при старте, см. `another_task_active`).
- `TaskItemBrief` = `{item_id, name, quantity: Qty2, norm_hours: Hours, status: ItemStatus, worked_seconds: int, running_since: iso|null}` — «мои работы в этом заказе».
- `MechanicComment` = `{id, item_id: uuid|null, author: UserRef, text, created_at}` (только комментарии с `is_internal = true`; комментарии «для клиента» механику не отдаются).
- `MechanicTaskDetail` = `MechanicTask` + `{complaint: str|null, intake_notes: str|null, mileage_in: int|null, my_items: TaskItemBrief[], comments: MechanicComment[]}` — `my_items` включает все неотменённые позиции этого механика в заказе (в том числе открытую), `comments` — комментарии заказа (все позиции), по возрастанию времени, не более 200.
- Во всех ответах-«корнях» этого модуля присутствует `server_time: iso` — серверное время; клиент считает таймер как `worked_seconds + (Date.now() + offset − running_since)`, где `offset = server_time − Date.now()` в момент получения ответа. Время для таймера, интервалов и `actual_minutes` берёт только сервер; клиентское время не принимается.
- `PartRequestStatus` = `"new"|"approved"|"rejected"|"issued"`
- `PartRequest` (вид механика) = `{id, order_id, order_number, item_id: uuid|null, item_name: str|null, part: {id, name, sku}|null, description, quantity: Qty3, unit: str|null, status: PartRequestStatus, reject_reason: str|null, created_at, handled_at: iso|null}` — без цен и остатков.
- `PartRequestFull` (вид менеджера) = `{id, location_id, order: {id, number, status: WorkOrderStatus, version: int}, vehicle: VehicleRef, item_id, item_name, mechanic: UserRef, part: {id, name, sku, unit, sale_price: Money, in_stock: SignedQty3|null}|null, description, quantity: Qty3, status, reject_reason, handled_by: UserRef|null, handled_at, created_at}` — `in_stock` заполняется после модуля 8 (до него `null`).
- `VehicleRecommendation` = `{id, vehicle_id, work_order_id: uuid|null, work_order_number: str|null, text, priority: "low"|"medium"|"high", status: "open"|"done"|"declined", created_by: UserRef, created_at, updated_at}`

## Задачи механика (`/mechanic/*`)

### Список
- `GET /mechanic/tasks?scope=today|open` → `{active: MechanicTask|null, items: MechanicTask[], server_time}`
  - `active` — позиция с открытым интервалом таймера (одна на механика) или `null`; в `items` она **не** дублируется.
  - Заказы учитываются в статусах `new|diagnostics|awaiting_approval|in_progress|awaiting_parts` (позиция в заказе `quality_check/ready/closed/cancelled` в списке не показывается; завершённая сегодня — показывается, см. ниже).
  - `scope=open` (по умолчанию) — все неотменённые, незавершённые позиции механика.
  - `scope=today` — `in_progress/paused` позиции, а также `pending` позиции заказов, у которых `planned_ready_at` — сегодня или раньше (в поясе точки заказа) либо `planned_ready_at` не задан и заказ создан сегодня, плюс позиции, завершённые сегодня (`finished_at` сегодня, `status = done`).
  - Сортировка: `in_progress` → `paused` → `pending` → `done`; внутри — `planned_ready_at` по возрастанию (пустые в конце), затем номер заказа. Пагинации нет (лимит 200 строк, лишнее отсекается).

### Карточка
- `GET /mechanic/tasks/{item_id}` → `MechanicTaskDetail` (позиция не своя / отменена / в закрытом заказе более 7 дней назад → 404).

### Таймер
Все три действия: тело `{}` кроме отмеченных; идемпотентны там, где указано; изменяют только `work_logs`, статус и время позиции — **`version` заказа не увеличивают**; пишут аудит (`entity_type = work_order_item`, `action = status_change`, `changes: {status: {old, new}}`).
- `POST /mechanic/tasks/{item_id}/start` `{pause_active?: bool}` → `{task: MechanicTask, active: MechanicTask, server_time}` — старт или возобновление.
  - Позиция должна быть `pending|paused`, заказ — в статусе `diagnostics|in_progress`, иначе 409 `order_not_workable`, `details: {"order_status": "awaiting_parts"}`; для позиции `done|cancelled` — 409 `invalid_state`.
  - Если у механика уже есть открытый интервал на другой позиции: при `pause_active = true` он закрывается (та позиция → `paused`), старт выполняется в одной транзакции; иначе 409 `another_task_active`, `details: {"item_id": "…", "order_number": "MSK1-000123", "item_name": "Полировка кузова"}` (фронтенд предлагает «Поставить на паузу и начать эту»). Гонка двух стартов гасится уникальным индексом `work_logs_one_active_per_mechanic` и возвращает тот же 409.
  - Повторный старт уже запущенной позиции (двойной клик) → 200 без изменений (идемпотентно).
  - Эффекты: создаётся `work_logs(item_id, mechanic_id, started_at = now())`; позиция → `in_progress`; `started_at` позиции ставится, если пусто; `started_at` заказа — если пусто.
- `POST /mechanic/tasks/{item_id}/pause` `{}` → `{task: MechanicTask, active: null, server_time}`. Закрывает открытый интервал (`ended_at = now()`), позиция → `paused`. Позиция не `in_progress` → 409 `invalid_state`.
- `POST /mechanic/tasks/{item_id}/finish` `{comment?}` → `{task, order_status: WorkOrderStatus, order_auto_moved: bool, active: null, server_time}`.
  - Допустимо из `in_progress|paused`; из `pending` → 409 `invalid_state` (сначала начать); заказ в статусе `diagnostics|in_progress`, иначе 409 `order_not_workable`.
  - Закрывает открытый интервал; позиция → `done`, `finished_at = now()`, `actual_minutes = round(Σ длительностей интервалов, секунды / 60)` (`ROUND_HALF_UP`, минимум 0 даже при нулевых интервалах).
  - `comment` (≤ 1000, `SafeText`) сохраняется как внутренний комментарий заказа с `item_id`.
  - Затем вызывается `on_item_done(order)` (модуль 5): если все неотменённые позиции заказа `done` и заказ `in_progress`, он переходит в `quality_check` (`order_auto_moved = true`, запись в историю с `comment: "Все работы выполнены"`, `changed_by` = механик, `version` заказа +1), публикуется событие `work_order.ready_for_check`.
  - Всегда публикуется `work_item.finished` менеджерам точки (кроме случая, когда одновременно публикуется `work_order.ready_for_check` — тогда только оно; состав и дедупликация — в модуле 7).
  - Повторное завершение уже `done` → 200 без изменений (идемпотентно, `order_auto_moved = false`).
- Системные инварианты: у механика не более одного открытого интервала; пауза/старт/завершение — только свои позиции; при выходе заказа из статусов `diagnostics|in_progress` (в том числе отмена) открытые интервалы закрываются автоматически (`timers.pause_all`, вызывается модулем 5 при смене статуса).

### Комментарии механика
- `POST /mechanic/tasks/{item_id}/comments` `{text}` → 201 `MechanicComment`. `text` 1..2000. Сохраняется как `work_order_comments(item_id, is_internal = true)`. Разрешено, пока позиция доступна механику (включая завершённую).

### Заявки на запчасти
- `POST /mechanic/part-requests` `{item_id, part_id?, description?, quantity?}` → 201 `PartRequest`.
  - Нужна хотя бы одна из `part_id` (активная запчасть справочника) и `description` (1..500); если `part_id` задан, а `description` пуст — подставляется название запчасти. `quantity` по умолчанию `"1.000"`, `Qty3`.
  - `item_id` — своя позиция; заказ не в `ready|closed|cancelled`, иначе 409 `invalid_state`.
  - Публикуется `part_request.created` менеджерам точки.
- `GET /mechanic/part-requests?status=&limit=&offset=` → `Page<PartRequest>` (свои, `created_at` по убыванию).
- Механик не может изменить или отозвать заявку.

### Рекомендации
- `POST /mechanic/recommendations` `{item_id, text, priority}` → 201 `VehicleRecommendation`. `text` 1..1000; `priority` — `low|medium|high` (по умолчанию `medium`). Привязка к авто и заказу берётся из позиции. Отдельного события нет.

## Заявки на запчасти: менеджер и директор
- `GET /part-requests?location_id=&status=&order_id=&mechanic_id=&limit=&offset=` → `Page<PartRequestFull>`. Менеджер без `location_id` — по всем своим точкам. Сортировка: `new` и `approved` вверху, внутри `created_at` по возрастанию (старые заявки раньше).
- `GET /part-requests/summary?location_id=` → `{new: int, approved: int}` (бейдж вкладки и блок «Требует внимания»).
- `POST /part-requests/{id}/approve` `{part_id?}` → `PartRequestFull`. Из `new`. `part_id` можно уточнить (если у заявки свободный текст). Публикуется `part_request.handled`. Не меняет склад.
- `POST /part-requests/{id}/reject` `{reason}` → `PartRequestFull`. Из `new|approved`; `reason` 1..500 обязателен (422 `fields.reason`). `reject_reason` сохраняется. Публикуется `part_request.handled` механику.
- `POST /part-requests/{id}/issue` `{version, part_id?, quantity?, unit_price?}` → `{request: PartRequestFull, order: WorkOrder}`. Из `new|approved`. Эквивалент `POST /work-orders/{order_id}/parts` с `part_request_id` (модуль 5): запчасть добавляется в заказ, заявка → `issued`. `version` — версия заказа (`order.version` из `PartRequestFull`). `part_id` обязателен, если у заявки его нет (иначе 422 `fields.part_id`); `quantity` по умолчанию из заявки; `unit_price` — как в `POST …/parts` (изменение каталожной цены — только директор). После модуля 8 может вернуть 409 `insufficient_stock`. Событие `part_request.handled` публикуется, если заявка не была ранее одобрена/отклонена (то есть механик ещё не уведомлён).
- Статусные ошибки: `approve` не из `new`, `issue/reject` из `rejected|issued` → 409 `invalid_transition`. Заказ `closed|cancelled` → 409 `invalid_state`. Чужая точка → 404.

## Возврат выполненной работы в исполнение
- `POST /work-orders/{id}/items/{item_id}/reopen` `{version}` → `WorkOrder` (модуль 5). Только для позиции `done`; иначе 409 `invalid_state`. Позиция → `paused`, `finished_at = null` (`actual_minutes` и интервалы сохраняются). Заказ в `quality_check` или `ready` автоматически возвращается в `in_progress` (запись в историю, `comment: "Работа возвращена в исполнение"`); `closed|cancelled` → 409 `invalid_state`. `version` +1; аудит `status_change`. Уведомление механику — `work_item.updated`.

## Рекомендации по авто (менеджер/директор)
- `GET /vehicles/{id}/recommendations?status=` → `VehicleRecommendation[]` (по умолчанию все, `created_at` по убыванию). Клиенты и авто в системе общие (модуль 2), поэтому доступ не зависит от точки.
- `POST /vehicles/{id}/recommendations` `{text, priority, work_order_id?}` → 201. `work_order_id` — заказ любого доступного пользователю места, если он принадлежит этому авто.
- `PATCH /recommendations/{id}` `{status?, priority?, text?, work_order_id?}` → `VehicleRecommendation`. Статус `open → done|declined`, `done|declined → open` допустимы; «Добавить в заказ» (MG-10): фронтенд добавляет работу в заказ (`POST …/items`, модуль 5), затем `PATCH {status: "done", work_order_id}`.
- Аудит: `entity_type = vehicle_recommendation`.

## Правила и ошибки
| Правило | Ответ |
|---|---|
| Позиция не своя / чужой точки / не существует | 404 |
| Роль не `mechanic` на `/mechanic/*` | 403 `forbidden` |
| У механика уже есть работающая позиция | 409 `another_task_active` (`details`: `item_id`, `order_number`, `item_name`) |
| Заказ не в `diagnostics|in_progress` для старта/завершения | 409 `order_not_workable` |
| Операция не соответствует статусу позиции | 409 `invalid_state` |
| Недопустимый переход статуса заявки | 409 `invalid_transition` |
| Нет `reason` при отклонении | 422 `fields.reason` |
| Нет `part_id`/`description` в заявке | 422 `fields.description` |
| `version` заказа не совпал (`issue`, `reopen`) | 409 `version_conflict` |
| Нехватка остатка (модуль 8) | 409 `insufficient_stock` |

Новые коды для `ERROR_MESSAGES`: `another_task_active`, `order_not_workable`. Аудит (`write_audit`): `work_order_item` (`status_change` — start/pause/finish, `entity_id` позиции, `location_id` заказа), `part_request` (`create`, `status_change` — approve/reject/issue), `vehicle_recommendation` (`create`, `update`), `work_order_comment` (`create`).

## Расширение сущностей
| Сущность | Что меняется |
|---|---|
| `WorkOrderItem.actual_minutes`, `started_at`, `finished_at` (модуль 5) | теперь заполняются таймером |
| `Vehicle` (модуль 2) | новый вложенный список через `GET /vehicles/{id}/recommendations`; карточка авто (MG-10) показывает открытые рекомендации |
| Статусы `WorkOrder` (модуль 5) | автопереход `in_progress → quality_check` при завершении последней работы; возврат в `in_progress` при `reopen` |

## Миграция `0006_mechanic_workplace`
- Таблицы (по `docs/02-database-schema.md`): `work_logs`, `part_requests`, `vehicle_recommendations`.
- `work_logs`: `CHECK (ended_at IS NULL OR ended_at > started_at)`; **`CREATE UNIQUE INDEX work_logs_one_active_per_mechanic ON work_logs (mechanic_id) WHERE ended_at IS NULL`**; индексы `(mechanic_id, started_at)`, `(item_id)`.
- `part_requests`: индексы `(status, created_at)`, `(work_order_id)`, `(mechanic_id, created_at DESC)`.
- `vehicle_recommendations`: индекс `(vehicle_id, status)`.
- Права БД: `crm_app` — `SELECT, INSERT, UPDATE` на `work_logs` (удаления нет), полный набор на остальные.
- Новых ролей нет; матрица прав — выше.

## Зависимости
Модуль 5 (заказы, позиции, `on_item_done`, `timers`-заглушка, `events.publish`-заглушка). Склад (модуль 8) подключается позже: `in_stock` в `PartRequestFull` и `insufficient_stock` в `issue`. Telegram (модуль 7) подключает реальную отправку без изменения кода модуля 6.

## Что можно разрабатывать параллельно
- Frontend механика (M-01…M-06) целиком на MSW-моках по этому контракту, независимо от backend.
- Backend `/mechanic/*` и backend менеджерских эндпоинтов (`part-requests`, `reopen`, `recommendations`) — два независимых среза.
- Компонент `PartRequestsPanel` (список заявок для менеджера) пишется как самостоятельный и встраивается в `/stock/requests` в модуле 8 (до него доступен на `/part-requests`).

## Экраны фронтенда (по `docs/03-ui-screens.md`)
Роль `mechanic` (телефон, кнопки от 56 px, без цен и контактов). Нижняя панель: «Задачи» (`/`) · «Заявки» (`/requests`) · «Заработок» (`/earnings`, модуль 10) · «Настройки» (`/settings`, C-02). Общие состояния: загрузка — скелетон карточек; ошибка — «Не удалось загрузить» + «Повторить»; офлайн — C-04, кнопки действий неактивны; pull-to-refresh и обновление при возврате на вкладку.

| Код | Маршрут | Содержание и состояния |
|---|---|---|
| M-01 | `/` | Карточка активной работы с живым таймером и кнопкой «Пауза» (если `active ≠ null`); переключатель «Сегодня / Все открытые» (`scope`); карточки: госномер крупно, марка и модель, название работы, норматив, статус, метка отдела, просрочка. Пусто: «На сегодня задач нет» / «Открытых задач нет». Ошибка `another_task_active` при «Начать» → диалог «Поставить на паузу и начать эту» (`pause_active: true`) |
| M-02 | `/tasks/:itemId` | Шапка: госномер, авто, пробег, номер заказа, метка отдела. Блоки: «Жалоба клиента», «Состояние при приёме», «Мои работы в этом заказе» (статус, норма, время), «Комментарии» (+ поле добавить). Липкая панель: «Начать»/«Продолжить» либо «Пауза», и «Завершить»; недоступное при `can_start = false` скрыто, под панелью подсказка «Заказ ещё не передан в работу». Меню «⋯»: «Нужна запчасть», «Рекомендация», «Комментарий». 404 → C-03 |
| M-03 | bottom sheet в `/tasks/:itemId` | Фактическое время (из таймера), комментарий (необязательно), «Завершить работу». После успеха — возврат на `/`; если `order_auto_moved`, toast «Все работы заказа выполнены» |
| M-04 | `/tasks/:itemId/part-request` | Поиск по справочнику (`GET /parts?search=`, модуль 3 — для механика предусмотреть доступ на чтение справочника без цен: см. ниже) или свободный текст, количество кнопками −/+, комментарий, «Отправить». Ошибки полей под полями |
| M-05 | `/requests` | Список заявок (`GET /mechanic/part-requests`) со статусами: новая, одобрена, отклонена (с причиной), выдана. Пусто: «Заявок пока нет» |
| M-06 | `/tasks/:itemId/recommendation` | Текст, приоритет (низкий / средний / высокий), «Сохранить». Подсказка «Менеджер увидит при следующем визите» |
| MG-11 (часть) | `/stock/requests` (вкладка «Заявки механиков» экрана склада; до модуля 8 — `/part-requests`) | Роли `manager`, `director`. Список `PartRequestFull` (заказ — ссылка, авто, механик, запчасть, количество, остаток), действия «Одобрить», «Отклонить» (причина), «Выдать» (диалог количества/цены; ошибка `insufficient_stock` → сообщение), бейдж новых. Пусто: «Новых заявок нет» |
| MG-05 (часть) | `/orders/:id` | В «Запчасти» — блок «Заявки механиков по заказу» с кнопкой «Выдать»; на работе со статусом `done` — действие «Вернуть в работу» (`reopen`) |
| MG-10 (часть) | `/vehicles/:id` | Блок «Рекомендации механиков» (открытые, приоритет цветом и текстом), кнопки «Добавить в заказ», «Выполнено», «Отклонить»; форма добавления рекомендации менеджером |

**Справочник запчастей для механика (M-04).** Модуль 3 закрывает `GET /parts` для механика (403). Для M-04 модуль 6 добавляет `GET /mechanic/parts?search=&limit=` → `{id, sku, name, brand, unit}[]` (до 20 записей, активные запчасти, без цен и остатков; `search` ≥ 2 символа, `%`/`_` экранируются).
