# Общие настройки прод-скриптов: переменные из .env.prod и команда compose. Подключается через `.`.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
[ -f .env.prod ] || { echo "Нет файла .env.prod (скопируйте .env.prod.example и заполните)" >&2; exit 1; }
set -a
# shellcheck disable=SC1091
. ./.env.prod
set +a
COMPOSE="docker compose --env-file .env.prod -f docker-compose.prod.yml"
# Без домена (HTTP_PORT задан): http://IP:порт без TLS, 80/443 не занимаются (docker-compose.ip.yml).
if [ -n "${HTTP_PORT:-}" ]; then
  COMPOSE="$COMPOSE -f docker-compose.ip.yml"
fi
