"""Приём вебхуков (п. 2.5, 7.1, 8.1). Каждое событие сначала пишется в журнал WebhookEvent,
затем обрабатывается задачей Celery (в dev — сразу) с повторными попытками при ошибке."""
import hashlib
import hmac
import json
import logging

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.crm.models import Attachment

from .models import Call, Message, WebhookEvent
from .services import incoming_call, inbound, missed_call

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v20.0"


def _enqueue(source, payload):
    from .tasks import process_webhook

    ev = WebhookEvent.objects.create(source=source, payload=payload)
    process_webhook.delay(ev.id)
    return ev


# ---------- WhatsApp Cloud API ----------

def _wa_media(media_id, filename):
    if not settings.WHATSAPP_TOKEN:
        return None
    h = {"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"}
    meta = requests.get(f"{GRAPH}/{media_id}", headers=h, timeout=15).json()
    data = requests.get(meta["url"], headers=h, timeout=30)
    att = Attachment(name=filename, size=len(data.content), mime=meta.get("mime_type", ""))
    att.file.save(filename, ContentFile(data.content), save=True)
    return att


def process_whatsapp(payload):
    for entry in payload.get("entry", []):
        for ch in entry.get("changes", []):
            v = ch.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in v.get("contacts", [])}
            for m in v.get("messages", []):
                wa = m.get("from")
                typ = m.get("type")
                text, att = "", None
                if typ == "text":
                    text = m["text"]["body"]
                elif typ in ("image", "document", "audio", "video", "voice"):
                    media = m.get(typ, {})
                    text = media.get("caption", "")
                    fname = media.get("filename") or f"{typ}_{m['id'][-6:]}.{ {'image': 'jpg', 'audio': 'ogg', 'voice': 'ogg', 'video': 'mp4'}.get(typ, 'bin')}"
                    try:
                        att = _wa_media(media.get("id"), fname)
                    except Exception:
                        log.exception("media download failed")
                    if not att:
                        text = text or f"[{typ}: {fname}]"
                elif typ == "button":
                    text = m.get("button", {}).get("text", "")
                else:
                    text = f"[{typ}]"
                referral = m.get("referral") or {}
                inbound("wa", name=names.get(wa, ""), phone="+" + wa, text=text, external_id=wa, attachment=att, msg_external_id=m.get("id"), campaign=referral.get("headline", ""), utm={"source": "meta_ctwa", **{k: referral.get(k) for k in ("source_id", "source_url") if referral.get(k)}} if referral else None)
            for s in v.get("statuses", []):
                Message.objects.filter(external_id=s.get("id")).update(delivery={"sent": "sent", "delivered": "delivered", "read": "read", "failed": "failed"}.get(s.get("status"), ""))


@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def whatsapp(request):
    if request.method == "GET":
        if request.query_params.get("hub.verify_token") == settings.WHATSAPP_VERIFY_TOKEN:
            return HttpResponse(request.query_params.get("hub.challenge", ""))
        return HttpResponse(status=403)
    if settings.WHATSAPP_APP_SECRET:
        sig = request.headers.get("X-Hub-Signature-256", "")
        exp = "sha256=" + hmac.new(settings.WHATSAPP_APP_SECRET.encode(), request.body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, exp):
            return HttpResponse(status=403)
    _enqueue("whatsapp", request.data)
    return Response({"ok": True})


# ---------- Google Ads Lead Form / форма сайта ----------

def process_google(p):
    if "user_column_data" in p:  # Google Ads Lead Form Extensions
        cols = {c.get("column_id"): c.get("string_value", "") for c in p["user_column_data"]}
        name = cols.get("FULL_NAME") or " ".join(x for x in (cols.get("FIRST_NAME"), cols.get("LAST_NAME")) if x)
        extra = [f"{k}: {v}" for k, v in cols.items() if k not in ("FULL_NAME", "FIRST_NAME", "LAST_NAME", "PHONE_NUMBER", "EMAIL")]
        inbound("g", name=name, phone=cols.get("PHONE_NUMBER", ""), email=cols.get("EMAIL", ""), text="; ".join(extra) or "Заявка из Google Ads", campaign=str(p.get("campaign_name") or p.get("campaign_id") or ""), utm={"gclid": p.get("gcl_id", ""), "campaign_id": p.get("campaign_id"), "form_id": p.get("form_id")}, form_data=cols, msg_external_id=f"g-{p.get('lead_id')}" if p.get("lead_id") else "")
        return
    utm = {k: p.get(k) for k in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term") if p.get(k)}
    inbound("g", name=p.get("name", ""), phone=p.get("phone", ""), email=p.get("email", ""), text=p.get("text") or p.get("message") or "Заявка с сайта", campaign=p.get("campaign") or utm.get("utm_campaign", ""), utm=utm, form_data=p)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def google(request):
    key = request.query_params.get("key") or request.data.get("google_key")
    if key != settings.GOOGLE_WEBHOOK_KEY:
        return Response({"detail": "bad key"}, status=403)
    _enqueue("google", request.data)
    return Response({"ok": True})


# ---------- Meta Lead Ads ----------

def _meta_lead(leadgen_id):
    r = requests.get(f"{GRAPH}/{leadgen_id}", params={"access_token": settings.META_PAGE_TOKEN, "fields": "field_data,campaign_name,ad_name,form_id"}, timeout=15)
    r.raise_for_status()
    return r.json()


def process_meta(p):
    leads = []
    if "field_data" in p:
        leads.append(p)
    for entry in p.get("entry", []):
        for ch in entry.get("changes", []):
            v = ch.get("value", {})
            if v.get("field_data"):
                leads.append(v)
            elif v.get("leadgen_id"):
                leads.append({**_meta_lead(v["leadgen_id"]), "leadgen_id": v["leadgen_id"]})
    for ld in leads:
        f = {x["name"]: (x.get("values") or [""])[0] for x in ld.get("field_data", [])}
        name = f.get("full_name") or f.get("first_name", "")
        extra = [f"{k}: {v}" for k, v in f.items() if k not in ("full_name", "first_name", "last_name", "phone_number", "email")]
        inbound("meta", name=name, phone=f.get("phone_number", ""), email=f.get("email", ""), text="; ".join(extra) or "Заявка из Meta Lead Ads", campaign=ld.get("campaign_name", ""), utm={"ad_name": ld.get("ad_name", ""), "form_id": ld.get("form_id", "")}, form_data=f, msg_external_id=f"meta-{ld.get('leadgen_id')}" if ld.get("leadgen_id") else "")


@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def meta(request):
    if request.method == "GET":
        if request.query_params.get("hub.verify_token") == settings.META_VERIFY_TOKEN:
            return HttpResponse(request.query_params.get("hub.challenge", ""))
        return HttpResponse(status=403)
    _enqueue("meta", request.data)
    return Response({"ok": True})


# ---------- IP-телефония (обобщённый формат; адаптируется под провайдера) ----------

def process_telephony(p):
    ev = p.get("event")
    ext = str(p.get("call_id", ""))
    call = Call.objects.filter(external_id=ext).first() if ext else None
    if ev == "ringing":
        if p.get("direction") == "out":
            return
        incoming_call(p.get("from", ""), external_id=ext)
    elif ev == "missed":
        call = call or incoming_call(p.get("from", ""), external_id=ext)
        if call.status != "missed":
            from apps.crm.services import is_work_time

            missed_call(call, not is_work_time())
    elif ev == "answered" and call:
        from apps.accounts.models import User

        call.status = "answered"
        call.user = User.objects.filter(phone=p.get("extension", "~")).first() or call.user
        call.save()
    elif ev == "ended" and call:
        call.duration = int(p.get("duration") or 0)
        call.record_url = p.get("record_url", "") or call.record_url
        if call.status == "ringing":
            call.status = "answered" if call.duration else "missed"
        if p.get("transcript"):
            call.transcript = p["transcript"]
        call.save()
        if call.status == "missed":
            missed_call(call)
        from .callsummary import summarize_call

        summarize_call(call)


PROCESSORS = {"whatsapp": process_whatsapp, "google": process_google, "meta": process_meta, "telephony": process_telephony}


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def telephony(request):
    if request.query_params.get("key") != settings.TELEPHONY_WEBHOOK_KEY:
        return Response({"detail": "bad key"}, status=403)
    _enqueue("telephony", request.data)
    return Response({"ok": True})
