import secrets

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

from . import mfa
from .models import User
from .permissions import IsAdmin, IsManagerPlus


class UserSerializer(serializers.ModelSerializer):
    initials = serializers.CharField(read_only=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    has_2fa = serializers.BooleanField(source="totp_enabled", read_only=True)
    twofa_required = serializers.SerializerMethodField()
    recovery_left = serializers.SerializerMethodField()
    substitute_id = serializers.IntegerField(read_only=True)
    workload = serializers.SerializerMethodField()
    password = serializers.CharField(write_only=True, required=False, min_length=8)

    class Meta:
        model = User
        fields = [
            "id", "username", "full_name", "initials", "role", "role_label", "specialization", "phone", "email",
            "is_active", "has_2fa", "twofa_required", "recovery_left", "substitute_id", "substitute_until", "workload", "password",
        ]
        read_only_fields = ["is_active", "substitute_until"]

    def get_twofa_required(self, u):
        return mfa.is_mandatory(u)

    def get_recovery_left(self, u):
        return len(u.recovery_codes or [])

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


def _locked(user):
    return bool(user and user.locked_until and user.locked_until > timezone.now())


LOCKED = {"detail": "Вход временно заблокирован после неудачных попыток. Попробуйте через 15 минут."}


def _fail(user):
    """Неудачная попытка (пароль или код): после 5 подряд — блокировка на 15 минут."""
    if not user:
        return
    user.failed_logins += 1
    if user.failed_logins >= 5:
        user.locked_until = timezone.now() + timezone.timedelta(minutes=15)
        user.failed_logins = 0
        audit(user, "Вход заблокирован на 15 минут после 5 неудачных попыток", user.full_name, type="access")
    user.save(update_fields=["failed_logins", "locked_until"])


def _success(user, request, via=""):
    user.failed_logins = 0
    user.last_login = timezone.now()
    user.save(update_fields=["failed_logins", "last_login"])
    audit(user, "Вход в систему" + (f" ({via})" if via else ""), user.full_name, type="access")
    return Response(_tokens(user))


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def login(request):
    """Шаг 1: логин + пароль."""
    username = (request.data.get("username") or "").strip()
    password = request.data.get("password") or ""
    existing = User.objects.filter(username=username).first()
    if _locked(existing):
        return Response(LOCKED, status=423)
    user = authenticate(request, username=username, password=password)
    if not user:
        _fail(existing)
        return Response({"detail": "Неверный логин или пароль"}, status=401)
    if user.role == "ai":
        return Response({"detail": "Системная учётная запись"}, status=403)
    if user.totp_enabled:
        otp = (request.data.get("otp") or "").strip()
        if otp:  # совместимость: код в том же запросе
            via = mfa.verify_any(user, otp)
            if not via:
                _fail(user)
                return Response({"detail": "Неверный код подтверждения", "otp_required": True, "mfa_token": mfa.make_token(user, "otp")}, status=401)
            return _success(user, request, "2FA" if via == "totp" else "резервный код")
        return Response({"detail": "Введите код из приложения-аутентификатора", "otp_required": True, "mfa_token": mfa.make_token(user, "otp")}, status=401)
    if mfa.is_mandatory(user):
        return Response({
            "detail": f"Для роли «{user.get_role_display()}» обязателен двухфакторный вход. Настройте его, чтобы продолжить.",
            "setup_required": True, "mfa_token": mfa.make_token(user, "setup"),
        }, status=403)
    return _success(user, request)


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def login_verify(request):
    """Шаг 2: mfa_token + код из приложения (6 цифр) или резервный код (XXXX-XXXX)."""
    user = mfa.read_token(request.data.get("mfa_token"), "otp")
    if not user:
        return Response({"detail": "Время на ввод кода истекло. Войдите заново.", "restart": True}, status=401)
    if _locked(user):
        return Response(LOCKED, status=423)
    via = mfa.verify_any(user, request.data.get("code"))
    if not via:
        _fail(user)
        if _locked(user):
            return Response(LOCKED, status=423)
        return Response({"detail": "Неверный код. Проверьте время на телефоне и попробуйте ещё раз."}, status=401)
    resp = _success(user, request, "2FA" if via == "totp" else "резервный код")
    if via == "recovery":
        resp.data["recovery_left"] = len(user.recovery_codes)
    return resp


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def enroll_start(request):
    """Обязательная настройка 2FA при входе: выдаёт ключ и QR."""
    user = mfa.read_token(request.data.get("mfa_token"), "setup")
    if not user:
        return Response({"detail": "Время на настройку истекло. Войдите заново.", "restart": True}, status=401)
    return Response(mfa.new_secret(user))


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginThrottle])
def enroll_finish(request):
    """Подтверждение первым кодом → 2FA включена, выдаются резервные коды и JWT."""
    user = mfa.read_token(request.data.get("mfa_token"), "setup")
    if not user:
        return Response({"detail": "Время на настройку истекло. Войдите заново.", "restart": True}, status=401)
    if not mfa.verify_totp(user, request.data.get("code")):
        _fail(user)
        return Response({"detail": "Неверный код. Убедитесь, что время на телефоне установлено автоматически."}, status=400)
    user.totp_enabled = True
    user.save(update_fields=["totp_enabled"])
    codes = mfa.new_recovery_codes(user)
    audit(user, "Включил двухфакторную аутентификацию", user.full_name, type="access")
    resp = _success(user, request, "2FA")
    resp.data["recovery_codes"] = codes
    return resp


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
    """Настройка из профиля: новый ключ + QR (2FA включится после подтверждения кодом)."""
    u = request.user
    if u.totp_enabled:
        return Response({"detail": "2FA уже включена. Чтобы сменить устройство, сначала отключите её."}, status=400)
    return Response(mfa.new_secret(u))


@api_view(["POST"])
def twofa_enable(request):
    u = request.user
    if not mfa.verify_totp(u, str(request.data.get("otp") or request.data.get("code") or "")):
        return Response({"detail": "Неверный код"}, status=400)
    u.totp_enabled = True
    u.save(update_fields=["totp_enabled"])
    codes = mfa.new_recovery_codes(u)
    audit(u, "Включил двухфакторную аутентификацию", u.full_name, type="access")
    return Response({**UserSerializer(u).data, "recovery_codes": codes})


@api_view(["POST"])
def twofa_disable(request):
    u = request.user
    if mfa.is_mandatory(u):
        return Response({"detail": f"Для роли «{u.get_role_display()}» двухфакторный вход обязателен — отключить нельзя."}, status=403)
    if not mfa.verify_any(u, request.data.get("code")):
        return Response({"detail": "Неверный код"}, status=400)
    u.totp_enabled, u.totp_secret, u.recovery_codes = False, "", []
    u.save(update_fields=["totp_enabled", "totp_secret", "recovery_codes"])
    audit(u, "Отключил двухфакторную аутентификацию", u.full_name, type="access")
    return Response(UserSerializer(u).data)


@api_view(["POST"])
def twofa_recovery_codes(request):
    """Новые резервные коды (старые перестают действовать). Нужен текущий код из приложения."""
    u = request.user
    if not u.totp_enabled:
        return Response({"detail": "2FA не включена"}, status=400)
    if not mfa.verify_totp(u, request.data.get("code")):
        return Response({"detail": "Неверный код"}, status=400)
    codes = mfa.new_recovery_codes(u)
    audit(u, "Выпустил новые резервные коды 2FA", u.full_name, type="access")
    return Response({"recovery_codes": codes})


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    http_method_names = ["get", "post", "patch"]

    def get_queryset(self):
        qs = User.objects.exclude(role="ai")
        if self.request.query_params.get("role"):
            qs = qs.filter(role=self.request.query_params["role"])
        return qs

    def get_permissions(self):
        if self.action in ("create", "partial_update", "update", "block", "reset_2fa"):
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

    @action(detail=True, methods=["post"], url_path="reset-2fa")
    def reset_2fa(self, request, pk=None):
        """Сотрудник потерял телефон: сброс 2FA. При следующем входе (admin/manager) настройка обязательна."""
        u = self.get_object()
        u.totp_enabled, u.totp_secret, u.recovery_codes, u.totp_last_step = False, "", [], 0
        u.save(update_fields=["totp_enabled", "totp_secret", "recovery_codes", "totp_last_step"])
        audit(request.user, "Сбросил двухфакторную аутентификацию сотрудника", u.full_name, type="access")
        return Response(UserSerializer(u).data)

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
