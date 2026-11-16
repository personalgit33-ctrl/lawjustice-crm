from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Администратор"
        MANAGER = "manager", "Руководитель"
        LAWYER = "lawyer", "Юрист"
        OPERATOR = "operator", "Оператор"
        AI = "ai", "Ассистент"

    role = models.CharField(max_length=16, choices=Role.choices, default=Role.LAWYER)
    full_name = models.CharField(max_length=160, blank=True)
    specialization = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    totp_secret = models.CharField(max_length=64, blank=True)
    totp_enabled = models.BooleanField(default=False)
    totp_last_step = models.BigIntegerField(default=0)  # защита от повторного использования кода
    recovery_codes = models.JSONField(default=list, blank=True)  # sha256-хэши одноразовых резервных кодов
    # Замещение (п. 4.4): пока substitute_until не прошло, substitute видит зону ответственности этого сотрудника
    substitute = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="substituting")
    substitute_until = models.DateTimeField(null=True, blank=True)
    failed_logins = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name or self.username

    @property
    def initials(self):
        parts = [p for p in (self.full_name or self.username).split() if p]
        return "".join(p[0] for p in parts[:2]).upper()

    @property
    def is_manager_plus(self):
        return self.role in (self.Role.ADMIN, self.Role.MANAGER)

    def represented_ids(self):
        """id сотрудников, чью зону видит пользователь: он сам + те, кого он сейчас замещает."""
        now = timezone.now()
        ids = [self.id]
        ids += list(
            User.objects.filter(substitute=self, substitute_until__gt=now).values_list("id", flat=True)
        )
        return ids

    @classmethod
    def ai_user(cls):
        user, _ = cls.objects.get_or_create(
            username="assistant",
            defaults={"full_name": "Ассистент", "role": cls.Role.AI, "is_active": False},
        )
        return user
