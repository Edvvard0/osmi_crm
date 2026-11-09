#!/bin/sh
# Резервное копирование PostgreSQL.
#   backup.sh daemon  — ежедневно в BACKUP_HOUR:00 по APP_TIMEZONE (по умолчанию 03:00);
#   backup.sh now     — немедленный дамп (make prod-backup).
# Дамп: pg_dump -Fc -> /backup/crm-YYYYmmdd-HHMMSS.dump; после проверки pg_restore -l обновляется
# метка /backup/last_success (её время читает GET /system/status); дампы старше
# BACKUP_RETENTION_DAYS суток удаляются. Пароль берётся из PGPASSWORD (роль crm_migrator —
# владелец всех объектов, читает любые таблицы).
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backup}"
BACKUP_HOUR="${BACKUP_HOUR:-03}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
export TZ="${APP_TIMEZONE:-Europe/Moscow}"
export PGHOST="${PGHOST:-db}" PGUSER="${PGUSER:-crm_migrator}" PGDATABASE="${PGDATABASE:-crm}"

log() { printf '%s backup: %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*"; }

do_backup() {
  ts="$(date '+%Y%m%d-%H%M%S')"
  tmp="$BACKUP_DIR/.crm-$ts.dump.part"
  out="$BACKUP_DIR/crm-$ts.dump"
  if pg_dump -Fc -f "$tmp" && pg_restore -l "$tmp" >/dev/null; then
    mv "$tmp" "$out"
    touch "$BACKUP_DIR/last_success"
    log "ok $(basename "$out") $(du -h "$out" | cut -f1)"
    find "$BACKUP_DIR" -maxdepth 1 -name 'crm-*.dump' -mmin +"$((RETENTION_DAYS * 1440))" -print -delete \
      | sed 's/^/backup: removed /'
    return 0
  fi
  rm -f "$tmp"
  log "ОШИБКА: дамп не создан"
  return 1
}

seconds_until_next_run() {
  now="$(date +%s)"
  target="$(date -d "$(date +%Y-%m-%d) $BACKUP_HOUR:00:00" +%s)"
  [ "$target" -gt "$now" ] || target="$((target + 86400))"
  echo "$((target - now))"
}

case "${1:-daemon}" in
  now) do_backup ;;
  daemon)
    trap 'exit 0' TERM INT
    log "запущен: ежедневно в $BACKUP_HOUR:00 ($TZ), хранение $RETENTION_DAYS дн."
    while :; do
      wait_s="$(seconds_until_next_run)"
      sleep "$wait_s" &
      wait $!
      do_backup || true   # сбой не останавливает цикл; метка last_success не обновляется
    done
    ;;
  *) echo "usage: backup.sh [daemon|now]" >&2; exit 2 ;;
esac
