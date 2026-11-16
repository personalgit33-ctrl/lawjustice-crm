from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import User
from apps.accounts.permissions import case_restricted

from .models import Attachment, CalendarEvent, Case, Client, ConflictCheck, Contract, Deadline, DictItem, Party, Payment
from .services import signed_url
from .utils import due_label, rel_label


def _req(ctx):
    return ctx.get("request")


class AttachmentSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    is_image = serializers.BooleanField(read_only=True)
    uploaded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = ["id", "name", "size", "mime", "is_image", "url", "created_at", "uploaded_by_name"]

    def get_url(self, a):
        return signed_url(a, _req(self.context))

    def get_uploaded_by_name(self, a):
        return str(a.uploaded_by) if a.uploaded_by else "Ассистент"


class DictItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = DictItem
        fields = ["id", "kind", "code", "name", "order", "extra"]


class ClientSerializer(serializers.ModelSerializer):
    responsible_name = serializers.SerializerMethodField()
    cases_count = serializers.SerializerMethodField()
    last_contact_label = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = [
            "id", "kind", "name", "city", "phone", "email", "pin", "source", "campaign", "responsible", "responsible_name",
            "notes", "consent_status", "consent_at", "consent_channel", "conflict_status", "cases_count", "last_contact_at",
            "last_contact_label", "created_at", "requisites",
        ]
        read_only_fields = ["consent_status", "consent_at", "consent_channel", "conflict_status", "last_contact_at", "created_at"]

    def get_responsible_name(self, c):
        return str(c.responsible) if c.responsible else ""

    def get_cases_count(self, c):
        return c.cases.count()

    def get_last_contact_label(self, c):
        if not c.last_contact_at:
            return "—"
        return f"{rel_label(c.last_contact_at)}" + (f", {c.last_contact_channel}" if c.last_contact_channel else "")

    def to_representation(self, c):
        data = super().to_representation(c)
        req = _req(self.context)
        # ПИН виден ответственному, руководителю и админу
        if req and data.get("pin") and req.user.role not in ("admin", "manager") and c.responsible_id not in req.user.represented_ids():
            data["pin"] = "•" * max(0, len(data["pin"]) - 4) + data["pin"][-4:]
        return data


class PartySerializer(serializers.ModelSerializer):
    class Meta:
        model = Party
        fields = ["id", "case", "lead", "role", "name", "pin", "phone"]


class CaseSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source="client.name", read_only=True)
    status_label = serializers.SerializerMethodField()
    responsible_name = serializers.SerializerMethodField()
    restricted = serializers.SerializerMethodField()
    opponents = serializers.SerializerMethodField()
    parties = PartySerializer(many=True, read_only=True)
    nearest_deadline = serializers.SerializerMethodField()
    nearest_deadline_state = serializers.SerializerMethodField()
    stale = serializers.SerializerMethodField()
    members = serializers.PrimaryKeyRelatedField(many=True, required=False, queryset=User.objects.all())

    class Meta:
        model = Case
        fields = [
            "id", "number", "title", "client", "client_name", "category", "status", "status_label", "responsible",
            "responsible_name", "members", "court", "is_confidential", "restricted", "opponents", "parties",
            "nearest_deadline", "nearest_deadline_state", "conflict_status", "is_archived", "fee", "created_at",
            "updated_at", "stale", "description",
        ]
        read_only_fields = ["number", "conflict_status", "created_at", "updated_at"]

    def _nd(self, c):
        if not hasattr(c, "_nd"):
            c._nd = c.deadlines.filter(done_at__isnull=True).order_by("due_at").first()
        return c._nd

    def get_status_label(self, c):
        return DictItem.status_label(c.status)

    def get_responsible_name(self, c):
        return str(c.responsible) if c.responsible else ""

    def get_restricted(self, c):
        req = _req(self.context)
        return bool(req and case_restricted(req.user, c))

    def get_opponents(self, c):
        return ", ".join(p.name for p in c.parties.all() if p.role == "opponent") or "—"

    def get_nearest_deadline(self, c):
        d = self._nd(c)
        return d.due_at.isoformat() if d else None

    def get_nearest_deadline_state(self, c):
        d = self._nd(c)
        return d.state if d else None

    def get_stale(self, c):
        from .services import get_settings

        days = get_settings()["security"]["stale_days"]
        return c.status not in ("done", "closed") and (timezone.now() - c.updated_at).days >= days

    def to_representation(self, c):
        data = super().to_representation(c)
        if data["restricted"]:
            for k in ("description", "court", "parties", "opponents", "fee"):
                data[k] = [] if k == "parties" else ("—" if k != "fee" else None)
            data["title"] = "Конфиденциальное дело"
        return data


class ConflictCheckSerializer(serializers.ModelSerializer):
    decided_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ConflictCheck
        fields = ["id", "subject_label", "subject_type", "query", "matches", "status", "decision_comment", "decided_by_name", "decided_at", "created_at", "source_label"]

    def get_decided_by_name(self, c):
        return str(c.decided_by) if c.decided_by else ""


class DeadlineSerializer(serializers.ModelSerializer):
    type_label = serializers.CharField(source="get_type_display", read_only=True)
    case_label = serializers.SerializerMethodField()
    is_confidential = serializers.SerializerMethodField()
    due_label = serializers.SerializerMethodField()
    state = serializers.CharField(read_only=True)
    done_file = AttachmentSerializer(read_only=True)

    class Meta:
        model = Deadline
        fields = [
            "id", "title", "type", "type_label", "case", "case_label", "is_confidential", "due_at", "due_label", "court",
            "judge", "room", "responsible", "backup", "basis", "state", "done_at", "done_file", "card",
        ]
        read_only_fields = ["done_at"]

    def get_case_label(self, d):
        if not d.case:
            return "—"
        last = d.case.client.name.split()[0] if d.case.client else ""
        return f"{d.case.number} · {last}"

    def get_is_confidential(self, d):
        return bool(d.case and d.case.is_confidential)

    def get_due_label(self, d):
        return due_label(d.due_at)


class PaymentSerializer(serializers.ModelSerializer):
    overdue_days = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = ["id", "contract", "due_date", "amount", "paid_amount", "paid_at", "overdue_days"]
        read_only_fields = ["contract", "paid_amount", "paid_at"]

    def get_overdue_days(self, p):
        if p.paid_amount >= p.amount:
            return 0
        d = (timezone.localdate() - p.due_date).days
        return max(0, d)

    def to_representation(self, p):
        d = super().to_representation(p)
        d["amount"], d["paid_amount"] = float(p.amount), float(p.paid_amount)
        return d


class ContractSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source="client.name", read_only=True)
    case_number = serializers.SerializerMethodField()
    model_label = serializers.CharField(source="get_model_display", read_only=True)
    paid = serializers.SerializerMethodField()
    debt = serializers.SerializerMethodField()
    next_payment_label = serializers.SerializerMethodField()
    next_payment_overdue = serializers.SerializerMethodField()
    payments = PaymentSerializer(many=True, required=False)

    class Meta:
        model = Contract
        fields = ["id", "client", "client_name", "case", "case_number", "status", "model", "model_label", "fee", "paid", "debt", "next_payment_label", "next_payment_overdue", "responsible", "payments"]

    def get_case_number(self, c):
        return c.case.number if c.case else "лид"

    def get_paid(self, c):
        return float(c.payments.aggregate(s=Sum("paid_amount"))["s"] or 0)

    def get_debt(self, c):
        today = timezone.localdate()
        due = c.payments.filter(due_date__lte=today).aggregate(s=Sum("amount"), p=Sum("paid_amount"))
        return float((due["s"] or 0) - (due["p"] or 0))

    def _next(self, c):
        for p in c.payments.all():
            if p.paid_amount < p.amount:
                return p
        return None

    def get_next_payment_label(self, c):
        p = self._next(c)
        if not p:
            return "—"
        days = (timezone.localdate() - p.due_date).days
        if days > 0:
            return f"Просрочен {days} дн."
        return f"{p.due_date.day} {['янв','фев','мар','апр','мая','июн','июл','авг','сен','окт','ноя','дек'][p.due_date.month-1]} · {int(p.amount - p.paid_amount):,}".replace(",", " ")

    def get_next_payment_overdue(self, c):
        p = self._next(c)
        return bool(p and p.due_date < timezone.localdate())

    def to_representation(self, c):
        d = super().to_representation(c)
        d["fee"] = float(c.fee)
        return d

    def create(self, data):
        pays = data.pop("payments", [])
        c = Contract.objects.create(**data)
        for p in pays:
            Payment.objects.create(contract=c, due_date=p["due_date"], amount=p["amount"])
        return c

    def update(self, c, data):
        pays = data.pop("payments", None)
        for k, v in data.items():
            setattr(c, k, v)
        if data.get("status") == "signed" and not c.signed_at:
            c.signed_at = timezone.localdate()
        c.save()
        if pays is not None:
            c.payments.filter(paid_amount=0).delete()
            for p in pays:
                Payment.objects.create(contract=c, due_date=p["due_date"], amount=p["amount"])
        return c


class CalendarEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = CalendarEvent
        fields = ["id", "title", "kind", "start", "end", "case", "client", "user", "card"]
