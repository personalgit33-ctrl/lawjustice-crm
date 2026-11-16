"""Бизнес-логика CRM: настройки, проверка конфликта интересов, файлы, поиск/создание клиента."""
import copy
import mimetypes

from django.conf import settings as dj
from django.core import signing
from django.utils import timezone

from apps.audit.services import audit, managers, notify

from .models import AppSetting, Attachment, Case, Client, ConflictCheck, Party
from .utils import names_match, normalize_name, normalize_phone

DEFAULT_SETTINGS = {
    "integrations": {
        "wa": {"enabled": True, "label": "WhatsApp Business API", "info": "Meta Cloud API · шаблоны сообщений, медиа, статусы"},
        "g": {"enabled": True, "label": "Google Ads и формы сайта", "info": "Вебхук заявок · UTM передаются"},
        "meta": {"enabled": True, "label": "Meta Lead Ads", "info": "Facebook / Instagram"},
        "ip": {"enabled": True, "label": "IP-телефония", "info": "Облачная АТС · запись, маршрутизация"},
        "claude": {"enabled": True, "label": "Claude API (Anthropic)", "info": "Языковая модель ассистента · данные не используются для обучения"},
        "speech": {"enabled": False, "label": "Распознавание и синтез речи", "info": "Звонки ассистента и транскрибация"},
        "trello": {"enabled": True, "label": "Trello", "info": "Импорт досок из JSON-экспорта"},
        "tg": {"enabled": False, "label": "Telegram", "info": "Не входит в текущий объём"},
    },
    "ai": {
        "chat_247": True, "calls_after_hours": True, "draft_mode_wa": True, "disclose_ai": True, "masking": True,
        "skip_confidential": True, "no_legal_advice": True, "monthly_limit_usd": 150, "spent_usd": 0,
    },
    "security": {
        "require_2fa_admin": True, "idle_logout_min": 30, "export_admin_only": True, "view_log": True,
        "recordings_retention_months": 12, "archive_years": 5, "stale_days": 7, "max_file_mb": 50,
    },
    "knowledge_base": (
        "Law & Justice — юридическая компания в Бишкеке.\n"
        "Направления: семейное, уголовное, корпоративное право, земельные споры.\n"
        "Консультация — 2 000 сом, 40 минут, офис или онлайн.\n"
        "Адрес: ул. Киевская, 95. График: пн–пт 9:00–18:00.\n"
        "Передавать сотруднику: запрос оценки перспектив, жалобы, задержание, обыск, заседание сегодня, клиент просит человека."
    ),
    "reminders_days": [7, 3, 1, 0],
    "work_hours": {"start": "09:00", "end": "18:00", "days": [0, 1, 2, 3, 4]},
    "first_response_sla_min": 5,
}

CONFIGURED = {
    "wa": lambda: bool(dj.WHATSAPP_TOKEN and dj.WHATSAPP_PHONE_ID),
    "g": lambda: bool(dj.GOOGLE_WEBHOOK_KEY),
    "meta": lambda: bool(dj.META_PAGE_TOKEN),
    "ip": lambda: bool(dj.TELEPHONY_API_URL),
    "claude": lambda: bool(dj.ANTHROPIC_API_KEY),
    "speech": lambda: False,
    "trello": lambda: True,
    "tg": lambda: False,
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def get_settings():
    obj = AppSetting.objects.filter(key="main").first()
    data = _merge(DEFAULT_SETTINGS, obj.value if obj else {})
    for k, v in data["integrations"].items():
        v["configured"] = CONFIGURED.get(k, lambda: False)()
    return data


def update_settings(patch):
    obj, _ = AppSetting.objects.get_or_create(key="main", defaults={"value": {}})
    obj.value = _merge(obj.value, patch)
    obj.save()
    return get_settings()


def is_work_time(dt=None):
    s = get_settings()["work_hours"]
    dt = timezone.localtime(dt or timezone.now())
    hm = dt.strftime("%H:%M")
    return dt.weekday() in s["days"] and s["start"] <= hm < s["end"]


# ---------- Конфликт интересов (п. 5.12) ----------

ROLE_LABEL = {"client": "Клиент", "opponent": "Противная сторона", "third": "Третье лицо"}


def find_matches(name="", pin="", phone="", exclude_client_id=None, exclude_case_id=None, exclude_lead_id=None, exclude_card_id=None):
    nn, pn, ph = normalize_name(name), (pin or "").strip(), normalize_phone(phone)
    if not (nn or pn or ph):
        return []
    out, seen = [], set()

    def basis(obj_name_norm, obj_pin, obj_phone):
        b = []
        if nn and names_match(nn, obj_name_norm):
            b.append("ФИО" if True else "")
        if pn and obj_pin and pn == obj_pin:
            b.append("ПИН / ИНН")
        if ph and obj_phone and ph == obj_phone:
            b.append("телефон")
        return b

    for c in Client.objects.filter(merged_into__isnull=True).exclude(id=exclude_client_id or 0).only("id", "name", "pin", "phone_norm", "responsible"):
        b = basis(normalize_name(c.name), c.pin, c.phone_norm)
        if not b:
            continue
        cases = list(c.cases.exclude(id=exclude_case_id or 0))
        for case in cases or [None]:
            key = ("client", c.id, case.id if case else None)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "party_name": c.name, "role": "client", "role_label": "Клиент",
                "case_id": case.id if case else None, "case_number": case.number if case else "",
                "case_title": case.title if case else "Клиент без дела", "client_name": c.name,
                "responsible_name": str((case.responsible if case else c.responsible) or "—"),
                "basis": " + ".join(b),
            })
    qs = Party.objects.select_related("case", "case__client", "case__responsible", "lead", "lead__client")
    qs = qs.exclude(case_id=exclude_case_id or 0) if exclude_case_id else qs
    for p in qs:
        if exclude_lead_id and p.lead_id == exclude_lead_id:
            continue
        if exclude_card_id and p.card_id == exclude_card_id:
            continue
        if p.role == "client" and p.case_id:
            continue  # клиенты дел уже найдены через Client
        if exclude_client_id and p.case_id and p.case.client_id == exclude_client_id and p.role == "client":
            continue
        b = basis(p.name_norm, p.pin, p.phone_norm)
        if not b:
            continue
        case = p.case
        key = (p.role, p.name_norm, case.id if case else f"lead{p.lead_id}")
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "party_name": p.name, "role": p.role, "role_label": ROLE_LABEL[p.role],
            "case_id": case.id if case else None, "case_number": case.number if case else "",
            "case_title": case.title if case else "Лид в работе",
            "client_name": case.client.name if case else (p.lead.client.name if p.lead_id else ""),
            "responsible_name": str(case.responsible) if case and case.responsible else "—",
            "basis": " + ".join(b),
        })
    return out


def run_conflict_check(subject_type, subject, people, user=None, source_label="", exclude=None):
    """people: [{name, pin, phone}] — клиент и противные стороны. Создаёт ConflictCheck, меняет статус субъекта."""
    exclude = exclude or {}
    matches = []
    for p in people:
        if not (p.get("name") or p.get("pin") or p.get("phone")):
            continue
        for m in find_matches(p.get("name", ""), p.get("pin", ""), p.get("phone", ""), **exclude):
            m["checked"] = p.get("name") or p.get("phone")
            matches.append(m)
    label = getattr(subject, "name", None) or getattr(subject, "title", None) or (people[0].get("name") if people else "")
    chk = ConflictCheck.objects.create(
        subject_type=subject_type,
        subject_id=getattr(subject, "id", None),
        subject_label=str(label or "")[:255],
        source_label=source_label,
        query=people[0] if people else {},
        matches=matches,
        status="pending" if matches else "ok",
        created_by=user if user and getattr(user, "pk", None) else None,
    )
    status = "hit" if matches else "ok"
    field_names = {f.name for f in type(subject)._meta.get_fields()} if subject is not None else set()
    if "conflict_status" in field_names:
        type(subject).objects.filter(pk=subject.pk).update(conflict_status=status)
        subject.conflict_status = status
    if subject_type in ("lead", "card") and getattr(subject, "client_id", None):
        from .models import Client as _C

        _C.objects.filter(id=subject.client_id, conflict_status__in=["none", "ok"]).update(conflict_status=status)
    audit(
        user, "Проверка конфликта интересов: " + ("совпадение" if matches else "совпадений нет"),
        f"{label}" + (f" ↔ дело № {matches[0]['case_number']}" if matches and matches[0]["case_number"] else ""),
        type="check", is_ai=getattr(user, "role", "") == "ai",
    )
    if matches and subject_type != "manual":
        notify(managers(), "conflict", f"Конфликт интересов: {label} — требуется решение руководителя", "/conflicts", dedup_key=f"cf{chk.id}")
    return chk


def decide_conflict(chk, decision, comment, user):
    from apps.boards.models import Card
    from apps.comms.models import Lead

    chk.status = decision
    chk.decision_comment = comment
    chk.decided_by = user
    chk.decided_at = timezone.now()
    chk.save()
    new_status = "cleared" if decision == "cleared" else "refused"
    model = {"client": Client, "case": Case}.get(chk.subject_type)
    if model and chk.subject_id:
        model.objects.filter(id=chk.subject_id).update(conflict_status=new_status)
    if chk.subject_type == "lead" and chk.subject_id:
        lead = Lead.objects.filter(id=chk.subject_id).first()
        if lead:
            Client.objects.filter(id=lead.client_id).update(conflict_status=new_status)
            if decision == "refused":
                lead.status, lead.refusal_reason = "refused", "Конфликт интересов"
                lead.save()
    if chk.subject_type == "card" and chk.subject_id:
        card = Card.objects.filter(id=chk.subject_id).first()
        if card and card.client_id:
            Client.objects.filter(id=card.client_id).update(conflict_status=new_status)
    for card in Card.objects.filter(conflict_check=chk):
        if card.client_id:
            Client.objects.filter(id=card.client_id).update(conflict_status=new_status)
    audit(user, "Решение по конфликту: " + ("конфликта нет" if decision == "cleared" else "отказ клиенту"), f"{chk.subject_label} · {comment}", type="check")
    return chk


def conflict_blocks(client=None, check=None) -> bool:
    if check is not None and check.status == "pending":
        return True
    return bool(client and client.conflict_status == "hit")


# ---------- Клиенты ----------

def find_or_create_client(name="", phone="", email="", source="manual", campaign="", utm=None, user=None, kind=None):
    """п. 5.3 / 7.2: объединение обращений одного клиента по телефону и email."""
    pn = normalize_phone(phone)
    client = None
    if pn:
        client = Client.objects.filter(phone_norm=pn, merged_into__isnull=True).first()
    if not client and email:
        client = Client.objects.filter(email__iexact=email, merged_into__isnull=True).first()
    created = False
    if not client:
        if kind is None:
            kind = "company" if any(w in (name or "") for w in ("ОсОО", "ООО", "«")) else "person"
        client = Client.objects.create(
            name=name or phone or email or "Без имени", phone=phone, email=email or "", source=source,
            campaign=campaign, utm=utm or {}, kind=kind,
        )
        created = True
    else:
        changed = False
        if email and not client.email:
            client.email, changed = email, True
        if name and client.name in (client.phone, "Без имени"):
            client.name, changed = name, True
        if changed:
            client.save()
    return client, created


# ---------- Файлы ----------

def save_upload(f, user=None, **links):
    max_mb = get_settings()["security"]["max_file_mb"]
    if f.size > max_mb * 1024 * 1024:
        raise ValueError(f"Файл больше {max_mb} МБ")
    mime = getattr(f, "content_type", "") or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
    return Attachment.objects.create(file=f, name=f.name[:255], size=f.size, mime=mime, uploaded_by=user if user and user.pk else None, **links)


def signed_url(att, request=None):
    if not att:
        return None
    sig = signing.TimestampSigner(salt="file").sign(str(att.id)).split(":", 1)[1]
    path = f"/api/files/{att.id}/?sig={sig}"
    return request.build_absolute_uri(path) if request else path


def check_signature(att_id, sig):
    try:
        signing.TimestampSigner(salt="file").unsign(f"{att_id}:{sig}", max_age=3600)
        return True
    except signing.BadSignature:
        return False
