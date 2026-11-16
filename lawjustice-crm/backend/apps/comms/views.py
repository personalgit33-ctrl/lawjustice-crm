from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.permissions import IsManagerPlus, can_access_recording, scope_calls, scope_conversations
from apps.audit.services import audit, broadcast, notify
from apps.boards.models import Board
from apps.boards.serializers import CardDetailSerializer
from apps.boards.services import create_card
from apps.crm.models import Attachment, Case, DictItem, Party
from apps.crm.serializers import AttachmentSerializer, CaseSerializer
from apps.crm.services import run_conflict_check, signed_url

from .channels import telephony
from .models import Call, Conversation, Message
from .serializers import CallSerializer, ConversationDetailSerializer, ConversationSerializer, MessageSerializer
from .services import CHANNEL_LABEL, call_popup_payload, conv_event, incoming_call, inbound, missed_call, send_message, set_mode

CLOSE_RESULT = {"client": "Стал клиентом", "consult": "Консультация", "refused": "Отказ", "spam": "Спам"}


class ConversationViewSet(viewsets.ReadOnlyModelViewSet):
    def get_serializer_class(self):
        return ConversationDetailSerializer if self.action != "list" else ConversationSerializer

    def get_queryset(self):
        qs = scope_conversations(self.request.user, Conversation.objects.select_related("client", "responsible", "lead"))
        f = self.request.query_params.get("filter", "all")
        if f == "closed":
            return qs.filter(status="closed")
        if self.action == "list":
            qs = qs.exclude(status="closed")
        if f == "urgent":
            qs = qs.filter(urgent=True)
        elif f == "ai":
            qs = qs.exclude(mode="op")
        elif f in ("wa", "g", "meta", "ph"):
            qs = qs.filter(channel=f)
        elif f == "unread":
            qs = qs.filter(unread__gt=0)
        elif f == "mine":
            qs = qs.filter(responsible_id__in=self.request.user.represented_ids())
        if self.request.query_params.get("responsible"):
            qs = qs.filter(responsible_id=self.request.query_params["responsible"])
        return qs

    def retrieve(self, request, *args, **kwargs):
        conv = self.get_object()
        if conv.unread:
            conv.unread = 0
            conv.save(update_fields=["unread"])
            conv_event(conv)
        return Response(ConversationDetailSerializer(conv, context={"request": request}).data)

    def _detail(self, conv):
        conv.refresh_from_db()
        return Response(ConversationDetailSerializer(conv, context={"request": self.request}).data)

    @action(detail=True, methods=["post"])
    def messages(self, request, pk=None):
        conv = self.get_object()
        text = (request.data.get("text") or "").strip()
        att = Attachment.objects.filter(id=request.data.get("attachment")).first() if request.data.get("attachment") else None
        if not text and not att:
            return Response({"detail": "Пустое сообщение"}, status=400)
        try:
            m = send_message(conv, request.user, text, attachment=att, is_note=bool(request.data.get("is_note")), template=request.data.get("template"))
        except PermissionError as e:
            return Response({"detail": str(e)}, status=409)
        return Response(MessageSerializer(m, context={"request": request}).data, status=201)

    @action(detail=True, methods=["post"])
    def mode(self, request, pk=None):
        conv = self.get_object()
        mode = request.data.get("mode")
        if mode not in ("ai", "draft", "op"):
            return Response({"detail": "mode: ai | draft | op"}, status=400)
        if mode != "op" and conv.client.cases.filter(is_confidential=True).exists():
            return Response({"detail": "Клиент по конфиденциальному делу: ассистент отключён"}, status=409)
        set_mode(conv, mode, request.user)
        if mode == "draft" and not conv.draft:
            conv.draft = "Здравствуйте! Спасибо за обращение в Law & Justice. Уточните, пожалуйста, удобное время для консультации."
            conv.save(update_fields=["draft"])
        return self._detail(conv)

    @action(detail=True, methods=["post"], url_path="send-draft")
    def send_draft(self, request, pk=None):
        conv = self.get_object()
        text = (request.data.get("text") or conv.draft or "").strip()
        if not text:
            return Response({"detail": "Черновика нет"}, status=400)
        edited = text != conv.draft
        send_message(conv, User.ai_user() if not edited else request.user, text, as_ai=not edited)
        conv.draft = ""
        conv.save(update_fields=["draft"])
        audit(request.user, "Отправил черновик ассистента" + (" (с правкой)" if edited else ""), conv.client.name, client_id=conv.client_id)
        return self._detail(conv)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        conv = self.get_object()
        u = get_object_or_404(User, id=request.data.get("user"), is_active=True)
        conv.responsible = u
        conv.save(update_fields=["responsible"])
        from .services import add_message

        add_message(conv, "sys", f"Диалог передан: {u}")
        if conv.mode != "op":
            set_mode(conv, "op", request.user, silent_text="Диалог переведён на сотрудника")
        if u != request.user:
            notify([u], "assign", f"Вам передан диалог: {conv.client.name}", f"/inbox?c={conv.id}")
        audit(request.user, f"Передал диалог: {u}", conv.client.name, client_id=conv.client_id)
        return self._detail(conv)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        conv = self.get_object()
        result = request.data.get("result")
        if result not in CLOSE_RESULT:
            return Response({"detail": "result: client | consult | refused | spam"}, status=400)
        reason = request.data.get("reason", "")
        if result == "refused" and not reason:
            return Response({"detail": "Выберите причину отказа"}, status=400)
        conv.status, conv.close_result, conv.close_reason = "closed", result, reason
        conv.save(update_fields=["status", "close_result", "close_reason"])
        if conv.lead:
            conv.lead.status = {"client": "contract", "consult": "consultation", "refused": "refused", "spam": "spam"}[result]
            conv.lead.refusal_reason = reason if result in ("refused", "spam") else ""
            if result == "spam":
                conv.lead.refusal_reason = "Спам"
            conv.lead.save()
        from .services import add_message

        add_message(conv, "sys", f"Диалог закрыт: {CLOSE_RESULT[result]}" + (f" · {reason}" if reason else ""))
        audit(request.user, f"Закрыл диалог: {CLOSE_RESULT[result]}", conv.client.name, client_id=conv.client_id)
        return self._detail(conv)

    @action(detail=True, methods=["post"], url_path="create-card")
    def create_card_from(self, request, pk=None):
        conv = self.get_object()
        board = Board.objects.filter(id=request.data.get("board")).first() or Board.objects.filter(template="leads", is_archived=False).first()
        lst = board.lists.filter(is_archived=False).order_by("order").first()
        topic = (conv.summary.split(".")[0] if conv.summary else "обращение").lower()
        card = create_card(lst, f"{conv.client.name} — {topic}"[:200], request.user, top=True, client=conv.client, conversation=conv, source=conv.channel, lead=conv.lead, summary=conv.summary, due_at=timezone.now() + timezone.timedelta(days=1))
        if conv.responsible:
            card.members.add(conv.responsible)
        from apps.boards.views import _client_check

        card.conflict_check = _client_check(card, request.user)
        card.save(update_fields=["conflict_check"])
        # файлы из переписки → в карточку (п. 10.3)
        for att in conv.attachments.filter(card__isnull=True):
            att.card = card
            att.save(update_fields=["card"])
        return Response(CardDetailSerializer(card, context={"request": request}).data, status=201)

    @action(detail=True, methods=["post"], url_path="create-case")
    def create_case_from(self, request, pk=None):
        conv = self.get_object()
        client = conv.client
        if client.conflict_status == "hit":
            return Response({"detail": "Нельзя создать дело: требуется решение по конфликту интересов"}, status=409)
        if request.user.role == "operator":
            return Response({"detail": "Дела создают юристы и руководитель"}, status=403)
        cat = request.data.get("category") or (conv.ai_state or {}).get("category", "")
        case = Case.objects.create(number=Case.next_number(), title=request.data.get("title") or (conv.summary.split(".")[0] if conv.summary else "Новое дело")[:200], client=client, category=cat, status="evaluation", responsible=conv.responsible if conv.responsible and conv.responsible.role == "lawyer" else request.user, description=conv.summary)
        Party.objects.create(case=case, role="client", name=client.name, phone=client.phone, pin=client.pin)
        if conv.lead:
            for p in conv.lead.parties.all():
                Party.objects.create(case=case, role=p.role, name=p.name, pin=p.pin, phone=p.phone)
        case.conflict_status = client.conflict_status if client.conflict_status != "none" else "ok"
        case.save(update_fields=["conflict_status"])
        for att in conv.attachments.filter(case__isnull=True):
            att.case = case
            att.save(update_fields=["case"])
        audit(request.user, "Создал дело из диалога", str(case), case_id=case.id, client_id=client.id)
        return Response(CaseSerializer(case, context={"request": request}).data, status=201)


@api_view(["POST"])
def message_to_card(request, pk):
    from apps.boards.models import Card
    from apps.boards.services import history

    m = get_object_or_404(Message, id=pk)
    card = get_object_or_404(Card, id=request.data.get("card"))
    if not m.attachment:
        return Response({"detail": "В сообщении нет файла"}, status=400)
    att = m.attachment
    if att.card_id and att.card_id != card.id:
        att = Attachment.objects.create(file=att.file, name=att.name, size=att.size, mime=att.mime, uploaded_by=att.uploaded_by, card=card, conversation=att.conversation)
    else:
        att.card = card
        att.save(update_fields=["card"])
    if card.case_id and not att.case_id:
        att.case_id = card.case_id
        att.save(update_fields=["case"])
    history(card, request.user, f"прикрепил(а) файл из переписки «{att.name}»")
    broadcast("card.updated", {"id": card.id, "board": card.list.board_id})
    return Response(AttachmentSerializer(att, context={"request": request}).data, status=201)


@api_view(["POST"])
def message_rate(request, pk):
    m = get_object_or_404(Message, id=pk, author="ai")
    m.rating = bool(request.data.get("correct"))
    m.save(update_fields=["rating"])
    audit(request.user, "Оценил ответ ассистента: " + ("верно" if m.rating else "неверно"), m.text[:120], type="ai")
    return Response(MessageSerializer(m, context={"request": request}).data)


# ---------- Звонки ----------

class CallViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CallSerializer

    def get_queryset(self):
        return scope_calls(self.request.user, Call.objects.select_related("client", "user", "case"))[:300]

    def get_object(self):
        return get_object_or_404(scope_calls(self.request.user, Call.objects.all()), pk=self.kwargs["pk"])

    @action(detail=True, methods=["post"])
    def recording(self, request, pk=None):
        """п. 8.8: доступ — ответственному, руководителю, админу; каждое прослушивание/скачивание — в журнал."""
        call = self.get_object()
        if not can_access_recording(request.user, call):
            return Response({"detail": "Запись доступна ответственному сотруднику, руководителю и администратору"}, status=403)
        act = request.data.get("action", "play")
        url = signed_url(call.recording, request) if call.recording_id else call.record_url
        if not url:
            return Response({"detail": "Записи нет"}, status=404)
        audit(request.user, "Прослушал запись звонка" if act == "play" else "Скачал запись звонка", f"{call.client.name if call.client else call.phone} · {timezone.localtime(call.started_at):%d.%m %H:%M}", type="record", client_id=call.client_id)
        return Response({"url": url + ("&dl=1" if act == "download" and call.recording_id else "")})

    @action(detail=False, methods=["post"])
    def originate(self, request):
        """Click-to-call (п. 8.3)."""
        from apps.crm.models import Client
        from apps.crm.utils import normalize_phone

        phone = request.data.get("phone")
        if not phone:
            return Response({"detail": "Не указан номер"}, status=400)
        client = Client.objects.filter(id=request.data.get("client")).first() or Client.objects.filter(phone_norm=normalize_phone(phone)).first()
        res = telephony.originate(request.user, phone)
        call = Call.objects.create(external_id=res.get("call_id", ""), client=client, phone=phone, direction="out", status="ringing", user=request.user)
        audit(request.user, "Исходящий звонок", f"{client.name if client else phone}", client_id=client.id if client else None)
        return Response(CallSerializer(call, context={"request": request}).data, status=201)

    @action(detail=True, methods=["post"])
    def answer(self, request, pk=None):
        call = self.get_object()
        call.status, call.user, call.handled_by_ai = "answered", request.user, False
        call.save()
        telephony.transfer(call, request.user)
        broadcast("call.updated", {"id": call.id, "status": "answered", "by": request.user.id})
        return Response(CallSerializer(call, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="to-ai")
    def to_ai(self, request, pk=None):
        call = self.get_object()
        call.handled_by_ai = True
        call.status = "answered"
        call.save()
        broadcast("call.updated", {"id": call.id, "status": "answered", "ai": True})
        audit(request.user, "Передал звонок ассистенту", call.phone, client_id=call.client_id)
        return Response(CallSerializer(call, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        call = self.get_object()
        call.duration = int(request.data.get("duration") or (timezone.now() - call.started_at).total_seconds())
        if call.status == "ringing":
            call.status = "answered"
        call.save()
        from .callsummary import summarize_call

        summarize_call(call)
        return Response(CallSerializer(call, context={"request": request}).data)


# ---------- Симуляция для stage/приёмки без боевых каналов ----------

@api_view(["POST"])
@permission_classes([IsManagerPlus])
def simulate_inbound(request):
    ch = request.data.get("channel", "wa")
    if ch not in ("wa", "g", "meta"):
        return Response({"detail": "channel: wa | g | meta"}, status=400)
    conv = inbound(ch, name=request.data.get("name", ""), phone=request.data.get("phone", ""), email=request.data.get("email", ""), text=request.data.get("text", ""), campaign=request.data.get("campaign", ""), external_id="".join(c for c in request.data.get("phone", "") if c.isdigit()) if ch == "wa" else "")
    conv.refresh_from_db()
    return Response(ConversationSerializer(conv, context={"request": request}).data, status=201)


@api_view(["POST"])
@permission_classes([IsManagerPlus])
def simulate_call(request):
    from apps.crm.services import is_work_time

    phone = request.data.get("phone") or "+996 555 12 34 56"
    call = incoming_call(phone)
    if request.data.get("missed"):
        missed_call(call, not is_work_time())
    else:
        # в песочнице окно звонка показываем и инициатору
        broadcast("call.incoming", call_popup_payload(call), [request.user.id])
    return Response(CallSerializer(call, context={"request": request}).data, status=201)
