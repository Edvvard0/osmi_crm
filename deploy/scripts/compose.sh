#!/bin/sh
# Обёртка: docker compose для прод-окружения с .env.prod (make prod-down / prod-logs / prod-backup).
set -eu
. "$(dirname "$0")/lib.sh"
exec $COMPOSE "$@"
