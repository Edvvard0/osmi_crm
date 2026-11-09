# Windows: Git Bash/WSL + make, либо те же команды напрямую (см. README и docs/deployment.md).
.PHONY: up down logs test lint migrate seed \
	prod-up prod-down prod-logs prod-backup prod-restore-check prod-cert prod-seed prod-demo prod-telegram-webhook

# ---------- dev ----------
up:
	docker compose up -d --build
down:
	docker compose down
logs:
	docker compose logs -f --tail=100
migrate:
	docker compose exec api alembic upgrade head
seed:
	docker compose exec api python -m app.cli seed
lint:
	docker compose run --rm --no-deps api sh -c "ruff check . && mypy app"
test:
	docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from api-tests api-tests; \
	r=$$?; docker compose -f docker-compose.test.yml down -v --remove-orphans; exit $$r

# ---------- прод (нужен .env.prod, см. docs/deployment.md) ----------
# Сборка и запуск; миграции применяет сервис migrate до старта api/worker.
# Ожидание GET /api/v1/health/ready до 120 с, при неготовности — ненулевой код выхода.
prod-up:
	sh deploy/scripts/compose.sh up -d --build
	sh deploy/scripts/wait-ready.sh 120
prod-down:
	sh deploy/scripts/compose.sh down
prod-logs:
	sh deploy/scripts/compose.sh logs -f --tail=100
# Немедленный дамп БД (том backups, метка last_success).
prod-backup:
	sh deploy/scripts/compose.sh exec -T backup /usr/local/bin/backup.sh now
# Проверка восстановления: последний дамп -> временная БД -> смоук-запросы -> удаление БД.
prod-restore-check:
	sh deploy/scripts/restore-check.sh
# Первичный выпуск сертификата Let's Encrypt (один раз на чистом сервере).
prod-cert:
	sh deploy/scripts/init-letsencrypt.sh
# Первичное заполнение: руководитель и точка.
prod-seed:
	sh deploy/scripts/seed.sh
# Демо-данные для показа (пароли DEMO_* — из окружения вызова).
prod-demo:
	sh deploy/scripts/demo.sh
prod-telegram-webhook:
	sh deploy/scripts/telegram-webhook.sh
