#!/bin/sh
# Первичное заполнение прод-БД: точка и руководитель (идемпотентно). Пароль — SEED_DIRECTOR_PASSWORD
# из .env.prod; после успешного входа руководителя удалите его из .env.prod.
set -eu
. "$(dirname "$0")/lib.sh"
: "${SEED_DIRECTOR_PASSWORD:?задайте SEED_DIRECTOR_PASSWORD в .env.prod}"
$COMPOSE exec -T -e SEED_DIRECTOR_PASSWORD api python -m app.cli seed
