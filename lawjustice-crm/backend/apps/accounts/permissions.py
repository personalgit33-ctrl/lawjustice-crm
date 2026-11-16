"""Разграничение доступа по роли и зоне ответственности (п. 4.1–4.6)."""
from django.db.models import Q
from rest_framework.permissions import BasePermission

ADMIN, MANAGER, LAWYER, OPERATOR = "admin", "manager", "lawyer", "operator"


class IsAdmin(BasePermission):
    message = "Действие доступно только администратору"

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == ADMIN


class IsManagerPlus(BasePermission):
    message = "Действие доступно руководителю и администратору"

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in (ADMIN, MANAGER)


class NotOperator(BasePermission):
    message = "Недоступно для роли «Оператор»"

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role != OPERATOR


def scope_clients(user, qs):
    qs = qs.filter(merged_into__isnull=True)
    if user.role in (ADMIN, MANAGER, OPERATOR):
        return qs
    ids = user.represented_ids()
    return qs.filter(
        Q(responsible_id__in=ids)
        | Q(cases__responsible_id__in=ids)
        | Q(cases__members__id__in=ids)
        | Q(conversations__responsible_id__in=ids)
    ).distinct()


def scope_cases(user, qs):
    if user.role in (ADMIN, MANAGER):
        return qs
    ids = user.represented_ids()
    return qs.filter(Q(responsible_id__in=ids) | Q(members__id__in=ids)).distinct()


def case_restricted(user, case) -> bool:
    """Конфиденциальное дело: материалы видят участники и руководитель. Админ видит только факт (п. 4.6)."""
    if not case or not case.is_confidential:
        return False
    if user.role == MANAGER:
        return False
    ids = set(user.represented_ids())
    if case.responsible_id in ids or case.members.filter(id__in=ids).exists():
        return False
    return True


def visible_case_q(user, prefix="case"):
    """Q-фильтр для объектов, привязанных к делу: скрыть конфиденциальные дела от неучастников."""
    if user.role in (ADMIN, MANAGER):
        return Q()
    ids = user.represented_ids()
    return (
        Q(**{f"{prefix}__isnull": True})
        | Q(**{f"{prefix}__is_confidential": False})
        | Q(**{f"{prefix}__responsible_id__in": ids})
        | Q(**{f"{prefix}__members__id__in": ids})
    )


def scope_conversations(user, qs):
    if user.role in (ADMIN, MANAGER, OPERATOR):
        return qs
    ids = user.represented_ids()
    return qs.filter(Q(responsible_id__in=ids) | Q(client__responsible_id__in=ids)).distinct()


def scope_boards(user, qs):
    if user.role in (ADMIN, MANAGER):
        return qs
    return qs.filter(Q(access="all") | Q(access="department") | Q(allowed_users=user)).distinct()


def scope_cards(user, qs):
    from apps.boards.models import Board

    boards = scope_boards(user, Board.objects.all())
    return qs.filter(list__board__in=boards).filter(visible_case_q(user)).distinct()


def scope_deadlines(user, qs):
    if user.role in (ADMIN, MANAGER):
        return qs
    ids = user.represented_ids()
    own = Q(responsible_id__in=ids) | Q(backup_id__in=ids)
    if user.role == OPERATOR:
        return qs.filter(own)
    return qs.filter(own | Q(case__responsible_id__in=ids) | Q(case__members__id__in=ids)).distinct()


def scope_calls(user, qs):
    if user.role in (ADMIN, MANAGER, OPERATOR):
        return qs.filter(visible_case_q(user))
    ids = user.represented_ids()
    return qs.filter(Q(user_id__in=ids) | Q(client__responsible_id__in=ids)).filter(visible_case_q(user)).distinct()


def can_access_recording(user, call) -> bool:
    if user.role in (ADMIN, MANAGER):
        return True
    ids = set(user.represented_ids())
    return call.user_id in ids or (call.client_id and call.client.responsible_id in ids)
