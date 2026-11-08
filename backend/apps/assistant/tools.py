"""Инструменты AI — единственный способ AI действовать в CRM (п. 9.6, 9.8).

level: auto — AI выполняет сам; confirm — после подтверждения сотрудника; запрещённые действия здесь отсутствуют.
Каждое выполнение пишется в журнал с пометкой «Ассистент» (п. 9.9).
"""
import re
from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import audit, notify
from apps.boards.models import Board, BoardList, Card, Checklist, ChecklistItem, Comment
from apps.boards.services import create_card, history, move_card
from apps.crm.models import CalendarEvent, Case, Client, Deadline, Party
from apps.crm.services import find_or_create_client, run_conflict_check
from apps.crm.utils import due_label, normalize_name

WEEKDAYS = {"понедельник": 0, "вторник": 1, "сред": 2, "четверг": 3, "пятниц": 4, "суббот": 5, "воскресен": 6}
CATEGORY_WORDS = [
    ("Уголовное право", ["уголов", "задерж", "обыск", "следоват", "арест", "ст.", "статья", "ровд", "полиц"]),
    ("Семейное право", ["семей", "развод", "алимент", "раздел имущ", "брак", "опек", "ребён", "ребен"]),
    ("Корпоративное право", ["корпорат", "осоо", "подряд", "аванс", "взыскан", "долг", "учредит", "компан"]),
    ("Земельные споры", ["земел", "участ", "сосед", "забор", "госакт", "границ"]),
]
LABEL_FOR = {"Уголовное право": "#D14343", "Семейное право": "#2A47A1", "Корпоративное право": "#6D5BD0", "Земельные споры": "#0F766E"}


class ToolError(Exception):
    pass


def detect_category(text):
    t = (text or "").lower()
    for cat, words in CATEGORY_WORDS:
        if any(w in t for w in words):
            return cat
    return ""


def resolve_user(name):
    if not name:
        return None
    if isinstance(name, int) or str(name).isdigit():
        return User.objects.filter(id=int(name), is_active=True).first()
    n = str(name).lower().strip()
    stem = n[:4]
    for u in User.objects.filter(is_active=True).exclude(role="ai"):
        parts = u.full_name.lower().split()
        if n in u.full_name.lower() or any(p.startswith(stem) for p in parts):
            return u
    return None


def parse_due(text, base=None):
    t = (text or "").lower()
    now = timezone.localtime(base or timezone.now())
    end_of = lambda d: timezone.make_aware(datetime.combine(d, time(18, 0)))
    m = re.search(r"(\d{1,2})[:.](\d{2})", t)
    hm = (int(m.group(1)), int(m.group(2))) if m else None
    d = None
    if "сегодня" in t:
        d = now.date()
    elif "послезавтра" in t:
        d = now.date() + timedelta(days=2)
    elif "завтра" in t:
        d = now.date() + timedelta(days=1)
    else:
        for w, wd in WEEKDAYS.items():
            if w in t:
                d = now.date() + timedelta(days=(wd - now.weekday()) % 7 or 7)
                break
        m2 = re.search(r"(\d{4}-\d{2}-\d{2})", t)
        if m2:
            d = datetime.fromisoformat(m2.group(1)).date()
    if not d:
        return None
    dt = end_of(d)
    if hm:
        dt = dt.replace(hour=hm[0], minute=hm[1])
    return dt


def find_card(query):
    q = (query or "").strip()
    if not q:
        return None
    qs = Card.objects.filter(is_archived=False).select_related("list", "list__board", "client")
    if q.isdigit():
        return qs.filter(id=int(q)).first()
    words = [re.sub(r"[«»\"']", "", w) for w in re.split(r"\s+", q) if len(w) > 2 and w.lower() not in ("карточку", "карточка", "клиента")]
    stems = [w.lower()[:4] if len(w) >= 5 else w.lower() for w in words if w]
    best = None
    # сравнение в Python: регистронезависимо для кириллицы на любой СУБД
    for c in qs if stems else []:
        hay = (c.title + " " + (c.client.name if c.client else "")).lower()
        score = sum(1 for st in stems if st in hay)
        if score and (not best or score > best[0]):
            best = (score, c)
    return best[1] if best else None


def find_list(name, board=None):
    n = (name or "").lower().strip(" «»\"'")
    qs = BoardList.objects.filter(is_archived=False, board__is_archived=False)
    if board:
        qs = qs.filter(board=board)
    for l in qs:
        if l.name.lower() == n:
            return l
    for l in qs:
        if n and (n in l.name.lower() or l.name.lower() in n):
            return l
    return None


def leads_board():
    return Board.objects.filter(template="leads", is_archived=False).first() or Board.objects.filter(is_archived=False).first()


def ai():
    return User.ai_user()


def _log(action, label, payload, undo=None, **links):
    return audit(ai(), action, label, type="ai", is_ai=True, payload=payload, undo=undo, **links)


# ---------- реализация инструментов ----------

def t_find_client(a, ctx):
    q = a.get("query", "")
    nn = normalize_name(q)
    digits = re.sub(r"\D", "", q)
    found = []
    for c in Client.objects.filter(merged_into__isnull=True):
        from apps.crm.utils import names_match

        if (nn and names_match(nn, normalize_name(c.name))) or (len(digits) >= 6 and digits in c.phone_norm):
            found.append({"id": c.id, "name": c.name, "phone": c.phone})
    return (f"«{q}» — " + (", ".join(f["name"] for f in found[:3]) if found else "не найден")), {"clients": found[:5]}


def t_create_client(a, ctx):
    client, created = find_or_create_client(name=a["name"], phone=a.get("phone", ""), email=a.get("email", ""), source=a.get("source", "manual"))
    if not created:
        return f"«{client.name}» уже есть в базе", {"client_id": client.id, "created": False}
    if a.get("responsible"):
        client.responsible = resolve_user(a["responsible"])
        client.save(update_fields=["responsible"])
    chk = run_conflict_check("client", client, [{"name": client.name, "phone": client.phone}], ai(), "Создание клиента ассистентом", exclude={"exclude_client_id": client.id})
    _log("Создал клиента", client.name, a, client_id=client.id)
    ctx.setdefault("notes", []).append(("Проверка конфликта интересов", "найдено совпадение — нужна проверка руководителя" if chk.status == "pending" else "совпадений нет"))
    return f"«{client.name}»", {"client_id": client.id, "created": True, "conflict": chk.status}


def t_create_card(a, ctx):
    board = Board.objects.filter(name__icontains=a["board"]).first() if a.get("board") else leads_board()
    if not board:
        raise ToolError("Нет доступной доски")
    lst = find_list(a.get("list"), board) if a.get("list") else board.lists.filter(is_archived=False).order_by("order").first()
    if lst.is_final:
        raise ToolError("Создание карточки сразу в итоговой колонке требует подтверждения — создайте в первой колонке")
    client = None
    if a.get("client_id"):
        client = Client.objects.filter(id=a["client_id"]).first()
    elif a.get("client_name"):
        client, _ = find_or_create_client(name=a["client_name"], phone=a.get("phone", ""))
    category = a.get("category") or detect_category(a.get("title", "") + " " + a.get("description", ""))
    title = a.get("title") or f"{client.name if client else 'Новая карточка'} — {category.lower() or 'обращение'}"
    due = parse_due(a["due"]) if isinstance(a.get("due"), str) else None
    card = create_card(lst, title, ai(), top=True, client=client, due_at=due, description=a.get("description", ""), summary=a.get("summary", ""), source=a.get("source", ""), conversation_id=a.get("conversation_id"))
    if category:
        lb = board.labels.filter(color=LABEL_FOR.get(category, "")).first()
        if lb:
            card.labels.add(lb)
    resp = resolve_user(a.get("responsible"))
    if resp:
        card.members.add(resp)
        card.subscribers.add(resp)
        history(card, ai(), f"назначил ответственного: {resp}", True)
        notify([resp], "assign", f"Ассистент назначил вам карточку «{card.title}»", f"/boards?board={board.id}&card={card.id}")
    if client:
        from apps.boards.views import _client_check

        card.conflict_check = _client_check(card, ai())
        card.save(update_fields=["conflict_check"])
    if ctx.get("command"):
        history(card, ai(), f"создал карточку по команде {ctx['user']}: «{ctx['command']}»", True)
    ctx["card"] = card
    return f"доска «{board.name}», колонка «{lst.name}»" + (f", {category}" if category else ""), {"card_id": card.id, "title": card.title, "responsible": str(resp or "")}


def t_set_due(a, ctx):
    card = ctx.get("card") or find_card(a.get("card", ""))
    if not card:
        raise ToolError("Карточка не найдена")
    due = parse_due(a.get("due", ""))
    if not due:
        raise ToolError("Не удалось распознать срок")
    card.due_at = due
    card.save(update_fields=["due_at"])
    history(card, ai(), f"установил срок: {due_label(due)}", True)
    _log("Установил срок карточки", f"{card.title} · {due_label(due)}", a, card_id=card.id)
    return due_label(due), {"due_at": due.isoformat()}


def t_add_task(a, ctx):
    card = ctx.get("card") or find_card(a.get("card", ""))
    if not card:
        raise ToolError("Карточка не найдена")
    cl = card.checklists.first() or Checklist.objects.create(card=card, title="Задачи")
    it = ChecklistItem.objects.create(checklist=cl, text=a.get("text") or "Связаться с клиентом", assignee=resolve_user(a.get("assignee")) or card.members.first(), due_at=parse_due(a.get("due", "")) or card.due_at, order=cl.items.count())
    history(card, ai(), f"добавил задачу «{it.text}»", True)
    _log("Добавил задачу", f"{card.title}: {it.text}", a, card_id=card.id, undo={"op": "delete_item", "id": it.id})
    return f"«{it.text}»", {"item_id": it.id}


def t_add_comment(a, ctx):
    card = ctx.get("card") or find_card(a.get("card", ""))
    if not card:
        raise ToolError("Карточка не найдена")
    Comment.objects.create(card=card, is_ai=True, text=a["text"])
    history(card, ai(), "добавил комментарий", True)
    _log("Добавил комментарий", card.title, a, card_id=card.id)
    return card.title, {"ok": True}


def t_move_card(a, ctx):
    card = find_card(a.get("card", ""))
    if not card:
        raise ToolError(f"Карточка «{a.get('card')}» не найдена")
    target = find_list(a.get("list", ""), card.list.board) or find_list(a.get("list", ""))
    if not target:
        raise ToolError(f"Колонка «{a.get('list')}» не найдена")
    move_card(card, target, ai())
    return f"«{card.title}» → «{target.name}»", {"card_id": card.id, "list": target.name}


def move_needs_confirm(a):
    card = find_card(a.get("card", ""))
    target = (find_list(a.get("list", ""), card.list.board) if card else None) or find_list(a.get("list", ""))
    return bool(target and target.is_final), card, target


def t_assign(a, ctx):
    card = find_card(a.get("card", ""))
    u = resolve_user(a.get("user"))
    if not card or not u:
        raise ToolError("Карточка или сотрудник не найдены")
    prev = list(card.members.all())
    card.members.set([u])
    history(card, ai(), f"сменил ответственного на {u}", True)
    _log("Сменил ответственного", f"{card.title} → {u}", a, card_id=card.id, undo={"op": "set_members", "id": card.id, "members": [p.id for p in prev]})
    notify([u], "assign", f"Вам назначена карточка «{card.title}»", f"/boards?board={card.list.board_id}&card={card.id}")
    return f"{card.title} → {u}", {"ok": True}


def t_update_client(a, ctx):
    c = Client.objects.filter(id=a.get("client_id")).first() or Client.objects.filter(name__icontains=a.get("client", "~")).first()
    if not c:
        raise ToolError("Клиент не найден")
    old = {k: getattr(c, k) for k in a.get("fields", {}) if hasattr(c, k)}
    for k, v in a.get("fields", {}).items():
        if k in ("name", "phone", "email", "city", "notes"):
            setattr(c, k, v)
    c.save()
    _log("Изменил данные клиента", c.name, a, client_id=c.id, undo={"op": "client_fields", "id": c.id, "fields": old})
    return c.name, {"ok": True}


def t_list_overdue(a, ctx):
    u = resolve_user(a.get("user"))
    qs = Deadline.objects.filter(done_at__isnull=True, due_at__lt=timezone.now())
    cards = Card.objects.filter(is_archived=False, due_done=False, due_at__lt=timezone.now())
    if u:
        qs = qs.filter(Q(responsible=u) | Q(backup=u))
        cards = cards.filter(members=u)
    items = [f"{d.title} по делу № {d.case.number if d.case else '—'} — просрочено на {(timezone.now() - d.due_at).days or 1} дн." for d in qs if not (d.case and d.case.is_confidential and ctx.get("user") and ctx["user"].role == "ai")]
    items += [f"карточка «{c.title}» — срок {due_label(c.due_at)}" for c in cards[:10]]
    who = f"ответственный {u}" if u else "все сотрудники"
    ctx["result_override"] = (f"Найдено {len(items)}: " + "; ".join(items)) if items else "Просроченных задач нет"
    return f"{who}, статус «просрочено»", {"items": items}


def t_free_slots(a, ctx):
    u = resolve_user(a.get("lawyer")) or default_lawyer(a.get("category", ""))
    slots = free_slots(u)
    return f"{u}: " + ", ".join(due_label(s) for s in slots), {"lawyer": str(u), "slots": [s.isoformat() for s in slots]}


def t_book(a, ctx):
    u = resolve_user(a.get("lawyer")) or default_lawyer(a.get("category", ""))
    start = a.get("start")
    start = datetime.fromisoformat(start) if isinstance(start, str) and "T" in start else parse_due(start or "")
    if not start:
        raise ToolError("Не указано время консультации")
    if timezone.is_naive(start):
        start = timezone.make_aware(start)
    client = Client.objects.filter(id=a.get("client_id")).first() or (find_or_create_client(name=a["client_name"])[0] if a.get("client_name") else None)
    ev = CalendarEvent.objects.create(title=f"Консультация · {client.name.split()[0] if client else ''}", kind="consultation", start=start, end=start + timedelta(minutes=40), client=client, user=u, created_by_ai=True)
    _log("Записал на консультацию", f"{client.name if client else ''} · {u} · {due_label(start)}", a, client_id=client.id if client else None, undo={"op": "delete_event", "id": ev.id})
    if u:
        notify([u], "assign", f"Ассистент записал на консультацию: {client.name if client else ''} — {due_label(start)}", "/calendar")
    return f"{due_label(start)} · {u}", {"event_id": ev.id}


def t_create_case(a, ctx):
    client = Client.objects.filter(id=a.get("client_id")).first() or (find_or_create_client(name=a["client_name"])[0] if a.get("client_name") else None)
    if not client:
        raise ToolError("Не указан клиент")
    u = resolve_user(a.get("responsible"))
    case = Case.objects.create(number=Case.next_number(), title=a.get("title") or "Новое дело", client=client, category=a.get("category", ""), status="new", responsible=u)
    Party.objects.create(case=case, role="client", name=client.name, phone=client.phone, pin=client.pin)
    for opp in a.get("opponents", []) or []:
        Party.objects.create(case=case, role="opponent", name=opp)
    if a.get("opponents"):
        run_conflict_check("case", case, [{"name": o} for o in a["opponents"]], ai(), f"Дело № {case.number}", exclude={"exclude_case_id": case.id, "exclude_client_id": client.id})
    _log("Создал дело", str(case), a, case_id=case.id, client_id=client.id)
    return str(case), {"case_id": case.id}


def default_lawyer(category=""):
    if category:
        u = User.objects.filter(role="lawyer", is_active=True, specialization__icontains=category.split()[0][:5]).first()
        if u:
            return u
    return User.objects.filter(role="lawyer", is_active=True).first()


def free_slots(user, count=2):
    """Свободное время юриста: рабочие дни, 11:00 и 15:00 (настраивается), без пересечений с событиями."""
    out = []
    d = timezone.localdate() + timedelta(days=1)
    while len(out) < count and (d - timezone.localdate()).days < 21:
        if d.weekday() < 5:
            for h in (11, 15):
                st = timezone.make_aware(datetime.combine(d, time(h, 0)))
                busy = CalendarEvent.objects.filter(user=user, start__lt=st + timedelta(minutes=40), start__gte=st - timedelta(minutes=40)).exists() or Deadline.objects.filter(responsible=user, type="hearing", due_at__date=d, due_at__hour=h).exists()
                if not busy:
                    out.append(st)
                if len(out) >= count:
                    break
        d += timedelta(days=1)
    return out


TOOLS = {
    "find_client": ("Найти клиента", "auto", t_find_client, {"query": "string"}),
    "create_client": ("Создать клиента", "auto", t_create_client, {"name": "string", "phone": "string", "responsible": "string"}),
    "create_card": ("Создать карточку", "auto", t_create_card, {"client_name": "string", "title": "string", "category": "string", "responsible": "string", "due": "string", "board": "string", "list": "string", "description": "string"}),
    "set_due": ("Установить срок", "auto", t_set_due, {"card": "string", "due": "string"}),
    "add_task": ("Создать задачу", "auto", t_add_task, {"card": "string", "text": "string", "assignee": "string", "due": "string"}),
    "add_comment": ("Добавить комментарий", "auto", t_add_comment, {"card": "string", "text": "string"}),
    "move_card": ("Переместить", "auto*", t_move_card, {"card": "string", "list": "string"}),
    "assign_responsible": ("Сменить ответственного", "confirm", t_assign, {"card": "string", "user": "string"}),
    "update_client": ("Изменить данные клиента", "confirm", t_update_client, {"client": "string", "fields": "object"}),
    "list_overdue": ("Найти задачи", "auto", t_list_overdue, {"user": "string"}),
    "free_slots": ("Свободное время юристов", "auto", t_free_slots, {"lawyer": "string", "category": "string"}),
    "book_consultation": ("Записать на консультацию", "auto", t_book, {"client_name": "string", "lawyer": "string", "start": "string"}),
    "create_case": ("Создать дело", "auto", t_create_case, {"client_name": "string", "title": "string", "category": "string", "responsible": "string", "opponents": "array"}),
}


def tool_level(name, args):
    label, level, fn, _ = TOOLS[name]
    if level == "auto*":  # перенос в итоговую колонку — с подтверждением
        need, _, _ = move_needs_confirm(args)
        return "confirm" if need else "auto"
    return level


def anthropic_tool_specs():
    specs = []
    for name, (label, level, fn, props) in TOOLS.items():
        properties = {k: ({"type": "object"} if v == "object" else {"type": "array", "items": {"type": "string"}} if v == "array" else {"type": "string"}) for k, v in props.items()}
        specs.append({"name": name, "description": label + (" (требует подтверждения сотрудника)" if level == "confirm" else ""), "input_schema": {"type": "object", "properties": properties}})
    return specs


def undo_action(entry, user):
    """п. 9.9: отмена обратимого действия AI администратором."""
    u = entry.undo or {}
    op = u.get("op")
    if op == "archive_card":
        Card.objects.filter(id=u["id"]).update(is_archived=True)
    elif op == "move_card":
        card = Card.objects.filter(id=u["id"]).first()
        lst = BoardList.objects.filter(id=u["list"]).first()
        if card and lst:
            move_card(card, lst, user)
    elif op == "delete_item":
        ChecklistItem.objects.filter(id=u["id"]).delete()
    elif op == "delete_event":
        CalendarEvent.objects.filter(id=u["id"]).delete()
    elif op == "set_members":
        card = Card.objects.filter(id=u["id"]).first()
        if card:
            card.members.set(u["members"])
    elif op == "client_fields":
        Client.objects.filter(id=u["id"]).update(**u["fields"])
    else:
        return False
    entry.undone = True
    entry.save(update_fields=["undone"])
    audit(user, "Отменил действие ассистента", entry.action, type="ai")
    return True
