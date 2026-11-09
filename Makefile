# Windows: Git Bash/WSL + make, либо те же команды напрямую (см. README).
.PHONY: up down logs test lint migrate seed
up:
	docker compose up -d --build
down:
	docker compose down
logs:
	docker compose logs -f --tail=100
migrate:
	docker compose exec api alembic upgrade head
seed:
	docker compose exec api python -m app.seed
lint:
	docker compose run --rm --no-deps api sh -c "ruff check . && mypy app"
test:
	docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from api-tests api-tests; \
	r=$$?; docker compose -f docker-compose.test.yml down -v --remove-orphans; exit $$r
