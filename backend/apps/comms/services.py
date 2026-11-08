"""Центр обращений: приём сообщений и заявок, отправка, звонки."""
import logging

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import audit, broadcast, managers, notify
from apps.crm.models import Client
from apps.crm.services import find_or_create_client, get_settings, is_work_time, run_conflict_check

from .channels import channel_for
from .models import Call, Conversation, Lead, Message

log = logging.getLogger(__name__)
CHANNEL_LABEL = {"wa": "WhatsApp", "g": "Google", "meta": "Meta", "ph": "Телефония", "manual": "Вручную"}


def conv_event(conv, event="conversation.updated"):
    broadcast(event, {"id": conv.id, "channel": conv.channel, "unread": conv.unread, "urgent": conv.urgent})


def add_message(conv, author, text="", user=None, attachment=None, delivery="", template=False, external_id="", created_at=None):
    m = Message.objects.create(
        conversation=conv, author=author, user=user if user and user.pk and user.role != "ai" else None, text=text,
        attachment=attachment, delivery=delivery, template=template, external_id=external_id,
        created_at=created_at or timezone.now(),
    )
    upd = {"updated_at": timezone.now()}
    if author == "client":
        upd["last_client_message_at"] = m.created_at
        conv.unread += 1
        upd["unread"] = conv.unread
    elif author in ("op", "ai") and not conv.first_response_at:
        upd["first_response_at"] = m.created_at
    Conversation.objects.filter(id=conv.id).update(**upd)
    for k, v in upd.items():
        setattr(conv, k, v)
    if author != "note":
        Client.objects.filter(id=conv.client_id).update(last_contact_at=m.created_at, last_contact_channel=CHANNEL_LABEL.get(conv.channel, ""))
    from .serializers import MessageSerializer

    broadcast("message.new", {"conversation": conv.id, "channel": conv.channel, "message": MessageSerializer(m).data})
    return m


def default_responsible(category=""):
    """п. 7.4: распределение — по направлению права, иначе по очереди среди операторов."""
    if category:
        u = User.objects.filter(role="lawyer", is_active=True, specialization__icontains=category.split()[0][:5]).first()
        if u:
            return u
    ops = list(User.objects.filter(role="operator", is_active=True).order_by("id"))
    if not ops:
        return User.objects.filter(role="manager", is_active=True).first()
    last = Conversation.objects.filter(responsible__in=ops).order_by("-created_at").first()
    if last and last.responsible in ops:
        return ops[(ops.index(last.responsible) + 1) % len(ops)]
    return ops[0]


@transaction.atomic
def inbound(channel, name="", phone="", email="", text="", campaign="", utm=None, external_id="", attachment=None, form_data=None, msg_external_id=""):
    """Любое обращение: найти/создать клиента, лида, диалог; сообщение; AI первая линия; уведомления (п. 7.2)."""
    if msg_external_id and Message.objects.filter(external_id=msg_external_id).exists():
        return None  # повторная доставка вебхука
    client, created = find_or_create_client(name=name, phone=phone, email=email, source=channel, campaign=campaign, utm=utm)
    conv = Conversation.objects.filter(client=client, channel=channel).exclude(status="closed").first()
    new_conv = conv is None
    if new_conv:
        lead = Lead.objects.create(client=client, channel=channel, campaign=campaign, utm=utm or {}, form_data=form_data or {})
        s = get_settings()["ai"]
        mode = "ai" if s["chat_247"] else "op"
        if channel == "wa" and s["draft_mode_wa"]:
            mode = "draft"
        conv = Conversation.objects.create(
            client=client, lead=lead, channel=channel, external_id=external_id, mode=mode,
            status="ai" if mode != "op" else "new", responsible=client.responsible or default_responsible(),
        )
        if not client.responsible:
            client.responsible = conv.responsible
            client.save(update_fields=["responsible"])
        audit(User.ai_user(), "Создал лида", f"{client.name} · {CHANNEL_LABEL.get(channel)}" + (f" · {campaign}" if campaign else ""), is_ai=True, type="ai", client_id=client.id)
        chk = run_conflict_check("lead", lead, [{"name": client.name, "pin": client.pin, "phone": client.phone}], User.ai_user(), f"Лид · {CHANNEL_LABEL.get(channel)}", exclude={"exclude_client_id": client.id, "exclude_lead_id": lead.id})
        if chk.status == "pending":
            m = chk.matches[0]
            add_message(conv, "sys", f"Проверка конфликта интересов: найдено совпадение — «{m['party_name']}» ({m['role_label'].lower()}" + (f", дело № {m['case_number']}" if m["case_number"] else "") + ")")
    elif external_id and not conv.external_id:
        conv.external_id = external_id
        conv.save(update_fields=["external_id"])
    if channel in ("g", "meta") and text and not text.startswith("Заявка"):
        text = f"Заявка {'с сайта' if channel == 'g' and not campaign else 'из ' + CHANNEL_LABEL[channel]}: «{text}»"
    msg = add_message(conv, "client", text, attachment=attachment, external_id=msg_external_id)
    if attachment:
        attachment.conversation = conv
        attachment.client = client
        attachment.save(update_fields=["conversation", "client"])
    if new_conv:
        notify([conv.responsible] if conv.responsible else managers(), "inbound", f"Новое обращение: {client.name} · {CHANNEL_LABEL.get(channel)}", f"/inbox?c={conv.id}")
        broadcast("conversation.updated", {"id": conv.id, "new": True})
    # AI первая линия — в фоне (Celery), в dev выполняется сразу после коммита
    from .tasks import ai_reply

    conv_id, msg_id = conv.id, msg.id
    transaction.on_commit(lambda: ai_reply.delay(conv_id, msg_id))
    return conv


def send_message(conv, user, text="", attachment=None, is_note=False, as_ai=False, template=None):
    if is_note:
        return add_message(conv, "note", text, user=user, attachment=attachment)
    win = conv.wa_window_seconds
    if conv.channel == "wa" and win == 0 and not template:
        raise PermissionError("24-часовое окно WhatsApp закрыто: отправьте одобренный шаблон")
    ch = channel_for(conv)
    res = ch.send_file(conv, attachment, text) if attachment else ch.send_text(conv, text, template)
    m = add_message(conv, "ai" if as_ai else "op", text, user=user, attachment=attachment, delivery=res.delivery, template=bool(template), external_id=res.external_id)
    if attachment and not attachment.conversation_id:
        attachment.conversation = conv
        attachment.save(update_fields=["conversation"])
    if not as_ai and conv.mode != "op":
        set_mode(conv, "op", user, silent_text="Сотрудник забрал диалог у ассистента")
    if not as_ai and conv.status in ("new", "ai"):
        conv.status = "op"
        conv.save(update_fields=["status"])
    return m


def set_mode(conv, mode, user, silent_text=None):
    if conv.mode == mode:
        return conv
    conv.mode = mode
    conv.status = {"ai": "ai", "draft": "ai", "op": "op"}[mode]
    conv.save(update_fields=["mode", "status"])
    who = str(user) if user and user.role != "ai" else "Ассистент"
    text = silent_text or {"ai": "Диалог передан ассистенту", "draft": "Включён режим «Черновик»: ассистент готовит ответ, отправляет сотрудник", "op": f"{who} забрал(а) диалог у ассистента"}[mode]
    add_message(conv, "sys", text)
    audit(user, text, f"{conv.client.name} · {CHANNEL_LABEL.get(conv.channel)}", client_id=conv.client_id, is_ai=getattr(user, "role", "") == "ai", type="ai" if getattr(user, "role", "") == "ai" else "change")
    conv_event(conv)
    return conv


def handoff(conv, reason, urgent=False):
    """Передача сотруднику (п. 9.2.7, 9.12)."""
    conv.mode, conv.status = "op", "op"
    conv.urgent = conv.urgent or urgent
    conv.save(update_fields=["mode", "status", "urgent"])
    text = ("Срочное обращение: диалог передан сотруднику, уведомлён руководитель" if urgent else f"Диалог передан сотруднику: {reason}") + f" · {timezone.localtime().strftime('%H:%M')}"
    add_message(conv, "sys", text)
    audit(User.ai_user(), f"Передал диалог сотруднику: {reason}", f"{conv.client.name} · {CHANNEL_LABEL.get(conv.channel)}", is_ai=True, type="ai", client_id=conv.client_id)
    targets = [conv.responsible] if conv.responsible else []
    if urgent:
        targets += managers()
    notify(targets or managers(), "handoff", f"{'СРОЧНО: ' if urgent else ''}{conv.client.name} — {reason}", f"/inbox?c={conv.id}")
    conv_event(conv)


# ---------- Звонки ----------

def call_popup_payload(call):
    from apps.crm.serializers import ClientSerializer

    c = call.client
    cards = list(c.cards.filter(is_archived=False).values_list("title", flat=True)[:3]) if c else []
    nearest = ""
    if c:
        ev = c.events.filter(start__gte=timezone.now()).order_by("start").first()
        if ev:
            from apps.crm.utils import due_label

            nearest = f"{ev.title} — {due_label(ev.start)}"
    return {
        "call_id": call.id, "phone": call.phone,
        "client": ClientSerializer(c).data if c else None,
        "open_cards": cards,
        "last_contact": (f"{timezone.localtime(c.last_contact_at).strftime('%d.%m %H:%M')}, {c.last_contact_channel}" if c and c.last_contact_at else ""),
        "nearest": nearest,
    }


def incoming_call(phone, external_id="", missed=False, record_url="", duration=0):
    from apps.crm.utils import normalize_phone

    client = Client.objects.filter(phone_norm=normalize_phone(phone), merged_into__isnull=True).first()
    call = Call.objects.create(external_id=external_id, client=client, phone=phone, direction="in", status="ringing", lead=client.leads.order_by("-created_at").first() if client else None)
    after_hours = not is_work_time()
    if missed:
        return missed_call(call, after_hours)
    targets = [client.responsible] if client and client.responsible else list(User.objects.filter(role__in=["operator", "manager"], is_active=True))
    if after_hours and get_settings()["ai"]["calls_after_hours"]:
        call.handled_by_ai = True
        call.save(update_fields=["handled_by_ai"])
    broadcast("call.incoming", call_popup_payload(call), [u.id for u in targets])
    return call


def missed_call(call, after_hours=None):
    """п. 7.6, 8.5: шаблон WhatsApp + задача «Перезвонить»."""
    from apps.boards.models import Board, BoardList
    from apps.boards.services import create_card
    from apps.crm.models import Deadline

    call.status = "missed"
    call.save(update_fields=["status"])
    client, created = (call.client, False) if call.client else find_or_create_client(phone=call.phone, source="ph")
    call.client = client
    call.save(update_fields=["client"])
    conv = Conversation.objects.filter(client=client).exclude(status="closed").order_by("-updated_at").first()
    if not conv:
        lead = Lead.objects.create(client=client, channel="ph")
        conv = Conversation.objects.create(client=client, lead=lead, channel="ph", mode="op", status="new", responsible=client.responsible or default_responsible(), stage="Перезвонить")
        if not client.responsible:
            client.responsible = conv.responsible
            client.save(update_fields=["responsible"])
    t = timezone.localtime(call.started_at).strftime("%H:%M")
    add_message(conv, "sys", f"Пропущенный звонок {t}" + (" (нерабочее время)" if after_hours else ""))
    ai = User.ai_user()
    add_message(conv, "ai", "Здравствуйте! Вы звонили в Law & Justice. Мы работаем пн–пт с 9:00 до 18:00 и перезвоним вам" + (" утром" if after_hours else " в ближайшее время") + ". Можете коротко описать вопрос здесь.", delivery="delivered", template=True)
    resp = conv.responsible
    now = timezone.localtime()
    if after_hours:
        due = now.replace(hour=10, minute=0, second=0, microsecond=0)
        if now.hour >= 10:
            due += timezone.timedelta(days=1)
    else:
        due = now + timezone.timedelta(hours=1)
    board = Board.objects.filter(template="leads", is_archived=False).first()
    if board:
        lst = board.lists.order_by("order").first()
        card = create_card(lst, f"Перезвонить: {client.name}", ai, top=True, client=client, source="ph", due_at=due, lead=conv.lead, conversation=conv, priority="high")
        if resp:
            card.members.add(resp)
        call.card = card
        call.save(update_fields=["card"])
    add_message(conv, "sys", f"Создана задача «Перезвонить» для {resp or 'оператора'}, срок — {timezone.localtime(due).strftime('%d.%m %H:%M')}")
    if resp:
        notify([resp], "call_missed", f"Пропущенный звонок {call.phone} — перезвонить", f"/calls?id={call.id}")
    broadcast("call.updated", {"id": call.id, "status": "missed"})
    return call
