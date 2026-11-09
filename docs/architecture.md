# Архитектура и разработка

## Состав

```
crm/
├─ backend/            FastAPI-приложение, воркер, бот, миграции, тесты
├─ frontend/           React PWA
├─ deploy/nginx/       конфигурация edge-nginx
├─ docs/               план, схема БД, экраны, API-контракты, руководства
├─ docker-compose.yml        dev
├─ docker-compose.test.yml   тесты в одноразовых контейнерах
└─ docker-compose.prod.yml   прод
```

Процессы в проде: `db` (PostgreSQL 16), `api` (uvicorn), `worker` (outbox, Telegram, периодические задачи), `web` (статические файлы фронтенда), `edge` (nginx, единственная точка входа). Redis и брокеры очередей не используются: очередь — таблица outbox в PostgreSQL.

## Бэкенд

Стек: Python 3.12+, FastAPI, SQLAlchemy 2 (async, asyncpg), Alembic, Pydantic 2, structlog, argon2 (пароли), PyJWT, nh3 (очистка HTML), fpdf2 (PDF).

```
app/
├─ main.py            сборка приложения, middleware, автоподключение роутеров
├─ api/v1/*.py        HTTP-слой: только разбор запроса, права, вызов сервиса
├─ api/deps.py        CurrentUser, Director, AllowedLocations, SessionDep …
├─ schemas/*.py       Pydantic-схемы (вход — extra="forbid")
├─ services/*.py      бизнес-логика и транзакции
├─ models/*.py        ORM-модели
├─ core/              конфиг, БД, ошибки, безопасность, rate limit, логи, периодические задачи
├─ tasks/*.py         периодические задачи воркера (register(...))
├─ worker.py          воркер: outbox → Telegram, периодические задачи, heartbeat
├─ bot.py             Telegram-бот (polling-режим)
└─ cli.py             seed, telegram-set-webhook
```

Соглашения:
- **Автоподключение.** Любой `app/api/v1/<name>.py` с переменной `router` подключается под `/api/v1`; модели из `app/models/*.py` и задачи из `app/tasks/*.py` импортируются автоматически.
- **Ошибки.** Единый формат `{"error": {"code", "message", "fields", "request_id", "details?"}}`. Сервисы бросают `AppError(status, code, …)`; 500 никогда не раскрывает внутренности, 422 не возвращает введённые значения.
- **Права.** Роль проверяется зависимостью (`Director`, `Staff` = менеджер или руководитель, `CurrentUser`), точка — через `AllowedLocations`: чужая и несуществующая сущность неразличимы (404).
- **Конкурентность.** Изменяемые сущности имеют `version`; несовпадение → 409 `version_conflict`. Денежные и складские операции блокируют строки (`SELECT … FOR UPDATE`). Оплаты идемпотентны по `client_request_id`.
- **Деньги и количества** — `Decimal`, в API передаются строками (`"1250.00"`, `"2.500"`), округление ROUND_HALF_UP.
- **События.** `services.events.publish(...)` пишет событие в outbox в той же транзакции; воркер рассылает уведомления (at-least-once с дедупликацией).
- **Аудит.** `services.audit.write_audit(...)` — кто/что/когда; секреты маскируются.
- **Время** хранится в UTC; часовой пояс точки — для отображения и отчётов.

Миграции: `migrations/versions/0001…0012`, одна голова. Новая миграция: `alembic revision -m "..."` → проверить `alembic heads`.

## Фронтенд

Стек: React 18, TypeScript, Vite 5, Tailwind 3, React Router 6, TanStack Query 5, vite-plugin-pwa, Vitest + Testing Library.

```
src/
├─ app/          App, Layout (меню по ролям), ErrorBoundary, OfflineBanner, UpdatePrompt, queryClient
├─ features/<x>/ модуль: api.ts (хуки запросов), types.ts, страницы, errors.ts, nav.ts, routes.tsx
├─ pages/        общие страницы (вход, рабочий стол, настройки, справочники)
├─ shared/       api-клиент, словарь ошибок, UI-компоненты, утилиты, PWA
└─ test/         тесты по модулям (m1…m12.test.tsx), mockApi
```

- **Автореестры:** `features/*/nav.ts` (пункты меню), `features/*/routes.tsx` (маршруты), `features/*/errors.ts` (тексты ошибок) собираются через `import.meta.glob`.
- **API-клиент** (`shared/api/client.ts`) добавляет access-токен, обновляет его по refresh-cookie, превращает ответы в `AppError`; текст для пользователя — только из словаря.
- **Офлайн:** кэш только GET из белого списка (`shared/lib/apiCachePolicy.ts`), изменения без сети блокируются в клиенте, кэш очищается при выходе и смене пользователя.

## Безопасность

- Ввод: Pydantic-типы (`SafeText`, `Phone`, `PlateNumber`, `VIN`, `Login`, `Money`) с лимитами длины, `extra="forbid"`; HTML вычищается nh3; SQL только через ORM/параметры.
- Пароли — argon2id; политика сложности; блокировка после неудачных попыток; rate limit входа.
- Access-токен JWT 15 мин в памяти, refresh-токен — httpOnly Secure SameSite cookie с ротацией, хранится хешем; сессии можно отзывать.
- Заголовки: CSP, HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy; в проде отключены `/api/docs` и OpenAPI.
- Фронтенд: без `dangerouslySetInnerHTML`, сборка без source maps; отчёты об ошибках обезличиваются.

## Локальная разработка

Нужны Python 3.12+, Node 20+, PostgreSQL 16.

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"        # Linux/macOS: .venv/bin/pip
.venv/Scripts/python -m alembic upgrade head
SEED_DIRECTOR_PASSWORD=demo-password-123 .venv/Scripts/python -m app.cli seed
.venv/Scripts/uvicorn app.main:app --reload --port 8000
.venv/Scripts/python -m app.worker           # отдельный терминал, нужен для уведомлений
```

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173, /api проксируется на :8000
```

## Тесты и проверки

```bash
cd backend
.venv/Scripts/python -m pytest -q --cov=app   # ~15 минут, нужна PostgreSQL (DATABASE_URL на тестовую БД)
.venv/Scripts/ruff check .
.venv/Scripts/mypy app
```

```bash
cd frontend
npm run lint && npx tsc --noEmit -p . && npx vitest run && npm run build && npm run check:bundle
```

Через Docker всё сразу: `make test`.

## Документы

- [01-development-plan.md](01-development-plan.md) — план по модулям
- [02-database-schema.md](02-database-schema.md) — схема БД
- [03-ui-screens.md](03-ui-screens.md) — экраны по ролям
- `api-contract-m1…m12.md` — контракты API по модулям
- [user-guide.md](user-guide.md) — руководство пользователя
- [deployment.md](deployment.md) — развёртывание и эксплуатация
