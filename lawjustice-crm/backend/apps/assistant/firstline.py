"""AI первой линии в чатах (п. 9.2, 9.11–9.13).

Сценарий: приветствие + раскрытие AI + политика ПД → квалификация → ответы по базе знаний →
предложение времени консультации → запись → передача сотруднику по правилам.
С ключом Claude ответы формулирует модель (по базе знаний и ограничениям), без ключа — сценарий на правилах.
"""
import re

from django.conf import settings
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import audit
from apps.comms.models import Conversation, Message
from apps.crm.services import get_settings
from apps.crm.utils import due_label

from . import llm
from .tools import CATEGORY_WORDS, default_lawyer, detect_category, free_slots, leads_board, t_book, t_create_card

URGENT = ["задерж", "обыск", "арест", "заседание сегодня", "суд сегодня", "сегодня суд", "в ровд", "в полици", "увезли", "кармалды", "тинтүү"]
HUMAN = ["человек", "оператор", "живой", "позовите", "соедините", "менеджер", "свяжите с юрист", "адам менен"]
LEGAL = ["шанс", "выиграю", "выиграем", "гарант", "перспектив", "оцените", "что мне грозит", "сколько дадут", "посадят"]
MONEY = ["предоплат", "реквизит", "куда перевест", "оплачу", "сколько стоит ведение", "стоимость дела", "цена дела"]
OTHER_CLIENTS = ["другой клиент", "кто ещё", "ваш клиент", "вы ведёте дело", "вы ведете дело"]
COMPLAINT = ["жалоб", "недовол", "безобраз", "ужасн", "обман", "верните деньги"]
APPROVED = "Этот вопрос требует участия юриста. Я передаю диалог специалисту — он свяжется с вами в ближайшее время."
APPROVED_KG = "Бул суроо юристтин катышуусун талап кылат. Диалогду адиске өткөрүп берем, ал жакында сиз менен байланышат."
QUESTIONS = {
    "Семейное право": "Брак зарегистрирован в Кыргызстане? Есть ли несовершеннолетние дети и совместно нажитое имущество?",
    "Уголовное право": "Подскажите, по какой статье и на какой стадии дело? Когда вызывают к следователю или в суд?",
    "Корпоративное право": "Есть ли подписанный договор и документы о перечислении денег? Какая сумма спора?",
    "Земельные споры": "Есть ли документы на участок (госакт, договор)? Когда начался спор?",
    "": "Опишите, пожалуйста, коротко ситуацию: что произошло и что вы хотите получить в итоге?",
}


def is_kg(text):
    t = (text or "").lower()
    return bool(re.search(r"[ңүө]", t)) or any(w in t for w in ("саламатсызбы", "салам", "рахмат", "керек", "жардам"))


def kb_lines():
    return [l.strip() for l in get_settings()["knowledge_base"].splitlines() if l.strip()]


def kb_answer(text):
    t = text.lower()
    lines = kb_lines()
    pick = lambda *ws: next((l for l in lines if any(w in l.lower() for w in ws)), None)
    if re.search(r"сколько стоит консульт|стоимость консульт|цена консульт|консультация платн|почём", t):
        return pick("консультация")
    if re.search(r"адрес|где вы|где находит|как добрат", t):
        return pick("адрес")
    if re.search(r"график|во сколько|работаете|часы работы|выходн", t):
        return pick("график")
    if re.search(r"какие услуги|чем занимает|направлени", t):
        return pick("направлени")
    return None


def _has_confidential(client):
    return client.cases.filter(is_confidential=True).exists()


def handle_inbound(conv_id, msg_id):
    from apps.comms.services import add_message, handoff, send_message

    conv = Conversation.objects.select_related("client", "lead").get(id=conv_id)
    msg = Message.objects.get(id=msg_id)
    s = get_settings()
    if conv.mode == "op" or conv.status == "closed" or not s["ai"]["chat_247"]:
        return
    if conv.channel in ("g", "meta", "ph") and not conv.client.phone and not conv.client.email:
        return
    client = conv.client
    text = msg.text or ""
    t = text.lower()
    kg = is_kg(text) or conv.ai_state.get("kg")
    st = dict(conv.ai_state or {})
    st["kg"] = kg

    if s["ai"]["skip_confidential"] and _has_confidential(client):
        handoff(conv, "клиент по конфиденциальному делу — ассистент отключён")
        return

    # Правила передачи (п. 9.2.7, 9.12)
    if any(w in t for w in URGENT):
        _reply(conv, "Понимаю, ситуация срочная. Передаю вас адвокату прямо сейчас — он свяжется с вами в течение нескольких минут." if not kg else "Түшүнөм, абал шашылыш. Сизди азыр адвокатка өткөрүп берем.", st)
        conv.summary = _summary(conv, prefix="СРОЧНО. ")
        conv.stage = "Срочно"
        conv.save(update_fields=["summary", "stage"])
        if not conv.responsible or conv.responsible.role != "lawyer":
            lw = default_lawyer("Уголовное право")
            if lw:
                conv.responsible = lw
                conv.save(update_fields=["responsible"])
        handoff(conv, "признаки срочности", urgent=True)
        _ensure_card(conv, "Уголовное право", st)
        return
    for words, reason in ((HUMAN, "клиент просит сотрудника"), (LEGAL, "запрос юридической оценки"), (MONEY, "вопрос оплаты"), (OTHER_CLIENTS, "вопрос о других клиентах"), (COMPLAINT, "недовольство клиента")):
        if any(w in t for w in words):
            _reply(conv, APPROVED_KG if kg else APPROVED, st, force_send=True)
            handoff(conv, reason)
            return

    # Согласие: продолжение переписки после ссылки на политику (п. 7.7)
    if st.get("privacy_sent") and client.consent_status == "none":
        client.consent_status, client.consent_at, client.consent_channel = "given", timezone.now(), {"wa": "WhatsApp", "g": "форма сайта", "meta": "форма Meta"}.get(conv.channel, conv.channel)
        client.consent_text = f"Продолжение переписки после уведомления: {settings.PRIVACY_URL}"
        client.save(update_fields=["consent_status", "consent_at", "consent_channel", "consent_text"])
    if conv.channel in ("g", "meta") and client.consent_status == "none":
        client.consent_status, client.consent_at, client.consent_channel = "given", timezone.now(), "форма " + ("сайта" if conv.channel == "g" else "Meta")
        client.save(update_fields=["consent_status", "consent_at", "consent_channel"])

    # Claude
    if llm.available():
        if _claude_turn(conv, msg, st):
            return

    # Правила
    cat = st.get("category") or detect_category(" ".join(m.text for m in conv.messages.filter(author="client")))
    if cat:
        st["category"] = cat
    step = st.get("step", 0)
    reply = None
    if step == 0:
        name = client.name.split()[0] if client.kind == "person" and not client.name.startswith("+") else ""
        greet = f"Здравствуйте{', ' + name if name else ''}! Вас приветствует Law & Justice, на связи виртуальный ассистент."
        if kg:
            greet = f"Саламатсызбы{', ' + name if name else ''}! Law & Justice компаниясынын виртуалдык жардамчысы байланышта."
        privacy = "" if client.consent_status == "given" else f" Продолжая переписку, вы соглашаетесь с политикой обработки персональных данных: {settings.PRIVACY_URL}."
        st["privacy_sent"] = bool(privacy) or st.get("privacy_sent", False)
        reply = f"{greet} Перед консультацией уточню пару моментов.{privacy} {QUESTIONS.get(cat, QUESTIONS[''])}"
        st["step"] = 1
        _ensure_card(conv, cat, st)
    else:
        kb = kb_answer(text)
        slots = st.get("slots") or []
        chosen = _chosen_slot(t, slots)
        if chosen:
            lw = User.objects.filter(id=st.get("lawyer")).first()
            _, res = t_book({"client_id": client.id, "lawyer": lw.id if lw else None, "start": chosen}, {})
            st["booked"] = chosen
            st["step"] = 3
            if conv.lead:
                conv.lead.status = "consultation"
                conv.lead.save(update_fields=["status"])
            conv.stage = "Консультация назначена"
            _move_lead_card(conv, "Консультация назначена")
            addr = next((l for l in kb_lines() if "адрес" in l.lower()), "")
            dt = timezone.datetime.fromisoformat(chosen)
            reply = f"Записали вас на консультацию {due_label(dt).lower()} к юристу {lw}. {addr} Если планы изменятся — напишите здесь."
        elif kb:
            reply = kb + (" Подобрать удобное время для консультации?" if step < 3 else "")
        elif msg.attachment_id:
            reply = "Спасибо, документ получен."
            if step < 2:
                reply += " " + _offer(conv, cat, st)
        elif step == 1:
            reply = _offer(conv, cat, st)
        elif step == 2:
            reply = "Подскажите, какое время вам удобнее: " + " или ".join(due_label(timezone.datetime.fromisoformat(x)).lower() for x in slots) + "?" if slots else _offer(conv, cat, st)
        else:
            reply = "Спасибо! Передам информацию юристу, он ответит вам в рабочее время."
    conv.summary = _summary(conv)
    conv.save(update_fields=["summary"])
    _sync_card_summary(conv)
    if reply:
        _reply(conv, reply, st)
    conv.ai_state = st
    conv.save(update_fields=["ai_state"])


def _offer(conv, cat, st):
    lw = default_lawyer(cat)
    slots = free_slots(lw) if lw else []
    st["lawyer"], st["slots"], st["step"] = (lw.id if lw else None), [x.isoformat() for x in slots], 2
    if not slots:
        return "Юрист свяжется с вами, чтобы согласовать время консультации."
    area = {"Семейное право": "по семейным делам", "Уголовное право": "по уголовным делам", "Корпоративное право": "по корпоративным спорам", "Земельные споры": "по земельным спорам"}.get(cat, "")
    return f"Консультации {area} ведёт {lw}. Удобно " + " или ".join(due_label(x).lower() for x in slots) + "?"


def _chosen_slot(t, slots):
    for iso in slots:
        dt = timezone.localtime(timezone.datetime.fromisoformat(iso))
        if re.search(rf"\b{dt.hour}(:00|\.00| ч|\b)", t):
            return iso
    if slots and re.search(r"\b(перв|давайте|подходит|удобно|да\b|ок\b)", t):
        return slots[0]
    if len(slots) > 1 and re.search(r"втор", t):
        return slots[1]
    return None


def _summary(conv, prefix=""):
    texts = [m.text for m in conv.messages.filter(author="client") if m.text][:4]
    cat = conv.ai_state.get("category") or detect_category(" ".join(texts))
    body = " ".join(texts)
    body = re.sub(r"^Заявка[^«]*«|»$", "", body)
    s = (prefix + (f"{cat}. " if cat else "") + body)[:400]
    files = conv.messages.filter(author="client", attachment__isnull=False).count()
    if files:
        s += f" Получено документов: {files}."
    return s


def _reply(conv, text, st, force_send=False):
    from apps.comms.services import send_message

    ai = User.ai_user()
    if conv.mode == "draft" and not force_send:
        # клиент написал ещё до отправки черновика — дополняем, а не затираем
        conv.draft = f"{conv.draft}\n\n{text}" if conv.draft else text
        conv.save(update_fields=["draft"])
        from apps.audit.services import broadcast

        broadcast("conversation.updated", {"id": conv.id, "draft": True})
        return
    if conv.channel == "wa" and conv.wa_window_seconds == 0:
        return
    send_message(conv, ai, text, as_ai=True)


def _ensure_card(conv, cat, st):
    if conv.cards.exists() or st.get("card"):
        return
    board = leads_board()
    if not board:
        return
    _, res = t_create_card({
        "client_id": conv.client_id, "category": cat, "conversation_id": conv.id, "source": conv.channel,
        "responsible": conv.responsible_id, "due": "завтра", "summary": _summary(conv),
    }, {})
    st["card"] = res["card_id"]
    from apps.boards.models import Card

    Card.objects.filter(id=res["card_id"]).update(lead=conv.lead)
    audit(User.ai_user(), "Создал карточку, заполнил поля и резюме", res["title"], type="ai", is_ai=True, card_id=res["card_id"], client_id=conv.client_id)


def _sync_card_summary(conv):
    from apps.boards.models import Card

    Card.objects.filter(conversation=conv).update(summary=conv.summary)


def _move_lead_card(conv, list_name):
    from apps.boards.services import MoveBlocked, move_card

    from .tools import find_list

    card = conv.cards.first()
    if not card:
        return
    target = find_list(list_name, card.list.board)
    if target and not target.is_final:
        try:
            move_card(card, target, User.ai_user())
        except MoveBlocked:
            pass


def _claude_turn(conv, msg, st):
    """Ответ модели по базе знаний. Возвращает True, если ход обработан."""
    from apps.comms.services import handoff

    kb = get_settings()["knowledge_base"]
    lw = default_lawyer(st.get("category", ""))
    slots = st.get("slots") or [x.isoformat() for x in (free_slots(lw) if lw else [])]
    st["slots"], st["lawyer"] = slots, (lw.id if lw else None)
    system = f"""Ты — виртуальный ассистент первой линии юридической компании Law & Justice в WhatsApp/формах.
База знаний компании:
{kb}

Правила (обязательны):
- В первом сообщении поздоровайся от имени компании, скажи, что отвечает виртуальный ассистент{', и дай ссылку на политику ПД: ' + settings.PRIVACY_URL if conv.client.consent_status != 'given' else ''}.
- Квалифицируй: направление права, суть, срочность, ключевые обстоятельства. Задавай по 1–2 вопроса.
- Отвечай только по базе знаний. Не давай юридических оценок и прогнозов, не обещай результат, не называй цены вне базы знаний,
  не сообщай сведения о других клиентах и делах, не принимай предоплату. В таких случаях handoff=true.
- Отвечай на языке клиента (русский или кыргызский). Коротко, вежливо, без эмодзи.
- Свободное время юриста {lw or ''}: {', '.join(due_label(timezone.datetime.fromisoformat(x)) for x in slots)}. Если клиент выбрал время — book_slot = индекс.
Верни только JSON: {{"reply": str, "category": "Семейное право|Уголовное право|Корпоративное право|Земельные споры|", "handoff": bool,
"handoff_reason": str, "urgent": bool, "summary": str, "book_slot": int|null}}"""
    history = []
    for m in conv.messages.exclude(author__in=["note", "sys"]).order_by("created_at")[:30]:
        role = "user" if m.author == "client" else "assistant"
        content = llm.masked(m.text or (f"[файл {m.attachment.name}]" if m.attachment_id else ""))
        if history and history[-1]["role"] == role:
            history[-1]["content"] += "\n" + content
        else:
            history.append({"role": role, "content": content or "…"})
    if not history or history[0]["role"] != "user":
        history.insert(0, {"role": "user", "content": "(начало диалога)"})
    if history[-1]["role"] != "user":
        return False
    out = llm.complete_json(system, history)
    if not out:
        return False
    if out.get("category"):
        st["category"] = out["category"]
    _ensure_card(conv, st.get("category", ""), st)
    if out.get("summary"):
        conv.summary = out["summary"][:600]
        conv.save(update_fields=["summary"])
        _sync_card_summary(conv)
    st["privacy_sent"] = True
    if out.get("book_slot") is not None and 0 <= int(out["book_slot"]) < len(slots):
        t_book({"client_id": conv.client_id, "lawyer": st["lawyer"], "start": slots[int(out["book_slot"])]}, {})
        conv.stage = "Консультация назначена"
        conv.save(update_fields=["stage"])
        _move_lead_card(conv, "Консультация назначена")
    if out.get("reply"):
        _reply(conv, out["reply"], st, force_send=bool(out.get("handoff")))
    conv.ai_state = st
    conv.save(update_fields=["ai_state"])
    if out.get("handoff") or out.get("urgent"):
        handoff(conv, out.get("handoff_reason") or "по правилам", urgent=bool(out.get("urgent")))
    return True
