from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import User
from apps.crm.serializers import AttachmentSerializer
from apps.crm.services import signed_url
from apps.crm.utils import due_label

from .models import Automation, Board, BoardList, Card, CardHistory, Checklist, ChecklistItem, Comment, Label


def card_due_state(c):
    if not c.due_at:
        return None
    if c.due_done:
        return "done"
    now = timezone.now()
    if c.due_at < now:
        return "late"
    if (c.due_at - now).total_seconds() < 36 * 3600:
        return "soon"
    return None


class LabelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Label
        fields = ["id", "board", "name", "color"]
        extra_kwargs = {"board": {"write_only": True}}


class CardSummarySerializer(serializers.ModelSerializer):
    labels = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    members = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    due_label = serializers.SerializerMethodField()
    due_state = serializers.SerializerMethodField()
    checklist = serializers.SerializerMethodField()
    attachments_count = serializers.SerializerMethodField()
    comments_count = serializers.SerializerMethodField()
    is_confidential = serializers.BooleanField(read_only=True)
    conflict_status = serializers.CharField(read_only=True)
    client_name = serializers.SerializerMethodField()
    cover_url = serializers.SerializerMethodField()
    board = serializers.IntegerField(source="list.board_id", read_only=True)
    board_name = serializers.CharField(source="list.board.name", read_only=True)
    list_name = serializers.CharField(source="list.name", read_only=True)

    class Meta:
        model = Card
        fields = [
            "id", "title", "list", "position", "labels", "members", "due_at", "due_label", "due_state", "checklist",
            "attachments_count", "comments_count", "is_confidential", "conflict_status", "source", "client_name",
            "cover_url", "ai_created", "priority", "board", "board_name", "list_name",
        ]

    def get_due_label(self, c):
        return due_label(c.due_at) if c.due_at else ""

    def get_due_state(self, c):
        return card_due_state(c)

    def get_checklist(self, c):
        items = [i for cl in c.checklists.all() for i in cl.items.all()]
        return [sum(1 for i in items if i.done), len(items)]

    def get_attachments_count(self, c):
        return c.attachments.count()

    def get_comments_count(self, c):
        return c.comments.count()

    def get_client_name(self, c):
        return c.client.name if c.client_id else ""

    def get_cover_url(self, c):
        return signed_url(c.cover, self.context.get("request")) if c.cover_id else None


class ChecklistItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChecklistItem
        fields = ["id", "checklist", "text", "done", "assignee", "due_at"]
        extra_kwargs = {"checklist": {"write_only": True}}


class ChecklistSerializer(serializers.ModelSerializer):
    items = ChecklistItemSerializer(many=True, read_only=True)

    class Meta:
        model = Checklist
        fields = ["id", "card", "title", "items"]
        extra_kwargs = {"card": {"write_only": True}}


class CommentSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    attachments = AttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Comment
        fields = ["id", "card", "author", "author_name", "is_ai", "text", "created_at", "attachments"]
        read_only_fields = ["author", "is_ai", "created_at"]
        extra_kwargs = {"card": {"write_only": True}}

    def get_author_name(self, c):
        return "Ассистент" if c.is_ai else (c.author_label or str(c.author or ""))


class HistorySerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = CardHistory
        fields = ["id", "actor_name", "is_ai", "text", "created_at"]

    def get_actor_name(self, h):
        return "Ассистент" if h.is_ai else str(h.actor or "Система")


class CardDetailSerializer(CardSummarySerializer):
    board = serializers.IntegerField(source="list.board_id", read_only=True)
    checklists = ChecklistSerializer(many=True, read_only=True)
    attachments = serializers.SerializerMethodField()
    comments = CommentSerializer(many=True, read_only=True)
    history = HistorySerializer(many=True, read_only=True)
    subscribed = serializers.SerializerMethodField()
    case_number = serializers.SerializerMethodField()
    opponent = serializers.SerializerMethodField()
    labels = serializers.PrimaryKeyRelatedField(many=True, queryset=Label.objects.all(), required=False)
    members = serializers.PrimaryKeyRelatedField(many=True, queryset=User.objects.all(), required=False)

    class Meta(CardSummarySerializer.Meta):
        fields = CardSummarySerializer.Meta.fields + [
            "description", "start_at", "client", "case", "case_number", "conversation", "opponent", "summary",
            "checklists", "attachments", "comments", "history", "subscribed", "is_archived", "conflict_check",
        ]
        read_only_fields = ["list", "position", "source", "ai_created", "is_archived", "conflict_check", "conversation"]

    def get_attachments(self, c):
        return AttachmentSerializer(c.attachments.filter(comment__isnull=True), many=True, context=self.context).data

    def get_subscribed(self, c):
        req = self.context.get("request")
        return bool(req and c.subscribers.filter(id=req.user.id).exists())

    def get_case_number(self, c):
        return c.case.number if c.case_id else ""

    def get_opponent(self, c):
        names = [p.name for p in c.parties.filter(role="opponent")]
        if not names and c.case_id:
            names = [p.name for p in c.case.parties.filter(role="opponent")]
        if not names and c.lead_id:
            names = [p.name for p in c.lead.parties.filter(role="opponent")]
        return ", ".join(names)

    def to_representation(self, c):
        data = super().to_representation(c)
        req = self.context.get("request")
        if req and c.case_id:
            from apps.accounts.permissions import case_restricted

            if case_restricted(req.user, c.case):
                data.update({"description": "", "summary": "", "checklists": [], "attachments": [], "comments": [], "history": [], "title": "Конфиденциальная карточка"})
        if c.is_confidential:
            data["summary"] = ""  # AI не обрабатывает конфиденциальные дела (п. 9.11.4)
        return data


class ListSerializer(serializers.ModelSerializer):
    cards = serializers.SerializerMethodField()

    class Meta:
        model = BoardList
        fields = ["id", "board", "name", "order", "wip_limit", "is_final", "blocks_on_conflict", "is_archived", "cards"]
        extra_kwargs = {"board": {"write_only": True}}

    def get_cards(self, l):
        cards = self.context.get("cards_by_list", {}).get(l.id)
        if cards is None:
            cards = l.cards.filter(is_archived=False)
        return CardSummarySerializer(cards, many=True, context=self.context).data


class AutomationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Automation
        fields = ["id", "board", "list", "action", "params", "is_active"]


class BoardShortSerializer(serializers.ModelSerializer):
    is_favorite = serializers.SerializerMethodField()
    cards_count = serializers.SerializerMethodField()

    class Meta:
        model = Board
        fields = ["id", "name", "color", "is_favorite", "is_archived", "cards_count", "access"]

    def get_is_favorite(self, b):
        req = self.context.get("request")
        return bool(req and b.favorites.filter(id=req.user.id).exists())

    def get_cards_count(self, b):
        return Card.objects.filter(list__board=b, is_archived=False).count()
