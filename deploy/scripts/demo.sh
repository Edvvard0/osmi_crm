#!/bin/sh
# Демо-данные для показа системы (идемпотентно: при наличии manager1 ничего не делает).
# Пароли демо-сотрудников передаются только через окружение вызова, в .env.prod их не храните:
#   DEMO_MANAGER_PASSWORD=... DEMO_MECHANIC_PASSWORD=... make prod-demo
# Пароль руководителя — SEED_DIRECTOR_PASSWORD из окружения вызова (приоритет) или из .env.prod.
set -eu
# lib.sh подключает .env.prod и перезаписал бы одноимённые переменные — сохраняем их заранее.
_demo_manager="${DEMO_MANAGER_PASSWORD:-}"
_demo_mechanic="${DEMO_MECHANIC_PASSWORD:-}"
_director="${SEED_DIRECTOR_PASSWORD:-}"
. "$(dirname "$0")/lib.sh"
DEMO_MANAGER_PASSWORD="$_demo_manager"
DEMO_MECHANIC_PASSWORD="$_demo_mechanic"
if [ -n "$_director" ]; then SEED_DIRECTOR_PASSWORD="$_director"; fi
: "${SEED_DIRECTOR_PASSWORD:?задайте SEED_DIRECTOR_PASSWORD (текущий пароль руководителя)}"
: "${DEMO_MANAGER_PASSWORD:?задайте DEMO_MANAGER_PASSWORD в окружении вызова}"
: "${DEMO_MECHANIC_PASSWORD:?задайте DEMO_MECHANIC_PASSWORD в окружении вызова}"
export SEED_DIRECTOR_PASSWORD DEMO_MANAGER_PASSWORD DEMO_MECHANIC_PASSWORD
$COMPOSE exec -T -e SEED_DIRECTOR_PASSWORD -e DEMO_MANAGER_PASSWORD -e DEMO_MECHANIC_PASSWORD \
  api python -m app.demo_seed
