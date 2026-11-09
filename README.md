# CRM для автосервиса и детейлинга

PWA для сети автосервисов: записи, заказ-наряды, склад, касса, отчёты, зарплата, уведомления в Telegram.
Роли: механик, менеджер, руководитель. Стек: FastAPI + PostgreSQL (async) + React.

## Документация

- [Руководство пользователя](docs/user-guide.md)
- [Архитектура и локальная разработка](docs/architecture.md)
- [Развёртывание и эксплуатация](docs/deployment.md)
- План, схема БД, экраны, контракты API — в [docs/](docs/)

## Запуск для разработки (Docker)

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
Запуск без Docker — см. [docs/architecture.md](docs/architecture.md#локальная-разработка).

## Прод

```bash
cp .env.prod.example .env.prod   # заполнить секреты
make prod-up                     # БД, миграции, API, воркер, фронтенд, nginx, бэкапы
make prod-seed                   # первый руководитель
```

Подробно (TLS, бэкапы, обновление, мониторинг) — [docs/deployment.md](docs/deployment.md).

## Безопасность

- Все входные схемы Pydantic с `extra="forbid"` и типами `SafeText`, `Phone`, `PlateNumber`, `VIN`, `Login`, `Money`; HTML вычищается; SQL только через ORM и параметры.
- Единый формат ошибок; 500 без деталей; 422 без введённых значений.
- argon2id, блокировка после неудачных входов, rate limit; access-токен в памяти, refresh — httpOnly cookie с ротацией.
- CSP, HSTS и прочие заголовки; в проде `/api/docs` и OpenAPI отключены.
- Фронтенд: словарь сообщений об ошибках, Error Boundary, сборка без source maps.

`.venv/`, `node_modules/`, `dist/`, `.env*` не коммитятся (см. `.gitignore`).
