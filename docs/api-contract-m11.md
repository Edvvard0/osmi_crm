# Контракт API модуля 11 — Журнал действий, сессии, системные настройки

Префикс `/api/v1`. Общие типы (`Page<T>`, `UserRef`, `Percent`), `get_setting`, аудит, правила миграций — в «Общих соглашениях» файла `api-contract-m5.md`. Формат ошибок, `extra="forbid"`, `SafeText` — как в модуле 1. Таблица `audit_log` и функция `write_audit` существуют с модуля 1; этот модуль добавляет **чтение** журнала, список сессий, системные настройки и закрывает «хвосты» (права БД, очистка).

## Права
| Операция | director | manager | mechanic |
|---|---|---|---|
| `GET /audit-log`, `/audit-log/{id}`, `/audit-log/meta` | ✓ (все точки) | 403 | 403 |
| `GET /settings`, `PATCH /settings` | ✓ | 403 | 403 |
| `GET /auth/sessions`, `DELETE /auth/sessions/{id}`, `POST /auth/sessions/revoke-others` | свои | свои | свои |
| `POST /users/{id}/revoke-sessions` | ✓ | 403 | 403 |
| `POST /auth/change-password` (модуль 1) | ✓ | ✓ | ✓ (только за себя) |

Журнал виден только руководителю: менеджер не получает даже записей своей точки (его «ленту» заменяют карточки и истории статусов модулей 4–9).

## Смена пароля (только в «Настройках»)
- Пользователь меняет **свой** пароль только в экране C-02 «Настройки → Безопасность» вызовом `POST /auth/change-password` (модуль 1, без изменений в контракте): `{current_password, new_password}` → 204, остальные сессии отозваны, текущая сохраняется. Аудит `password_change` (`entity_type = "user"`).
- **Принудительной смены пароля нет**: в `User`, в ответах `/auth/login` и `/auth/me` нет флага `must_change_password`, `login` никогда не требует смены, после входа открывается рабочий стол роли. Фронтенд не создаёт маршрутов «сменить пароль» вне C-02.
- Руководитель сбрасывает пароль **другого** сотрудника через `POST /users/{id}/reset-password` (модуль 1, экран D-04/D-05); это не «смена пароля» в смысле C-02, и новая запись аудита — `password_change` с `entity_id` сотрудника и `user_id` руководителя.

## Расширение `User` (все ответы с `User`)
Добавляется `last_login_at: iso|null` (колонка `users.last_login_at` существует с модуля 1; в схему `UserRead` её добавляет этот модуль). Поле информационное и видно тем, кто видит `User`.

## Журнал действий (D-08)
### Типы
- `AuditEntry` = `{id: int, created_at: iso, user: UserRef|null, action: AuditAction, entity_type: str, entity_id: uuid|null, entity_label: str|null, entity_path: str|null, location: {id, name, timezone}|null, changes: object|null, ip: str|null, user_agent: str|null}`
  - `user = null` — системное действие или неудачный вход.
  - `entity_label` — читаемое имя объекта на момент **чтения** (номер заказа, ФИО, название); `null`, если объект не найден или метки для типа нет — фронтенд показывает «`entity_type` · первые 8 символов `entity_id`». Метка не содержит телефонов и госномеров.
  - `entity_path` — готовый путь в приложении для ссылки (`/orders/<id>`, `/clients/<id>`, `/users/<id>` …) по таблице ниже или `null` (нет страницы / объект недоступен). Фронтенд не строит ссылки сам.
  - `changes` — как записано через `diff(old, new)`: для `update` значения вида `{"поле": {"old": …, "new": …}}` (фронтенд показывает «было → стало»), для `create` — `{"поле": значение}`; прочие служебные ключи (`reason`, `to_location_id` …) — простые значения. Секреты (ключи, содержащие `password`, `token`, `secret`, `hash`, `code`) заменяются строкой `"***"` **и при записи в `write_audit`, и при чтении**.
- `AuditAction` = `"create"|"update"|"delete"|"archive"|"restore"|"status_change"|"refund"|"login"|"login_failed"|"logout"|"token_reuse"|"password_change"|"export"|"revoke_session"` (расширение списка из модуля 5: добавлены `export` — модуль 10, `revoke_session` — этот модуль).
- `AuditMeta` = `{actions: [{value: AuditAction, label: str}], entity_types: [{value: str, label: str}]}` — русские подписи для фильтров и ленты; значения только из каталога ниже.

### Эндпоинты (только `director`)
- `GET /audit-log?date_from=&date_to=&user_id=&action=&entity_type=&entity_id=&location_id=&limit=50&offset=0` → `Page<AuditEntry>`
  - `date_from`/`date_to` — даты `YYYY-MM-DD` включительно в APP_TIMEZONE; по умолчанию последние 30 суток; период > 366 суток или `date_to < date_from` → 422 `fields.date_to`.
  - `action` и `entity_type` принимают несколько значений через запятую (ИЛИ внутри параметра, И между параметрами); неизвестное значение → 422 по имени параметра.
  - `user_id` с литералом `system` отбирает записи без пользователя.
  - Сортировка фиксирована: `created_at DESC, id DESC`. `limit` 1..200 (по умолчанию 50); `offset` ≤ 10 000, иначе 422 `fields.offset` (глубже — сужать фильтры). `total` — точное число записей по фильтру.
  - Неизвестные `user_id`/`location_id` не дают 404 — пустой результат.
- `GET /audit-log/{id}` → `AuditEntry` (id — `int`; не найден → 404).
- `GET /audit-log/meta` → `AuditMeta` (значения могут расти по мере добавления модулей; фронтенд не хардкодит).
- Изменяющих эндпоинтов нет: запись только из сервисов, правка/удаление невозможны (см. «Миграция»).
- Просмотр журнала сам не аудируется.

### Каталог аудируемых операций
`write_audit` вызывается **в той же транзакции**, что и изменение. `location_id` — точка объекта (для глобальных объектов `null`). Источник правды по составу `changes` каждой операции — контракт её модуля.

| `entity_type` | Действия | Модуль | `entity_path` |
|---|---|---|---|
| `user` | `create`, `update`, `password_change`, `login`, `login_failed`, `logout`, `token_reuse`, `revoke_session` | 1, 7, 11 | `/users/<id>` |
| `location` | `create`, `update` | 1, 7 | `/locations/<id>` |
| `client` | `create`, `update`, `archive`, `restore` | 2 | `/clients/<id>` |
| `vehicle` | `create`, `update`, `archive`, `restore` | 2 | `/vehicles/<id>` |
| `service_category`, `service`, `part`, `post` | `create`, `update`, `archive`, `restore` | 3 | `/catalog` |
| `service_price` | `create`, `update`, `delete` | 3 | `/catalog` |
| `appointment` | `create`, `update`, `status_change` | 4 | `/calendar` (с `?date=<дата записи>`, если дата известна из `changes`, иначе без параметров) |
| `work_order` | `create`, `update`, `status_change` | 5, 9 | `/orders/<id>` |
| `work_order_item`, `work_order_part`, `work_order_comment` | `create`, `update`, `delete`, `status_change` | 5, 6 | `/orders/<changes.work_order_id>` |
| `part_request` | `create`, `status_change` | 6 | `/orders/<changes.work_order_id>` |
| `vehicle_recommendation` | `create`, `update` | 6 | `/vehicles/<changes.vehicle_id>` (если ключа нет — `null`) |
| `stock_balance`, `stock_receipt`, `stock_transfer`, `stock_inventory`, `stock_movement` | `create`, `update` | 8 | `/stock/<part_id>` для `stock_balance`; остальные — `/stock/movements` |
| `payment` | `create`, `refund` | 9 | `/orders/<changes.order_id>` (если ключа нет — `null`) |
| `expense`, `expense_category` | `create`, `update` | 9 | `/cash` |
| `payroll_scheme`, `payroll_adjustment` | `create`, `update`, `delete` | 10 | `/payroll` |
| `report`, `payroll` | `export` | 10 | `null` |
| `system_settings` | `update` | 11 | `/system-settings` |
| `session` | `revoke_session` | 11 | `null` |

Дополнительные правила:
- В `changes` записей, привязанных к заказу (`work_order_item|part|comment`, `part_request`, `payment`), сервис-автор обязан класть `work_order_id` (или `order_id` для платежа) — иначе `entity_path = null`.
- Записи `login_failed` не раскрывают, существует ли логин: `entity_id = null`, `changes = {login, reason}` — как в модуле 1 (поле `login` — введённая строка, обрезанная до 64 символов без управляющих символов).
- Тексты клиентских данных (телефоны, комментарии) в `changes` попадают только как поля сущности, изменяемой самой записью; журнал сообщений Telegram в аудит не попадает.
- Неуспешная операция (откат транзакции) записи в аудите не оставляет, кроме `login_failed` и `token_reuse` (пишутся отдельной транзакцией).

## Сессии (C-02, раздел «Безопасность»)
Сессия = «семья» refresh-токенов одного входа (`refresh_sessions.family_id`); идентификатор сессии в API — `family_id`.

- `Session` = `{id: uuid, created_at: iso, last_active_at: iso, ip: str|null, user_agent: str|null, device: str, is_current: bool}`
  - `created_at` — первый токен семьи; `last_active_at` — время последней ротации (`created_at` последнего токена семьи).
  - `device` — читаемое краткое описание из `user_agent` на сервере («Chrome · Windows», «Safari · iPhone», «Неизвестное устройство»); сырой `user_agent` дополнительно отдаётся для подсказки. Определение устройства — простой разбор, без внешних сервисов.
  - `is_current` — семья токена из cookie текущего запроса.
- `GET /auth/sessions` → `Session[]` — активные (не отозванные, не истёкшие) сессии **текущего** пользователя, текущая первой, затем по `last_active_at` убыв. Требует cookie `refresh_token` для пометки `is_current` (без cookie — `is_current = false` у всех).
- `DELETE /auth/sessions/{id}` → 204 — завершить чужую (не текущую) сессию текущего пользователя: у всех токенов семьи `revoked_at = now()`. Идемпотентно для уже завершённой; чужая сессия другого пользователя или несуществующая → 404; текущая сессия → 409 `invalid_state` (для выхода служит `POST /auth/logout`). Аудит `revoke_session`, `entity_type = "session"`, `entity_id` = id сессии.
- `POST /auth/sessions/revoke-others` → 204 — завершить все сессии, кроме текущей (кнопка «Завершить все остальные»); без cookie → 401 `invalid_token`. Аудит одной записью `revoke_session` (`changes: {count}`).
- `POST /users/{id}/revoke-sessions` (только `director`) → 204 — завершить все сессии указанного сотрудника (кнопка в D-05 «Завершить все сессии»); неизвестный → 404. Аудит `revoke_session` (`entity_type = "user"`, `entity_id` сотрудника, `changes: {count}`). Если руководитель вызывает метод для себя — текущая сессия сохраняется.
- Лимиты: чтение — без ограничения; два изменяющих `/auth/sessions…` — 30 запросов в минуту на пользователя (429 `rate_limited`).
- Очистка: задача воркера `session_cleanup` (см. «Воркер») удаляет строки `refresh_sessions` с `expires_at` или `revoked_at` старше `session_retention_days` суток. Срок жизни самого refresh-токена (14 суток) настройкой **не** меняется.

## Системные настройки (D-09)
Хранение — таблица `system_settings (key, value jsonb, updated_by, updated_at)`. Читают код через `get_setting(session, key)` (кэш процесса с TTL ≤ 10 с; `PATCH` сбрасывает кэш процесса API, остальные процессы подхватывают за TTL). Значение по умолчанию возвращается, если строки нет.

### Ключи и значения по умолчанию
Единственное место, где перечислены значения; `core/settings_defaults.py` (создаётся модулем 5) обязан повторять их один в один.

| Ключ | Тип JSON | По умолчанию | Допустимые значения | Потребители |
|---|---|---|---|---|
| `discount_alert_percent` | `Percent` (строка с 2 знаками) | `"20.00"` | `"1.00".."100.00"` | модуль 5 (`order.discount_alert`), модуль 10 («Внимание») |
| `daily_summary_time` | `"HH:MM"` или `null` | `"21:00"` | время 00:00..23:59 (APP_TIMEZONE); `null` — сводка отключена | модуль 10 (`daily_summary`) |
| `session_retention_days` | int | `30` | 7..365 | задача `session_cleanup` |
| `heatmap_thresholds` | `{hours: [n,n,n], actions: [n,n,n]}` | `{"hours": [2, 5, 8], "actions": [5, 15, 30]}` | в каждой тройке значения строго возрастают; `hours`: числа 0.5..24 с шагом 0.5; `actions`: целые 1..1000 | модуль 10 (уровни тепловой карты) |

Служебные ключи с префиксом `_` (`_worker_heartbeat` — модуль 12) принадлежат воркеру и **не** отдаются/не принимаются через `/settings`.

### Эндпоинты (только `director`)
- `GET /settings` → `Settings` = `{discount_alert_percent: Percent, daily_summary_time: "HH:MM"|null, session_retention_days: int, heatmap_thresholds: {hours: number[3], actions: number[3]}, updated_at: iso|null, updated_by: UserRef|null}`; `updated_at`/`updated_by` — последнее изменение любого из ключей (`null`, если всё по умолчанию).
- `PATCH /settings` — любое подмножество ключей (`extra="forbid"`, неизвестный ключ → 422 по его имени; пустое тело → 422 `validation_error`) → `Settings`. Значение `heatmap_thresholds` заменяется целиком (обе тройки обязательны). Нарушение диапазона → 422 `fields.<ключ>`; невозрастающая тройка → 422 `fields.heatmap_thresholds`. Оптимистической блокировки нет (последняя запись побеждает).
- Аудит одной записью: `action = update`, `entity_type = "system_settings"`, `entity_id = null`, `changes = diff` по изменённым ключам.
- Категории расходов в экране D-09 управляются эндпоинтами модуля 9 (`GET/POST/PATCH /expense-categories`); отдельных эндпоинтов в `/settings` для них нет.

## Воркер (регистрация задач)
Задачи регистрируются в реестре воркера из `api-contract-m7.md` (общий процесс `python -m app.worker`, advisory lock):
| Задача | Расписание | Действие |
|---|---|---|
| `session_cleanup` | ежедневно в 03:45 APP_TIMEZONE | удаление старых `refresh_sessions` (см. выше) |

## Правила и ошибки
| Правило | Ответ |
|---|---|
| Не `director` обращается к журналу / настройкам | 403 `forbidden` |
| Период журнала > 366 суток, `date_to < date_from` | 422 `fields.date_to` |
| `offset` > 10 000 | 422 `fields.offset` |
| Неизвестное значение `action` / `entity_type` | 422 `fields.action` / `fields.entity_type` |
| Запись журнала не найдена | 404 |
| Пороги тепловой карты не возрастают / вне диапазона | 422 `fields.heatmap_thresholds` |
| Недопустимое значение настройки | 422 `fields.<ключ>` |
| Завершение текущей сессии через `DELETE /auth/sessions/{id}` | 409 `invalid_state` |
| Чужая / несуществующая сессия | 404 |
| `revoke-others` без cookie | 401 `invalid_token` |

Новых кодов для `ERROR_MESSAGES` модуль не вводит.

## Миграция `0011_audit_settings`
- Таблица `system_settings` (по `docs/02-database-schema.md`): `key varchar(50) PK`, `value jsonb NOT NULL`, `updated_by uuid FK → users`, `updated_at timestamptz NOT NULL DEFAULT now()`. Права `crm_app`: `SELECT, INSERT, UPDATE`.
- `audit_log`: идемпотентно (`DO $$ … IF EXISTS role crm_app … $$`) повторить `REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM crm_app`; добавить индекс `ix_audit_log_location (location_id, created_at DESC)` и `ix_audit_log_action (action, created_at DESC)`. Новых колонок в `audit_log` нет (`id` — `bigint`, как есть).
- `refresh_sessions`: индекс `ix_refresh_sessions_family (family_id, created_at DESC)` (если ещё нет) и `ix_refresh_sessions_revoked (revoked_at) WHERE revoked_at IS NOT NULL` для очистки.
- Seed значений по умолчанию не нужен (значения по умолчанию возвращает `get_setting`).
- Новые права доступа: нет (журнал и настройки — только `director`; сессии — свои).

## Зависимости
- Модуль 1 (аудит, сессии, пользователи), модуль 5 (определяет заглушку `get_setting`, которую этот модуль подключает к БД), модуль 7 (воркер и реестр задач), модуль 10 (`export`, пороги тепловой карты, время сводки), модуль 9 (категории расходов).
- Журнал читает записи **всех** предыдущих модулей без каких-либо хуков в их коде: достаточно, чтобы они писали аудит по каталогу выше.

## Что можно разрабатывать параллельно
- Backend: (а) чтение журнала и `meta` — зависит только от таблицы `audit_log`; (б) сессии (`/auth/sessions…`) — зависят только от `refresh_sessions`; (в) настройки и подключение `get_setting` к БД; (г) задача `session_cleanup` (после воркера модуля 7).
- Frontend: D-08 и D-09 независимы друг от друга; вкладка «Сессии» в C-02 — отдельный компонент, не зависящий от Telegram-секции.

## Экраны фронтенда (по `docs/03-ui-screens.md`)
| Код | Маршрут | Роли | Содержание и состояния |
|---|---|---|---|
| D-08 | `/audit` | `director` | Лента `AuditEntry`: время (в часовом поясе точки записи — `location.timezone`; для записей без точки — в часовом поясе браузера), сотрудник, действие (подпись из `meta`), объект (ссылка по `entity_path`, иначе текст), точка. Фильтры: период, сотрудник, действие, тип объекта, точка (синхронизируются с URL). Раскрытие строки — «было → стало» из `changes`, IP и устройство. Пагинация «Показать ещё» (по 50). Загрузка — скелетон строк; пусто — «Записей по выбранным фильтрам нет» + «Сбросить фильтры»; ошибка — баннер «Повторить» |
| D-09 | `/system-settings` | `director` | Форма настроек: порог скидки (%), время ежедневной сводки (или «Отключено»), срок хранения сессий (дни), пороги тепловой карты (две тройки, превью цветов). Кнопка «Сохранить» активна при изменениях; ошибки полей — из `fields`. Ссылка «Категории расходов» ведёт к управлению на экране модуля 9. Состояния: загрузка — скелетон, ошибка — баннер с «Повторить», успех — toast «Настройки сохранены» |
| C-02 (завершение) | `/settings` | все роли | Секция «Безопасность»: форма «Сменить пароль» (модуль 1) и список активных сессий: устройство, IP, последняя активность, метка «Это устройство», кнопка «Завершить» (подтверждение), «Завершить все остальные». Пусто (единственная сессия): «Других активных сессий нет». Ошибка загрузки — баннер внутри секции |
| D-05 (дополнение) | `/users/:id` | `director` | Кнопка «Завершить все сессии», поле «Последний вход» из `User.last_login_at` |
