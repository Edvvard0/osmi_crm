#!/bin/sh
# Регистрация вебхука Telegram (TELEGRAM_MODE=webhook): https://DOMAIN/api/v1/telegram/webhook.
set -eu
. "$(dirname "$0")/lib.sh"
$COMPOSE exec -T api python -m app.cli telegram-set-webhook
