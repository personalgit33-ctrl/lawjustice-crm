"""AI-ассистент администратора (п. 9.5): команда → план шагов → выполнение / подтверждение.

С ключом ANTHROPIC_API_KEY команда разбирается моделью Claude с инструментами CRM (tools.py).
Без ключа — детерминированный разбор типовых команд (rules), поведение и права те же.
"""
import re

from apps.accounts.models import User

from . import llm
from .models import AssistantRun
from .tools import TOOLS, ToolError, anthropic_tool_specs, detect_category, find_card, move_needs_confirm, resolve_user, tool_level

FORBIDDEN = [
    (r"удал", "удаление данных"),
    (r"закро?й\w* дел|закрыть дел", "закрытие дела"),
    (r"оплат|платеж|плат[её]ж|возврат денег|счёт на оплату|финанс", "финансовые операции"),
    (r"настройк|прав[ао]? доступ|роль|пароль", "изменение настроек и прав"),
    (r"перспектив|шанс|оценк[ау] дела|заключени", "юридические заключения и оценка перспектив"),
    (r"конфликт.*(сним|реш|одобр)", "решения по конфликту интересов"),
    (r"официальн\w* (письм|документ)", "отправка официальных документов"),
]

SYSTEM = """Ты — ассистент администратора юридической CRM Law & Justice. Выполняй команды сотрудника только через инструменты.
Правила: не удаляй данные, не закрывай дела, не проводи финансовые операции, не давай юридических оценок, не меняй настройки и права —
если просят такое, ответь, что это запрещено. Смена ответственного, перенос в итоговые колонки и изменение данных существующего клиента
требуют подтверждения — просто вызови инструмент, система сама запросит подтверждение. Перед созданием карточки найди клиента (find_client),
если не найден — создай (create_client). Сроки передавай словами («сегодня», «завтра», «пятница») или датой YYYY-MM-DD.
В конце одной строкой опиши результат: «Готово: …»."""


class Run:
    def __init__(self, user, command):
        self.user, self.command = user, command
        self.steps, self.pending = [], []
        self.ctx = {"user": user, "command": command}
        self.denied = None

    def step(self, tool, detail, status="done", needs_confirm=False, label=None):
        self.steps.append({"tool": tool, "label": label or TOOLS.get(tool, (tool,))[0], "detail": detail, "needs_confirm": needs_confirm, "status": status})

    def call(self, name, args):
        level = tool_level(name, args)
        if level == "confirm":
            detail = self._confirm_detail(name, args)
            self.pending.append({"tool": name, "args": args})
            self.step(name, detail, "pending", True)
            return {"status": "awaiting_confirmation"}
        try:
            detail, res = TOOLS[name][2](args, self.ctx)
        except ToolError as e:
            self.step(name, str(e), "denied")
            return {"error": str(e)}
        self.step(name, detail)
        for label, d in self.ctx.pop("notes", []):
            self.step("check_conflict", d, label=label)
        return res

    def _confirm_detail(self, name, args):
        if name == "move_card":
            _, card, target = move_needs_confirm(args)
            return f"«{card.title if card else args.get('card')}» в колонку «{target.name if target else args.get('list')}»"
        if name == "assign_responsible":
            card = find_card(args.get("card", ""))
            return f"«{card.title if card else args.get('card')}» → {resolve_user(args.get('user')) or args.get('user')}"
        return ", ".join(f"{k}: {v}" for k, v in args.items())


def _forbidden(text):
    t = text.lower()
    for rx, what in FORBIDDEN:
        if re.search(rx, t):
            return what
    return None


def run_command(user, text):
    text = text.strip()
    r = Run(user, text)
    what = _forbidden(text)
    if what:
        r.step("policy", f"Ассистент не выполняет: {what}", "denied", label="Запрещено")
        return _save(r, f"Действие запрещено правилами ассистента: {what}. Выполните его вручную.", "denied", "rules")
    engine = "rules"
    final = None
    if llm.available():
        def on_tool(name, args):
            if name not in TOOLS:
                return {"error": "нет такого инструмента"}, False
            return r.call(name, args), False

        final = llm.run_tools(SYSTEM, text, anthropic_tool_specs(), on_tool=on_tool)
        if final is not None and r.steps:
            engine = "claude"
    if engine == "rules":
        r = Run(user, text)
        final = rules(r, text)
    state = "awaiting_confirm" if r.pending else ("done" if any(s["status"] == "done" for s in r.steps) else "denied")
    if r.pending and not final:
        final = "Требуется подтверждение: " + ", ".join(s["label"].lower() for s in r.steps if s["status"] == "pending")
    elif r.pending:
        final = "Требуется подтверждение: " + ", ".join(s["label"].lower() for s in r.steps if s["status"] == "pending")
    return _save(r, final or "Команда не распознана. Пример: «Создай карточку на Айбека, уголовное дело, ответственный Бакыт, связаться сегодня».", state, engine)


def _save(r, result, state, engine):
    return AssistantRun.objects.create(user=r.user, command=r.command, steps=r.steps, pending=r.pending, result=result, state=state, engine=engine)


def confirm(run, user):
    r = Run(user, run.command)
    r.steps = [s for s in run.steps]
    for p in run.pending:
        try:
            detail, _ = TOOLS[p["tool"]][2](p["args"], r.ctx)
            for s in r.steps:
                if s["tool"] == p["tool"] and s["status"] == "pending":
                    s["status"], s["detail"] = "done", detail
                    break
        except ToolError as e:
            for s in r.steps:
                if s["tool"] == p["tool"] and s["status"] == "pending":
                    s["status"], s["detail"] = "denied", str(e)
                    break
    run.steps, run.pending, run.state = r.steps, [], "done"
    done = [s for s in r.steps if s["tool"] in ("move_card", "assign_responsible", "update_client") and s["status"] == "done"]
    run.result = "Готово: " + "; ".join(s["detail"] for s in done) + f" · подтвердил(а) {user}" if done else "Не выполнено"
    run.save()
    return run


def cancel(run, user):
    for s in run.steps:
        if s["status"] == "pending":
            s["status"] = "cancelled"
    run.pending, run.state, run.result = [], "cancelled", f"Действие отменено · {user}"
    run.save()
    return run


# ---------- разбор без модели ----------

def _name_after(text, words):
    for w in words:
        m = re.search(w + r"\s+([А-ЯЁA-Z«][^,;]+)", text)
        if m:
            return m.group(1).strip().rstrip(".")
    return None


def _quoted(text):
    m = re.findall(r"[«\"]([^»\"]+)[»\"]", text)
    return m[-1] if m else None


def rules(r, text):
    t = text.lower()
    # Перенос карточки
    if re.search(r"перенес|перенеси|перемест", t):
        target = _quoted(text) or _name_after(text, [r"в колонку", r"\bв\b"])
        card_q = re.sub(r"(перенеси|перемести)\s+(карточку\s+)?", "", text, flags=re.I)
        card_q = re.split(r"\s+в\s+[«\"]|\s+в колонку", card_q)[0]
        if not target:
            r.step("move_card", "не указана колонка", "denied")
            return "Укажите колонку в кавычках: «Консультация назначена»"
        card = find_card(card_q)
        r.step("find_card", f"«{card.title}»" if card else f"«{card_q}» — не найдена", "done" if card else "denied", label="Найти карточку")
        if not card:
            return "Карточка не найдена"
        res = r.call("move_card", {"card": str(card.id), "list": target})
        return None if r.pending else (f"Готово: карточка перемещена в «{target}»" if "error" not in res else res["error"])
    # Просроченные
    if re.search(r"покажи|найди|какие", t) and re.search(r"просроч", t):
        who = None
        for u in User.objects.filter(is_active=True).exclude(role="ai"):
            first = u.full_name.split()[0].lower()
            if first[:4] in t:
                who = u.full_name
                break
        r.call("list_overdue", {"user": who})
        return r.ctx.get("result_override")
    # Смена ответственного
    m = re.search(r"(смени|назначь|поменяй)\s+ответственн\w*\s+(?:по карточке|в карточке|карточки)?\s*(.+?)\s+на\s+(\S+)", text, re.I)
    if m:
        card = find_card(m.group(2))
        r.step("find_card", f"«{card.title}»" if card else "не найдена", "done" if card else "denied", label="Найти карточку")
        if card:
            r.call("assign_responsible", {"card": str(card.id), "user": m.group(3)})
        return None
    # Консультация
    if re.search(r"запиши|запись", t) and "консультац" in t:
        name = _name_after(text, [r"запиши"]) or ""
        name = re.split(r"\s+на консультац", name)[0]
        lawyer = _name_after(text, [r"\bк\b"])
        lawyer = lawyer.split()[0] if lawyer else None
        res = r.call("book_consultation", {"client_name": name, "lawyer": lawyer, "start": text})
        return f"Готово: {name} записан(а) на консультацию" if "error" not in res else res["error"]
    # Создание дела
    if re.search(r"создай\w*\s+дело|открой\w*\s+дело", t):
        name = _name_after(text, [r"дело на", r"дело для", r"дело клиента"]) or ""
        resp = _name_after(text, [r"ответственн\w*"])
        cat = detect_category(text)
        opp = _name_after(text, [r"против"])
        r.call("find_client", {"query": name})
        res = r.call("create_case", {"client_name": name, "title": (cat or "Новое дело") + (f" · против {opp}" if opp else ""), "category": cat, "responsible": resp.split()[0] if resp else None, "opponents": [opp] if opp else []})
        return f"Готово: {res.get('case_id') and 'дело создано'} · {name}" if "error" not in res else res["error"]
    # Создание карточки (основной сценарий)
    if re.search(r"созда\w*|заведи|добавь", t) and re.search(r"карточк|лид|задач", t):
        name = _name_after(text, [r"карточку на", r"карточку для", r"лид на", r"на"]) or "Новый клиент"
        name = re.split(r"\s*,", name)[0]
        cat = detect_category(text)
        resp = _name_after(text, [r"ответственн\w*", r"назначь"])
        resp_first = resp.split()[0] if resp else None
        due_m = re.search(r"(сегодня|завтра|послезавтра|понедельник|вторник|сред[ау]|четверг|пятниц[ау]|суббот[ау]|\d{4}-\d{2}-\d{2})", t)
        found = r.call("find_client", {"query": name})
        client_id = None
        if found.get("clients"):
            client_id = found["clients"][0]["id"]
        else:
            res = r.call("create_client", {"name": name, "responsible": resp_first})
            client_id = res.get("client_id")
        res = r.call("create_card", {"client_id": client_id, "category": cat, "title": f"{name} — {(cat or 'обращение').lower()}"})
        if "error" in res:
            return res["error"]
        u = resolve_user(resp_first)
        if u:
            r.ctx["card"].members.add(u)
            r.step("assign", str(u), label="Назначить ответственного")
        task = "Связаться с клиентом" if re.search(r"связат|позвон|написат", t) else "Первичная консультация"
        r.call("add_task", {"text": task, "assignee": resp_first, "due": due_m.group(1) if due_m else "завтра"})
        due = r.call("set_due", {"due": due_m.group(1) if due_m else "завтра"})
        from apps.crm.utils import due_label as dl
        from django.utils.dateparse import parse_datetime

        due_txt = dl(parse_datetime(due["due_at"])) if due.get("due_at") else "—"
        return f"Готово: {name} · {cat or 'без категории'} · {u or 'без ответственного'} · срок {due_txt.lower()}"
    return None
