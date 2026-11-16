#!/usr/bin/env bash
# Law & Justice CRM — установка бэкенда на чистый Ubuntu VPS (Oracle Cloud Free, Google e2-micro, любой другой).
#
#   sudo bash deploy/setup-vps.sh --frontend https://lawjustice-crm.netlify.app [--domain api.example.com] [--demo]
#
# --frontend  адрес фронтенда на Netlify (или Vercel) — для CORS
# --domain    домен API; если не указан — бесплатный <ip>.sslip.io с настоящим SSL
# --demo      загрузить демо-данные (для stage); без флага — только справочники и сотрудники
set -euo pipefail

FRONTEND=""; DOMAIN=""; DEMO=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --frontend) FRONTEND="${2%/}"; shift 2 ;;
    --domain) DOMAIN="$2"; shift 2 ;;
    --demo) DEMO=1; shift ;;
    *) echo "Неизвестный параметр: $1"; exit 1 ;;
  esac
done
[[ -z "$FRONTEND" ]] && { echo "Укажите --frontend https://<сайт>.netlify.app"; exit 1; }
[[ $EUID -ne 0 ]] && { echo "Запустите через sudo"; exit 1; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> 1/6 Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker >/dev/null 2>&1 || true

echo "==> 2/6 Память"
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [[ $MEM_MB -lt 3000 && ! -f /swapfile ]]; then
  echo "   RAM ${MEM_MB} МБ — добавляю swap 2 ГБ"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> 3/6 Порты 80 и 443"
# В образах Ubuntu на Oracle Cloud iptables по умолчанию отклоняет входящие, кроме SSH
if command -v iptables >/dev/null; then
  for p in 80 443; do
    iptables -C INPUT -p tcp --dport $p -j ACCEPT 2>/dev/null || iptables -I INPUT 6 -p tcp -m state --state NEW --dport $p -j ACCEPT 2>/dev/null || iptables -I INPUT -p tcp --dport $p -j ACCEPT
  done
  if command -v netfilter-persistent >/dev/null; then netfilter-persistent save >/dev/null 2>&1 || true; fi
fi
command -v ufw >/dev/null && ufw status | grep -q active && { ufw allow 80/tcp; ufw allow 443/tcp; } || true

echo "==> 4/6 Домен"
IP=$(curl -fsS https://api.ipify.org || curl -fsS https://ifconfig.me)
if [[ -z "$DOMAIN" ]]; then
  DOMAIN="api-${IP//./-}.sslip.io"
fi
echo "   API: https://$DOMAIN   (IP $IP)"

echo "==> 5/6 Настройки (.env)"
rand() { python3 -c "import secrets;print(secrets.token_urlsafe($1))" 2>/dev/null || openssl rand -base64 "$1" | tr -dc 'A-Za-z0-9' | head -c "$1"; }
if [[ ! -f deploy/.env ]]; then
  cat > deploy/.env <<EOF
API_DOMAIN=$DOMAIN
POSTGRES_PASSWORD=$(rand 24)
EOF
fi
if [[ ! -f backend/.env ]]; then
  SITE=$(echo "$FRONTEND" | sed -E 's#https?://([^.]+)\..*#\1#')
  # превью-деплои: Netlify — https://deploy-preview-12--<site>.netlify.app, Vercel — https://<site>-<хэш>.vercel.app
  PREVIEWS="^https://[a-z0-9-]+--${SITE}\.netlify\.app\$,^https://${SITE}-[a-z0-9-]+\.vercel\.app\$"
  cat > backend/.env <<EOF
DJANGO_SECRET_KEY=$(rand 50)
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=$DOMAIN,localhost,backend
CSRF_TRUSTED_ORIGINS=https://$DOMAIN,$FRONTEND
CORS_ALLOWED_ORIGINS=$FRONTEND
CORS_ALLOWED_ORIGIN_REGEXES=$PREVIEWS
PUBLIC_BASE_URL=https://$DOMAIN
TIME_ZONE=Asia/Bishkek
MAX_UPLOAD_MB=50
GOOGLE_WEBHOOK_KEY=$(rand 24)
TELEPHONY_WEBHOOK_KEY=$(rand 24)
WHATSAPP_VERIFY_TOKEN=$(rand 16)
META_VERIFY_TOKEN=$(rand 16)
PRIVACY_URL=lawjustice.kg/privacy
# Заполните, когда будут доступы:
WHATSAPP_TOKEN=
WHATSAPP_PHONE_ID=
WHATSAPP_APP_SECRET=
META_PAGE_TOKEN=
TELEPHONY_API_URL=
TELEPHONY_API_TOKEN=
ANTHROPIC_API_KEY=
EOF
  chmod 600 backend/.env deploy/.env
else
  echo "   backend/.env уже есть — не трогаю"
fi

echo "==> 6/6 Запуск"
cd deploy
docker compose -f docker-compose.vps.yml --env-file .env up -d --build
echo "   жду бэкенд…"
for i in $(seq 1 60); do
  if docker compose -f docker-compose.vps.yml exec -T backend python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/health/')" >/dev/null 2>&1; then break; fi
  sleep 3
done
if [[ $DEMO -eq 1 ]]; then
  docker compose -f docker-compose.vps.yml exec -T backend python manage.py seed
fi

cat <<EOF

Готово.
  API:        https://$DOMAIN/api/health/
  Админка:    https://$DOMAIN/admin/
  Фронтенд:   $FRONTEND  (в Netlify: NEXT_PUBLIC_API_URL=https://$DOMAIN)

  Вебхуки:
    WhatsApp:   https://$DOMAIN/api/webhooks/whatsapp/   (verify token — WHATSAPP_VERIFY_TOKEN в backend/.env)
    Google:     https://$DOMAIN/api/webhooks/google/?key=<GOOGLE_WEBHOOK_KEY>
    Meta:       https://$DOMAIN/api/webhooks/meta/
    Телефония:  https://$DOMAIN/api/webhooks/telephony/?key=<TELEPHONY_WEBHOOK_KEY>

  Логи:       cd $ROOT/deploy && docker compose -f docker-compose.vps.yml logs -f backend
EOF
