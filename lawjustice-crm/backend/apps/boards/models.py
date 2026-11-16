from django.conf import settings
from django.db import models
from django.utils import timezone

U = settings.AUTH_USER_MODEL


class Board(models.Model):
    ACCESS = [("all", "Все"), ("department", "Отдел"), ("selected", "Выбранные")]
    name = models.CharField(max_length=160)
    color = models.CharField(max_length=16, default="#2A47A1")
    is_archived = models.BooleanField(default=False)
    access = models.CharField(max_length=12, choices=ACCESS, default="all")
    allowed_users = models.ManyToManyField(U, blank=True, related_name="boards_allowed")
    favorites = models.ManyToManyField(U, blank=True, related_name="boards_favorite")
    template = models.CharField(max_length=32, blank=True)
    trello_id = models.CharField(max_length=64, blank=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.name


class BoardList(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="lists")
    name = models.CharField(max_length=160)
    order = models.IntegerField(default=0)
    wip_limit = models.PositiveIntegerField(null=True, blank=True)
    # Итоговая колонка: AI переносит сюда только с подтверждением; при конфликте интересов — блок
    is_final = models.BooleanField(default=False)
    blocks_on_conflict = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    trello_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["order", "id"]


class Label(models.Model):
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="labels")
    name = models.CharField(max_length=64, blank=True)
    color = models.CharField(max_length=16)


class Card(models.Model):
    PRIORITY = [("low", "Низкий"), ("normal", "Обычный"), ("high", "Высокий"), ("urgent", "Срочный")]
    list = models.ForeignKey(BoardList, on_delete=models.CASCADE, related_name="cards")
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    position = models.FloatField(default=0)
    labels = models.ManyToManyField(Label, blank=True, related_name="cards")
    members = models.ManyToManyField(U, blank=True, related_name="cards")
    subscribers = models.ManyToManyField(U, blank=True, related_name="cards_subscribed")
    due_at = models.DateTimeField(null=True, blank=True)
    start_at = models.DateTimeField(null=True, blank=True)
    due_done = models.BooleanField(default=False)
    priority = models.CharField(max_length=8, choices=PRIORITY, default="normal")
    client = models.ForeignKey("crm.Client", null=True, blank=True, on_delete=models.SET_NULL, related_name="cards")
    case = models.ForeignKey("crm.Case", null=True, blank=True, on_delete=models.SET_NULL, related_name="cards")
    lead = models.ForeignKey("comms.Lead", null=True, blank=True, on_delete=models.SET_NULL, related_name="cards")
    conversation = models.ForeignKey("comms.Conversation", null=True, blank=True, on_delete=models.SET_NULL, related_name="cards")
    conflict_check = models.ForeignKey("crm.ConflictCheck", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    source = models.CharField(max_length=10, blank=True)
    summary = models.TextField(blank=True)
    cover = models.ForeignKey("crm.Attachment", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    ai_created = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    trello_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.title

    @property
    def board(self):
        return self.list.board

    @property
    def is_confidential(self):
        return bool(self.case_id and self.case.is_confidential)

    @property
    def conflict_status(self):
        if self.conflict_check_id:
            st = self.conflict_check.status
            return {"pending": "hit", "ok": "ok", "cleared": "cleared", "refused": "refused"}[st]
        if self.client_id:
            return self.client.conflict_status
        return "none"


class Checklist(models.Model):
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="checklists")
    title = models.CharField(max_length=160, default="Чек-лист")
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]


class ChecklistItem(models.Model):
    checklist = models.ForeignKey(Checklist, on_delete=models.CASCADE, related_name="items")
    text = models.CharField(max_length=500)
    done = models.BooleanField(default=False)
    assignee = models.ForeignKey(U, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    due_at = models.DateTimeField(null=True, blank=True)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]


class Comment(models.Model):
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(U, null=True, blank=True, on_delete=models.SET_NULL)
    author_label = models.CharField(max_length=160, blank=True)  # для импорта Trello
    is_ai = models.BooleanField(default=False)
    text = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]


class CardHistory(models.Model):
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="history")
    actor = models.ForeignKey(U, null=True, blank=True, on_delete=models.SET_NULL)
    is_ai = models.BooleanField(default=False)
    text = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class Automation(models.Model):
    """Правило доски (п. 6.5): при переносе в колонку list выполнить action."""

    ACTIONS = [
        ("assign", "Назначить ответственного"),
        ("set_due_days", "Поставить срок"),
        ("add_checklist", "Добавить чек-лист"),
        ("notify", "Отправить уведомление"),
        ("set_case_status", "Изменить статус дела"),
    ]
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="automations")
    list = models.ForeignKey(BoardList, on_delete=models.CASCADE, related_name="automations")
    action = models.CharField(max_length=20, choices=ACTIONS)
    params = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
