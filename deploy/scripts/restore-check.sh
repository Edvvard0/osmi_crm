#!/bin/sh
# Проверка восстановления: последний дамп разворачивается во временную БД, выполняются смоук-запросы
# (число пользователей, версия миграции равна head), временная БД удаляется. Рабочая БД не затрагивается.
set -eu
. "$(dirname "$0")/lib.sh"

TMPDB="crm_restore_check"
DB_PSQL="$COMPOSE exec -T db psql -U ${POSTGRES_USER:-crm} -v ON_ERROR_STOP=1 -At"

dump="$($COMPOSE exec -T backup sh -c 'ls -1t /backup/crm-*.dump 2>/dev/null | head -n 1' | tr -d '\r')"
[ -n "$dump" ] || { echo "Дампов нет. Сначала: make prod-backup" >&2; exit 1; }
echo "Дамп: $dump"

cleanup() { $DB_PSQL -d postgres -c "DROP DATABASE IF EXISTS $TMPDB" >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM

cleanup
$DB_PSQL -d postgres -c "CREATE DATABASE $TMPDB" >/dev/null
$COMPOSE exec -T backup cat "$dump" \
  | $COMPOSE exec -T db pg_restore -U "${POSTGRES_USER:-crm}" -d "$TMPDB" --no-owner --exit-on-error

users="$($DB_PSQL -d "$TMPDB" -c 'SELECT count(*) FROM users')"
current="$($DB_PSQL -d "$TMPDB" -c 'SELECT version_num FROM alembic_version')"
head="$($COMPOSE exec -T api alembic heads | awk '{print $1}' | tr -d '\r')"
echo "Пользователей: $users; версия миграции в дампе: $current; head в коде: $head"

[ "$users" -ge 1 ] || { echo "ОШИБКА: в дампе нет пользователей" >&2; exit 1; }
[ "$current" = "$head" ] || { echo "ОШИБКА: версия миграции дампа ($current) не равна head ($head)" >&2; exit 1; }
echo "Восстановление проверено: дамп пригоден."
