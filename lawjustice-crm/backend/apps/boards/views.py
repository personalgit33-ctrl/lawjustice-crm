import re

from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.permissions import IsAdmin, IsManagerPlus, case_restricted, scope_boards, scope_cards
from apps.audit.services import audit, broadcast, notify
from apps.crm.models import Attachment, Party
from apps.crm.services import run_conflict_check

from .models import Automation, Board, BoardList, Card, Checklist, ChecklistItem, Comment, Label
from .serializers import (
    AutomationSerializer, BoardShortSerializer, CardDetailSerializer, CardSummarySerializer, ChecklistItemSerializer,
    ChecklistSerializer, CommentSerializer, LabelSerializer, ListSerializer,
)
from .services import MoveBlocked, create_board, create_card, history, import_trello, move_card

CARD_PREFETCH = ["labels", "members", "checklists__items", "attachments", "comments"]


def card_qs(user):
    return scope_cards(user, Card.objects.select_related("list", "list__board", "client", "case", "conflict_check", "cover").prefetch_related(*CARD_PREFETCH))


def board_payload(board, request):
    user = request.user
    cards = card_qs(user).filter(list__board=board, is_archived=False)
    p = request.query_params
    if p.get("member"):
        cards = cards.filter(members__id=p["member"])
    if p.get("label"):
        cards = cards.filter(labels__id=p["label"])
    if p.get("client"):
        cards = cards.filter(client_id=p["client"])
    if p.get("priority"):
        cards = cards.filter(priority=p["priority"])
    if p.get("q"):
        cards = cards.filter(Q(title__icontains=p["q"]) | Q(description__icontains=p["q"]) | Q(client__name__icontains=p["q"]))
    if p.get("due") == "late":
        cards = cards.filter(due_at__lt=timezone.now(), due_done=False)
    elif p.get("due") == "week":
        cards = cards.filter(due_at__lte=timezone.now() + timezone.timedelta(days=7), due_done=False)
    elif p.get("due") == "none":
        cards = cards.filter(due_at__isnull=True)
    by_list = {}
    for c in cards.distinct().order_by("position", "id"):
        by_list.setdefault(c.list_id, []).append(c)
    lists = board.lists.filter(is_archived=False)
    ctx = {"request": request, "cards_by_list": {l.id: by_list.get(l.id, []) for l in lists}}
    data = BoardShortSerializer(board, context=ctx).data
    data["lists"] = ListSerializer(lists, many=True, context=ctx).data
    data["labels"] = LabelSerializer(board.labels.all(), many=True).data
    data["automations"] = AutomationSerializer(board.automations.all(), many=True).data
    return data


class BoardViewSet(viewsets.ModelViewSet):
    serializer_class = BoardShortSerializer
    http_method_names = ["get", "post", "patch"]

    def get_queryset(self):
        qs = scope_boards(self.request.user, Board.objects.all())
        return qs.filter(is_archived=bool(self.request.query_params.get("archived")))

    def get_object(self):
        b = get_object_or_404(scope_boards(self.request.user, Board.objects.all()), pk=self.kwargs["pk"])
        return b

    def retrieve(self, request, *args, **kwargs):
        return Response(board_payload(self.get_object(), request))

    def create(self, request, *args, **kwargs):
        b = create_board(request.data.get("name"), request.data.get("template") or "blank", request.data.get("color") or "#2A47A1")
        audit(request.user, "Создал доску", b.name)
        broadcast("board.updated", {"id": b.id})
        return Response(board_payload(b, request), status=201)

    def partial_update(self, request, *args, **kwargs):
        b = self.get_object()
        if "is_favorite" in request.data:
            (b.favorites.add if request.data["is_favorite"] else b.favorites.remove)(request.user)
        for f in ("name", "color", "is_archived", "access"):
            if f in request.data:
                if f != "name" and request.user.role not in ("admin", "manager"):
                    continue
                setattr(b, f, request.data[f])
        b.save()
        if "allowed_users" in request.data and request.user.role in ("admin", "manager"):
            b.allowed_users.set(request.data["allowed_users"])
        broadcast("board.updated", {"id": b.id})
        return Response(BoardShortSerializer(b, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def copy(self, request, pk=None):
        src = self.get_object()
        b = Board.objects.create(name=f"{src.name} (копия)", color=src.color, template=src.template)
        lmap = {}
        for lb in src.labels.all():
            lmap[lb.id] = Label.objects.create(board=b, name=lb.name, color=lb.color)
        for l in src.lists.filter(is_archived=False):
            nl = BoardList.objects.create(board=b, name=l.name, order=l.order, wip_limit=l.wip_limit, is_final=l.is_final, blocks_on_conflict=l.blocks_on_conflict)
            if request.data.get("with_cards", True):
                for c in l.cards.filter(is_archived=False):
                    _copy_card(c, nl, request.user, lmap)
        audit(request.user, "Скопировал доску", src.name)
        return Response(board_payload(b, request), status=201)

    @action(detail=False, methods=["post"], url_path="import-trello", permission_classes=[IsManagerPlus])
    def import_trello(self, request):
        f = request.FILES.get("file")
        if not f:
            return Response({"detail": "Загрузите JSON-экспорт Trello"}, status=400)
        try:
            rep = import_trello(f.read(), request.user)
        except (ValueError, KeyError) as e:
            return Response({"detail": f"Не удалось разобрать файл Trello: {e}"}, status=400)
        broadcast("board.updated", {})
        return Response(rep)


def _copy_card(c, target, user, lmap=None):
    n = Card.objects.create(list=target, title=c.title, description=c.description, position=c.position, due_at=c.due_at, priority=c.priority, client=c.client, case=c.case, source=c.source)
    n.members.set(c.members.all())
    n.labels.set([lmap[l.id] for l in c.labels.all()] if lmap else c.labels.all())
    for cl in c.checklists.all():
        ncl = Checklist.objects.create(card=n, title=cl.title, order=cl.order)
        for it in cl.items.all():
            ChecklistItem.objects.create(checklist=ncl, text=it.text, done=False, order=it.order, assignee=it.assignee)
    history(n, user, f"скопировал(а) из «{c.title}»")
    return n


class ListViewSet(mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = ListSerializer
    queryset = BoardList.objects.all()
    http_method_names = ["post", "patch"]

    def perform_create(self, ser):
        b = ser.validated_data["board"]
        l = ser.save(order=b.lists.count())
        broadcast("board.updated", {"id": b.id})

    def perform_update(self, ser):
        l = ser.save()
        broadcast("board.updated", {"id": l.board_id})

    @action(detail=False, methods=["post"])
    def reorder(self, request):
        ids = request.data.get("ids") or []
        for i, lid in enumerate(ids):
            BoardList.objects.filter(id=lid, board_id=request.data.get("board")).update(order=i)
        broadcast("board.updated", {"id": request.data.get("board")})
        return Response({"ok": True})


class CardViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = CardDetailSerializer
    http_method_names = ["get", "post", "patch"]

    def get_queryset(self):
        return card_qs(self.request.user)

    def create(self, request, *args, **kwargs):
        from apps.comms.models import Conversation
        from apps.crm.models import Case, Client

        lst = get_object_or_404(BoardList.objects.filter(board__in=scope_boards(request.user, Board.objects.all())), id=request.data.get("list"))
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"detail": "Введите название"}, status=400)
        fields = {}
        if request.data.get("client"):
            fields["client"] = get_object_or_404(Client, id=request.data["client"])
        if request.data.get("case"):
            fields["case"] = get_object_or_404(Case, id=request.data["case"])
            fields.setdefault("client", fields["case"].client)
        if request.data.get("conversation"):
            conv = get_object_or_404(Conversation, id=request.data["conversation"])
            fields.update(conversation=conv, client=conv.client, source=conv.channel, lead=conv.lead)
        card = create_card(lst, title, request.user, top=bool(request.data.get("top")), **fields)
        if request.user.role in ("lawyer", "operator"):
            card.members.add(request.user)
        if card.client_id:
            card.conflict_check = _client_check(card, request.user)
            card.save(update_fields=["conflict_check"])
        return Response(CardDetailSerializer(card, context={"request": request}).data, status=201)

    def retrieve(self, request, *args, **kwargs):
        card = self.get_object()
        if card.is_confidential:
            audit(request.user, "Открыл карточку (конфиденциальное дело)", card.title, type="view", card_id=card.id, case_id=card.case_id)
        return Response(self.get_serializer(card).data)

    def partial_update(self, request, *args, **kwargs):
        card = self.get_object()
        if card.case_id and case_restricted(request.user, card.case):
            raise PermissionDenied("Нет доступа к материалам конфиденциального дела")
        before_members = set(card.members.values_list("id", flat=True))
        ser = self.get_serializer(card, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        card = ser.save()
        changed = [k for k in request.data.keys()]
        names = {"title": "название", "description": "описание", "due_at": "срок", "start_at": "дату начала", "priority": "приоритет", "labels": "метки", "members": "участников", "client": "клиента", "case": "дело", "due_done": "отметку срока"}
        history(card, request.user, "изменил(а) " + ", ".join(names.get(k, k) for k in changed))
        if "due_done" in request.data:
            Card.objects.filter(id=card.id).update(due_done=bool(request.data["due_done"]))
        if "members" in request.data:
            added = set(card.members.values_list("id", flat=True)) - before_members
            new_users = [u for u in User.objects.filter(id__in=added) if u != request.user]
            if new_users:
                notify(new_users, "assign", f"Вас добавили в карточку «{card.title}»", f"/boards?board={card.list.board_id}&card={card.id}")
                card.subscribers.add(*new_users)
        if "client" in request.data and card.client_id:
            card.conflict_check = _client_check(card, request.user)
            card.save(update_fields=["conflict_check"])
        broadcast("card.updated", {"id": card.id, "board": card.list.board_id})
        card.refresh_from_db()
        return Response(CardDetailSerializer(card, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        card = self.get_object()
        target = get_object_or_404(BoardList.objects.filter(board__in=scope_boards(request.user, Board.objects.all())), id=request.data.get("list"))
        try:
            move_card(card, target, request.user, request.data.get("position"))
        except MoveBlocked as e:
            return Response({"detail": str(e)}, status=409)
        card.refresh_from_db()
        return Response(CardDetailSerializer(card, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def copy(self, request, pk=None):
        card = self.get_object()
        target = BoardList.objects.filter(id=request.data.get("list")).first() or card.list
        n = _copy_card(card, target, request.user)
        broadcast("card.created", {"id": n.id, "board": target.board_id, "list": target.id})
        return Response(CardDetailSerializer(n, context={"request": request}).data, status=201)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        card = self.get_object()
        card.is_archived = True
        card.save(update_fields=["is_archived"])
        history(card, request.user, "архивировал(а) карточку")
        broadcast("card.updated", {"id": card.id, "board": card.list.board_id, "archived": True})
        return Response(CardDetailSerializer(card, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        card = get_object_or_404(scope_cards(request.user, Card.objects.all()), pk=pk)
        card.is_archived = False
        card.save(update_fields=["is_archived"])
        history(card, request.user, "восстановил(а) карточку")
        broadcast("card.updated", {"id": card.id, "board": card.list.board_id})
        return Response(CardDetailSerializer(card, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def subscribe(self, request, pk=None):
        card = self.get_object()
        if card.subscribers.filter(id=request.user.id).exists():
            card.subscribers.remove(request.user)
        else:
            card.subscribers.add(request.user)
        return Response(CardDetailSerializer(card, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def cover(self, request, pk=None):
        card = self.get_object()
        att = Attachment.objects.filter(id=request.data.get("attachment"), card=card).first()
        card.cover = att if att and att.is_image else None
        card.save(update_fields=["cover"])
        broadcast("card.updated", {"id": card.id, "board": card.list.board_id})
        return Response(CardDetailSerializer(card, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def opponent(self, request, pk=None):
        """Добавить противную сторону в карточку лида → повторная проверка конфликта."""
        card = self.get_object()
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"detail": "Укажите противную сторону"}, status=400)
        Party.objects.create(card=card, role="opponent", name=name, pin=request.data.get("pin", ""), phone=request.data.get("phone", ""))
        card.conflict_check = _client_check(card, request.user)
        card.save(update_fields=["conflict_check"])
        history(card, request.user, f"добавил(а) противную сторону «{name}»")
        return Response(CardDetailSerializer(card, context={"request": request}).data)

    @action(detail=False)
    def search(self, request):
        q = request.query_params.get("q", "").strip()
        if not q:
            return Response([])
        qs = card_qs(request.user).filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(client__name__icontains=q)).filter(is_archived=False)[:50]
        return Response(CardSummarySerializer(qs, many=True, context={"request": request}).data)


def _client_check(card, user):
    people = [{"name": card.client.name, "pin": card.client.pin, "phone": card.client.phone}]
    people += [{"name": p.name, "pin": p.pin, "phone": p.phone} for p in card.parties.filter(role="opponent")]
    exclude = {"exclude_client_id": card.client_id, "exclude_card_id": card.id}
    if card.lead_id:
        exclude["exclude_lead_id"] = card.lead_id
    if card.case_id:
        exclude["exclude_case_id"] = card.case_id
    return run_conflict_check("card", card, people, user, f"Карточка «{card.title}»", exclude=exclude)


class ChecklistViewSet(mixins.CreateModelMixin, mixins.DestroyModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = ChecklistSerializer
    http_method_names = ["post", "patch", "delete"]

    def get_queryset(self):
        return Checklist.objects.filter(card__in=card_qs(self.request.user))

    def perform_create(self, ser):
        card = ser.validated_data["card"]
        if not card_qs(self.request.user).filter(id=card.id).exists():
            raise PermissionDenied()
        cl = ser.save(order=card.checklists.count())
        for i, t in enumerate(self.request.data.get("items") or []):
            ChecklistItem.objects.create(checklist=cl, text=t, order=i)
        history(card, self.request.user, f"добавил(а) чек-лист «{cl.title}»")
        broadcast("card.updated", {"id": card.id, "board": card.list.board_id})

    def perform_destroy(self, cl):
        history(cl.card, self.request.user, f"удалил(а) чек-лист «{cl.title}»")
        broadcast("card.updated", {"id": cl.card_id, "board": cl.card.list.board_id})
        cl.delete()


class ChecklistItemViewSet(mixins.CreateModelMixin, mixins.DestroyModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = ChecklistItemSerializer
    http_method_names = ["post", "patch", "delete"]

    def get_queryset(self):
        return ChecklistItem.objects.filter(checklist__card__in=card_qs(self.request.user))

    def perform_create(self, ser):
        cl = ser.validated_data["checklist"]
        it = ser.save(order=cl.items.count())
        broadcast("card.updated", {"id": cl.card_id, "board": cl.card.list.board_id})

    def perform_update(self, ser):
        it = ser.save()
        card = it.checklist.card
        if "done" in self.request.data:
            history(card, self.request.user, f"{'отметил(а)' if it.done else 'снял(а) отметку'}: «{it.text}»")
        if it.assignee and "assignee" in self.request.data and it.assignee != self.request.user:
            notify([it.assignee], "assign", f"Вам назначен пункт «{it.text}» в карточке «{card.title}»", f"/boards?board={card.list.board_id}&card={card.id}")
        broadcast("card.updated", {"id": card.id, "board": card.list.board_id})

    def perform_destroy(self, it):
        card = it.checklist.card
        it.delete()
        broadcast("card.updated", {"id": card.id, "board": card.list.board_id})


class CommentViewSet(mixins.CreateModelMixin, viewsets.GenericViewSet):
    serializer_class = CommentSerializer
    queryset = Comment.objects.all()

    def perform_create(self, ser):
        card = ser.validated_data["card"]
        if not card_qs(self.request.user).filter(id=card.id).exists() or (card.case_id and case_restricted(self.request.user, card.case)):
            raise PermissionDenied()
        com = ser.save(author=self.request.user)
        for aid in self.request.data.get("attachments") or []:
            Attachment.objects.filter(id=aid, uploaded_by=self.request.user).update(comment=com, card=card)
        history(card, self.request.user, "добавил(а) комментарий")
        mentions = set(re.findall(r"@([\w.\-]+)", com.text))
        users = list(User.objects.filter(username__in=mentions, is_active=True).exclude(id=self.request.user.id))
        if users:
            notify(users, "mention", f"{self.request.user} упомянул(а) вас: «{com.text[:120]}»", f"/boards?board={card.list.board_id}&card={card.id}", email=True)
        subs = [u for u in card.subscribers.all() if u != self.request.user and u not in users]
        if subs:
            notify(subs, "comment", f"Новый комментарий в «{card.title}»", f"/boards?board={card.list.board_id}&card={card.id}")
        broadcast("card.updated", {"id": card.id, "board": card.list.board_id})


class LabelViewSet(mixins.CreateModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = LabelSerializer
    queryset = Label.objects.all()
    http_method_names = ["post", "patch", "delete"]


class AutomationViewSet(viewsets.ModelViewSet):
    serializer_class = AutomationSerializer
    http_method_names = ["get", "post", "patch", "delete"]

    def get_permissions(self):
        return [IsAdmin()] if self.action not in ("list", "retrieve") else super().get_permissions()

    def get_queryset(self):
        qs = Automation.objects.all()
        if self.request.query_params.get("board"):
            qs = qs.filter(board_id=self.request.query_params["board"])
        return qs

    def perform_create(self, ser):
        a = ser.save()
        audit(self.request.user, "Создал правило доски", f"{a.board.name}: «{a.list.name}» → {a.get_action_display()}", type="access")
