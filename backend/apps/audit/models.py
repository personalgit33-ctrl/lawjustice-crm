from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Журнал «кто, когда, что» (п. 5.9, 9.9, 12.8, 12.9)."""

    class Type(models.TextChoices):
        VIEW = "view", "Просмотр"
        EXPORT = "export", "Выгрузка"
        AI = "ai", "Ассистент"
        RECORD = "record", "Запись звонка"
        ACCESS = "access", "Права и доступ"
        CHANGE = "change", "Изменение"
        CHECK = "check", "Проверка"

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    actor_label = models.CharField(max_length=160, blank=True)
    is_ai = models.BooleanField(default=False)
    action = models.CharField(max_length=255)
    object_label = models.CharField(max_length=255, blank=True)
    type = models.CharField(max_length=16, choices=Type.choices, default=Type.CHANGE, db_index=True)
    # Для AI: инструмент, параметры, результат, источник; для отмены — undo
    payload = models.JSONField(default=dict, blank=True)
    undo = models.JSONField(null=True, blank=True)
    undone = models.BooleanField(default=False)
    # Привязки для хронологии
    client_id = models.IntegerField(null=True, blank=True, db_index=True)
    case_id = models.IntegerField(null=True, blank=True, db_index=True)
    card_id = models.IntegerField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=32)  # inbound, assign, mention, deadline, escalation, call_missed, handoff, status
    text = models.CharField(max_length=500)
    link = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    dedup_key = models.CharField(max_length=120, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
