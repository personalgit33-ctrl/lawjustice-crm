import csv
import io
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.db.models import Q, Sum
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.accounts.permissions import (
    IsAdmin, IsManagerPlus, NotOperator, case_restricted, scope_cases, scope_clients, scope_deadlines,
)
from apps.audit.services import audit, broadcast, managers, notify

from .models import Attachment, CalendarEvent, Case, Client, ConflictCheck, Contract, Deadline, DictItem, Party, Payment
from .serializers import (
    AttachmentSerializer, CalendarEventSerializer, CaseSerializer, ClientSerializer, ConflictCheckSerializer,
    ContractSerializer, DeadlineSerializer, DictItemSerializer, PartySerializer, PaymentSerializer,
)
from .services import (
    check_signature, conflict_blocks, decide_conflict, get_settings, run_conflict_check, save_upload, update_settings,
)
from .utils import due_label

BLOCKED_BY_CONFLICT = {"in_work", "assigned"}


def conflict_409():
    return Response({"detail": "Нельзя перевести: не принято решение по конфликту интересов"}, status=409)


# ---------- Справочники и настройки ----------

class DictViewSet(viewsets.ModelViewSet):
    serializer_class = DictItemSerializer
    queryset = DictItem.objects.all()

    def get_permissions(self):
        return [IsAdmin()] if self.action not in ("list", "retrieve") else super().get_permissions()

    def list(self, request):
        out = {k: [] for k, _ in DictItem.KINDS}
        for it in DictItem.objects.all():
            out[it.kind].append(DictItemSerializer(it).data)
        return Response(out)

    def perform_create(self, ser):
        it = ser.save()
        audit(self.request.user, "Добавил элемент справочника", f"{it.get_kind_display()}: {it.name}")


@api_view(["GET", "PATCH"])
def settings_view(request):
    if request.method == "PATCH":
        if request.user.role != "admin":
            return Response({"detail": "Настройки меняет только администратор"}, status=403)
        data = update_settings(request.data)
        audit(request.user, "Изменил настройки", ", ".join(request.data.keys()), type="access")
        return Response(data)
    return Response(get_settings())


# ---------- Клиенты ----------

class ClientViewSet(viewsets.ModelViewSet):
    serializer_class = ClientSerializer
    http_method_names = ["get", "post", "patch"]

    def get_queryset(self):
        qs = scope_clients(self.request.user, Client.objects.select_related("responsible"))
        p = self.request.query_params
        if p.get("search"):
            s = p["search"]
            qs = qs.filter(Q(name__icontains=s) | Q(phone__icontains=s) | Q(phone_norm__icontains="".join(ch for ch in s if ch.isdigit()) or "§") | Q(email__icontains=s) | Q(pin__icontains=s))
        if p.get("kind"):
            qs = qs.filter(kind=p["kind"])
        if p.get("no_consent"):
            qs = qs.exclude(consent_status="given")
        return qs

    def perform_create(self, ser):
        c = ser.save(responsible=ser.validated_data.get("responsible") or self.request.user)
        audit(self.request.user, "Создал клиента", c.name, client_id=c.id)
        people = [{"name": c.name, "pin": c.pin, "phone": c.phone}]
        people += [{"name": n.strip()} for n in (self.request.data.get("opponents") or []) if isinstance(n, str) and n.strip()]
        run_conflict_check("client", c, people, self.request.user, "Создание клиента", exclude={"exclude_client_id": c.id})

    def perform_update(self, ser):
        c = ser.save()
        audit(self.request.user, "Изменил данные клиента", c.name, client_id=c.id)

    def retrieve(self, request, *args, **kwargs):
        c = self.get_object()
        if get_settings()["security"]["view_log"]:
            audit(request.user, "Открыл карточку клиента", c.name, type="view", client_id=c.id)
        return Response(self.get_serializer(c).data)

    @action(detail=True)
    def timeline(self, request, pk=None):
        c = self.get_object()
        return Response(client_timeline(c, request.user))

    @action(detail=True)
    def related(self, request, pk=None):
        from apps.boards.serializers import CardSummarySerializer
        from apps.comms.serializers import CallSerializer, ConversationSerializer
        from apps.accounts.permissions import scope_cards, scope_calls

        c = self.get_object()
        ctx = {"request": request}
        cases = scope_cases(request.user, c.cases.all())
        return Response({
            "cases": CaseSerializer(cases, many=True, context=ctx).data,
            "cards": CardSummarySerializer(scope_cards(request.user, c.cards.filter(is_archived=False)), many=True, context=ctx).data,
            "conversations": ConversationSerializer(c.conversations.all(), many=True, context=ctx).data,
            "calls": CallSerializer(scope_calls(request.user, c.calls.all()), many=True, context=ctx).data,
            "files": AttachmentSerializer(Attachment.objects.filter(Q(client=c) | Q(conversation__client=c) | Q(case__client=c, case__is_confidential=False)), many=True, context=ctx).data,
        })

    @action(detail=True, methods=["post"])
    def consent(self, request, pk=None):
        """п. 7.7: фиксация согласия и его отзыва."""
        c = self.get_object()
        st = request.data.get("status")
        if st not in ("given", "revoked"):
            return Response({"detail": "status: given | revoked"}, status=400)
        c.consent_status = st
        c.consent_at = timezone.now()
        c.consent_channel = request.data.get("channel", "вручную")
        c.consent_text = request.data.get("text", "")
        c.save()
        audit(request.user, "Согласие на обработку ПД: " + ("получено" if st == "given" else "отозвано"), c.name, client_id=c.id)
        return Response(self.get_serializer(c).data)

    @action(detail=False, methods=["post"], permission_classes=[IsManagerPlus])
    def merge(self, request):
        """Ручное слияние дублей (п. 5.3): всё переносится на primary."""
        from apps.boards.models import Card
        from apps.comms.models import Call, Conversation, Lead

        primary = get_object_or_404(Client, id=request.data.get("primary"))
        dup = get_object_or_404(Client, id=request.data.get("duplicate"))
        if primary.id == dup.id:
            return Response({"detail": "Выберите разных клиентов"}, status=400)
        with transaction.atomic():
            for model in (Case, Conversation, Lead, Call, Card, Contract, Attachment, CalendarEvent):
                model.objects.filter(client=dup).update(client=primary)
            for f in ("email", "pin", "city", "phone"):
                if not getattr(primary, f) and getattr(dup, f):
                    setattr(primary, f, getattr(dup, f))
            primary.notes = "\n".join(x for x in (primary.notes, dup.notes) if x)
            primary.save()
            dup.merged_into = primary
            dup.save()
        audit(request.user, "Объединил дубли клиентов", f"{dup.name} → {primary.name}", client_id=primary.id)
        return Response(self.get_serializer(primary).data)

    @action(detail=False, permission_classes=[IsAdmin])
    def export(self, request):
        """п. 12.8: экспорт только администратором, с записью в журнал."""
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "Тип", "Имя", "Город", "Телефон", "Email", "ПИН/ИНН", "Источник", "Ответственный", "Согласие", "Создан"])
        for c in Client.objects.filter(merged_into__isnull=True).select_related("responsible"):
            w.writerow([c.id, c.get_kind_display(), c.name, c.city, c.phone, c.email, c.pin, c.source, c.responsible or "", c.get_consent_status_display(), c.created_at.date()])
        audit(request.user, "Выгрузил клиентскую базу", "CSV", type="export")
        resp = HttpResponse("﻿" + buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="clients.csv"'
        return resp


def client_timeline(c, user):
    from apps.audit.models import AuditLog
    from apps.comms.models import Call, Message

    items = []
    for m in Message.objects.filter(conversation__client=c).exclude(author="note").select_related("conversation", "user")[:300]:
        who = {"client": c.name, "ai": "Ассистент", "op": str(m.user or "Сотрудник"), "sys": "Система"}.get(m.author, "")
        items.append({"id": f"m{m.id}", "kind": "message", "text": f"[{m.conversation.get_channel_display() if hasattr(m.conversation,'get_channel_display') else m.conversation.channel}] {m.text or (m.attachment.name if m.attachment else '')}", "actor": who, "is_ai": m.author == "ai", "created_at": m.created_at.isoformat(), "link": f"/inbox?c={m.conversation_id}"})
    from apps.accounts.permissions import scope_calls
    for call in scope_calls(user, Call.objects.filter(client=c)):
        st = {"answered": "отвечен", "missed": "пропущен", "transferred": "переведён", "ringing": "идёт"}[call.status]
        items.append({"id": f"c{call.id}", "kind": "call", "text": f"{'Входящий' if call.direction == 'in' else 'Исходящий'} звонок, {st}" + (f": {call.summary}" if call.summary else ""), "actor": "Ассистент" if call.handled_by_ai else str(call.user or "—"), "is_ai": call.handled_by_ai, "created_at": call.started_at.isoformat(), "link": f"/calls?id={call.id}"})
    for case in scope_cases(user, c.cases.all()):
        items.append({"id": f"k{case.id}", "kind": "case", "text": f"Открыто дело № {case.number}" + ("" if case_restricted(user, case) else f" · {case.title}"), "actor": str(case.responsible or ""), "is_ai": False, "created_at": case.created_at.isoformat(), "link": f"/cases/{case.id}"})
    for card in c.cards.all():
        items.append({"id": f"b{card.id}", "kind": "card", "text": f"Карточка «{card.title}» на доске «{card.list.board.name}»", "actor": "Ассистент" if card.ai_created else "", "is_ai": card.ai_created, "created_at": card.created_at.isoformat(), "link": f"/boards?card={card.id}"})
    for a in AuditLog.objects.filter(client_id=c.id).exclude(type="view")[:100]:
        items.append({"id": f"a{a.id}", "kind": "audit", "text": a.action, "actor": a.actor_label, "is_ai": a.is_ai, "created_at": a.created_at.isoformat()})
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items


# ---------- Дела ----------

class CaseViewSet(viewsets.ModelViewSet):
    serializer_class = CaseSerializer
    http_method_names = ["get", "post", "patch"]
    permission_classes = [NotOperator]

    def get_queryset(self):
        qs = scope_cases(self.request.user, Case.objects.select_related("client", "responsible").prefetch_related("parties", "members"))
        p = self.request.query_params
        qs = qs.filter(is_archived=bool(p.get("archived")))
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("court"):
            qs = qs.filter(status__in=["court"])
        if p.get("mine"):
            ids = self.request.user.represented_ids()
            qs = qs.filter(Q(responsible_id__in=ids) | Q(members__id__in=ids)).distinct()
        if p.get("search"):
            s = p["search"]
            qs = qs.filter(Q(number__icontains=s) | Q(title__icontains=s) | Q(client__name__icontains=s) | Q(parties__name__icontains=s)).distinct()
        return qs

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        parties = request.data.get("parties") or []
        with transaction.atomic():
            case = ser.save(number=Case.next_number(), responsible=ser.validated_data.get("responsible") or request.user)
            for p in parties:
                if p.get("name"):
                    Party.objects.create(case=case, role=p.get("role", "opponent"), name=p["name"], pin=p.get("pin", ""), phone=p.get("phone", ""))
            Party.objects.get_or_create(case=case, role="client", defaults={"name": case.client.name, "pin": case.client.pin, "phone": case.client.phone})
        people = [{"name": p["name"], "pin": p.get("pin", ""), "phone": p.get("phone", "")} for p in parties if p.get("name") and p.get("role", "opponent") != "client"]
        if people:
            chk = run_conflict_check("case", case, people, request.user, f"Дело № {case.number}", exclude={"exclude_case_id": case.id, "exclude_client_id": case.client_id})
            if chk.status == "pending" and case.status in BLOCKED_BY_CONFLICT:
                case.status = "new"
                case.save(update_fields=["status"])
        else:
            case.conflict_status = case.client.conflict_status if case.client.conflict_status != "none" else "ok"
            case.save(update_fields=["conflict_status"])
        audit(request.user, "Создал дело", str(case), case_id=case.id, client_id=case.client_id)
        if case.responsible and case.responsible != request.user:
            notify([case.responsible], "assign", f"Вам назначено дело № {case.number}", f"/cases/{case.id}")
        return Response(self.get_serializer(case).data, status=201)

    def retrieve(self, request, *args, **kwargs):
        case = self.get_object()
        if case.is_confidential or get_settings()["security"]["view_log"]:
            audit(request.user, "Открыл карточку дела", str(case) + (" (конфиденциально)" if case.is_confidential else ""), type="view", case_id=case.id)
        return Response(self.get_serializer(case).data)

    def partial_update(self, request, *args, **kwargs):
        case = self.get_object()
        if case_restricted(request.user, case):
            return Response({"detail": "Нет доступа к материалам конфиденциального дела"}, status=403)
        new_status = request.data.get("status")
        if new_status and new_status != case.status:
            if new_status in BLOCKED_BY_CONFLICT and (case.conflict_status == "hit" or conflict_blocks(case.client)):
                return conflict_409()
            if new_status == "closed" and request.user.role not in ("admin", "manager", "lawyer"):
                return Response({"detail": "Недостаточно прав"}, status=403)
        old_resp, old_status = case.responsible_id, case.status
        super().partial_update(request, *args, **kwargs)
        case.refresh_from_db()
        changes = ", ".join(k for k in request.data.keys())
        audit(request.user, f"Изменил дело ({changes})", str(case), case_id=case.id, client_id=case.client_id)
        if new_status and new_status != old_status:
            members = list(case.members.all()) + ([case.responsible] if case.responsible else [])
            notify([m for m in members if m != request.user], "status", f"Дело № {case.number}: статус «{DictItem.status_label(case.status)}»", f"/cases/{case.id}")
            if new_status in ("done", "closed"):
                case.is_archived = new_status == "closed"
                case.save(update_fields=["is_archived"])
        if case.responsible_id != old_resp and case.responsible:
            notify([case.responsible], "assign", f"Вам назначено дело № {case.number}", f"/cases/{case.id}")
        return Response(self.get_serializer(case).data)

    @action(detail=True)
    def timeline(self, request, pk=None):
        from apps.audit.models import AuditLog

        case = self.get_object()
        if case_restricted(request.user, case):
            return Response([])
        items = [{"id": f"a{a.id}", "kind": "audit", "text": a.action, "actor": a.actor_label, "is_ai": a.is_ai, "created_at": a.created_at.isoformat()} for a in AuditLog.objects.filter(case_id=case.id).exclude(type="view")[:200]]
        for d in case.deadlines.all():
            items.append({"id": f"d{d.id}", "kind": "audit", "text": f"Срок: {d.title} — {due_label(d.due_at)}" + (" (выполнен)" if d.done_at else ""), "actor": str(d.responsible or ""), "is_ai": False, "created_at": d.created_at.isoformat(), "link": "/deadlines"})
        for f in case.attachments.all():
            items.append({"id": f"f{f.id}", "kind": "file", "text": f"Документ: {f.name}", "actor": str(f.uploaded_by or ""), "is_ai": False, "created_at": f.created_at.isoformat()})
        for card in case.cards.all():
            for com in card.comments.all()[:20]:
                items.append({"id": f"cm{com.id}", "kind": "comment", "text": com.text, "actor": com.author_label or str(com.author or ""), "is_ai": com.is_ai, "created_at": com.created_at.isoformat()})
        items.sort(key=lambda x: x["created_at"], reverse=True)
        return Response(items)

    @action(detail=True)
    def files(self, request, pk=None):
        case = self.get_object()
        if case_restricted(request.user, case):
            return Response([])
        return Response(AttachmentSerializer(case.attachments.all(), many=True, context={"request": request}).data)


class PartyViewSet(mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = PartySerializer
    queryset = Party.objects.all()

    def perform_create(self, ser):
        p = ser.save()
        target = p.case or p.lead
        if p.role != "client":
            if p.case:
                run_conflict_check("case", p.case, [{"name": p.name, "pin": p.pin, "phone": p.phone}], self.request.user, f"Дело № {p.case.number}: новый участник", exclude={"exclude_case_id": p.case_id, "exclude_client_id": p.case.client_id})
            elif p.lead:
                run_conflict_check("lead", p.lead, [{"name": p.name, "pin": p.pin, "phone": p.phone}], self.request.user, "Лид: новый участник", exclude={"exclude_lead_id": p.lead_id, "exclude_client_id": p.lead.client_id})
        audit(self.request.user, f"Добавил участника ({p.get_role_display()})", p.name, case_id=p.case_id)


# ---------- Конфликт интересов ----------

class ConflictViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ConflictCheckSerializer

    def get_queryset(self):
        qs = ConflictCheck.objects.all()
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"]).exclude(subject_type="manual")
        else:
            qs = qs.exclude(subject_type="manual", status="ok")
        return qs

    @action(detail=False, methods=["post"])
    def check(self, request):
        q = {k: (request.data.get(k) or "").strip() for k in ("name", "pin", "phone")}
        if not any(q.values()):
            return Response({"detail": "Укажите ФИО, наименование, ПИН / ИНН или телефон"}, status=400)
        chk = run_conflict_check("manual", None, [q], request.user, "Ручная проверка")
        return Response(ConflictCheckSerializer(chk).data)

    @action(detail=True, methods=["post"], permission_classes=[IsManagerPlus])
    def decide(self, request, pk=None):
        chk = self.get_object()
        decision = request.data.get("decision")
        comment = (request.data.get("comment") or "").strip()
        if decision not in ("cleared", "refused"):
            return Response({"detail": "decision: cleared | refused"}, status=400)
        if not comment:
            return Response({"detail": "Комментарий к решению обязателен"}, status=400)
        decide_conflict(chk, decision, comment, request.user)
        return Response(ConflictCheckSerializer(chk).data)


# ---------- Сроки ----------

class DeadlineViewSet(viewsets.ModelViewSet):
    serializer_class = DeadlineSerializer
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        from apps.accounts.permissions import visible_case_q

        u = self.request.user
        qs = scope_deadlines(u, Deadline.objects.select_related("case", "case__client", "done_file")).filter(visible_case_q(u))
        p = self.request.query_params
        if p.get("user"):
            qs = qs.filter(Q(responsible_id=p["user"]) | Q(backup_id=p["user"]))
        if p.get("case"):
            qs = qs.filter(case_id=p["case"])
        st = p.get("state")
        if st and st != "all":
            ids = [d.id for d in qs if (d.state == st) or (st == "active" and d.state != "done")]
            qs = qs.filter(id__in=ids)
        return qs.distinct()

    def perform_create(self, ser):
        d = ser.save()
        audit(self.request.user, "Добавил срок", f"{d.title} · {due_label(d.due_at)}", case_id=d.case_id)
        notify([x for x in (d.responsible, d.backup) if x and x != self.request.user], "deadline", f"Новый срок: {d.title} — {due_label(d.due_at)}", "/deadlines")

    def perform_destroy(self, d):
        if self.request.user.role not in ("admin", "manager"):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Удалять сроки может руководитель")
        audit(self.request.user, "Удалил срок", d.title, case_id=d.case_id)
        d.delete()

    @action(detail=True, methods=["post"])
    def done(self, request, pk=None):
        d = self.get_object()
        f = request.FILES.get("file")
        if f:
            try:
                d.done_file = save_upload(f, request.user, case=d.case)
            except ValueError as e:
                return Response({"detail": str(e)}, status=400)
        d.done_at = timezone.now()
        d.done_by = request.user
        d.save()
        audit(request.user, "Отметил срок выполненным", f"{d.title} · {d.case.number if d.case else ''}", case_id=d.case_id)
        return Response(self.get_serializer(d).data)

    @action(detail=False, methods=["post"])
    def calc(self, request):
        """Помощник расчёта (п. 5.13.3): дата события + дни по шаблону. Итог подтверждает юрист."""
        tpl = get_object_or_404(DictItem, id=request.data.get("template_id"), kind="deadline_template")
        try:
            base = date.fromisoformat(request.data.get("base_date"))
        except (TypeError, ValueError):
            return Response({"detail": "base_date: YYYY-MM-DD"}, status=400)
        days = int(tpl.extra.get("days", 0))
        return Response({"date": (base + timedelta(days=days)).isoformat(), "days": days})

    @action(detail=False)
    def counts(self, request):
        res = {"late": 0, "today": 0, "week": 0, "later": 0, "done": 0}
        for d in self.get_queryset():
            res[d.state] += 1
        res["active"] = res["late"] + res["today"] + res["week"] + res["later"]
        return Response(res)


# ---------- Календарь ----------

@api_view(["GET"])
def calendar(request):
    from apps.accounts.permissions import scope_cards, visible_case_q
    from apps.boards.models import Card

    tz = timezone.get_current_timezone()
    try:
        f = datetime.combine(date.fromisoformat(request.query_params.get("from")), time.min, tz)
        t = datetime.combine(date.fromisoformat(request.query_params.get("to")), time.max, tz)
    except (TypeError, ValueError):
        today = timezone.localdate()
        f = datetime.combine(today.replace(day=1), time.min, tz)
        t = f + timedelta(days=42)
    u = request.user
    out = []
    for d in scope_deadlines(u, Deadline.objects.filter(due_at__range=(f, t))).filter(visible_case_q(u)).select_related("case", "case__client"):
        who = d.case.client.name.split()[0] if d.case else ""
        out.append({"id": f"d{d.id}", "title": f"{d.title}" + (f" · {who}" if who else ""), "kind": "hearing" if d.type == "hearing" else "deadline", "start": d.due_at.isoformat(), "end": None, "link": f"/cases/{d.case_id}" if d.case_id else "/deadlines", "user_id": d.responsible_id, "done": bool(d.done_at)})
    ev = CalendarEvent.objects.filter(start__range=(f, t)).filter(visible_case_q(u))
    if u.role == "lawyer":
        ev = ev.filter(Q(user_id__in=u.represented_ids()) | Q(case__members=u) | Q(case__responsible=u)).distinct()
    for e in ev:
        out.append({"id": f"e{e.id}", "title": e.title, "kind": e.kind, "start": e.start.isoformat(), "end": e.end.isoformat() if e.end else None, "link": f"/cases/{e.case_id}" if e.case_id else (f"/clients/{e.client_id}" if e.client_id else ""), "user_id": e.user_id})
    for c in scope_cards(u, Card.objects.filter(due_at__range=(f, t), is_archived=False)):
        out.append({"id": f"c{c.id}", "title": f"Карточка: {c.title}", "kind": "card", "start": c.due_at.isoformat(), "end": None, "link": f"/boards?board={c.list.board_id}&card={c.id}", "user_id": None})
    out.sort(key=lambda x: x["start"])
    return Response(out)


class EventViewSet(viewsets.ModelViewSet):
    serializer_class = CalendarEventSerializer
    queryset = CalendarEvent.objects.all()
    http_method_names = ["get", "post", "patch", "delete"]

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        e = ser.save(user=ser.validated_data.get("user") or request.user)
        audit(request.user, "Добавил событие в календарь", e.title, case_id=e.case_id, client_id=e.client_id)
        if e.user and e.user != request.user:
            notify([e.user], "assign", f"Новое событие: {e.title}", "/calendar")
        return Response({"id": f"e{e.id}", "title": e.title, "kind": e.kind, "start": e.start.isoformat(), "end": e.end.isoformat() if e.end else None, "link": "", "user_id": e.user_id}, status=201)


# ---------- Договоры и оплаты ----------

class ContractViewSet(viewsets.ModelViewSet):
    serializer_class = ContractSerializer
    http_method_names = ["get", "post", "patch"]
    permission_classes = [NotOperator]

    def get_queryset(self):
        qs = Contract.objects.select_related("client", "case").prefetch_related("payments")
        u = self.request.user
        if u.role == "lawyer":
            qs = qs.filter(Q(responsible_id__in=u.represented_ids()) | Q(case__members=u)).distinct()
        return qs.order_by("-id")

    def perform_create(self, ser):
        c = ser.save()
        audit(self.request.user, "Создал договор", f"{c.client.name} · {c.fee}", client_id=c.client_id, case_id=c.case_id)

    def perform_update(self, ser):
        c = ser.save()
        audit(self.request.user, "Изменил договор", f"{c.client.name} · {c.get_status_display()}", client_id=c.client_id, case_id=c.case_id)


@api_view(["POST"])
@permission_classes([IsManagerPlus])
def pay(request, pk):
    p = get_object_or_404(Payment, id=pk)
    amount = request.data.get("amount")
    try:
        amount = float(amount) if amount is not None else float(p.amount - p.paid_amount)
    except ValueError:
        return Response({"detail": "Неверная сумма"}, status=400)
    p.paid_amount = float(p.paid_amount) + amount
    p.paid_at = request.data.get("paid_at") or timezone.localdate()
    p.save()
    audit(request.user, "Отметил оплату", f"{p.contract.client.name} · {amount:,.0f} сом".replace(",", " "), client_id=p.contract.client_id, case_id=p.contract.case_id)
    return Response(PaymentSerializer(p).data)


def finance_summary_data():
    today = timezone.localdate()
    m0 = today.replace(day=1)
    pm0 = (m0 - timedelta(days=1)).replace(day=1)
    nm0 = (m0 + timedelta(days=32)).replace(day=1)
    nm1 = (nm0 + timedelta(days=32)).replace(day=1)
    P = Payment.objects
    received = float(P.filter(paid_at__gte=m0).aggregate(s=Sum("paid_amount"))["s"] or 0)
    received_prev = float(P.filter(paid_at__gte=pm0, paid_at__lt=m0).aggregate(s=Sum("paid_amount"))["s"] or 0)
    expected = sum(float(p.amount - p.paid_amount) for p in P.filter(due_date__gte=today, due_date__lt=nm1) if p.paid_amount < p.amount)
    overdue = [p for p in P.filter(due_date__lt=today) if p.paid_amount < p.amount]
    receivables = sum(float(p.amount - p.paid_amount) for p in overdue)
    signed = Contract.objects.filter(status="signed")
    fees = [float(c.fee) for c in signed]
    by_cat = {}
    for p in P.filter(paid_amount__gt=0).select_related("contract__case"):
        cat = (p.contract.case.category if p.contract.case else "") or "Без категории"
        by_cat[cat] = by_cat.get(cat, 0) + float(p.paid_amount)
    total = sum(by_cat.values()) or 1
    return {
        "received_month": received, "received_prev_month": received_prev, "expected_next": expected,
        "receivables": receivables, "overdue_count": len(overdue), "contracts_signed": signed.count(),
        "avg_fee": round(sum(fees) / len(fees)) if fees else 0,
        "by_category": sorted([{"name": k, "amount": v, "share": round(v * 100 / total)} for k, v in by_cat.items()], key=lambda x: -x["amount"]),
    }


@api_view(["GET"])
@permission_classes([NotOperator])
def finance_summary(request):
    return Response(finance_summary_data())


@api_view(["GET"])
@permission_classes([IsManagerPlus])
def finance_export(request):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Договоры"
    ws.append(["Клиент", "Дело", "Договор", "Модель", "Гонорар", "Оплачено", "Долг", "Следующий платёж"])
    for c in Contract.objects.all():
        d = ContractSerializer(c).data
        ws.append([d["client_name"], d["case_number"], c.get_status_display(), d["model_label"], d["fee"], d["paid"], d["debt"], d["next_payment_label"]])
    buf = io.BytesIO()
    wb.save(buf)
    audit(request.user, "Выгрузил реестр договоров и оплат", "Excel", type="export")
    resp = HttpResponse(buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = 'attachment; filename="finance.xlsx"'
    return resp


# ---------- Файлы ----------

class AttachmentViewSet(mixins.CreateModelMixin, mixins.DestroyModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = AttachmentSerializer
    queryset = Attachment.objects.all()
    http_method_names = ["post", "patch", "delete"]

    def create(self, request, *args, **kwargs):
        from apps.boards.models import Card, CardHistory, Comment
        from apps.comms.models import Conversation

        f = request.FILES.get("file")
        if not f:
            return Response({"detail": "Файл не передан"}, status=400)
        links = {}
        for key, model in (("card", Card), ("case", Case), ("client", Client), ("conversation", Conversation), ("comment", Comment)):
            if request.data.get(key):
                links[key] = get_object_or_404(model, id=request.data[key])
        if links.get("case") and case_restricted(request.user, links["case"]):
            return Response({"detail": "Нет доступа к делу"}, status=403)
        if request.data.get("parent"):
            links["parent"] = get_object_or_404(Attachment, id=request.data["parent"])
        try:
            att = save_upload(f, request.user, **links)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        if att.card_id:
            CardHistory.objects.create(card=att.card, actor=request.user, text=f"прикрепил файл «{att.name}»")
            broadcast("card.updated", {"id": att.card_id, "board": att.card.list.board_id})
        audit(request.user, "Загрузил файл", att.name, case_id=att.case_id, client_id=att.client_id, card_id=att.card_id)
        return Response(AttachmentSerializer(att, context={"request": request}).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        att = self.get_object()
        if request.data.get("name"):
            att.name = request.data["name"][:255]
            att.save(update_fields=["name"])
            audit(request.user, "Переименовал файл", att.name, case_id=att.case_id, card_id=att.card_id)
        return Response(AttachmentSerializer(att, context={"request": request}).data)

    def perform_destroy(self, att):
        u = self.request.user
        if u.role not in ("admin", "manager") and att.uploaded_by_id != u.id:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Удалить файл может автор, руководитель или администратор")
        audit(u, "Удалил файл", att.name, case_id=att.case_id, card_id=att.card_id)
        att.file.delete(save=False)
        att.delete()


@api_view(["GET"])
@permission_classes([AllowAny])
def file_download(request, pk):
    if not check_signature(pk, request.query_params.get("sig", "")):
        raise Http404
    att = get_object_or_404(Attachment, id=pk)
    try:
        fh = att.file.open("rb")
    except FileNotFoundError:
        raise Http404
    inline = att.is_image or att.mime == "application/pdf" or att.mime.startswith("audio/")
    return FileResponse(fh, as_attachment=not inline or request.query_params.get("dl") == "1", filename=att.name, content_type=att.mime)
