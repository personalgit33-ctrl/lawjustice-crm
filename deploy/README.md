# Деплой: фронтенд на Netlify, бэкенд на бесплатном VPS

```
Браузер ──► Netlify (Next.js)           https://<сайт>.netlify.app
   │
   └──────► VPS: Caddy (SSL) ─► daphne (Django API + WebSocket)
                                 ├─ Celery worker  (AI, вебхуки)
                                 ├─ Celery beat    (напоминания, эскалации)
                                 ├─ PostgreSQL
                                 └─ Redis
```

Домен для API не нужен заранее: скрипт выдаёт бесплатный адрес `api-<ip>.sslip.io` с настоящим SSL от Let's Encrypt. Когда заказчик даст домен, перезапустите скрипт с `--domain api.их-домен.kg`.

> Stage — только демо-данные. Реальные данные клиентов — на сервере, согласованном с заказчиком (ТЗ, разд. 12).

---

## Шаг 1. VPS (Oracle Cloud Always Free)

1. Регистрация: https://www.oracle.com/cloud/free/ — нужна банковская карта для проверки, деньги не списываются. **Home region** выбирайте ближе: Frankfurt или Amsterdam. Сменить потом нельзя.
2. **Compute → Instances → Create instance**:
   - Image: **Ubuntu 22.04** (или 24.04);
   - Shape: **Ampere → VM.Standard.A1.Flex, 2 OCPU, 12 GB** — это бесплатный предел;
   - SSH keys: «Generate a key pair» → скачайте приватный ключ.
   - Если пишет «Out of capacity» — попробуйте другой Availability Domain или повторите через час.
3. Откройте порты 80 и 443: **Networking → Virtual Cloud Networks → ваша сеть → Security Lists → Default → Add Ingress Rules**:
   Source CIDR `0.0.0.0/0`, TCP, Destination port `80`; ещё одно правило — `443`.
4. Запишите **Public IP** инстанса. Адрес API будет: `https://api-<IP-через-дефисы>.sslip.io`, например для `141.147.10.20` → `https://api-141-147-10-20.sslip.io`.

> Альтернатива — Google Cloud e2-micro (1 ГБ RAM, Always Free в регионах США). Скрипт сам добавит swap, но будет заметно медленнее.

## Шаг 2. Фронтенд на Netlify

1. https://app.netlify.com → **Add new project → Import an existing project → GitHub** → репозиторий `Genesis-Hub-Dev/LawJusticeCRM`. Если репозитория нет в списке — «Configure the Netlify app on GitHub» и дайте доступ к организации (может потребоваться одобрение владельца организации).
2. Настройки сборки подтянутся из `netlify.toml` в корне репозитория: Base directory `frontend`, команда `npm run build`, Publish `.next`, Node 22. Ничего менять не нужно.
3. **Site name** — например `lawjustice-crm` → адрес будет `https://lawjustice-crm.netlify.app`.
4. **Environment variables → Add a variable:**
   - `NEXT_PUBLIC_API_URL` = `https://api-<ваш-IP>.sslip.io`
   - (необязательно) `NEXT_PUBLIC_SIDEBAR` = `brand` — синее меню вместо белого.
5. **Deploy.** Адрес сайта понадобится на шаге 3.

> `NEXT_PUBLIC_API_URL` вшивается в сборку. Если поменяли — **Deploys → Trigger deploy → Clear cache and deploy site**.

## Шаг 3. Бэкенд на VPS

Подключитесь (Windows PowerShell):
```powershell
ssh -i C:\путь\к\ssh-key.key ubuntu@<IP>
```
На сервере:
```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/Genesis-Hub-Dev/LawJusticeCRM.git lawjustice-crm
cd lawjustice-crm
sudo bash deploy/setup-vps.sh --frontend https://lawjustice-crm.netlify.app --demo
```
Репозиторий приватный: на запрос пароля введите логин GitHub и **Personal Access Token** (GitHub → Settings → Developer settings → Fine-grained tokens → доступ «Contents: Read» к `LawJusticeCRM`).

Первый запуск — 5–10 минут (сборка образов). В конце скрипт печатает адреса API и вебхуков.

Проверка: откройте `https://api-<IP>.sslip.io/api/health/` → `{"ok": true}`. Затем откройте сайт на Netlify.

Вход: `elmira` / `demo12345` (руководитель — сразу попросит настроить 2FA), `bakyt` / `demo12345` (юрист).

## Обновление после новых коммитов

- **Фронтенд** — Netlify пересобирает сам при каждом `git push` в `main`. Pull request получает свой превью-адрес `deploy-preview-N--<сайт>.netlify.app` (CORS для них уже настроен).
- **Бэкенд:**
```bash
cd ~/lawjustice-crm && git pull
cd deploy && sudo docker compose -f docker-compose.vps.yml --env-file .env up -d --build
```

## Полезное

```bash
cd ~/lawjustice-crm/deploy
sudo docker compose -f docker-compose.vps.yml ps                      # статус
sudo docker compose -f docker-compose.vps.yml logs -f backend         # логи API
sudo docker compose -f docker-compose.vps.yml logs -f worker          # AI, вебхуки
sudo docker compose -f docker-compose.vps.yml exec backend python manage.py seed --reset   # сбросить демо
sudo docker compose -f docker-compose.vps.yml exec backend python manage.py createsuperuser
# резервная копия базы
sudo docker compose -f docker-compose.vps.yml exec -T db pg_dump -U lj lj | gzip > ~/backup-$(date +%F).sql.gz
```

Ключи интеграций (WhatsApp, Meta, телефония, Claude) — в `backend/.env` на сервере. После изменения: `... up -d` (без `--build`).

## Если что-то не так

| Симптом | Причина и решение |
|---|---|
| `health` не открывается, таймаут | Не открыты порты 80/443 в Security List (шаг 1.3) |
| Ошибка SSL / сертификат не выдан | Порт 80 закрыт или DNS ещё не видит адрес — `logs caddy`, подождать 1–2 минуты |
| На Netlify «Ошибка сети» при входе | Неверный `NEXT_PUBLIC_API_URL` (пересоберите с очисткой кэша) или `--frontend` не совпадает с адресом Netlify. Исправьте `CORS_ALLOWED_ORIGINS` и `CSRF_TRUSTED_ORIGINS` в `backend/.env` и выполните `up -d` |
| Netlify: «publish directory cannot be the same as the base directory» | В UI переопределён Publish directory — очистите поле, должен использоваться `netlify.toml` |
| Инстанс Oracle остановлен сам | Oracle может забрать простаивающие бесплатные машины. Помогает перевод аккаунта в Pay As You Go: бесплатные лимиты сохраняются |
