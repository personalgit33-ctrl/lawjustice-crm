from django.conf import settings
from django.db import models
from django.utils import timezone

U = settings.AUTH_USER_MODEL


class DictItem(models.Model):
    """Справочники (п. 5.11): категории, статусы дел, источники, теги, причины отказа, шаблоны сроков, быстрые ответы."""

    KINDS = [
        ("case_category", "Категория дела"),
        ("case_status", "Статус дела"),
        ("source", "Источник"),
        ("tag", "Тег"),
        ("refusal_reason", "Причина отказа"),
        ("deadline_template", "Шаблон срока"),
        ("quick_reply", "Быстрый ответ"),
    ]
    kind = models.CharField(max_length=32, choices=KINDS, db_index=True)
    code = models.CharField(max_length=64, blank=True)
    name = models.CharField(max_length=255)
    order = models.IntegerField(default=0)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["kind", "order", "id"]

    @classmethod
    def status_label(cls, code):
        item = cls.objects.filter(kind="case_status", code=code).first()
        return item.name if item else code


class AppSetting(models.Model):
    """Настройки системы — один JSON-документ (ключ "main")."""

    key = models.CharField(max_length=32, unique=True)
    value = models.JSONField(default=dict)


class Client(models.Model):
    KIND = [("person", "Физлицо"), ("company", "Юрлицо")]
    CONSENT = [("none", "Не получено"), ("given", "Получено"), ("revoked", "Отозвано")]
    kind = models.CharField(max_length=10, choices=KIND, default="person")
    name = models.CharField(max_length=255, db_index=True)
    city = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=32, blank=True, db_index=True)
    phone_norm = models.CharField(max_length=20, blank=True, db_index=True)
    email = models.EmailField(blank=True, db_index=True)
    pin = models.CharField(max_length=32, blank=True, db_index=True)
    # Реквизиты юрлица / доп. поля физлица
    requisites = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=10, default="manual")
    campaign = models.CharField(max_length=255, blank=True)
    utm = models.JSONField(default=dict, blank=True)
    responsible = models.ForeignKey(U, null=True, blank=True, on_delete=models.SET_NULL, related_name="clients")
    notes = models.TextField(blank=True)
    consent_status = models.CharField(max_length=10, choices=CONSENT, default="none")
    consent_at = models.DateTimeField(null=True, blank=True)
    consent_channel = models.CharField(max_length=64, blank=True)
    consent_text = models.TextField(blank=True)
    conflict_status = models.CharField(max_length=10, default="none")
    last_contact_at = models.DateTimeField(null=True, blank=True)
    last_contact_channel = models.CharField(max_length=32, blank=True)
    merged_into = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-last_contact_at", "-id"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        from .utils import normalize_phone

        self.phone_norm = normalize_phone(self.phone)
        super().save(*args, **kwargs)


class Case(models.Model):
    number = models.CharField(max_length=32, unique=True)
    title = models.CharField(max_length=255)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="cases")
    category = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=32, default="new")
    responsible = models.ForeignKey(U, null=True, blank=True, on_delete=models.SET_NULL, related_name="cases_responsible")
    members = models.ManyToManyField(U, blank=True, related_name="cases_member")
    court = models.CharField(max_length=255, blank=True)
    is_confidential = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    conflict_status = models.CharField(max_length=10, default="none")
    fee = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-number"]

    def __str__(self):
        return f"№ {self.number} · {self.title}"

    @classmethod
    def next_number(cls):
        year = timezone.localdate().year
        last = cls.objects.filter(number__startswith=f"{year}-").order_by("-number").first()
        n = int(last.number.split("-")[1]) + 1 if last else 1
        return f"{year}-{n:03d}"


class Party(models.Model):
    ROLES = [("client", "Клиент"), ("opponent", "Противная сторона"), ("third", "Третье лицо")]
    case = models.ForeignKey(Case, null=True, blank=True, on_delete=models.CASCADE, related_name="parties")
    lead = models.ForeignKey("comms.Lead", null=True, blank=True, on_delete=models.CASCADE, related_name="parties")
    card = models.ForeignKey("boards.Card", null=True, blank=True, on_delete=models.CASCADE, related_name="parties")
    role = models.CharField(max_length=10, choices=ROLES)
    name = models.CharField(max_length=255, db_index=True)
    name_norm = models.CharField(max_length=255, blank=True, db_index=True)
    pin = models.CharField(max_length=32, blank=True, db_index=True)
    phone = models.CharField(max_length=32, blank=True)
    phone_norm = models.CharField(max_length=20, blank=True, db_index=True)
    imported = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        from .utils import normalize_name, normalize_phone

        self.name_norm = normalize_name(self.name)
        self.phone_norm = normalize_phone(self.phone)
        super().save(*args, **kwargs)


class ConflictCheck(models.Model):
    STATUS = [("ok", "Совпадений нет"), ("pending", "Ожидает решения"), ("cleared", "Конфликта нет"), ("refused", "Отказ клиенту")]
    subject_type = models.CharField(max_length=10, default="manual")
    subject_id = models.IntegerField(null=True, blank=True)
    subject_label = models.CharField(max_length=255, blank=True)
    source_label = models.CharField(max_length=255, blank=True)
    query = models.JSONField(default=dict)
    matches = models.JSONField(default=list)
    status = models.CharField(max_length=10, choices=STATUS, default="ok")
    decision_comment = models.TextField(blank=True)
    decided_by = models.ForeignKey(U, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(U, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Deadline(models.Model):
    TYPES = [
        ("hearing", "Заседание"),
        ("procedural", "Процессуальный"),
        ("execution", "Срок исполнения"),
        ("contract", "Договорный"),
        ("internal", "Внутренний"),
    ]
    title = models.CharField(max_length=255)
    type = models.CharField(max_length=12, choices=TYPES, default="procedural")
    case = models.ForeignKey(Case, null=True, blank=True, on_delete=models.CASCADE, related_name="deadlines")
    card = models.ForeignKey("boards.Card", null=True, blank=True, on_delete=models.SET_NULL, related_name="deadlines")
    due_at = models.DateTimeField(db_index=True)
    court = models.CharField(max_length=255, blank=True)
    judge = models.CharField(max_length=160, blank=True)
    room = models.CharField(max_length=32, blank=True)
    responsible = models.ForeignKey(U, null=True, blank=True, on_delete=models.SET_NULL, related_name="deadlines")
    backup = models.ForeignKey(U, null=True, blank=True, on_delete=models.SET_NULL, related_name="deadlines_backup")
    basis = models.CharField(max_length=255, blank=True)
    done_at = models.DateTimeField(null=True, blank=True)
    done_by = models.ForeignKey(U, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    done_file = models.ForeignKey("crm.Attachment", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reminders_sent = models.JSONField(default=list, blank=True)
    escalated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_at"]

    @property
    def state(self):
        if self.done_at:
            return "done"
        now = timezone.localtime()
        due = timezone.localtime(self.due_at)
        if due < now:
            return "late"
        if due.date() == now.date():
            return "today"
        if (due.date() - now.date()).days <= 7:
            return "week"
        return "later"


class CalendarEvent(models.Model):
    KINDS = [("hearing", "Заседание"), ("consultation", "Консультация"), ("meeting", "Встреча")]
    title = models.CharField(max_length=255)
    kind = models.CharField(max_length=16, choices=KINDS, default="meeting")
    start = models.DateTimeField(db_index=True)
    end = models.DateTimeField(null=True, blank=True)
    case = models.ForeignKey(Case, null=True, blank=True, on_delete=models.CASCADE, related_name="events")
    client = models.ForeignKey(Client, null=True, blank=True, on_delete=models.CASCADE, related_name="events")
    card = models.ForeignKey("boards.Card", null=True, blank=True, on_delete=models.SET_NULL, related_name="events")
    user = models.ForeignKey(U, null=True, blank=True, on_delete=models.SET_NULL, related_name="events")
    created_by_ai = models.BooleanField(default=False)


class Contract(models.Model):
    STATUS = [("none", "Не заключён"), ("sent", "Отправлен"), ("signed", "Подписан")]
    MODEL = [("fixed", "Фикс"), ("staged", "Поэтапно"), ("subscription", "Абонентская")]
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="contracts")
    case = models.ForeignKey(Case, null=True, blank=True, on_delete=models.SET_NULL, related_name="contracts")
    status = models.CharField(max_length=8, choices=STATUS, default="none")
    model = models.CharField(max_length=14, choices=MODEL, default="fixed")
    fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    responsible = models.ForeignKey(U, null=True, blank=True, on_delete=models.SET_NULL, related_name="contracts")
    signed_at = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Payment(models.Model):
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="payments")
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    paid_at = models.DateField(null=True, blank=True)
    reminded = models.BooleanField(default=False)

    class Meta:
        ordering = ["due_date"]


class AdSpend(models.Model):
    month = models.CharField(max_length=7)  # YYYY-MM
    channel = models.CharField(max_length=10)
    campaign = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        unique_together = ("month", "channel", "campaign")


class Attachment(models.Model):
    """Файл (п. 10). Хранится локально или в S3 — см. storage.py. Версии по делу — через parent."""

    file = models.FileField(upload_to="files/%Y/%m/")
    name = models.CharField(max_length=255)
    size = models.BigIntegerField(default=0)
    mime = models.CharField(max_length=120, blank=True)
    uploaded_by = models.ForeignKey(U, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    card = models.ForeignKey("boards.Card", null=True, blank=True, on_delete=models.CASCADE, related_name="attachments")
    case = models.ForeignKey(Case, null=True, blank=True, on_delete=models.CASCADE, related_name="attachments")
    client = models.ForeignKey(Client, null=True, blank=True, on_delete=models.CASCADE, related_name="attachments")
    conversation = models.ForeignKey("comms.Conversation", null=True, blank=True, on_delete=models.CASCADE, related_name="attachments")
    comment = models.ForeignKey("boards.Comment", null=True, blank=True, on_delete=models.CASCADE, related_name="attachments")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="versions")

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_image(self):
        return self.mime.startswith("image/")
