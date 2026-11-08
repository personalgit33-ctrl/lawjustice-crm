"""Панель управления, отчёт «Реклама и воронка», глобальный поиск, полная выгрузка данных."""
import io
import json
import zipfile
from datetime import timedelta

from django.core import serializers as dj_serializers
from django.db.models import Avg, Count, F, Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.permissions import IsAdmin, IsManagerPlus, scope_cards, scope_cases, scope_clients, scope_conversations, scope_deadlines, visible_case_q
from apps.audit.services import audit

from .models import AdSpend, Attachment, CalendarEvent, Case, Client, Deadline, Payment
from .serializers import CaseSerializer, ClientSerializer, DeadlineSerializer
from .views import finance_summary_data


@api_view(["GET"])
def dashboard(request):
    from apps.boards.models import Card
    from apps.comms.models import Call, Conversation, Lead, Message

    u = request.user
    now = timezone.now()
    today = timezone.localdate()
    tz = timezone.get_current_timezone()
    d0 = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()), tz)
    leads = Lead.objects.all()
    new_today = leads.filter(created_at__gte=d0).count()
    new_y = leads.filter(created_at__gte=d0 - timedelta(days=1), created_at__lt=d0).count()
    convs = Conversation.objects.filter(first_response_at__isnull=False, created_at__gte=now - timedelta(days=7))
    resp_secs = [(c.first_response_at - c.created_at).total_seconds() for c in convs]
    cases = scope_cases(u, Case.objects.filter(is_archived=False)).exclude(status__in=["done", "closed"])
    week_dl = Deadline.objects.filter(done_at__isnull=True, due_at__lte=now + timedelta(days=7), case__in=cases).values("case").distinct().count()
    fin = finance_summary_data() if u.role != "operator" else {"received_month": 0, "received_prev_month": 0, "receivables": 0, "overdue_count": 0}
    growth = round((fin["received_month"] - fin["received_prev_month"]) * 100 / fin["received_prev_month"]) if fin["received_prev_month"] else 0
    dls = [d for d in scope_deadlines(u, Deadline.objects.filter(done_at__isnull=True)).filter(visible_case_q(u)).select_related("case", "case__client") if d.state in ("late", "today", "week")][:8]

    attention = []
    for c in scope_conversations(u, Conversation.objects.filter(urgent=True).exclude(status="closed"))[:3]:
        attention.append({"level": "r", "title": "Срочное обращение", "text": f"{c.client.name}" + (f" — передано {c.responsible}" if c.responsible else ""), "link": f"/inbox?c={c.id}"})
    for d in dls:
        if d.state == "late":
            attention.append({"level": "r", "title": "Просрочен срок", "text": f"{d.title}" + (f" по делу № {d.case.number}" if d.case else ""), "link": "/deadlines"})
    from .models import ConflictCheck

    for chk in ConflictCheck.objects.filter(status="pending").exclude(subject_type="manual")[:3]:
        attention.append({"level": "a", "title": "Конфликт интересов", "text": f"{chk.subject_label} — требуется решение руководителя", "link": "/conflicts"})
    for call in Call.objects.filter(status="missed", started_at__gte=now - timedelta(days=2))[:3]:
        attention.append({"level": "a", "title": "Пропущенный звонок", "text": f"{call.phone} — перезвонить", "link": f"/calls?id={call.id}"})
    for c in scope_conversations(u, Conversation.objects.filter(unread__gt=0).exclude(status="closed").exclude(urgent=True))[:3]:
        mins = int((now - c.updated_at).total_seconds() // 60)
        attention.append({"level": "b", "title": f"Ждёт ответа {mins} мин" if mins < 120 else "Ждёт ответа", "text": f"{c.client.name} · {dict(wa='WhatsApp', g='Google', meta='Meta', ph='Звонок').get(c.channel)}", "link": f"/inbox?c={c.id}"})

    week = now - timedelta(days=7)
    ch_counts = {k: 0 for k in ("wa", "ph", "g", "meta")}
    for row in Lead.objects.filter(created_at__gte=week).values("channel").annotate(n=Count("id")):
        ch_counts[row["channel"]] = row["n"]
    ch_counts["ph"] = max(ch_counts["ph"], Call.objects.filter(started_at__gte=week, direction="in").count())

    lawyers = User.objects.filter(role="lawyer", is_active=True)
    loads = [(l, l.cases_responsible.filter(is_archived=False).exclude(status__in=["done", "closed"]).count()) for l in lawyers]
    mx = max([n for _, n in loads] + [10])

    week_convs = Conversation.objects.filter(created_at__gte=week)
    total = week_convs.count() or 1
    handed = week_convs.filter(messages__author="sys", messages__text__startswith="Диалог передан").distinct().count() + week_convs.filter(messages__author="sys", messages__text__startswith="Срочное").distinct().count()
    ai_only = week_convs.exclude(messages__author="op").count()
    return Response({
        "kpis": {
            "new_today": new_today, "new_yesterday": new_y,
            "first_response_sec": int(sum(resp_secs) / len(resp_secs)) if resp_secs else 0,
            "active_cases": cases.count(), "cases_deadline_week": week_dl,
            "received_month": fin["received_month"], "received_growth_pct": growth,
            "receivables": fin["receivables"], "overdue_payments": fin["overdue_count"],
        },
        "deadlines": DeadlineSerializer(dls, many=True, context={"request": request}).data,
        "attention": attention[:8],
        "channels": [{"channel": k, "count": v} for k, v in ch_counts.items()],
        "workload": [{"user": l.id, "name": l.full_name, "initials": l.initials, "cases": n, "pct": round(n * 100 / mx)} for l, n in loads],
        "first_line": {
            "ai_share_pct": round(ai_only * 100 / total), "handed_pct": round(min(handed, total) * 100 / total),
            "consultations": CalendarEvent.objects.filter(kind="consultation", created_by_ai=True, start__gte=week).count(),
            "ai_wrong": Message.objects.filter(author="ai", rating=False, created_at__gte=week).count(),
        },
        "missed_calls": Call.objects.filter(status="missed", started_at__gte=week).count(),
        "stale_items": Card.objects.filter(is_archived=False, updated_at__lt=now - timedelta(days=7), list__is_final=False).count()
        + Case.objects.filter(is_archived=False, updated_at__lt=now - timedelta(days=7)).exclude(status__in=["done", "closed"]).count(),
    })


def _period_start(period):
    today = timezone.localdate()
    if period == "week":
        return today - timedelta(days=7)
    if period == "quarter":
        return today - timedelta(days=90)
    return today.replace(day=1)


def funnel_data(period):
    from apps.comms.models import Lead
    from .models import Contract

    start = _period_start(period)
    leads = Lead.objects.filter(created_at__date__gte=start).select_related("client")
    rows = {}
    for l in leads:
        key = (l.channel, l.campaign or {"g": "Форма на сайте", "wa": "Прямые обращения", "ph": "Входящие звонки", "meta": "Lead Ads"}.get(l.channel, ""))
        r = rows.setdefault(key, {"channel": key[0], "campaign": key[1], "spend": 0, "leads": 0, "consultations": 0, "contracts": 0, "paid_amount": 0})
        r["leads"] += 1
        has_consult = l.status in ("consultation", "contract") or CalendarEvent.objects.filter(client=l.client, kind="consultation").exists()
        contracts = Contract.objects.filter(client=l.client, status="signed")
        r["consultations"] += 1 if has_consult or contracts.exists() else 0
        r["contracts"] += 1 if contracts.exists() else 0
        r["paid_amount"] += float(Payment.objects.filter(contract__in=contracts).aggregate(s=Sum("paid_amount"))["s"] or 0)
    months = {start.strftime("%Y-%m"), timezone.localdate().strftime("%Y-%m")}
    for s in AdSpend.objects.filter(month__in=months):
        key = (s.channel, s.campaign)
        r = rows.setdefault(key, {"channel": s.channel, "campaign": s.campaign, "spend": 0, "leads": 0, "consultations": 0, "contracts": 0, "paid_amount": 0})
        r["spend"] += float(s.amount)
    out = []
    for r in rows.values():
        r["cost_per_lead"] = round(r["spend"] / r["leads"]) if r["spend"] and r["leads"] else None
        r["cost_per_client"] = round(r["spend"] / r["contracts"]) if r["spend"] and r["contracts"] else None
        out.append(r)
    out.sort(key=lambda r: (["g", "meta", "wa", "ph", "manual"].index(r["channel"]) if r["channel"] in ("g", "meta", "wa", "ph", "manual") else 9, -r["leads"]))
    tl = sum(r["leads"] for r in out)
    tc = sum(r["consultations"] for r in out)
    tk = sum(r["contracts"] for r in out)
    qual = leads.exclude(status__in=["new", "spam"]).count() or tc
    paid = Contract.objects.filter(client__leads__in=leads, payments__paid_amount__gt=0).distinct().count()
    spend = sum(r["spend"] for r in out)
    pct = lambda n: round(n * 100 / tl) if tl else 0
    reasons = {}
    for l in leads.filter(status__in=["refused", "spam"]):
        k = l.refusal_reason or ("Спам" if l.status == "spam" else "Другое")
        reasons[k] = reasons.get(k, 0) + 1
    from apps.comms.models import Conversation

    ai_handled = Conversation.objects.filter(lead__in=leads).exclude(messages__author="op").count()
    return {
        "period": period,
        "totals": {"leads": tl, "consultations": tc, "contracts": tk, "paid": paid, "spend": spend, "cost_per_client": round(spend / tk) if tk and spend else None, "ai_share_pct": round(ai_handled * 100 / tl) if tl else 0},
        "rows": out,
        "funnel": [{"name": "Лиды", "count": tl, "pct": 100 if tl else 0}, {"name": "Квалифицированы", "count": qual, "pct": pct(qual)}, {"name": "Консультации", "count": tc, "pct": pct(tc)}, {"name": "Договоры", "count": tk, "pct": pct(tk)}, {"name": "Оплачено", "count": paid, "pct": pct(paid)}],
        "refusals": sorted([{"name": k, "count": v} for k, v in reasons.items()], key=lambda x: -x["count"]),
    }


@api_view(["GET"])
@permission_classes([IsManagerPlus])
def funnel(request):
    return Response(funnel_data(request.query_params.get("period", "month")))


@api_view(["POST"])
@permission_classes([IsManagerPlus])
def ad_spend(request):
    d = request.data
    try:
        amount = float(d.get("amount"))
    except (TypeError, ValueError):
        return Response({"detail": "Неверная сумма"}, status=400)
    AdSpend.objects.update_or_create(month=d.get("month") or timezone.localdate().strftime("%Y-%m"), channel=d.get("channel", "g"), campaign=d.get("campaign", ""), defaults={"amount": amount})
    audit(request.user, "Внёс расходы на рекламу", f"{d.get('month')} · {d.get('channel')} · {d.get('campaign', '')} · {amount:,.0f}".replace(",", " "))
    return Response({"ok": True})


@api_view(["GET"])
@permission_classes([IsManagerPlus])
def funnel_export(request):
    from openpyxl import Workbook

    data = funnel_data(request.query_params.get("period", "month"))
    wb = Workbook()
    ws = wb.active
    ws.title = "Каналы"
    ws.append(["Канал", "Кампания", "Расход", "Лиды", "Консультации", "Договоры", "Оплаты", "Цена лида", "Цена клиента"])
    for r in data["rows"]:
        ws.append([r["channel"], r["campaign"], r["spend"], r["leads"], r["consultations"], r["contracts"], r["paid_amount"], r["cost_per_lead"], r["cost_per_client"]])
    ws2 = wb.create_sheet("Воронка")
    for f in data["funnel"]:
        ws2.append([f["name"], f["count"], f["pct"]])
    ws3 = wb.create_sheet("Причины отказа")
    for f in data["refusals"]:
        ws3.append([f["name"], f["count"]])
    buf = io.BytesIO()
    wb.save(buf)
    audit(request.user, "Выгрузил отчёт «Реклама и воронка»", f"Excel, {data['period']}", type="export")
    resp = HttpResponse(buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = 'attachment; filename="funnel.xlsx"'
    return resp


@api_view(["GET"])
def search(request):
    from apps.boards.models import Card
    from apps.boards.serializers import CardSummarySerializer
    from apps.comms.models import Conversation
    from apps.comms.serializers import ConversationSerializer

    q = (request.query_params.get("q") or "").strip()
    if len(q) < 2:
        return Response({"clients": [], "cases": [], "cards": [], "conversations": []})
    u = request.user
    digits = "".join(ch for ch in q if ch.isdigit())
    cq = Q(name__icontains=q) | Q(email__icontains=q) | Q(pin=q)
    if len(digits) >= 5:
        cq |= Q(phone_norm__contains=digits)
    clients = scope_clients(u, Client.objects.filter(cq))[:5]
    ctx = {"request": request}
    cases = scope_cases(u, Case.objects.filter(Q(number__icontains=q) | Q(title__icontains=q) | Q(client__name__icontains=q)))[:5] if u.role != "operator" else []
    cards = scope_cards(u, Card.objects.filter(Q(title__icontains=q) | Q(client__name__icontains=q), is_archived=False))[:5]
    convs = scope_conversations(u, Conversation.objects.filter(Q(client__name__icontains=q) | (Q(client__phone_norm__contains=digits) if len(digits) >= 5 else Q(pk=0))))[:5]
    return Response({
        "clients": ClientSerializer(clients, many=True, context=ctx).data,
        "cases": CaseSerializer(cases, many=True, context=ctx).data,
        "cards": CardSummarySerializer(cards, many=True, context=ctx).data,
        "conversations": ConversationSerializer(convs, many=True, context=ctx).data,
    })


@api_view(["GET"])
@permission_classes([IsAdmin])
def export_all(request):
    """п. 12.10: все данные заказчика в открытых форматах (JSON + исходные файлы)."""
    from django.apps import apps as django_apps

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for label in ("crm", "boards", "comms", "audit", "assistant"):
            for model in django_apps.get_app_config(label).get_models():
                z.writestr(f"data/{label}.{model.__name__}.json", dj_serializers.serialize("json", model.objects.all(), ensure_ascii=False, indent=1))
        z.writestr("data/accounts.User.json", json.dumps(list(User.objects.values("id", "username", "full_name", "role", "email", "phone", "specialization", "is_active")), ensure_ascii=False, indent=1))
        for a in Attachment.objects.all():
            try:
                with a.file.open("rb") as fh:
                    z.writestr(f"files/{a.id}_{a.name}", fh.read())
            except Exception:
                pass
    audit(request.user, "Выгрузил все данные компании", "ZIP: JSON + файлы", type="export")
    resp = HttpResponse(buf.getvalue(), content_type="application/zip")
    resp["Content-Disposition"] = f'attachment; filename="lawjustice-export-{timezone.localdate()}.zip"'
    return resp
