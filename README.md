# CRM для автосервиса и детейлинга

PWA: FastAPI + PostgreSQL (async) + React. Документы: [docs/](docs/).

## Запуск (Docker)

```bash
docker compose up -d --build     # или: make up
```

Приложение: http://localhost:8080 · health: http://localhost:8080/api/v1/health · Swagger (только dev): http://localhost:8080/api/docs

| Команда | Что делает |
|---|---|
| `make up` / `make down` | запуск / остановка |
| `make logs` | логи |
| `make migrate` | миграции Alembic |
| `make test` | тесты, линтеры, mypy, покрытие в одноразовых контейнерах |
| `make lint` | ruff + mypy |

На Windows без `make` выполняйте команды из Makefile напрямую (`docker compose ...`).

## Локальный запуск без Docker (запасной вариант)

Нужны Python 3.12+, Node 20+, PostgreSQL 16.

```bash
cd backend && python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # Linux/macOS: .venv/bin/pip
.venv/Scripts/alembic upgrade head && .venv/Scripts/uvicorn app.main:app --reload
cd frontend && npm install && npm run dev
```

Тесты без БД: `cd backend && .venv/Scripts/python -m pytest -m "not integration"`; фронтенд: `npm test`.
`.venv/`, `node_modules/`, `dist/`, `.env` не коммитятся (см. `.gitignore`).

## Безопасность (модуль 0)
- Все входные схемы Pydantic с `extra="forbid"`; типы `Phone`, `PlateNumber`, `VIN`, `Login`, `SafeText`, `Money`.
- Единый формат ошибок; 500 без деталей; 422 без введённых значений; ошибки БД → доменные коды.
- В проде `/api/docs`, `/api/redoc`, `/openapi.json` отключены; нет заголовков `Server`/`X-Powered-By`.
- Nginx: CSP, HSTS, `X-Content-Type-Options`, `X-Frame-Options`, лимит запросов и размера тела.
- Фронтенд: словарь сообщений, Error Boundary, `window.onerror`/`unhandledrejection`, сборка без source maps и `console.*`.
