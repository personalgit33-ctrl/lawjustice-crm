"""Журнал, уведомления и рассылка событий реального времени."""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.mail import send_mail
from django.db import transaction

from .models import AuditLog, Notification

log = logging.getLogger(__name__)


def broadcast(event_type: str, payload, user_ids=None):
    """Событие в WebSocket. user_ids=None — всем, иначе в личные группы."""
    layer = get_channel_layer()
    if not layer:
        return
    groups = ["all"] if user_ids is None else [f"user_{uid}" for uid in set(user_ids) if uid]
    msg = {"type": "event", "event": {"type": event_type, "payload": payload}}

    def _send():
        for g in groups:
            try:
                async_to_sync(layer.group_send)(g, msg)
            except Exception as e:  # realtime не должен ронять запрос
                log.warning("ws broadcast failed: %s", e)

    transaction.on_commit(_send)


def audit(actor, action, object_label="", type="change", is_ai=False, payload=None, undo=None, client_id=None, case_id=None, card_id=None):
    label = "Ассистент" if is_ai else (getattr(actor, "full_name", "") or getattr(actor, "username", "") or "Система")
    return AuditLog.objects.create(
        actor=actor if actor and getattr(actor, "pk", None) else None,
        actor_label=label,
        is_ai=is_ai,
        action=action,
        object_label=object_label[:255],
        type=type,
        payload=payload or {},
        undo=undo,
        client_id=client_id,
        case_id=case_id,
        card_id=card_id,
    )


def notify(users, kind, text, link="", dedup_key="", email=False):
    """Уведомление в интерфейсе (+ WS, + email при email=True). users — iterable User."""
    created = []
    for u in {u for u in users if u and u.is_active and u.role != "ai"}:
        if dedup_key and Notification.objects.filter(user=u, dedup_key=dedup_key).exists():
            continue
        n = Notification.objects.create(user=u, kind=kind, text=text[:500], link=link, dedup_key=dedup_key)
        created.append(n)
        broadcast("notification", {"id": n.id, "kind": kind, "text": n.text, "link": link, "is_read": False, "created_at": n.created_at.isoformat()}, [u.id])
        if email and u.email:
            try:
                send_mail("Law & Justice CRM", text, None, [u.email], fail_silently=True)
            except Exception:
                pass
    return created


def managers():
    from apps.accounts.models import User

    return list(User.objects.filter(role__in=["manager"], is_active=True)) or list(User.objects.filter(role="admin", is_active=True))
