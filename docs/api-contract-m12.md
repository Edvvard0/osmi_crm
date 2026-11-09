# Контракт модуля 12 — PWA, офлайн, безопасность, развёртывание

Префикс `/api/v1`. Общие соглашения (типы, ошибки, миграции, воркер) — в `api-contract-m5.md` и `api-contract-m7.md`. Модуль почти не меняет бизнес-API: он добавляет проверки готовности, закрепляет заголовки безопасности и офлайн-поведение клиента, доводит инфраструктуру до промышленного вида и задаёт перечень обязательных проверок. Исходные требования — `docs/01-development-plan.md` (раздел 4 «Безопасность» и модуль 12).

## Конфигурация окружения (общий реестр)
Переменные читает `app/core/config.py` (`Settings`, `extra="ignore"`). Модули 1–11 уже используют часть из них; полный перечень — единственный источник для `.env.example` и `.env.prod.example`.

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `ENV` | `dev` | `dev` / `test` / `prod`; в `prod` отключены `/api/docs`, `/api/redoc`, `/openapi.json`, cookie `Secure` |
| `DATABASE_URL`, `SECRET_KEY` | — (в `prod` обязательны; `SECRET_KEY` не равен dev-значению) | БД и подпись JWT |
| `APP_TIMEZONE` | `Europe/Moscow` | IANA-зона для «сегодня» вне контекста точки: планировщик воркера, сводка директору, значения по умолчанию периодов отчётов. Расчёты, привязанные к точке, всегда идут в `Location.timezone` |
| `PUBLIC_BASE_URL` | `http://localhost:5173` | Публичный адрес фронтенда (ссылки в уведомлениях, единственный разрешённый CORS-origin в `prod`) |
| `CORS_ORIGINS` | пусто | Дополнительные origin через запятую (только для `dev`); в `prod` игнорируется — запросы идут с того же домена через edge |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_MODE`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_API_BASE` | см. `api-contract-m7.md` | Telegram |
| `SEED_DIRECTOR_PASSWORD` | — | Пароль руководителя при первичном заполнении (в `prod` без неё команда отказывается работать) |
| `LOG_LEVEL` | `INFO` | Уровень структурных логов (JSON в `prod`) |
| `WORKER_HEARTBEAT_SECONDS` | `30` | Период записи heartbeat воркера |
| `READY_WORKER_MAX_AGE_SECONDS` | `120` | Максимальный возраст heartbeat для `ok` |
| `READY_OUTBOX_MAX_AGE_SECONDS` | `300` | Максимальный возраст самого старого `pending` в `notification_outbox` |
| `BACKUP_RETENTION_DAYS` | `30` | Срок хранения дампов |
| `APP_VERSION` | `dev` | Строка сборки (передаётся build-arg образа) для `GET /system/status` |

Остальные (`ACCESS_TTL_SECONDS`, `REFRESH_TTL_DAYS`, `LOGIN_PER_MINUTE`, `MAX_BODY_BYTES` …) остаются как в модуле 1.

## Здоровье и готовность
Все три эндпоинта доступны **без аутентификации**, не раскрывают версий и строк подключения, не пишут аудит.

| Эндпоинт | Назначение | Ответ |
|---|---|---|
| `GET /api/v1/health` | Liveness (уже есть): процесс жив и достаёт БД | 200 `{"status":"ok","db":true}` / 503 `{"status":"degraded","db":false}` — формат не меняется |
| `GET /api/v1/health/ready` | Readiness (новый) | см. ниже |
| `GET /api/v1/system/status` | Подробное состояние для руководителя (D-01, блок «Система») | `SystemStatus`; только `director` (иначе 403 `forbidden`) |

### `GET /health/ready`
```
{ "status": "ok"|"degraded"|"down",
  "checks": {
    "db":         {"ok": bool},
    "migrations": {"ok": bool, "current": str|null, "head": str},
    "worker":     {"ok": bool, "heartbeat_age_seconds": int|null},
    "outbox":     {"ok": bool, "pending": int, "oldest_pending_age_seconds": int|null}
  } }
```
- `db` — `SELECT 1` за ≤ 2 с. `migrations` — значение `alembic_version` равно единственной голове скриптов (`head`, вычисляется при старте процесса).
- `worker` — возраст ключа `_worker_heartbeat` (таблица `system_settings`, значение `{"at": iso, "pid": int}`; воркер обновляет его каждые `WORKER_HEARTBEAT_SECONDS`). Нет записи или возраст > `READY_WORKER_MAX_AGE_SECONDS` → `ok = false`. Если `TELEGRAM_MODE = disabled`, проверка `worker.ok` не учитывается в статусе, но поле остаётся.
- `outbox` — число `pending` и возраст старейшего (`created_at`); старше `READY_OUTBOX_MAX_AGE_SECONDS` → `ok = false`. При `TELEGRAM_MODE = disabled` — всегда `ok = true`.
- Статус и код: `db` или `migrations` не `ok` → `"down"`, HTTP **503**. Иначе `worker` или `outbox` не `ok` → `"degraded"`, HTTP **200** (приложение обслуживает запросы; сигнал для мониторинга). Всё `ok` → `"ok"`, 200.
- Используется: healthcheck контейнера `api` в `docker-compose.prod.yml` (только `down` считается нездоровым), шаг «ждать готовности» в `make prod-up` и e2e.
- Ограничение частоты: общий лимит edge (см. ниже); результат кэшируется в процессе на 2 с.

### Heartbeat воркера
Задача `heartbeat`, которую модуль 12 регистрирует в реестре воркера (`api-contract-m7.md`), пишет `system_settings['_worker_heartbeat']` каждые `WORKER_HEARTBEAT_SECONDS`. Healthcheck контейнера воркера — `python -m app.worker --healthcheck` (код выхода 0, если heartbeat свежий). Ключ с префиксом `_` не отдаётся через `/settings` (модуль 11).

### `GET /system/status` (director)
`SystemStatus` = `{server_time: iso, app_timezone: str, env: "prod"|"dev"|"test", migrations: {current, head}, worker: {last_heartbeat_at: iso|null, ok: bool}, outbox: {pending: int, failed_24h: int, oldest_pending_age_seconds: int|null}, telegram: {mode: "disabled"|"polling"|"webhook", bot_username: str|null}, last_backup_at: iso|null, version: str}`
- `version` — строка сборки из `APP_VERSION` (образ, по умолчанию `dev`); `last_backup_at` — из файла-метки `backup/last_success` (контейнер `backup` пишет, `api` монтирует только для чтения); при отсутствии `null`.
- Секретов (токены, пароли, URL БД) в ответе нет.

## Ответы об ошибках
- Необработанное исключение → 500 `{"error":{"code":"internal_error","message":"Внутренняя ошибка сервера","fields":{},"request_id":"…"}}`; стека, SQL и путей в ответе нет, подробности только в логе с тем же `request_id`.
- Ошибки edge-прокси (502/503/504, когда `api` недоступен) возвращает nginx собственным JSON-ответом **в том же формате**: `{"error":{"code":"service_unavailable","message":"Сервис временно недоступен","fields":{},"request_id":"$request_id"}}` с `Content-Type: application/json`; для 413 — `{"code":"payload_too_large"}`, для 429 лимита edge — `{"code":"rate_limited"}`. Новые коды `service_unavailable`, `payload_too_large` добавляются в `ERROR_MESSAGES`; `rate_limited` и `internal_error` уже есть.
- Для запросов не к `/api/` при недоступности `web` nginx отдаёт статический `offline.html`.

## Заголовки безопасности и edge-прокси
Устанавливаются **nginx (edge)** на каждый ответ (`always`), включая ошибки; API дополнительно ставит `X-Content-Type-Options: nosniff` и `Cache-Control: no-store` на все ответы `/api/v1/**` (кроме `/health*`), чтобы данные не оседали в HTTP-кэшах.

| Заголовок | Значение |
|---|---|
| `Content-Security-Policy` | `default-src 'self'; script-src 'self'; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'` (расширение относительно плана: `form-action`; `font-src` и `style-src` наследуются от `default-src`). Режим `'unsafe-inline'` для стилей **не допускается**: если сборка его требует, это дефект фронтенда |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains` (только по HTTPS) |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `same-origin` |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` |
| `X-Frame-Options` | `DENY` (дублирует `frame-ancestors` для старых браузеров) |
| `server_tokens off`, скрытые `X-Powered-By`/`Server` версии | обязательно |

- **TLS**: порт 80 только перенаправляет на HTTPS (кроме `/.well-known/acme-challenge/`); TLS 1.2+, современные шифры; сертификаты Let's Encrypt (`certbot`), автообновление, `nginx -s reload` после выпуска.
- **CORS**: в `prod` API не отдаёт `Access-Control-Allow-*` вообще (приложение и API с одного origin). В `dev` разрешён только `PUBLIC_BASE_URL` и `CORS_ORIGINS`, с `allow_credentials`; подстановочного `*` нигде нет.
- **Лимиты edge**: общая зона `api` — 20 запросов/с на IP (burst 40); отдельная зона для `POST /api/v1/auth/login` и `/auth/refresh` — 30 запросов/мин (точный лимит по аккаунту/IP остаётся на backend, модуль 1); `client_max_body_size 1m`; `POST /api/v1/telegram/webhook` — тело ≤ 64 КБ. Превышение → 429 в формате выше.
- **Кэш статики**: `/assets/*` — `public, max-age=31536000, immutable`; `index.html`, `sw.js`, `manifest.webmanifest`, `offline.html` — `no-cache`; `/api/**` — не кэшируется прокси.
- **Cookie refresh** (модуль 1): `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth`.
- **Прочее**: `/api/docs`, `/api/redoc`, `/openapi.json` в `prod` возвращают 404; доступа к PostgreSQL снаружи нет (порт 5432 не опубликован); в логах нет паролей, токенов, содержимого Telegram-сообщений и тел запросов.

## PWA и офлайн-поведение (клиент)
Реализуется во фронтенде (`vite-plugin-pwa`, `registerType: "prompt"`); серверных изменений, кроме заголовков кэша статики, нет.

### Манифест
`name: "CRM Автосервис"`, `short_name: "CRM"`, `lang: "ru"`, `start_url: "/"`, `scope: "/"`, `display: "standalone"`, `background_color`/`theme_color` — цвет шапки; иконки 192×192, 512×512 (`any`) и 512×512 (`maskable`); `id: "/"`. Страница установки на iOS — meta-теги `apple-mobile-web-app-*` и `apple-touch-icon` 180×180.

### Что кэшируется
- **Оболочка приложения** (precache): `index.html`, хешированные `/assets/*`, иконки, `offline.html`; навигационные запросы (кроме `/api/`) отвечают `index.html` (SPA-fallback).
- **Данные (runtime-кэш `api-read-v1`)**: стратегия NetworkFirst, таймаут сети 4 с, не более 100 записей, возраст ≤ 24 ч, только `GET` с кодом 200 и только по белому списку:
  `/api/v1/work-orders` (список и карточка), `/api/v1/mechanic/*` (модуль 6: «Мои задачи» и связанные чтения), `/api/v1/appointments`, `/api/v1/services`, `/api/v1/service-categories`, `/api/v1/posts`, `/api/v1/locations`, `/api/v1/parts`.
- **Никогда не кэшируется**: `/api/v1/auth/**`, `/api/v1/users**`, `/api/v1/clients**`, `/api/v1/vehicles**`, `/api/v1/search`, `/api/v1/telegram/**`, `/api/v1/payments**`, `/api/v1/expenses**`, `/api/v1/cash/**`, `/api/v1/stock**`, `/api/v1/payroll**`, `/api/v1/reports/**`, `/api/v1/me/**`, `/api/v1/audit-log**`, `/api/v1/settings`, `/api/v1/health**`, `/api/v1/system/**`, любые не-`GET`. Финансы, персональные данные и административные чтения офлайн не показываются.
- **Очистка**: кэш `api-read-v1` удаляется при выходе (`logout`), при принудительном выходе (`invalid_token` после неудачного refresh) и **перед** первым запросом после входа другого пользователя; смена роли/блокировка тоже приводят к принудительному выходу. Ключ кэша — полный URL, поэтому очистка при смене пользователя обязательна.

### Состояния соединения
- **Офлайн** определяется по `navigator.onLine === false` либо по сетевой ошибке (не HTTP-статусу) запроса. Появляется баннер C-04 под шапкой: «Нет соединения. Показаны данные на HH:MM», где `HH:MM` — время последнего успешного ответа для текущего экрана (локальное время устройства); если данных из кэша нет — «Нет соединения». Баннер исчезает после события `online` и первого успешного запроса.
- **Мутации офлайн заблокированы**: кнопки действий (`POST/PATCH/PUT/DELETE`) отключены с подсказкой «Нет соединения — действие недоступно», отправка форм невозможна; очередь отложенных действий и фоновая синхронизация **не** применяются. Если мутация всё же упала с сетевой ошибкой, показывается toast «Нет соединения. Действие не выполнено», автоповтора мутаций нет (повтор безопасных `GET` — как сейчас в `queryClient`).
- **Сервер недоступен (502/503/504)**: баннер C-04 не показывается; обработчик ошибок выводит `ERROR_MESSAGES.service_unavailable` в toast / блоке ошибки экрана («Повторить»).
- Просроченная сессия офлайн: access-токен живёт в памяти и не восстанавливается; после перезагрузки страницы без сети экран логина показывает баннер C-04, вход невозможен до восстановления сети.

### Обновление версии
- Service worker регистрируется с `registerType: "prompt"`: новая версия скачивается в фоне, **автоперезагрузки нет**.
- Проверка обновлений: при возврате вкладки в фокус и раз в 60 минут.
- Когда новая версия готова, показывается C-05 — плашка «Доступна новая версия» с кнопкой «Обновить» (вызов `updateServiceWorker(true)` и перезагрузка) и «Позже» (скрыть до следующего запуска). Если на экране есть несохранённая форма, кнопка «Обновить» предупреждает о потере ввода.
- Несовместимость API: сервер при несовпадении не отдаёт ничего особенного; клиент и сервер выпускаются одной сборкой, а кэшированные ответы из `api-read-v1` старой версии при обновлении оболочки очищаются (имя кэша содержит версию схемы `v1`; смена формата ответов повышает номер версии).
- C-06 «Сломанный экран» (`ErrorBoundary`): при необработанной ошибке рендера — сообщение «Что-то пошло не так», кнопки «Обновить страницу» и «На главную»; ошибка отправляется на `POST /api/v1/client-errors` (модуль 0) без персональных данных.

### Требования к качеству
- Lighthouse (мобильный профиль, production-сборка): PWA — все обязательные проверки установимости, Accessibility ≥ 90, Best Practices ≥ 90, Performance ≥ 85. Размер начального JS (gzip) ≤ 250 КБ; маршруты загружаются лениво.
- Минимальные размеры касания 44×44 px на mobile; контраст по WCAG AA (проверка есть в Lighthouse/axe).

## Безопасность: обязательные проверки
Модуль 12 добавляет автоматические проверки (backend `tests/security/`, e2e/CI-шаги) и ручной чек-лист; продуктовых эндпоинтов они не требуют.

### Автоматические (backend)
1. **Матрица авторизации**: тест обходит `app.routes`; для каждого маршрута, кроме белого списка (`/health`, `/health/ready`, `/auth/login`, `/auth/refresh`, `/client-errors`, `/telegram/webhook`), без токена ожидается 401, с токеном недопустимой роли — 403, для объектов чужой точки — 404 (список ролей по таблицам прав контрактов 1–11). Новый маршрут без записи в матрице роняет тест.
2. **Заголовки и конфигурация** (интеграционный тест через nginx в `e2e`): все заголовки таблицы выше, отсутствие `Server` версии, 404 на `/api/docs` в `prod`, cookie с `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth`, отсутствие CORS-заголовков для чужого `Origin`.
3. **Инъекции**: SQL-инъекции в параметрах поиска/фильтров (параметризованные запросы), XSS-пейлоады в `SafeText`-полях (вырезаются), CSV/XLSX-экспорт с префиксом `'` для значений, начинающихся с `=`, `+`, `-`, `@`.
4. **Ограничения**: размер тела (413), лимиты `login` (429), блокировка аккаунта (423), повторное использование refresh-токена (отзыв семьи).
5. **Секреты**: тест запрещает попадание значений `password|token|secret|hash` в `audit_log.changes`, логи и ответы об ошибках.
6. **Права БД**: роль `crm_app` не имеет `UPDATE/DELETE/TRUNCATE` на `audit_log` и `stock_movements`, `UPDATE/DELETE` на `payments`, `payroll_adjustments` (проверка через `has_table_privilege`).
7. **Миграции**: `upgrade → downgrade → upgrade` на пустой БД; ровно одна голова `alembic heads == 0012`; схема после `upgrade head` совпадает с моделями SQLAlchemy.
8. **Покрытие**: backend ≥ 85 % (модули `auth`, `cash`/платежи, `warehouse`/склад, `payroll` ≥ 95 %), frontend ≥ 70 % (порог в `vite.config.ts` уже задан). Падение порога — красный CI.

### CI и сканирование
- Шаги: `lint` (ruff, mypy, eslint, tsc), `test` (backend, frontend), `e2e` (Playwright на `docker-compose.test.yml` против nginx), `trivy` (образы и зависимости: High/Critical блокируют), `pip-audit`/`npm audit --omit=dev` (High/Critical блокируют), сборка прод-образов.
- **Нагрузка** (Locust, сценарии «менеджер», «механик», «директор»): 200 одновременных пользователей, p95 < 300 мс на чтениях и записях, доля ошибок < 1 %; отчёт сохраняется как артефакт CI.
- **ZAP baseline** против поднятого стенда: High/Medium = 0; результат сопоставляется с чек-листом OWASP ASVS уровня 2 (файл `docs/security-checklist.md` — пункты «выполнено/не применимо/исключение с обоснованием»).

## Развёртывание
### Состав прод-окружения (`docker-compose.prod.yml`)
Файл в репозитории — заготовка (`db`, `api`, `web`, `edge`); модуль 12 приводит его к составу ниже.

| Сервис | Образ / команда | Примечания |
|---|---|---|
| `db` | `postgres:16-alpine` | Данные в томе `pgdata`; порт наружу не публикуется; пароль из секрета; healthcheck `pg_isready`; роли `crm_migrator` (DDL) и `crm_app` (DML) создаёт init-скрипт |
| `migrate` | образ backend, `alembic upgrade head` | Одноразовый; от роли `crm_migrator`; `api` и `worker` ждут `service_completed_successfully` |
| `api` | образ backend, `uvicorn` без `--reload`, 2 воркера | Роль `crm_app`; `read_only`, `cap_drop: [ALL]`, `no-new-privileges`; healthcheck `GET /api/v1/health/ready` |
| `worker` | образ backend, `python -m app.worker` | Тот же код и окружение; один экземпляр (advisory lock страхует от дубля); healthcheck `--healthcheck` |
| `web` | образ frontend (статика, SPA fallback) | `read_only`; `GET /healthz` |
| `edge` | `nginx` | Порты 80/443; конфиг из `deploy/nginx`; заголовки и лимиты как выше; общий том с сертификатами |
| `certbot` | `certbot/certbot` | Цикл автообновления раз в 12 часов; webroot для `/.well-known/acme-challenge/` |
| `backup` | образ с `pg_dump` + `cron` | Ежедневно в 03:00 `APP_TIMEZONE`: `pg_dump -Fc` → том `backups`, хранение `BACKUP_RETENTION_DAYS` (30) дней, метка `last_success`; опционально выгрузка на внешнее хранилище |

- Для всех сервисов `restart: unless-stopped`, логи `json-file` с ротацией (`max-size: 10m`, `max-file: 5`). Секреты — через Docker secrets / `.env.prod` вне репозитория (в репозитории только `.env.prod.example` без значений). Образы собираются с зафиксированными тегами, процессы не от root.
- Бот Telegram: в `webhook`-режиме — через `edge`; в `polling` — внутри `worker` (отдельного сервиса `bot` в проде нет; в dev-compose он есть по плану).
- **dev-compose**: `postgres`, `migrate`, `api`, `worker`, `bot` (polling), `frontend` (Vite), `nginx`. **test-compose**: `postgres-test` (tmpfs), `backend-tests`, `frontend-tests`, `e2e`.

### Команды Makefile
| Цель | Действие |
|---|---|
| `make up` / `down` / `logs` | dev-стенд |
| `make migrate` | `alembic upgrade head` в dev |
| `make seed` | первичное заполнение (команда сидирования модуля 1) |
| `make test` | тесты в `docker-compose.test.yml` |
| `make lint` | ruff, mypy, eslint, tsc |
| `make prod-up` | `docker compose -f docker-compose.prod.yml up -d --build`, затем ожидание `GET /api/v1/health/ready` до 120 с (ненулевой код выхода при неготовности) |
| `make prod-down`, `make prod-logs` | остановка / логи прод |
| `make prod-backup` | немедленный дамп |
| `make prod-restore-check` | проверка восстановления: поднять временную БД, развернуть последний дамп, выполнить смоук-запросы (число пользователей, версия миграции равна `head`), удалить временную БД |

Обновление на сервере — `git pull && make prod-up`: миграции применяются автоматически сервисом `migrate` до старта `api`/`worker`, простой ≤ нескольких секунд (перезапуск контейнеров), потери данных нет. Откат — предыдущий коммит и `make prod-up` (миграции `downgrade` вручную, только по инструкции в `docs/deployment.md`).

### Документация (результат модуля)
`docs/deployment.md` (подготовка VPS, DNS, переменные, первичный запуск, получение сертификата, настройка Telegram, обновление, откат, бэкапы и восстановление, мониторинг `health/ready`), `docs/security-checklist.md` (ASVS L2), руководство пользователя в `docs/user-guide.md` (разделы по ролям: механик, менеджер, руководитель; установка PWA на Android и iOS; что делать без связи).

## Ручные проверки перед выпуском
- Установка PWA на Android (Chrome) и iOS (Safari, «На экран Домой»); запуск как отдельного приложения.
- Офлайн: режим «в самолёте» на открытой «Моей задаче» и календаре — данные из кэша, баннер C-04, мутации заблокированы; возврат сети снимает баннер.
- Выход и вход другим пользователем — кэшированные данные первого недоступны.
- Обновление: выпустить новую сборку при открытом приложении — появляется «Доступна новая версия», «Обновить» применяет её.
- Чистый VPS: выполнение `docs/deployment.md` с нуля до рабочей системы; HTTPS, выпуск и автообновление сертификата.
- Перезапуск: `reboot` сервера — все сервисы поднимаются сами, данные на месте, воркер продолжает отправку.
- Резервное копирование: `make prod-restore-check` на реальном дампе; удаление дампов старше 30 дней.
- ZAP baseline без High/Medium; чек-лист ASVS L2 заполнен.
- Telegram: тестовое сообщение на группу точки и на личный чат (модуль 7) через прод-контур.
- Остановка `api` → пользователь видит JSON-ошибку nginx и сообщение в интерфейсе; остановка `worker` → `health/ready` показывает `degraded`.

## Миграция `0012_hardening`
- **Новых таблиц нет.** Ревизия `0012` занята заглушкой: `upgrade()`/`downgrade()` пустые; при необходимости — только идемпотентные `GRANT`/`REVOKE`, выравнивающие права `crm_app` (см. проверку 6), и индексы, найденные нагрузочным тестом. Любые индексы добавляются `CREATE INDEX IF NOT EXISTS` и не меняют контракты API.
- Таблица `system_settings` (миграция `0011`) используется для служебного ключа `_worker_heartbeat`. Задачу `heartbeat` добавляет **модуль 12** (в реестр воркера из модуля 7); до выхода модуля 12 (и если таблицы `system_settings` ещё нет) воркер работает без неё.
- Новых прав доступа в ролевой матрице нет, кроме `GET /system/status` (только `director`).

## Зависимости
- От всех модулей 1–11: матрица авторизации охватывает все маршруты; `health/ready` читает `system_settings` (11), `notification_outbox` (7) и воркер (7); белый список офлайн-кэша ссылается на эндпоинты 4–6.
- Фронтенд-часть (PWA, баннеры C-04/C-05/C-06) зависит только от модуля 0 и существующего `queryClient`/`OfflineBanner`.

## Что можно разрабатывать параллельно
- Не дожидаясь остальных модулей: (а) edge-nginx, заголовки, TLS, сервисы certbot/backup, Makefile, `docs/deployment.md`; (б) офлайн-кэш и баннеры C-04/C-05/C-06 на уже существующих эндпоинтах; (в) `health/ready` (с заглушкой heartbeat до модуля 7); (г) Locust-сценарии и ZAP-стенд на готовых модулях.
- После модулей 1–11: матрица авторизации, полное покрытие, нагрузочные цифры, финальные ручные проверки.

## Экраны фронтенда (по `docs/03-ui-screens.md`)
Новых страниц нет: модуль добавляет сквозные компоненты, видимые всем ролям.

| Код | Где | Роли | Содержание и состояния |
|---|---|---|---|
| C-04 | под шапкой всех экранов (включая `/login`) | все | Баннер «Нет соединения. Показаны данные на HH:MM» / «Нет соединения»; `role="alert"`; мутации отключены с подсказкой; исчезает при восстановлении |
| C-05 | плашка поверх нижней панели / в шапке | все | «Доступна новая версия» + «Обновить» / «Позже»; предупреждение о несохранённой форме |
| C-06 | `ErrorBoundary` на весь маршрутный экран | все | «Что-то пошло не так» + «Обновить страницу» / «На главную»; отчёт в `client-errors` |
| (блок) | D-01 | `director` | Небольшая карточка «Система» по `GET /system/status`: воркер, очередь уведомлений, последняя резервная копия; состояния: загрузка — скелетон, ошибка — «Нет данных о состоянии системы» |
