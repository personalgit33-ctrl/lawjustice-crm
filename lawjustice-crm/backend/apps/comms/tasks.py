import logging

from celery import shared_task
from django.utils import timezone

log = logging.getLogger(__name__)


@shared_task
def ai_reply(conv_id, msg_id):
    from apps.assistant.firstline import handle_inbound

    try:
        handle_inbound(conv_id, msg_id)
    except Exception:  # AI не ломает приём обращения
        log.exception("AI first line failed")


@shared_task
def process_webhook(event_id):
    from .models import WebhookEvent
    from .webhooks import PROCESSORS

    ev = WebhookEvent.objects.get(id=event_id)
    ev.attempts += 1
    try:
        PROCESSORS[ev.source](ev.payload)
        ev.status, ev.error = "done", ""
    except Exception as e:
        log.exception("webhook %s failed", ev.id)
        ev.status, ev.error = "error", str(e)[:2000]
    ev.save()


@shared_task
def retry_failed_webhooks():
    from .models import WebhookEvent

    for ev in WebhookEvent.objects.filter(status="error", attempts__lt=5):
        process_webhook(ev.id)


@shared_task
def first_response_sla():
    """п. 7.4: оповестить руководителя, если обращение не взято в работу за заданное время."""
    from apps.audit.services import managers, notify
    from apps.crm.services import get_settings

    from .models import Conversation

    minutes = get_settings().get("first_response_sla_min", 5)
    limit = timezone.now() - timezone.timedelta(minutes=minutes)
    for c in Conversation.objects.filter(first_response_at__isnull=True, sla_alerted=False, created_at__lt=limit).exclude(status="closed"):
        notify(managers(), "sla", f"Обращение {c.client.name} без ответа более {minutes} мин", f"/inbox?c={c.id}")
        c.sla_alerted = True
        c.save(update_fields=["sla_alerted"])


@shared_task
def recordings_retention():
    """п. 8.8: автоудаление записей по сроку хранения с отметкой в журнале."""
    from apps.audit.services import audit
    from apps.crm.services import get_settings

    from .models import Call

    months = get_settings()["security"]["recordings_retention_months"]
    border = timezone.now() - timezone.timedelta(days=30 * months)
    for call in Call.objects.filter(started_at__lt=border).exclude(recording__isnull=True):
        call.recording.file.delete(save=False)
        call.recording.delete()
        call.record_url = ""
        call.save(update_fields=["record_url"])
        audit(None, "Запись звонка удалена по сроку хранения", f"{call.phone} · {call.started_at:%d.%m.%Y}", type="record")
