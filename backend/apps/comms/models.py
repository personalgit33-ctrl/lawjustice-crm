from django.conf import settings
from django.db import models
from django.utils import timezone

U = settings.AUTH_USER_MODEL


class Lead(models.Model):
    STATUS = [("new", "Новый"), ("qualified", "Квалифицирован"), ("consultation", "Консультация"), ("contract", "Договор"), ("refused", "Отказ"), ("spam", "Спам")]
    client = models.ForeignKey("crm.Client", on_delete=models.CASCADE, related_name="leads")
    channel = models.CharField(max_length=10)
    campaign = models.CharField(max_length=255, blank=True)
    utm = models.JSONField(default=dict, blank=True)
    form_data = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=14, choices=STATUS, default="new")
    refusal_reason = models.CharField(max_length=120, blank=True)
    category = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)


class Conversation(models.Model):
    MODE = [("ai", "Ведёт ассистент"), ("draft", "Черновик"), ("op", "Ведёт сотрудник")]
    STATUS = [("new", "Новый"), ("ai", "У ассистента"), ("op", "У оператора"), ("waiting", "Ожидает клиента"), ("closed", "Закрыт")]
    client = models.ForeignKey("crm.Client", on_delete=models.CASCADE, related_name="conversations")
    lead = models.ForeignKey(Lead, null=True, blank=True, on_delete=models.SET_NULL, related_name="conversations")
    channel = models.CharField(max_length=10)
    external_id = models.CharField(max_length=120, blank=True, db_index=True)  # wa_id и т. п.
    mode = models.CharField(max_length=6, choices=MODE, default="ai")
    status = models.CharField(max_length=8, choices=STATUS, default="new")
    responsible = models.ForeignKey(U, null=True, blank=True, on_delete=models.SET_NULL, related_name="conversations")
    unread = models.PositiveIntegerField(default=0)
    urgent = models.BooleanField(default=False)
    stage = models.CharField(max_length=64, default="Новый лид")
    summary = models.TextField(blank=True)
    draft = models.TextField(blank=True)
    last_client_message_at = models.DateTimeField(null=True, blank=True)  # для 24-часового окна WhatsApp
    first_response_at = models.DateTimeField(null=True, blank=True)
    sla_alerted = models.BooleanField(default=False)
    close_result = models.CharField(max_length=16, blank=True)
    close_reason = models.CharField(max_length=120, blank=True)
    ai_state = models.JSONField(default=dict, blank=True)  # данные, собранные ассистентом
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-updated_at"]

    @property
    def wa_window_seconds(self):
        if self.channel != "wa":
            return None
        if not self.last_client_message_at:
            return 0
        left = (self.last_client_message_at + timezone.timedelta(hours=24) - timezone.now()).total_seconds()
        return max(0, int(left))


class Message(models.Model):
    AUTHOR = [("client", "Клиент"), ("ai", "Ассистент"), ("op", "Сотрудник"), ("sys", "Система"), ("note", "Заметка")]
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    author = models.CharField(max_length=6, choices=AUTHOR)
    user = models.ForeignKey(U, null=True, blank=True, on_delete=models.SET_NULL)
    text = models.TextField(blank=True)
    attachment = models.ForeignKey("crm.Attachment", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    external_id = models.CharField(max_length=160, blank=True, db_index=True)
    delivery = models.CharField(max_length=10, blank=True)
    template = models.BooleanField(default=False)
    rating = models.BooleanField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]

    def save(self, *args, **kwargs):
        # п. 9.14: сообщения не редактируются задним числом — разрешено менять только статус доставки и оценку
        if self.pk:
            old = Message.objects.filter(pk=self.pk).values("text", "author").first()
            if old and (old["text"] != self.text or old["author"] != self.author):
                raise ValueError("Сообщения нельзя редактировать")
        super().save(*args, **kwargs)


class Call(models.Model):
    DIR = [("in", "Входящий"), ("out", "Исходящий")]
    STATUS = [("ringing", "Звонит"), ("answered", "Отвечен"), ("missed", "Пропущен"), ("transferred", "Переведён")]
    external_id = models.CharField(max_length=120, blank=True, db_index=True)
    client = models.ForeignKey("crm.Client", null=True, blank=True, on_delete=models.SET_NULL, related_name="calls")
    lead = models.ForeignKey(Lead, null=True, blank=True, on_delete=models.SET_NULL, related_name="calls")
    case = models.ForeignKey("crm.Case", null=True, blank=True, on_delete=models.SET_NULL, related_name="calls")
    card = models.ForeignKey("boards.Card", null=True, blank=True, on_delete=models.SET_NULL, related_name="calls")
    phone = models.CharField(max_length=32)
    direction = models.CharField(max_length=3, choices=DIR)
    status = models.CharField(max_length=12, choices=STATUS, default="ringing")
    handled_by_ai = models.BooleanField(default=False)
    user = models.ForeignKey(U, null=True, blank=True, on_delete=models.SET_NULL, related_name="calls")
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    duration = models.PositiveIntegerField(default=0)
    record_url = models.URLField(blank=True)
    recording = models.ForeignKey("crm.Attachment", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    transcript = models.JSONField(default=list, blank=True)
    summary = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]


class WebhookEvent(models.Model):
    """Журнал входящих событий интеграций (п. 2.5) с повторной обработкой."""

    source = models.CharField(max_length=16)
    payload = models.JSONField()
    status = models.CharField(max_length=10, default="new")  # new, done, error
    error = models.TextField(blank=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
