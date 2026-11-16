from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts import views as acc
from apps.assistant import views as ai
from apps.audit import views as aud
from apps.boards import views as brd
from apps.comms import views as com
from apps.comms import webhooks as wh
from apps.crm import reports as rep
from apps.crm import views as crm

r = DefaultRouter(trailing_slash=True)
r.register("users", acc.UserViewSet, basename="users")
r.register("dict", crm.DictViewSet, basename="dict")
r.register("clients", crm.ClientViewSet, basename="clients")
r.register("cases", crm.CaseViewSet, basename="cases")
r.register("parties", crm.PartyViewSet, basename="parties")
r.register("conflicts", crm.ConflictViewSet, basename="conflicts")
r.register("deadlines", crm.DeadlineViewSet, basename="deadlines")
r.register("events", crm.EventViewSet, basename="events")
r.register("contracts", crm.ContractViewSet, basename="contracts")
r.register("attachments", crm.AttachmentViewSet, basename="attachments")
r.register("boards", brd.BoardViewSet, basename="boards")
r.register("lists", brd.ListViewSet, basename="lists")
r.register("cards", brd.CardViewSet, basename="cards")
r.register("checklists", brd.ChecklistViewSet, basename="checklists")
r.register("checklist-items", brd.ChecklistItemViewSet, basename="checklist-items")
r.register("comments", brd.CommentViewSet, basename="comments")
r.register("labels", brd.LabelViewSet, basename="labels")
r.register("automations", brd.AutomationViewSet, basename="automations")
r.register("conversations", com.ConversationViewSet, basename="conversations")
r.register("calls", com.CallViewSet, basename="calls")
r.register("assistant", ai.AssistantViewSet, basename="assistant")

api = [
    path("auth/login/", acc.login),
    path("auth/refresh/", acc.refresh),
    path("auth/me/", acc.me),
    path("auth/2fa/setup/", acc.twofa_setup),
    path("auth/2fa/enable/", acc.twofa_enable),
    path("auth/2fa/disable/", acc.twofa_disable),
    path("auth/2fa/recovery-codes/", acc.twofa_recovery_codes),
    path("auth/login/verify/", acc.login_verify),
    path("auth/2fa/enroll/start/", acc.enroll_start),
    path("auth/2fa/enroll/finish/", acc.enroll_finish),
    path("settings/", crm.settings_view),
    path("calendar/", crm.calendar),
    path("payments/<int:pk>/pay/", crm.pay),
    path("finance/summary/", crm.finance_summary),
    path("finance/export/", crm.finance_export),
    path("files/<int:pk>/", crm.file_download),
    path("messages/<int:pk>/to-card/", com.message_to_card),
    path("messages/<int:pk>/rate/", com.message_rate),
    path("simulate/inbound/", com.simulate_inbound),
    path("simulate/call/", com.simulate_call),
    path("webhooks/whatsapp/", wh.whatsapp),
    path("webhooks/google/", wh.google),
    path("webhooks/meta/", wh.meta),
    path("webhooks/telephony/", wh.telephony),
    path("ai/undo/<int:pk>/", ai.undo),
    path("dashboard/", rep.dashboard),
    path("reports/funnel/", rep.funnel),
    path("reports/funnel/export/", rep.funnel_export),
    path("reports/ad-spend/", rep.ad_spend),
    path("search/", rep.search),
    path("export/all/", rep.export_all),
    path("notifications/", aud.notifications),
    path("notifications/read-all/", aud.notifications_read_all),
    path("notifications/<int:pk>/read/", aud.notification_read),
    path("audit/", aud.audit_list),
    path("health/", lambda request: JsonResponse({"ok": True})),
    path("", include(r.urls)),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(api)),
]
