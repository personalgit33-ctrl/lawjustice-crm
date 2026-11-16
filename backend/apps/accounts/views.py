import secrets

import pyotp
from django.contrib.auth import authenticate
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from apps.audit.services import audit

from .models import User
from .permissions import IsAdmin, IsManagerPlus


class UserSerializer(serializers.ModelSerializer):
    initials = serializers.CharField(read_only=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    has_2fa = serializers.BooleanField(source="totp_enabled", read_only=True)
    substitute_id = serializers.IntegerField(read_only=True)
    workload = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, min_length=8)

    class Meta:
        model = User
        fields = [
            "id", "username", "full_name", "initials", "role", "role_label", "specialization", "phone", "email",
            "is_active", "has_2fa", "substitute_id", "substitute_until", "workload", "password",
        ]
        read_only_fields = ["is_active", "substitute_until"]

    def get_workload(self, u):
        return u.cases_responsible.filter(is_archived=False).exclude(status__in=["done", "closed"]).count()

    def create(self, data):
        pwd = data.pop("password", None)
        u = User(**data)
        u.set_password(pwd or secrets.token_urlsafe(12))
        u.save()
        return u

    def update(self, u, data):
        pwd = data.pop("password", None)
        for k, v in data.items():
            setattr(u, k, v)
        if pwd:
            u.set_password(pwd)
        u.save()
        return u


class LoginThrottle(AnonRateThrottle):
    scope = "login"


def _tokens(user):
    r = RefreshToken.for_user(user)
    return {"access": str(r.access_token), "refresh": str(r), "user": UserSerializer(user).data}


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def login(request):
    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""
    otp = (request.data.get("otp") or "").strip()
    existing = User.objects.filter(username=username).first()
    if existing and existing.locked_until and existing.locked_until > timezone.now():
        return Response({"detail": "Вход временно заблокирован после неудачных попыток. Попробуйте через 15 минут."}, status=423)
    user = authenticate(request, username=username, password=password)
    if not user:
        if existing:
            existing.failed_logins += 1
            if existing.failed_logins >= 5:
                existing.locked_until = timezone.now() + timezone.timedelta(minutes=15)
                existing.failed_logins = 0
            existing.save(update_fields=["failed_logins", "locked_until"])
        return Response({"detail": "Неверный логин или пароль"}, status=401)
    if user.role == "ai":
        return Response({"detail": "Системная учётная запись"}, status=403)
    if user.totp_enabled:
        if not otp:
            return Response({"detail": "Введите код из приложения-аутентификатора", "otp_required": True}, status=401)
        if not pyotp.TOTP(user.totp_secret).verify(otp, valid_window=1):
            return Response({"detail": "Неверный код подтверждения", "otp_required": True}, status=401)
    user.failed_logins = 0
    user.last_login = timezone.now()
    user.save(update_fields=["failed_logins", "last_login"])
    audit(user, "Вход в систему", user.full_name, type="access")
    return Response(_tokens(user))


@api_view(["POST"])
@permission_classes([AllowAny])
def refresh(request):
    try:
        r = RefreshToken(request.data.get("refresh"))
        user = User.objects.get(id=r["user_id"])
        if not user.is_active:
            raise ValueError
        return Response({"access": str(r.access_token)})
    except Exception:
        return Response({"detail": "Сессия истекла, войдите снова"}, status=401)


@api_view(["GET"])
def me(request):
    return Response(UserSerializer(request.user).data)


@api_view(["POST"])
def twofa_setup(request):
    u = request.user
    u.totp_secret = pyotp.random_base32()
    u.totp_enabled = False
    u.save(update_fields=["totp_secret", "totp_enabled"])
    uri = pyotp.TOTP(u.totp_secret).provisioning_uri(name=u.username, issuer_name="Law & Justice CRM")
    return Response({"secret": u.totp_secret, "otpauth_url": uri})


@api_view(["POST"])
def twofa_enable(request):
    u = request.user
    if not u.totp_secret or not pyotp.TOTP(u.totp_secret).verify(str(request.data.get("otp", "")), valid_window=1):
        return Response({"detail": "Неверный код"}, status=400)
    u.totp_enabled = True
    u.save(update_fields=["totp_enabled"])
    audit(u, "Включил двухфакторную аутентификацию", u.full_name, type="access")
    return Response(UserSerializer(u).data)


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    http_method_names = ["get", "post", "patch"]

    def get_queryset(self):
        qs = User.objects.exclude(role="ai")
        if self.request.query_params.get("role"):
            qs = qs.filter(role=self.request.query_params["role"])
        return qs

    def get_permissions(self):
        if self.action in ("create", "partial_update", "update", "block"):
            return [IsAdmin()]
        if self.action == "substitute":
            return [IsManagerPlus()]
        return super().get_permissions()

    def perform_create(self, ser):
        u = ser.save()
        audit(self.request.user, f"Создал учётную запись ({u.get_role_display()})", u.full_name, type="access")

    def perform_update(self, ser):
        u = ser.save()
        audit(self.request.user, "Изменил учётную запись", u.full_name, type="access")

    @action(detail=True, methods=["post"])
    def block(self, request, pk=None):
        """Увольнение (п. 4.5): блокировка + передача всего другому сотруднику, история сохраняется."""
        from apps.boards.models import Card
        from apps.comms.models import Conversation
        from apps.crm.models import Case, Client, Contract, Deadline

        u = self.get_object()
        to = User.objects.filter(id=request.data.get("transfer_to"), is_active=True).exclude(id=u.id).first()
        if not to:
            return Response({"detail": "Выберите сотрудника, которому передать дела"}, status=400)
        with transaction.atomic():
            res = {
                "clients": Client.objects.filter(responsible=u).update(responsible=to),
                "cases": Case.objects.filter(responsible=u).update(responsible=to),
                "conversations": Conversation.objects.filter(responsible=u).update(responsible=to),
                "deadlines": Deadline.objects.filter(responsible=u).update(responsible=to)
                + Deadline.objects.filter(backup=u).update(backup=to),
                "contracts": Contract.objects.filter(responsible=u).update(responsible=to),
            }
            for c in Case.objects.filter(members=u):
                c.members.remove(u)
                c.members.add(to)
            cards = 0
            for card in Card.objects.filter(members=u):
                card.members.remove(u)
                card.members.add(to)
                cards += 1
            res["cards"] = cards
            u.is_active = False
            u.save(update_fields=["is_active"])
        audit(request.user, "Заблокировал учётную запись, передал дела", f"Сотрудник: {u.full_name} → {to.full_name}", type="access", payload=res)
        return Response({"transferred": res})

    @action(detail=True, methods=["post"])
    def substitute(self, request, pk=None):
        """Замещение (п. 4.4): доступ возвращается автоматически после until."""
        u = self.get_object()
        sid = request.data.get("substitute_id")
        if not sid:
            u.substitute, u.substitute_until = None, None
        else:
            sub = User.objects.filter(id=sid, is_active=True).exclude(id=u.id).first()
            if not sub:
                return Response({"detail": "Сотрудник не найден"}, status=400)
            until = serializers.DateTimeField().to_internal_value(request.data.get("until"))
            u.substitute, u.substitute_until = sub, until
        u.save(update_fields=["substitute", "substitute_until"])
        audit(request.user, "Назначил замещение" if sid else "Снял замещение", f"{u.full_name} → {u.substitute.full_name if u.substitute else '—'}", type="access")
        return Response(UserSerializer(u).data)
