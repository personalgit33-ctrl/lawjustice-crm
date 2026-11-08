from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.permissions import IsManagerPlus

from .models import AuditLog, Notification


@api_view(["GET"])
def notifications(request):
    qs = Notification.objects.filter(user=request.user)[:50]
    return Response([{"id": n.id, "kind": n.kind, "text": n.text, "link": n.link, "is_read": n.is_read, "created_at": n.created_at.isoformat()} for n in qs])


@api_view(["POST"])
def notifications_read_all(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return Response({"ok": True})


@api_view(["POST"])
def notification_read(request, pk):
    Notification.objects.filter(user=request.user, id=pk).update(is_read=True)
    return Response({"ok": True})


@api_view(["GET"])
@permission_classes([IsManagerPlus])
def audit_list(request):
    qs = AuditLog.objects.all()
    t = request.query_params.get("type")
    if t:
        qs = qs.filter(type=t)
    if request.query_params.get("q"):
        q = request.query_params["q"]
        from django.db.models import Q

        qs = qs.filter(Q(action__icontains=q) | Q(object_label__icontains=q) | Q(actor_label__icontains=q))
    limit = min(int(request.query_params.get("limit", 50)), 200)
    offset = int(request.query_params.get("offset", 0))
    labels = dict(AuditLog.Type.choices)
    items = qs[offset : offset + limit]
    return Response({
        "count": qs.count(),
        "results": [{
            "id": a.id, "created_at": a.created_at.isoformat(), "actor_name": a.actor_label, "is_ai": a.is_ai, "action": a.action,
            "object_label": a.object_label, "type": a.type, "type_label": labels.get(a.type, a.type),
            "can_undo": bool(a.is_ai and a.undo and not a.undone and request.user.role == "admin"),
        } for a in items],
    })
