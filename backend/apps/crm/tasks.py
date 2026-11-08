"""Фоновые задачи CRM (Celery beat): напоминания по срокам, эскалация, платежи, «застой»."""
from celery import shared_task
from django.utils import timezone

from apps.audit.services import managers, notify

from .services import get_settings
from .utils import due_label


@shared_task
def deadline_reminders():
    """п. 5.13.4: за 7, 3, 1 день и в день срока — ответственному и дублирующему; невыполненный — эскалация руководителю."""
    from .models import Deadline, Payment

    days_list = get_settings()["reminders_days"]
    today = timezone.localdate()
    sent = 0
    for d in Deadline.objects.filter(done_at__isnull=True).select_related("case", "responsible", "backup"):
        left = (timezone.localtime(d.due_at).date() - today).days
        label = f"{d.title}" + (f" · дело № {d.case.number}" if d.case else "")
        if left in days_list and left not in d.reminders_sent:
            when = "сегодня" if left == 0 else f"через {left} дн."
            notify([x for x in (d.responsible, d.backup) if x], "deadline", f"Срок {when}: {label} — {due_label(d.due_at)}", "/deadlines", dedup_key=f"dl{d.id}-{left}", email=True)
            d.reminders_sent = d.reminders_sent + [left]
            d.save(update_fields=["reminders_sent"])
            sent += 1
        if d.due_at < timezone.now() and not d.escalated:
            notify(managers() + [x for x in (d.responsible, d.backup) if x], "escalation", f"Просрочен срок: {label} (ответственный {d.responsible or '—'})", "/deadlines", dedup_key=f"esc{d.id}", email=True)
            d.escalated = True
            d.save(update_fields=["escalated"])
            sent += 1
    # п. 5.14: напоминание о просроченном платеже
    for p in Payment.objects.filter(due_date__lt=today, reminded=False).select_related("contract", "contract__client", "contract__responsible"):
        if p.paid_amount >= p.amount:
            continue
        resp = p.contract.responsible
        notify([resp] if resp else managers(), "payment", f"Просрочен платёж: {p.contract.client.name} — {int(p.amount - p.paid_amount):,} сом".replace(",", " "), "/finance")
        p.reminded = True
        p.save(update_fields=["reminded"])
        sent += 1
    return sent


@shared_task
def stale_report():
    """п. 5.10: дела и карточки без движения дольше N дней — в отчёт руководителю."""
    from apps.boards.models import Card

    from .models import Case

    days = get_settings()["security"]["stale_days"]
    border = timezone.now() - timezone.timedelta(days=days)
    cases = Case.objects.filter(is_archived=False, updated_at__lt=border).exclude(status__in=["done", "closed"]).count()
    cards = Card.objects.filter(is_archived=False, updated_at__lt=border, list__is_final=False).count()
    if cases or cards:
        notify(managers(), "stale", f"Без движения более {days} дн.: дел — {cases}, карточек — {cards}", "/cases", dedup_key=f"stale-{timezone.localdate()}", email=True)
    return cases + cards
