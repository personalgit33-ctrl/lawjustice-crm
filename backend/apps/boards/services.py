"""Логика досок: шаблоны, создание и перенос карточек, автоматизации, импорт Trello."""
import json
from datetime import timedelta

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.audit.services import audit, broadcast, notify

from .models import Automation, Board, BoardList, Card, CardHistory, Checklist, ChecklistItem, Comment, Label

LABEL_COLORS = [("Красная", "#D14343"), ("Синяя", "#2A47A1"), ("Бирюзовая", "#0F766E"), ("Янтарная", "#B7791F"), ("Серая", "#64748B"), ("Фиолетовая", "#6D5BD0")]
CASE_COLS = [("Подготовка документов", 0), ("Подано в суд", 0), ("Заседание", 0), ("Решение получено", 1)]
TEMPLATES = {
    "leads": ("Лиды и консультации", [("Новый лид", 0), ("Квалификация", 0), ("Консультация назначена", 0), ("Договор подписан", 1), ("Отказ", 1)]),
    "cases": ("Дела в работе", CASE_COLS),
    "family": ("Семейные дела", CASE_COLS),
    "criminal": ("Уголовные дела", CASE_COLS),
    "inner": ("Внутренние задачи", [("К выполнению", 0), ("В процессе", 0), ("Готово", 1)]),
    "blank": ("Новая доска", [("К выполнению", 0), ("В работе", 0), ("Готово", 1)]),
}
BLOCKING = ("договор подписан", "в работе")


def create_board(name=None, template="blank", color="#2A47A1"):
    tname, cols = TEMPLATES.get(template, TEMPLATES["blank"])
    b = Board.objects.create(name=name or tname, template=template, color=color)
    for i, (n, final) in enumerate(cols):
        BoardList.objects.create(board=b, name=n, order=i, is_final=bool(final), blocks_on_conflict=n.lower() in BLOCKING)
    for n, c in LABEL_COLORS:
        Label.objects.create(board=b, name=n, color=c)
    return b


def history(card, actor, text, is_ai=False):
    CardHistory.objects.create(card=card, actor=actor if actor and actor.pk and actor.role != "ai" else None, is_ai=is_ai or getattr(actor, "role", "") == "ai", text=text)
    Card.objects.filter(id=card.id).update(updated_at=timezone.now())


def _next_pos(lst, top=False):
    agg = lst.cards.aggregate(m=Max("position"))["m"]
    if top:
        mn = lst.cards.order_by("position").values_list("position", flat=True).first()
        return (mn or 0) - 1
    return (agg or 0) + 1


def create_card(lst, title, user, top=False, **fields):
    is_ai = getattr(user, "role", "") == "ai"
    card = Card.objects.create(list=lst, title=title[:500], position=_next_pos(lst, top), ai_created=is_ai, **fields)
    if user and user.pk and not is_ai:
        card.subscribers.add(user)
    history(card, user, "создал карточку" + (f" в «{lst.name}»" if lst else ""), is_ai)
    audit(user, "Создал карточку", card.title, is_ai=is_ai, card_id=card.id, client_id=card.client_id, case_id=card.case_id, type="ai" if is_ai else "change",
          undo={"op": "archive_card", "id": card.id} if is_ai else None)
    broadcast("card.created", {"id": card.id, "board": lst.board_id, "list": lst.id})
    return card


class MoveBlocked(Exception):
    pass


def card_conflict_pending(card):
    if card.conflict_check_id and card.conflict_check.status == "pending":
        return True
    return bool(card.client_id and card.client.conflict_status == "hit")


def move_card(card, target, user, position=None):
    if target.blocks_on_conflict and card_conflict_pending(card):
        raise MoveBlocked("Нельзя перенести: не принято решение по конфликту интересов")
    if target.wip_limit and target.id != card.list_id and target.cards.filter(is_archived=False).count() >= target.wip_limit:
        raise MoveBlocked(f"В колонке «{target.name}» достигнут лимит карточек ({target.wip_limit})")
    src = card.list
    with transaction.atomic():
        if position is None:
            card.position = _next_pos(target)
        else:
            # вставка по индексу: перенумеровываем колонку
            ids = list(target.cards.filter(is_archived=False).exclude(id=card.id).order_by("position", "id").values_list("id", flat=True))
            idx = max(0, min(int(position), len(ids)))
            ids.insert(idx, card.id)
            for i, cid in enumerate(ids):
                Card.objects.filter(id=cid).update(position=i)
            card.position = idx
        card.list = target
        card.save(update_fields=["list", "position"])
        if src.id != target.id:
            history(card, user, f"переместил(а) в «{target.name}»")
            audit(user, f"Переместил карточку в «{target.name}»", card.title, card_id=card.id, client_id=card.client_id, is_ai=getattr(user, "role", "") == "ai", type="ai" if getattr(user, "role", "") == "ai" else "change",
                  undo={"op": "move_card", "id": card.id, "list": src.id} if getattr(user, "role", "") == "ai" else None)
            run_automations(card, target, user)
            subs = [u for u in card.subscribers.all() if u != user]
            if subs:
                notify(subs, "status", f"«{card.title}» → «{target.name}»", f"/boards?board={target.board_id}&card={card.id}")
    broadcast("card.moved", {"id": card.id, "board": target.board_id, "from_list": src.id, "list": target.id, "position": card.position, "by": getattr(user, "id", None)})
    return card


def run_automations(card, lst, user):
    from apps.accounts.models import User

    for a in Automation.objects.filter(list=lst, is_active=True):
        p = a.params or {}
        if a.action == "assign" and p.get("user"):
            u = User.objects.filter(id=p["user"]).first()
            if u:
                card.members.add(u)
                notify([u], "assign", f"Вам назначена карточка «{card.title}»", f"/boards?board={lst.board_id}&card={card.id}")
                history(card, None, f"Автоматизация: назначен {u}")
        elif a.action == "set_due_days":
            card.due_at = timezone.now() + timedelta(days=int(p.get("days", 1)))
            card.save(update_fields=["due_at"])
            history(card, None, f"Автоматизация: срок через {p.get('days', 1)} дн.")
        elif a.action == "add_checklist":
            cl = Checklist.objects.create(card=card, title=p.get("title", "Чек-лист"))
            for i, t in enumerate(p.get("items", [])):
                ChecklistItem.objects.create(checklist=cl, text=t, order=i)
            history(card, None, f"Автоматизация: добавлен чек-лист «{cl.title}»")
        elif a.action == "notify":
            ids = p.get("users") or ([p["user"]] if p.get("user") else [])
            users = list(User.objects.filter(id__in=ids)) or list(card.members.all())
            notify(users, "status", p.get("text") or f"Карточка «{card.title}» в колонке «{lst.name}»", f"/boards?board={lst.board_id}&card={card.id}")
        elif a.action == "set_case_status" and card.case_id and p.get("status"):
            card.case.status = p["status"]
            card.case.save(update_fields=["status", "updated_at"])
            history(card, None, f"Автоматизация: статус дела → {p['status']}")


# ---------- Импорт Trello (п. 6.7) ----------

def import_trello(data, user, user_map=None):
    """data — JSON экспорта доски Trello (Board → Menu → Print and export → JSON).
    Вложения-ссылки сохраняются как ссылки в описании (файлы Trello требуют API-ключа и качаются фоновой задачей)."""
    from apps.accounts.models import User

    if isinstance(data, (bytes, str)):
        data = json.loads(data)
    boards = data if isinstance(data, list) else [data]
    rep = {"boards": 0, "lists": 0, "cards": 0, "checklists": 0, "comments": 0, "labels": 0, "attachments": 0, "unmatched_users": []}
    users_by_name = {u.full_name.lower(): u for u in User.objects.exclude(role="ai")}
    user_map = user_map or {}
    with transaction.atomic():
        for bd in boards:
            members = {m["id"]: m for m in bd.get("members", [])}

            def map_user(mid):
                m = members.get(mid, {})
                key = (m.get("fullName") or m.get("username") or "").lower()
                if mid in user_map:
                    return User.objects.filter(id=user_map[mid]).first()
                u = users_by_name.get(key) or User.objects.filter(username__iexact=m.get("username", "")).first()
                if not u and key and key not in rep["unmatched_users"]:
                    rep["unmatched_users"].append(m.get("fullName") or m.get("username"))
                return u

            b = Board.objects.create(name=bd.get("name", "Trello"), trello_id=bd.get("id", ""), template="trello", color="#2A47A1")
            rep["boards"] += 1
            labels = {}
            for lb in bd.get("labels", []):
                color = {"green": "#15803D", "yellow": "#B7791F", "orange": "#B45309", "red": "#D14343", "purple": "#6D5BD0", "blue": "#2A47A1", "sky": "#0284C7", "lime": "#65A30D", "pink": "#DB2777", "black": "#111827"}.get(lb.get("color") or "", "#64748B")
                labels[lb["id"]] = Label.objects.create(board=b, name=lb.get("name", ""), color=color)
                rep["labels"] += 1
            lists = {}
            for i, l in enumerate(sorted(bd.get("lists", []), key=lambda x: x.get("pos", 0))):
                if l.get("closed"):
                    continue
                lists[l["id"]] = BoardList.objects.create(board=b, name=l.get("name", "")[:160], order=i, trello_id=l["id"], blocks_on_conflict=l.get("name", "").lower() in BLOCKING)
                rep["lists"] += 1
            cards = {}
            for c in sorted(bd.get("cards", []), key=lambda x: x.get("pos", 0)):
                lst = lists.get(c.get("idList"))
                if not lst:
                    continue
                desc = c.get("desc", "")
                card = Card.objects.create(
                    list=lst, title=c.get("name", "")[:500], description=desc, position=c.get("pos", 0),
                    due_at=parse_datetime(c["due"]) if c.get("due") else None, due_done=bool(c.get("dueComplete")),
                    is_archived=bool(c.get("closed")), trello_id=c["id"],
                )
                card.labels.set([labels[x] for x in c.get("idLabels", []) if x in labels])
                card.members.set([u for u in (map_user(m) for m in c.get("idMembers", [])) if u])
                links = [a.get("url") for a in c.get("attachments", []) if a.get("url")]
                if links:
                    card.description = (desc + "\n\nВложения из Trello:\n" + "\n".join(links)).strip()
                    card.save(update_fields=["description"])
                    rep["attachments"] += len(links)
                history(card, user, "импортировал карточку из Trello")
                cards[c["id"]] = card
                rep["cards"] += 1
            for cl in bd.get("checklists", []):
                card = cards.get(cl.get("idCard"))
                if not card:
                    continue
                ch = Checklist.objects.create(card=card, title=cl.get("name", "Чек-лист"))
                for i, it in enumerate(sorted(cl.get("checkItems", []), key=lambda x: x.get("pos", 0))):
                    ChecklistItem.objects.create(checklist=ch, text=it.get("name", "")[:500], done=it.get("state") == "complete", order=i)
                rep["checklists"] += 1
            for act in bd.get("actions", []):
                if act.get("type") != "commentCard":
                    continue
                card = cards.get(act.get("data", {}).get("card", {}).get("id"))
                if not card:
                    continue
                author = map_user(act.get("idMemberCreator"))
                creator = act.get("memberCreator", {})
                Comment.objects.create(card=card, author=author, author_label="" if author else (creator.get("fullName") or "Trello"), text=act.get("data", {}).get("text", ""), created_at=parse_datetime(act.get("date")) or timezone.now())
                rep["comments"] += 1
    audit(user, "Импортировал доски из Trello", f"досок {rep['boards']}, карточек {rep['cards']}", type="change", payload=rep)
    return rep
