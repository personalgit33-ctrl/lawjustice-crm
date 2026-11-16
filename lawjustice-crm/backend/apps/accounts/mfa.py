"""Двухфакторная аутентификация (ТЗ п. 12.7): TOTP + одноразовые резервные коды.

Вход в два шага:
  1. логин + пароль → если 2FA включена: 401 {otp_required, mfa_token};
     если роль обязана иметь 2FA, а она не настроена: 403 {setup_required, mfa_token}.
  2. mfa_token + код → JWT. Пароль на втором шаге не передаётся повторно.
mfa_token — подписанный токен на 5 минут, привязан к пользователю и этапу.
"""
import base64
import hashlib
import io
import secrets
import time

import pyotp
from django.core import signing

MFA_TTL = 300
STEP = 30
ISSUER = "Law & Justice CRM"
MANDATORY_ROLES = ("admin", "manager")


def make_token(user, stage):
    return signing.dumps({"uid": user.id, "stage": stage, "pw": user.password[-12:]}, salt="mfa")


def read_token(token, stage):
    """Возвращает пользователя или None. Токен недействителен после смены пароля."""
    from .models import User

    try:
        data = signing.loads(token or "", salt="mfa", max_age=MFA_TTL)
    except signing.BadSignature:
        return None
    if data.get("stage") != stage:
        return None
    user = User.objects.filter(id=data.get("uid"), is_active=True).first()
    if not user or user.password[-12:] != data.get("pw"):
        return None
    return user


def is_mandatory(user):
    from apps.crm.services import get_settings

    return user.role in MANDATORY_ROLES and get_settings()["security"].get("require_2fa_admin", True)


def new_secret(user):
    user.totp_secret = pyotp.random_base32()
    user.totp_enabled = False
    user.totp_last_step = 0
    user.save(update_fields=["totp_secret", "totp_enabled", "totp_last_step"])
    return provisioning(user)


def provisioning(user):
    uri = pyotp.TOTP(user.totp_secret).provisioning_uri(name=user.username, issuer_name=ISSUER)
    return {"secret": user.totp_secret, "otpauth_url": uri, "qr_svg": qr_data_uri(uri)}


def qr_data_uri(text):
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def _hash(code):
    return hashlib.sha256(code.replace("-", "").replace(" ", "").upper().encode()).hexdigest()


def new_recovery_codes(user, count=8):
    codes = []
    for _ in range(count):
        raw = secrets.token_hex(4).upper()
        codes.append(f"{raw[:4]}-{raw[4:]}")
    user.recovery_codes = [_hash(c) for c in codes]
    user.save(update_fields=["recovery_codes"])
    return codes


def verify_totp(user, code):
    """Проверка кода с окном ±1 шаг и запретом повторного использования того же кода."""
    code = (code or "").replace(" ", "")
    if not user.totp_secret or not code.isdigit() or len(code) != 6:
        return False
    totp = pyotp.TOTP(user.totp_secret)
    now_step = int(time.time()) // STEP
    for step in (now_step - 1, now_step, now_step + 1):
        if step <= user.totp_last_step:
            continue
        if secrets.compare_digest(totp.at(step * STEP), code):
            user.totp_last_step = step
            user.save(update_fields=["totp_last_step"])
            return True
    return False


def use_recovery_code(user, code):
    h = _hash(code or "")
    if h in (user.recovery_codes or []):
        user.recovery_codes = [x for x in user.recovery_codes if x != h]
        user.save(update_fields=["recovery_codes"])
        return True
    return False


def verify_any(user, code):
    """Код из приложения или резервный код. Возвращает 'totp' | 'recovery' | None."""
    code = (code or "").strip()
    if verify_totp(user, code):
        return "totp"
    if len(code.replace("-", "").replace(" ", "")) == 8 and use_recovery_code(user, code):
        return "recovery"
    return None
