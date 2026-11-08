"""Сквозная проверка API под ролями: python tests/smoke_api.py [base_url]"""
import json
import sys

import requests

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000") + "/api/"
FAILS = []


SECRETS = {}


def login(u):
    """Вход с учётом 2FA: admin/manager проходят обязательную настройку, затем вводят код."""
    import time

    import pyotp

    r = requests.post(BASE + "auth/login/", json={"username": u, "password": "demo12345"})
    d = r.json()
    if r.status_code == 403 and d.get("setup_required"):
        st = requests.post(BASE + "auth/2fa/enroll/start/", json={"mfa_token": d["mfa_token"]}).json()
        SECRETS[u] = st["secret"]
        r = requests.post(BASE + "auth/2fa/enroll/finish/", json={"mfa_token": d["mfa_token"], "code": pyotp.TOTP(st["secret"]).now()})
    elif r.status_code == 401 and d.get("otp_required"):
        time.sleep(31)  # код из предыдущего шага уже использован
        r = requests.post(BASE + "auth/login/verify/", json={"mfa_token": d["mfa_token"], "code": pyotp.TOTP(SECRETS[u]).now()})
    r.raise_for_status()
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + r.json()["access"]
    return s


def check(name, resp, expect=(200, 201)):
    ok = resp.status_code in (expect if isinstance(expect, tuple) else (expect,))
    print(("OK  " if ok else "FAIL"), resp.status_code, name, "" if ok else resp.text[:300])
    if not ok:
        FAILS.append(name)
    try:
        return resp.json()
    except Exception:
        return None


m = login("elmira")
GETS = ["auth/me/", "users/", "dict/", "settings/", "clients/", "cases/", "conflicts/", "deadlines/?state=active", "deadlines/counts/",
        "calendar/", "contracts/", "finance/summary/", "boards/", "conversations/", "calls/", "assistant/", "dashboard/",
        "reports/funnel/?period=month", "notifications/", "audit/", "search/?q=Петров", "cards/search/?q=Петров"]
for g in GETS:
    check("GET " + g, m.get(BASE + g))

boards = m.get(BASE + "boards/").json()
leads = next(b for b in boards if "Лиды" in b["name"])
b = check("GET board", m.get(BASE + f"boards/{leads['id']}/"))
lists = {l["name"]: l for l in b["lists"]}
timur_card = next(c for c in lists["Новый лид"]["cards"] if "Тимур" in c["title"])
check("move conflict card → 409", m.post(BASE + f"cards/{timur_card['id']}/move/", json={"list": lists["Договор подписан"]["id"]}), 409)
ivan = next(c for c in lists["Новый лид"]["cards"] if "Иван" in c["title"])
check("move Ivan → Квалификация", m.post(BASE + f"cards/{ivan['id']}/move/", json={"list": lists["Квалификация"]["id"], "position": 0}))
d = check("card detail", m.get(BASE + f"cards/{ivan['id']}/"))
check("comment @azamat", m.post(BASE + "comments/", json={"card": ivan["id"], "text": "Проверка @azamat"}))
cl = check("checklist", m.post(BASE + "checklists/", json={"card": ivan["id"], "title": "Подготовка"}))
it = check("item", m.post(BASE + "checklist-items/", json={"checklist": cl["id"], "text": "Позвонить"}))
check("item done", m.patch(BASE + f"checklist-items/{it['id']}/", json={"done": True}))
check("upload", m.post(BASE + "attachments/", data={"card": ivan["id"]}, files={"file": ("test.pdf", b"%PDF-1.4 test", "application/pdf")}))
check("card patch", m.patch(BASE + f"cards/{ivan['id']}/", json={"priority": "high", "due_at": "2026-11-05T12:00:00+06:00"}))
nb = check("new board", m.post(BASE + "boards/", json={"name": "Семейные дела", "template": "family"}))
check("new list", m.post(BASE + "lists/", json={"board": nb["id"], "name": "Архив"}))
check("new card", m.post(BASE + "cards/", json={"list": nb["lists"][0]["id"], "title": "Тестовая карточка"}))

# Conflict
chk = check("conflict check", m.post(BASE + "conflicts/check/", json={"name": "Тимур Садыков"}))
print("   matches:", len(chk["matches"]), [x["role_label"] + ":" + x["case_number"] for x in chk["matches"]])
pend = check("pending", m.get(BASE + "conflicts/?status=pending"))
if pend:
    check("decide", m.post(BASE + f"conflicts/{pend[0]['id']}/decide/", json={"decision": "cleared", "comment": "Интересы не противоречат"}))
    check("move Timur after decision", m.post(BASE + f"cards/{timur_card['id']}/move/", json={"list": lists["Договор подписан"]["id"]}))

# Inbox
convs = m.get(BASE + "conversations/").json()
cv = next(c for c in convs if c["client_name"] == "Жаныл Асанова")
check("send msg", m.post(BASE + f"conversations/{cv['id']}/messages/", json={"text": "Добрый день!"}))
check("note", m.post(BASE + f"conversations/{cv['id']}/messages/", json={"text": "Внутренняя заметка", "is_note": True}))
check("create card from chat", m.post(BASE + f"conversations/{cv['id']}/create-card/", json={}))
check("create case from chat", m.post(BASE + f"conversations/{cv['id']}/create-case/", json={}))
cvi = next(c for c in convs if c["client_name"] == "Иван Петров")
det = check("conv detail", m.get(BASE + f"conversations/{cvi['id']}/"))
fm = next((x for x in det["messages"] if x["attachment"]), None)
if fm:
    check("file → card", m.post(BASE + f"messages/{fm['id']}/to-card/", json={"card": ivan["id"]}))
    f = requests.get(fm["attachment"]["url"] if fm["attachment"]["url"].startswith("http") else BASE[:-5] + fm["attachment"]["url"])
    print("   file download", f.status_code, f.headers.get("content-type"))
check("mode op", m.post(BASE + f"conversations/{cvi['id']}/mode/", json={"mode": "op"}))
check("mode ai", m.post(BASE + f"conversations/{cvi['id']}/mode/", json={"mode": "ai"}))

# Simulated inbound with AI
new = check("simulate WA", m.post(BASE + "simulate/inbound/", json={"channel": "wa", "name": "Айбек Жумалиев", "phone": "+996 701 11 22 33", "text": "Здравствуйте, хочу развестись, есть общий дом"}))
if new:
    check("simulate WA 2", m.post(BASE + "simulate/inbound/", json={"channel": "wa", "name": "Айбек Жумалиев", "phone": "+996 701 11 22 33", "text": "Брак в Бишкеке, детей нет"}))
    det = m.get(BASE + f"conversations/{new['id']}/").json()
    print("   mode:", det["mode"], "draft:", det["draft"][:80])
    for x in det["messages"]:
        print("   ", x["author"], ":", x["text"][:110])
urg = check("simulate urgent", m.post(BASE + "simulate/inbound/", json={"channel": "wa", "name": "Канат", "phone": "+996 702 00 00 01", "text": "Срочно! Отца задержали, он в РОВД"}))
det = m.get(BASE + f"conversations/{urg['id']}/").json()
print("   urgent:", det["urgent"], det["mode"], [x["text"][:60] for x in det["messages"]])
check("simulate google", m.post(BASE + "simulate/inbound/", json={"channel": "g", "name": "Света Ким", "phone": "+996 703 12 12 12", "text": "Нужна консультация по договору аренды", "campaign": "Юрист по разводу"}))
# Webhooks
check("webhook google", requests.post(BASE + "webhooks/google/?key=lj-google-key", json={"lead_id": "L1", "campaign_id": 77, "user_column_data": [{"column_id": "FULL_NAME", "string_value": "Гульнара Ж."}, {"column_id": "PHONE_NUMBER", "string_value": "+996705999888"}]}))
check("webhook meta", requests.post(BASE + "webhooks/meta/", json={"entry": [{"changes": [{"value": {"leadgen_id": "M1", "campaign_name": "Семейные споры", "field_data": [{"name": "full_name", "values": ["Данияр"]}, {"name": "phone_number", "values": ["+996555777666"]}]}}]}]}))
check("webhook wa", requests.post(BASE + "webhooks/whatsapp/", json={"entry": [{"changes": [{"value": {"contacts": [{"wa_id": "996555121212", "profile": {"name": "Асель"}}], "messages": [{"from": "996555121212", "id": "wamid.1", "type": "text", "text": {"body": "Сколько стоит консультация?"}}]}}]}]}))
check("webhook tel ringing", requests.post(BASE + "webhooks/telephony/?key=lj-tel-key", json={"event": "ringing", "call_id": "T1", "from": "+996 555 12 34 56"}))
check("webhook tel ended", requests.post(BASE + "webhooks/telephony/?key=lj-tel-key", json={"event": "ended", "call_id": "T1", "duration": 65, "transcript": [{"speaker": "Клиент", "text": "Хочу перенести консультацию на пятницу"}]}))
check("webhook tel missed", requests.post(BASE + "webhooks/telephony/?key=lj-tel-key", json={"event": "missed", "call_id": "T2", "from": "+996 709 00 11 22"}))

# Assistant
for cmd in ["Создай карточку на Айбека, уголовное дело, ответственный Бакыт, связаться сегодня",
            "Перенеси карточку Ивана Петрова в «Консультация назначена»",
            "Перенеси карточку Ак-Тоо в «Договор подписан»",
            "Покажи просроченные задачи Бакыта",
            "Удали клиента Иван Петров"]:
    r = check("assistant: " + cmd[:40], m.post(BASE + "assistant/command/", json={"text": cmd}))
    print("   ", r["state"], "|", r["result"])
    for s in r["steps"]:
        print("      -", s["label"], "—", s["detail"], f"[{s['status']}]")
    if r["state"] == "awaiting_confirm":
        r2 = check("confirm", m.post(BASE + f"assistant/{r['id']}/confirm/"))
        print("    →", r2["result"])

# Deadlines
dl = m.get(BASE + "deadlines/?state=late").json()
check("deadline done", m.post(BASE + f"deadlines/{dl[0]['id']}/done/"))
tpl = m.get(BASE + "dict/").json()["deadline_template"][0]
check("calc", m.post(BASE + "deadlines/calc/", json={"base_date": "2026-10-01", "template_id": tpl["id"]}))
cases = m.get(BASE + "cases/").json()
check("new deadline", m.post(BASE + "deadlines/", json={"title": "Кассационная жалоба", "type": "procedural", "case": cases[0]["id"], "due_at": "2026-11-20T18:00:00+06:00", "responsible": 4, "backup": 7, "basis": "Шаблон"}))
# Cases & clients
newc = check("new client", m.post(BASE + "clients/", json={"name": "Мамытов Эмиль", "phone": "+996 777 000 111", "kind": "person"}))
check("new case w/ opponent=client → conflict", m.post(BASE + "cases/", json={"title": "Спор", "client": newc["id"], "category": "Гражданское право", "parties": [{"role": "opponent", "name": "Петров Иван"}]}))
c = m.get(BASE + "cases/").json()[0]
print("   last case conflict:", c["number"], c["conflict_status"])
check("case → in_work blocked", m.patch(BASE + f"cases/{c['id']}/", json={"status": "in_work"}), 409)
check("client timeline", m.get(BASE + f"clients/{newc['id']}/timeline/"))
check("client related", m.get(BASE + f"clients/{newc['id']}/related/"))
check("client export (manager) → 403", m.get(BASE + "clients/export/"), 403)
# Finance
ct = m.get(BASE + "contracts/").json()
pay = next(p for x in ct for p in x["payments"] if p["overdue_days"])
check("pay", m.post(BASE + f"payments/{pay['id']}/pay/", json={}))
check("finance xlsx", m.get(BASE + "finance/export/"))
check("funnel xlsx", m.get(BASE + "reports/funnel/export/"))
check("ad spend", m.post(BASE + "reports/ad-spend/", json={"month": "2026-10", "channel": "g", "campaign": "Форма на сайте", "amount": 5000}))
# Calls
calls = m.get(BASE + "calls/").json()
check("recording", m.post(BASE + f"calls/{calls[-1]['id']}/recording/", json={"action": "play"}))
check("originate", m.post(BASE + "calls/originate/", json={"phone": "+996 555 12 34 56"}))
check("sim call", m.post(BASE + "simulate/call/", json={"phone": "+996 555 12 34 56"}))

# Roles
a = login("admin")
check("admin export clients", a.get(BASE + "clients/export/"))
check("admin export all", a.get(BASE + "export/all/"))
check("admin settings patch", a.patch(BASE + "settings/", json={"ai": {"monthly_limit_usd": 200}}))
case087 = next(x for x in a.get(BASE + "cases/").json() if x["number"].endswith("087"))
print("   admin sees 087 restricted:", case087["restricted"], case087["title"])
law = login("nurlan")
lc = law.get(BASE + "cases/").json()
print("   nurlan cases:", [x["number"] for x in lc])
check("lawyer cannot see 087", law.get(BASE + f"cases/{case087['id']}/"), 404)
check("lawyer settings patch → 403", law.patch(BASE + "settings/", json={"ai": {"chat_247": False}}), 403)
check("lawyer audit → 403", law.get(BASE + "audit/"), 403)
op = login("meerim")
check("operator cases → 403", op.get(BASE + "cases/"), 403)
check("operator inbox", op.get(BASE + "conversations/"))
bak = login("bakyt")
check("bakyt sees 087", bak.get(BASE + f"cases/{case087['id']}/"))
check("bakyt calls", bak.get(BASE + "calls/"))
# Users
check("block user", a.post(BASE + "users/6/block/", json={"transfer_to": 4}))
check("substitute", m.post(BASE + "users/5/substitute/", json={"substitute_id": 4, "until": "2026-12-01T00:00:00+06:00"}))
check("audit", m.get(BASE + "audit/?type=ai"))
print("\nFAILS:", FAILS)
