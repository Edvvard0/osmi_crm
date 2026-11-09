# Контракт API модуля 7 — Telegram-уведомления

Префикс `/api/v1`. Общие типы, `events.publish`, нумерация миграций, аудит — в «Общих соглашениях» файла `api-contract-m5.md`. Формат ошибок и авторизация — как в модуле 1, `extra="forbid"`, `SafeText`.

Уведомления уходят **сотрудникам** (клиентских уведомлений в системе нет) и в **групповой чат точки**. Бот двусторонний только для привязки аккаунта; управления заказами из Telegram нет. Фоновая отправка — asyncio-воркер и таблица `notification_outbox` в PostgreSQL (Redis и Celery не используются).

## Права
| Ресурс | director | manager | mechanic |
|---|---|---|---|
| `GET /telegram/status`, `POST /telegram/link-code`, `DELETE /telegram/link` | ✓ (себе) | ✓ (себе) | ✓ (себе) |
| `GET/PATCH /telegram/notification-settings` | ✓ (себе, события роли) | ✓ | ✓ |
| `POST /telegram/webhook` | — (аутентификация секретом, см. ниже) | — | — |
| `PATCH /locations/{id}` с `telegram_chat_id`, `POST /locations/{id}/telegram-test` | ✓ | 403 | 403 |
| Поля `User.telegram_linked`, `telegram_username` | всех | `telegram_linked` у механиков своих точек; своё всё | своё |

Настройки уведомлений и привязка — только собственные: чужой `user_id` в API нет.

## Конфигурация (переменные окружения; значения не отдаются в API)
| Переменная | Значение |
|---|---|
| `TELEGRAM_BOT_TOKEN` | токен бота; пустой → Telegram выключен (`enabled: false`), outbox не пишется, воркер не стартует отправку |
| `TELEGRAM_BOT_USERNAME` | имя бота без `@` (для ссылки `https://t.me/<name>?start=<code>`) |
| `TELEGRAM_MODE` | `webhook` (прод) · `polling` (dev; запускается отдельным процессом `python -m app.bot`, контейнер `bot` из `docker-compose.yml`) · `off` (по умолчанию) |
| `TELEGRAM_WEBHOOK_SECRET` | секрет для заголовка `X-Telegram-Bot-Api-Secret-Token` (≥ 32 символов в проде) |
| `TELEGRAM_API_BASE` | базовый URL Bot API (по умолчанию `https://api.telegram.org`; в тестах — мок-сервер) |
| `PUBLIC_BASE_URL` | публичный адрес системы для регистрации вебхука |

Регистрация вебхука — CLI `python -m app.cli telegram-set-webhook` (идемпотентна; вызывается при деплое после миграций). В `webhook`-режиме webhook принимает процесс `api`, в `polling`-режиме эндпоинт отвечает 404.

## Типы
- `TelegramStatus` = `{enabled: bool, bot_username: str|null, linked: bool, telegram_username: str|null}`
- `LinkCode` = `{code: str, link: str, expires_at: iso}` — `code` 8 символов `[A-Z2-9]` без `0O1IL`; `link` = `https://t.me/<bot_username>?start=<code>`.
- `NotificationSetting` = `{event_type: str, title: str, description: str, is_enabled: bool, is_default: bool}` — `is_default = true`, если явной записи в БД нет и действует значение по умолчанию для роли.
- `User` (расширение модуля 1) += `telegram_linked: bool`, `telegram_username: str|null` (в списках и карточке `GET /users`, в `GET /auth/me` и `POST /auth/login`). Для `manager`/`mechanic` поле `telegram_username` в чужих записях всегда `null`.
- `Location` (расширение модуля 1/4) += `has_telegram_chat: bool` (всем ролям, у кого есть доступ к точке), `telegram_chat_id: int|null` (значение — только у `director`, у остальных `null`).

## Привязка аккаунта
- `GET /telegram/status` → `TelegramStatus`
- `POST /telegram/link-code` `{}` → 201 `LinkCode`. Предыдущие неиспользованные коды пользователя аннулируются. Ограничение: 5 запросов в минуту на пользователя → 429 `rate_limited`. Telegram выключен → 409 `telegram_disabled`; аккаунт уже привязан → 409 `already_linked`.
  - В БД хранится только SHA-256 кода (`code_hash`); код действует 10 минут и одноразовый; сравнение — по хешу.
- `DELETE /telegram/link` → 204 (идемпотентно): очищает `telegram_chat_id`/`telegram_username` пользователя, все его `pending`-сообщения помечаются `skipped`. Аудит `update` пользователя (`changes: {telegram_linked: {old: true, new: false}}`).
- Фронтенд после показа кода опрашивает `GET /telegram/status` каждые 3 секунды до `linked: true` или истечения `expires_at`.

### Бот
Бот обрабатывает только личные чаты (`chat.type = private`), кроме команды `/chatid`.
| Команда | Действие |
|---|---|
| `/start <code>` | Привязка: код найден по хешу, не использован, не истёк, пользователь активен → записать `chat_id`, `username`; ответ «Готово, <Имя>. Уведомления включены»; код помечается использованным; аудит `update` пользователя. Иначе единый ответ «Код не подходит или устарел. Получите новый в разделе «Настройки»». Если `chat_id` уже привязан к другому сотруднику → ответ «Этот чат уже привязан к другому сотруднику», привязка не выполняется |
| `/start` без кода, `/help` | Краткая справка: как привязать аккаунт, `/stop` |
| `/stop` | Отвязать этот чат (как `DELETE /telegram/link`) |
| `/chatid` | В любом чате (в том числе в группе) отвечает «ID этого чата: <число>» — чтобы директор мог ввести его в карточке точки |
Прочие сообщения игнорируются. Попытки привязки ограничены 10 в минуту на `chat_id` (в памяти процесса). Пользовательские данные в ответах бота экранируются `html.escape`.

### Вебхук
- `POST /telegram/webhook` — тело: Telegram `Update` (JSON, до 1 МБ). Заголовок `X-Telegram-Bot-Api-Secret-Token` обязателен и сверяется с `TELEGRAM_WEBHOOK_SECRET` (постоянное время), несовпадение/отсутствие → 403 `forbidden`. Всегда 200 `{}` после обработки (в том числе для необработанных типов обновлений), чтобы Telegram не повторял. Не отражается в документации API в проде. JWT не требуется.

## Настройки уведомлений
- `GET /telegram/notification-settings` → `NotificationSetting[]` — только события, применимые к роли (таблица ниже); порядок фиксирован.
- `PATCH /telegram/notification-settings` `{items: [{event_type, is_enabled}]}` → `NotificationSetting[]` (весь актуальный список). Неизвестное или не относящееся к роли событие → 422 `fields.items`. Пустой `items` → 422. Запись в `notification_settings` создаётся/обновляется (upsert); если значение совпало с умолчанием, запись остаётся.

## Точка: групповой чат
- `PATCH /locations/{id}` дополнительно принимает `telegram_chat_id: int|null` (только `director`; для менеджера → 403 `forbidden`). `null` отключает чат. Значение проверяется как целое со знаком в диапазоне int64. Аудит `update` точки без секретов.
- `POST /locations/{id}/telegram-test` `{}` → 200 `{sent: true}` — синхронно отправляет в чат точки сообщение «Проверка связи: точка <Название>» (таймаут 5 с, минуя outbox). Нет чата → 422 `fields.telegram_chat_id`; Telegram выключен → 409 `telegram_disabled`; Telegram вернул ошибку → 502 `telegram_unavailable` (без деталей Bot API; при 403/400 «chat not found» чат остаётся записанным, ошибка только отображается). Лимит 5 запросов в минуту.

## Каталог событий
`publish(event_type, payload, location_id=…, actor_id=…, target_user_id=…)` вызывается модулем-владельцем (колонка «Публикует») в транзакции бизнес-изменения. Получателей определяет модуль 7 в `publish`; публикующий код их не передаёт, кроме `target_user_id` там, где указан механик. Получатель получает сообщение, только если: пользователь активен, `telegram_chat_id` задан, событие у него включено (`notification_settings` либо значение по умолчанию), он привязан к точке события (для `manager`/`mechanic`; директор — без ограничения). Все события по умолчанию **включены** для подходящих ролей.

| Событие | Публикует | Получатели | Групповой чат точки | Ключ дедупликации (база) |
|---|---|---|---|---|
| `work_item.assigned` | м5 | механик `target_user_id` | нет | — |
| `work_item.updated` | м5 (срок, комментарий к позиции), м6 (`reopen`) | механик `target_user_id` | нет | — |
| `part_request.handled` | м6 | механик — автор заявки (`target_user_id`) | нет | `part_request.handled:{request_id}:{status}` |
| `appointment.created` | м4 (хук в сервисе записей, добавляет модуль 7) | менеджеры точки, **кроме** создавшего (`actor_id`) | нет | — |
| `appointment.no_show` | м4 (хук при смене статуса на `no_show`, добавляет модуль 7) | менеджеры точки | да | `appointment.no_show:{appointment_id}` |
| `work_item.finished` | м6 | менеджер заказа (`manager_id` заказа) | нет | — |
| `work_order.ready_for_check` | м6 | менеджер заказа | нет | `work_order.ready_for_check:{order_id}:{version}` |
| `part_request.created` | м6 | менеджеры точки | нет | — |
| `work_order.overdue` | м7 (задача каждые 5 минут) | менеджер заказа | да | `work_order.overdue:{order_id}:{planned_ready_at_epoch}` |
| `stock.low` | м8 | менеджеры точки | да | — (публикуется при пересечении порога, см. м8) |
| `payment.refund` | м9 | директора | нет | — |
| `order.discount_alert` | м5 | директора | нет | `order.discount_alert:{order_id}:{discount_percent}` |
| `user.locked` | м7 (хук в `auth` при блокировке по неудачным входам) | директора | нет | `user.locked:{user_id}:{locked_until_epoch}` |
| `report.daily_summary` | м10 (задача по расписанию) | директора | нет | `report.daily_summary:{date}` |

- «Менеджеры точки» — активные пользователи с ролью `manager`, привязанные к `location_id` события. «Директора» — все активные `director`. «Менеджер заказа» — пользователь `work_orders.manager_id` (любая роль `manager|director`).
- Строка в `notification_outbox` создаётся **на каждого получателя** (`user_id`, `chat_id`) и, если событие групповое и у точки задан `telegram_chat_id`, ещё одна строка на групповой чат (`user_id = null`). Ключ дедупликации в таблице = база + `:` + получатель (`user_id` либо `chat:<chat_id>`); повторная вставка с тем же ключом тихо игнорируется (`INSERT … ON CONFLICT DO NOTHING`).
- По умолчанию для ролей (для `GET /telegram/notification-settings`): `mechanic` — `work_item.assigned`, `work_item.updated`, `part_request.handled`; `manager` — `appointment.created`, `appointment.no_show`, `work_item.finished`, `work_order.ready_for_check`, `part_request.created`, `work_order.overdue`, `stock.low`; `director` — `user.locked`, `payment.refund`, `order.discount_alert`, `report.daily_summary`. Групповой чат от настроек пользователей не зависит.

### Состав `payload` и текст
`payload` — плоский словарь строк/чисел, хранится в `notification_outbox.payload` (jsonb) для диагностики; текст формируется при публикации и сохраняется готовым (`text`, ≤ 4096 символов, при превышении обрезается с `…`). Все пользовательские значения экранируются `html.escape`, режим отправки — `parse_mode=HTML`. Форматы времени — `DD.MM HH:MM` в поясе точки. Эмодзи в текстах не используются. Телефоны и ФИО клиентов в уведомления не включаются (только госномер и марка/модель).

| Событие | Ключи `payload` | Текст (шаблон) |
|---|---|---|
| `work_item.assigned` | `order_id, order_number, item_id, item_name, make, model, plate_number, planned_ready_at` | «Вам назначена работа: <b>{item_name}</b>. {make} {model} {plate_number}. Заказ {order_number}. Срок: {planned_ready_at\|«не задан»}» |
| `work_item.updated` | `order_id, order_number, item_id, item_name, change` (`deadline`\|`comment`\|`reopened`), `planned_ready_at?` | «Изменение по работе «{item_name}», заказ {order_number}: {новый срок {…}\|добавлен комментарий\|работа возвращена в исполнение}» |
| `part_request.handled` | `request_id, order_number, description, status` (`approved`\|`rejected`\|`issued`), `reject_reason?` | «Заявка «{description}» ({order_number}): {одобрена\|отклонена: {reject_reason}\|выдана}» |
| `appointment.created` | `appointment_id, start_at, plate_number, make, model, services_count, created_by_name` | «Новая запись: {start_at} {make} {model} {plate_number}, услуг: {n}. Создал: {created_by_name}» |
| `appointment.no_show` | `appointment_id, start_at, plate_number` | «Клиент не приехал: {start_at} {plate_number}» |
| `work_item.finished` | `order_id, order_number, item_name, mechanic_name, plate_number` | «{mechanic_name} завершил(а) работу «{item_name}», заказ {order_number}» |
| `work_order.ready_for_check` | `order_id, order_number, plate_number` | «Заказ {order_number} ({plate_number}): все работы выполнены, нужна проверка» |
| `part_request.created` | `request_id, order_number, description, quantity, mechanic_name` | «Заявка на запчасть: {description} × {quantity}, заказ {order_number}, {mechanic_name}» |
| `work_order.overdue` | `order_id, order_number, plate_number, planned_ready_at, status` | «Просрочен заказ {order_number} ({plate_number}), срок был {planned_ready_at}» |
| `stock.low` | `part_id, sku, name, quantity, min_quantity, location_name` | «Остаток ниже минимума: {name} ({sku}) — {quantity} при минимуме {min_quantity}, {location_name}» |
| `payment.refund` | `order_number, amount, method, location_name, user_name, reason` | «Возврат {amount} ₽ по заказу {order_number} ({location_name}), оформил {user_name}. Причина: {reason}» |
| `order.discount_alert` | `order_id, order_number, discount_percent, location_name, user_name` | «Скидка {discount_percent}% в заказе {order_number} ({location_name}), {user_name}» |
| `user.locked` | `user_id, login, full_name, locked_until` | «Учётная запись {login} ({full_name}) заблокирована после неудачных попыток входа до {locked_until}» |
| `report.daily_summary` | `date, location_name\|null, revenue, orders_closed, orders_open, cash_received` | Форматирует модуль 10 (см. `api-contract-m10.md`): итоги дня по точкам |

Суммы в `payload` — `Money`-строки, форматирование текста (пробелы тысяч, `₽`) — на сервере.

## Воркер
Единый процесс `python -m app.worker` (контейнер `worker`), создаётся модулем 7. Внутри — asyncio-цикл и **реестр периодических задач** (`name`, `interval|cron`, `callable`); модули 10, 11, 12 регистрируют свои задачи в том же реестре, не создавая отдельных процессов. Каждая задача выполняется под PostgreSQL advisory lock (`pg_try_advisory_lock(hashtext(name))` на выделенном соединении) — при нескольких экземплярах воркера задача идёт ровно в одном. Ошибки задач логируются (`structlog`, без персональных данных) и не останавливают цикл; на сигнал остановки текущая итерация дорабатывается.

Задачи модуля 7:
| Задача | Расписание | Действие |
|---|---|---|
| `outbox_dispatch` | постоянный цикл: пауза 1 с при пустой очереди | Берёт до 30 строк `status = 'pending' AND next_attempt_at <= now()` через `FOR UPDATE SKIP LOCKED`, отправляет `sendMessage`; общий лимит 30 сообщений/с, на один чат — не чаще 1 в секунду (для групп не чаще 20 в минуту) |
| `overdue_scan` | каждые 5 минут | Находит заказы `planned_ready_at < now()`, статус `∉ {ready, closed, cancelled}` и публикует `work_order.overdue` (дедупликация по ключу не даёт повторов для того же срока) |
| `outbox_cleanup` | раз в сутки, 03:30 `APP_TIMEZONE` | Удаляет `sent|skipped|failed` старше 30 дней |

Правила отправки:
- Успех → `status = sent`, `sent_at`.
- Временная ошибка (сеть, 5xx, таймаут 10 с) или 429 → `attempts += 1`, `next_attempt_at = now + 30 с × 2^(attempts − 1)` (для 429 — не раньше `retry_after`), после 5 неудач `status = failed`, `last_error` (≤ 500 символов, без токена).
- 403 «бот заблокирован/исключён» или 400 «chat not found» → `status = skipped`, `last_error = 'blocked'`; `telegram_chat_id` пользователя (или точки, если это групповой чат) очищается, остальные `pending` для этого `chat_id` → `skipped`. Аудит `update`.
- Сообщения обрабатываются в порядке `id`.
- Telegram выключен (`enabled = false`) → `publish` строки не создаёт.

## Правила и ошибки
| Правило | Ответ |
|---|---|
| Telegram выключен (нет токена) | 409 `telegram_disabled` на `link-code`, `telegram-test` |
| Аккаунт уже привязан | 409 `already_linked` |
| Лимит запросов кода / тестов | 429 `rate_limited` |
| Неверный/отсутствующий секрет вебхука | 403 `forbidden` |
| Событие не относится к роли | 422 `fields.items` |
| Нет `telegram_chat_id` у точки в тесте | 422 `fields.telegram_chat_id` |
| Ошибка Bot API при тесте | 502 `telegram_unavailable` |

Новые коды для `ERROR_MESSAGES`: `telegram_disabled`, `already_linked`, `telegram_unavailable`. Аудит: привязка/отвязка и смена `telegram_chat_id` точки пишутся как `update` (`entity_type = user | location`); содержимое сообщений в аудит не попадает.

## Миграция `0007_telegram_outbox`
- Таблицы (по `docs/02-database-schema.md` §3.1, §3.9): `telegram_link_codes`, `notification_settings`, `notification_outbox`.
- Расширение `notification_outbox` относительно схемы: колонка `dedup_key varchar(120) NULL` и `CREATE UNIQUE INDEX notification_outbox_dedup ON notification_outbox (dedup_key) WHERE dedup_key IS NOT NULL`; индекс `(next_attempt_at) WHERE status = 'pending'` (из схемы); индекс `(chat_id, status)` для массового пропуска.
- `telegram_link_codes`: индекс `(user_id, created_at DESC)`; уникальный `code_hash`.
- Колонки `users.telegram_chat_id` (уникальная), `users.telegram_username`, `locations.telegram_chat_id` уже есть в модуле 1; в миграцию не входят.
- Права БД: `crm_app` — полный набор на три таблицы.
- Новых ролей нет.

## Зависимости
- Модуль 6 (события таймера и заявок), модуль 5 (`events.publish`-заглушка, заказы). Хуки в модуле 4 (`appointment.created`, `no_show`) и модуле 1 (`user.locked`) добавляет **агент модуля 7**, внеся минимальные правки в `services/appointments.py` и `services/auth.py` (одна строка `publish(...)` в каждом месте).
- События модулей 8, 9, 10 публикуют сами эти модули; если модуль 7 ещё не влит, вызовы остаются no-op.

## Что можно разрабатывать параллельно
- Backend: (а) бот и привязка; (б) outbox, воркер и каталог событий; (в) `overdue_scan`. Frontend (секция Telegram в C-02, поле чата в D-06) — независимо на MSW.
- Модули 8, 9, 10, 11 могут стартовать без модуля 7: они вызывают заглушку `publish`.

## Экраны фронтенда (по `docs/03-ui-screens.md`)
| Код | Маршрут | Содержание и состояния |
|---|---|---|
| C-02 (секция «Telegram») | `/settings` | Все роли. Состояния: `enabled = false` — «Telegram не настроен, обратитесь к руководителю»; не привязан — кнопка «Привязать Telegram» → код (крупно, моноширинно), кнопка «Открыть в Telegram» (`link`), обратный отсчёт до `expires_at`, автоопрос статуса, при истечении — «Получить новый код»; привязан — «Подключён: @username», «Отключить» (подтверждение), список переключателей событий роли (`GET /telegram/notification-settings`) с мгновенным сохранением и откатом при ошибке. Ошибки `already_linked`, `rate_limited` — под кнопкой. Загрузка — скелетон секции |
| D-06 (поле) | `/locations/:id` | Только `director`. Поле «Telegram-чат точки» (числовой ID; подсказка «Добавьте бота в группу и отправьте /chatid»), кнопка «Отправить тест», индикатор результата; для менеджера — только статус «Чат подключён / не подключён» (`has_telegram_chat`) |
| D-04 (колонка) | `/users` | Колонка «Telegram подключён» по `User.telegram_linked` |
