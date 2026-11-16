from django.shortcuts import get_object_or_404
from rest_framework import serializers, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.permissions import IsAdmin, IsManagerPlus
from apps.audit.models import AuditLog

from .engine import cancel, confirm, run_command
from .models import AssistantRun
from .tools import undo_action


class RunSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssistantRun
        fields = ["id", "command", "created_at", "steps", "result", "state", "engine"]


class AssistantViewSet(viewsets.ReadOnlyModelViewSet):
    """п. 9.5: ассистент доступен администратору и руководителю (п. 4.1)."""

    serializer_class = RunSerializer
    permission_classes = [IsManagerPlus]

    def get_queryset(self):
        return AssistantRun.objects.filter(user=self.request.user)[:50]

    def get_object(self):
        return get_object_or_404(AssistantRun, id=self.kwargs["pk"], user=self.request.user)

    @action(detail=False, methods=["post"])
    def command(self, request):
        text = (request.data.get("text") or "").strip()
        if not text:
            return Response({"detail": "Введите команду"}, status=400)
        return Response(RunSerializer(run_command(request.user, text)).data, status=201)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        run = self.get_object()
        if run.state != "awaiting_confirm":
            return Response({"detail": "Нечего подтверждать"}, status=400)
        return Response(RunSerializer(confirm(run, request.user)).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        run = self.get_object()
        return Response(RunSerializer(cancel(run, request.user)).data)


@api_view(["POST"])
@permission_classes([IsAdmin])
def undo(request, pk):
    entry = get_object_or_404(AuditLog, id=pk, is_ai=True)
    if entry.undone or not entry.undo:
        return Response({"detail": "Действие нельзя отменить"}, status=400)
    if not undo_action(entry, request.user):
        return Response({"detail": "Действие нельзя отменить"}, status=400)
    return Response({"ok": True})
