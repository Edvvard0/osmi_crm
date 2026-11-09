#!/bin/sh
# Ожидание готовности системы после `make prod-up`: GET /api/v1/health/ready == 200 (до 120 с).
# Запрос идёт внутри контейнера api (минуя TLS и DNS). 200 = ok или degraded (воркер/очередь
# Telegram не критичны для входа пользователей), 503 = down (БД/миграции).
set -u
. "$(dirname "$0")/lib.sh"
TIMEOUT="${1:-120}"
PY="import urllib.request as u,sys;r=u.urlopen('http://127.0.0.1:8000/api/v1/health/ready',timeout=3);print(r.read().decode());sys.exit(0)"
elapsed=0
while [ "$elapsed" -lt "$TIMEOUT" ]; do
  if out="$($COMPOSE exec -T api python -c "$PY" 2>/dev/null)"; then
    echo "Система готова: $out"
    exit 0
  fi
  sleep 3
  elapsed=$((elapsed + 3))
done
echo "Система не стала готова за ${TIMEOUT} с. Состояние и логи:" >&2
$COMPOSE ps >&2
$COMPOSE logs --tail=40 migrate api >&2
exit 1
