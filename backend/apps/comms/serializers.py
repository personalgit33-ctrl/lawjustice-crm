from rest_framework import serializers

from apps.crm.serializers import AttachmentSerializer
from apps.crm.utils import rel_label

from .models import Call, Conversation, Message

SOURCE_LABEL = {"wa": "WhatsApp · прямое обращение", "g": "Google · форма на сайте", "meta": "Meta Lead Ads", "ph": "Звонок", "manual": "Вручную"}


class MessageSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    attachment = AttachmentSerializer(read_only=True)

    class Meta:
        model = Message
        fields = ["id", "author", "author_name", "text", "attachment", "created_at", "delivery", "template", "rating"]

    def get_author_name(self, m):
        if m.author == "ai":
            return "Ассистент"
        if m.author in ("op", "note"):
            return str(m.user or "Сотрудник")
        if m.author == "client":
            return m.conversation.client.name
        return "Система"


class ConversationSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source="client.name", read_only=True)
    phone = serializers.CharField(source="client.phone", read_only=True)
    last_message = serializers.SerializerMethodField()
    last_at = serializers.DateTimeField(source="updated_at", read_only=True)
    last_label = serializers.SerializerMethodField()
    responsible_name = serializers.SerializerMethodField()
    wa_window_seconds = serializers.IntegerField(read_only=True)
    source_label = serializers.SerializerMethodField()
    consent_label = serializers.SerializerMethodField()
    consent_ok = serializers.SerializerMethodField()
    conflict_status = serializers.CharField(source="client.conflict_status", read_only=True)
    related = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id", "client", "client_name", "phone", "channel", "mode", "status", "unread", "urgent", "last_message", "last_at",
            "last_label", "responsible", "responsible_name", "wa_window_seconds", "source_label", "stage", "consent_label",
            "consent_ok", "conflict_status", "summary", "draft", "lead", "related",
        ]

    def get_last_message(self, c):
        m = c.messages.exclude(author="note").exclude(text="").order_by("-created_at", "-id").first()
        if not m:
            return ""
        return m.text[:140]

    def get_last_label(self, c):
        return rel_label(c.updated_at)

    def get_responsible_name(self, c):
        return str(c.responsible) if c.responsible else ""

    def get_source_label(self, c):
        if c.lead and c.lead.campaign:
            return f"{ {'g': 'Google Ads', 'meta': 'Instagram Lead Ads', 'wa': 'WhatsApp'}.get(c.channel, c.channel)} · «{c.lead.campaign}»"
        if c.channel == "ph" and c.messages.filter(text__startswith="Пропущенный").exists():
            return "Пропущенный звонок"
        return SOURCE_LABEL.get(c.channel, c.channel)

    def get_consent_label(self, c):
        cl = c.client
        if cl.consent_status == "given":
            return f"Получено {cl.consent_at:%d.%m}, {cl.consent_channel}" if cl.consent_at else "Получено"
        return "Отозвано" if cl.consent_status == "revoked" else "Не получено"

    def get_consent_ok(self, c):
        return c.client.consent_status == "given"

    def get_related(self, c):
        cards = c.client.cards.filter(is_archived=False).select_related("list__board")[:5]
        cases = c.client.cases.filter(is_confidential=False)[:5]
        return {
            "cards": [{"id": x.id, "title": x.title, "board_name": x.list.board.name, "board": x.list.board_id} for x in cards],
            "cases": [{"id": x.id, "number": x.number, "title": x.title} for x in cases],
            "calls": c.client.calls.count(),
            "files": c.attachments.count(),
        }


class ConversationDetailSerializer(ConversationSerializer):
    messages = MessageSerializer(many=True, read_only=True)

    class Meta(ConversationSerializer.Meta):
        fields = ConversationSerializer.Meta.fields + ["messages"]


class CallSerializer(serializers.ModelSerializer):
    client_name = serializers.SerializerMethodField()
    handled_by = serializers.SerializerMethodField()
    handled_by_name = serializers.SerializerMethodField()
    started_label = serializers.SerializerMethodField()
    has_recording = serializers.SerializerMethodField()
    is_confidential = serializers.SerializerMethodField()
    transcript = serializers.SerializerMethodField()

    class Meta:
        model = Call
        fields = ["id", "client", "client_name", "phone", "direction", "handled_by", "handled_by_name", "status", "started_at", "started_label", "duration", "has_recording", "summary", "transcript", "is_confidential"]

    def get_client_name(self, c):
        return c.client.name if c.client else c.phone

    def get_handled_by(self, c):
        return "ai" if c.handled_by_ai else ("user" if c.user_id else "none")

    def get_handled_by_name(self, c):
        return "Ассистент" if c.handled_by_ai else (str(c.user) if c.user else "—")

    def get_started_label(self, c):
        from django.utils import timezone

        lbl = rel_label(c.started_at)
        t = timezone.localtime(c.started_at).strftime("%H:%M")
        if lbl == t:
            return f"Сегодня, {t}"
        return f"{lbl}, {t}"

    def get_has_recording(self, c):
        return bool(c.recording_id or c.record_url)

    def get_is_confidential(self, c):
        return bool((c.case and c.case.is_confidential) or (c.client and c.client.cases.filter(is_confidential=True).exists()))

    def get_transcript(self, c):
        req = self.context.get("request")
        if self.get_is_confidential(c) and req and req.user.role not in ("manager",) and not (c.user_id == req.user.id):
            return []
        return c.transcript
