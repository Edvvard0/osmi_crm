#!/bin/sh
# Первичный выпуск сертификата Let's Encrypt (один раз, на чистом сервере).
# Порядок: временный самоподписанный сертификат -> старт edge -> выпуск настоящего через webroot
# -> удаление временного -> nginx -s reload. Дальше обновляет сервис certbot (раз в 12 часов).
# Требуется: DNS A-запись DOMAIN указывает на сервер, порты 80 и 443 открыты,
# в .env.prod заданы DOMAIN, LETSENCRYPT_EMAIL, LETSENCRYPT_AGREE_TOS=yes.
# LETSENCRYPT_STAGING=1 — тестовый выпуск (без лимитов, сертификат не доверенный).
set -eu
. "$(dirname "$0")/lib.sh"

: "${DOMAIN:?DOMAIN не задан в .env.prod}"
: "${LETSENCRYPT_EMAIL:?LETSENCRYPT_EMAIL не задан в .env.prod}"
[ "${LETSENCRYPT_AGREE_TOS:-}" = "yes" ] || {
  echo "Выпуск сертификата означает согласие с условиями Let's Encrypt (https://letsencrypt.org/repository/)." >&2
  echo "Если вы согласны, задайте LETSENCRYPT_AGREE_TOS=yes в .env.prod и повторите." >&2
  exit 1
}

echo "1/4 Временный сертификат для $DOMAIN"
$COMPOSE run --rm --no-deps -T -e DOMAIN --entrypoint python certbot - <<'PY'
import datetime
import os

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

domain = os.environ["DOMAIN"]
path = f"/etc/letsencrypt/live/{domain}"
os.makedirs(path, exist_ok=True)
key = ec.generate_private_key(ec.SECP256R1())
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, domain)])
now = datetime.datetime.now(datetime.timezone.utc)
cert = (
    x509.CertificateBuilder()
    .subject_name(name).issuer_name(name).public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
    .sign(key, hashes.SHA256())
)
with open(f"{path}/fullchain.pem", "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))
with open(f"{path}/privkey.pem", "wb") as f:
    f.write(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
PY

echo "2/4 Запуск edge"
$COMPOSE up -d --no-deps edge
sleep 3

echo "3/4 Выпуск сертификата Let's Encrypt"
$COMPOSE run --rm --no-deps -T --entrypoint sh certbot -c \
  "rm -rf /etc/letsencrypt/live/$DOMAIN /etc/letsencrypt/archive/$DOMAIN /etc/letsencrypt/renewal/$DOMAIN.conf"
STAGING=""
[ "${LETSENCRYPT_STAGING:-0}" = "1" ] && STAGING="--staging"
# shellcheck disable=SC2086
$COMPOSE run --rm --no-deps -T --entrypoint certbot certbot certonly --webroot -w /var/www/certbot \
  -d "$DOMAIN" --email "$LETSENCRYPT_EMAIL" --agree-tos --no-eff-email --non-interactive $STAGING

echo "4/4 Перезагрузка nginx"
$COMPOSE exec -T edge nginx -s reload
echo "Готово. Дальше: make prod-up"
