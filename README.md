# Law & Justice CRM

Веб-CRM юридической компании по ТЗ ред. 1.1: дела, клиенты, доски вместо Trello, Центр обращений (WhatsApp, Google, Meta, телефония), сроки, конфликт интересов, договоры и оплаты, AI первой линии и AI-ассистент администратора.

**Стек (ТЗ, раздел 2):** Next.js 16 + React 19 + TypeScript · Django 5 + DRF · PostgreSQL · Celery + Redis · WebSocket (Channels) · S3-совместимое хранилище · Claude API через AI Gateway.

## Быстрый старт на Windows

1. Установите Python 3.12 (python.org, галочка «Add python.exe to PATH») и Node.js LTS (nodejs.org).
2. Двойной клик `start-backend.bat` — дождитесь строки «Бэкенд: http://localhost:8000».
3. Двойной клик `start-frontend.bat` — откройте http://localhost:3000.

## Быстрый старт (локально, без Docker)

```bash
# бэкенд — SQLite, фоновые задачи выполняются сразу, WebSocket в памяти
cd backend
pip install -r requirements.txt
python manage.py migrate
python manage.py seed            # справочники, 7 сотрудников, демо-данные как в прототипе
daphne -p 8000 config.asgi:application

# фронтенд
cd frontend
npm install
npm run dev                      # http://localhost:3000
```

Учётные записи (пароль `demo12345`): `admin` — администратор, `elmira` — руководитель, `bakyt` / `azamat` / `aigul` / `nurlan` — юристы, `meerim` — оператор.

## Деплой: Netlify + бесплатный VPS

Пошаговая инструкция — [deploy/README.md](deploy/README.md). Коротко: фронтенд импортируется в Netlify (настройки в `netlify.toml`), бэкенд ставится на VPS одной командой `sudo bash deploy/setup-vps.sh --frontend https://<сайт>.netlify.app --demo`.

## Stage / prod на одном сервере

```bash
cp backend/.env.example backend/.env    # заполнить секреты и ключи интеграций
PUBLIC_API_URL=https://api.crm.lawjustice.kg docker compose up -d --build
docker compose exec backend python manage.py createsuperuser
```

Сервисы: `db` (PostgreSQL), `redis`, `backend` (daphne: HTTP + WebSocket), `worker` и `beat` (Celery: вебхуки, AI, напоминания, эскалации, срок хранения записей), `frontend`. SSL, домен, бэкапы (`pg_dump` + бакет, 14 дней) и мониторинг настраиваются на уровне хостинга.

Боковое меню: синее по прототипу (по умолчанию). Белое по ТЗ п. 3.6: `SIDEBAR=light`.

## Подключение каналов

| Канал | URL вебхука | Что нужно в `.env` |
|---|---|---|
| WhatsApp Cloud API | `/api/webhooks/whatsapp/` (verify token `WHATSAPP_VERIFY_TOKEN`) | `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_APP_SECRET` |
| Google Ads Lead Form / форма сайта | `/api/webhooks/google/?key=GOOGLE_WEBHOOK_KEY` | `GOOGLE_WEBHOOK_KEY` |
| Meta Lead Ads | `/api/webhooks/meta/` | `META_PAGE_TOKEN`, `META_VERIFY_TOKEN` |
| IP-телефония | `/api/webhooks/telephony/?key=…` — события `ringing / answered / ended / missed` | `TELEPHONY_*`; адаптер — `apps/comms/channels.py::Telephony` |
| Claude | — | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` |

Пока ключей нет, всё работает в режиме песочницы: сообщения сохраняются, AI работает по сценарию на правилах, а для демо и приёмки есть `POST /api/simulate/inbound/` и `/api/simulate/call/` (кнопки в интерфейсе у руководителя).

## Структура

```
backend/
  apps/accounts   роли, JWT, 2FA (TOTP), блокировка входа, замещение, увольнение, WebSocket
  apps/crm        клиенты, дела, стороны, конфликт интересов, сроки, календарь, договоры, файлы, отчёты, справочники, настройки
  apps/boards     доски, колонки, карточки, чек-листы, комментарии с @, история, автоматизации, импорт Trello
  apps/comms      диалоги, сообщения, лиды, звонки, адаптеры каналов, вебхуки, фоновые задачи
  apps/assistant  AI Gateway (llm.py), инструменты с правами (tools.py), AI первой линии, AI-ассистент
  apps/audit      журнал действий и просмотров, уведомления
  tests/smoke_api.py   сквозная проверка API под всеми ролями
frontend/src
  app/(app)/…     19 экранов: панель, обращения, доски, звонки, сроки, ассистент, клиенты, дела, конфликты, календарь, финансы, отчёты, журнал, настройки
  lib/types.ts    контракт фронта и бэка (вместе с API.md)
```

## Проверка

```bash
cd backend && python manage.py seed --reset && python tests/smoke_api.py
```
