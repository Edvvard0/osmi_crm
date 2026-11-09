#!/bin/sh
# Первичная инициализация БД (выполняется postgres-образом один раз, при пустом томе pgdata).
# Роли: crm_migrator — владелец схемы (DDL, alembic); crm_app — DML для api и worker.
# Пароли берутся из окружения контейнера db (.env.prod), в SQL подставляются как литералы psql.
set -eu

: "${DB_MIGRATOR_PASSWORD:?DB_MIGRATOR_PASSWORD не задан}"
: "${DB_APP_PASSWORD:?DB_APP_PASSWORD не задан}"

psql -v ON_ERROR_STOP=1 -v mpw="$DB_MIGRATOR_PASSWORD" -v apw="$DB_APP_PASSWORD" \
  -v dbname="$POSTGRES_DB" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE crm_migrator LOGIN PASSWORD :'mpw' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE crm_app      LOGIN PASSWORD :'apw' NOSUPERUSER NOCREATEDB NOCREATEROLE;

-- Расширения (создаёт суперпользователь, миграция 0001 затем выполняет IF NOT EXISTS).
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS citext;

SELECT format('ALTER DATABASE %I OWNER TO crm_migrator', :'dbname') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'dbname') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO crm_app', :'dbname') \gexec

ALTER SCHEMA public OWNER TO crm_migrator;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO crm_app;

-- Новые таблицы, созданные миграциями, доступны crm_app на чтение/запись; журналы только на
-- добавление сужает миграция 0012 (REVOKE UPDATE/DELETE/TRUNCATE).
ALTER DEFAULT PRIVILEGES FOR ROLE crm_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO crm_app;
ALTER DEFAULT PRIVILEGES FOR ROLE crm_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO crm_app;
SQL
