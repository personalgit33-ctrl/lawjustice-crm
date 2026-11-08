from django.conf import settings
from django.db import models


class AssistantRun(models.Model):
    """Команда AI-ассистенту администратора (п. 9.5): план шагов, подтверждение, результат."""

    STATE = [("done", "Выполнено"), ("awaiting_confirm", "Ждёт подтверждения"), ("cancelled", "Отменено"), ("denied", "Запрещено")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assistant_runs")
    command = models.TextField()
    steps = models.JSONField(default=list)
    pending = models.JSONField(default=list)  # вызовы инструментов, ждущие подтверждения
    result = models.TextField(blank=True)
    state = models.CharField(max_length=18, choices=STATE, default="done")
    engine = models.CharField(max_length=8, default="rules")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
