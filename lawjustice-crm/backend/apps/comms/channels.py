"""Адаптеры каналов. Новый канал (Telegram, Instagram Direct, чат на сайте) = новый класс с send() (п. 2.7).

Без токенов адаптер работает в режиме «песочницы»: сообщение сохраняется и помечается доставленным,
во внешний сервис ничего не уходит — так stage работает до подключения боевых аккаунтов заказчика.
"""
import logging

import requests
from django.conf import settings

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v20.0"


class SendResult:
    def __init__(self, ok=True, external_id="", delivery="delivered", error=""):
        self.ok, self.external_id, self.delivery, self.error = ok, external_id, delivery, error


class BaseChannel:
    code = ""

    def send_text(self, conv, text, template=None) -> SendResult:
        return SendResult(delivery="delivered")

    def send_file(self, conv, attachment, caption="") -> SendResult:
        return SendResult(delivery="delivered")


class WhatsAppChannel(BaseChannel):
    """WhatsApp Business Cloud API: текст, медиа, шаблоны вне 24-часового окна."""

    code = "wa"

    @property
    def live(self):
        return bool(settings.WHATSAPP_TOKEN and settings.WHATSAPP_PHONE_ID)

    def _post(self, payload):
        r = requests.post(
            f"{GRAPH}/{settings.WHATSAPP_PHONE_ID}/messages",
            json={"messaging_product": "whatsapp", **payload},
            headers={"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"},
            timeout=15,
        )
        if r.status_code >= 300:
            log.error("WhatsApp send failed %s %s", r.status_code, r.text[:500])
            return SendResult(False, delivery="failed", error=r.text[:300])
        mid = (r.json().get("messages") or [{}])[0].get("id", "")
        return SendResult(True, mid, "sent")

    def _to(self, conv):
        return conv.external_id or "".join(ch for ch in conv.client.phone if ch.isdigit())

    def send_text(self, conv, text, template=None):
        if not self.live:
            return SendResult(delivery="delivered")
        if template:
            return self._post({"to": self._to(conv), "type": "template", "template": {"name": template, "language": {"code": "ru"}}})
        return self._post({"to": self._to(conv), "type": "text", "text": {"body": text}})

    def send_file(self, conv, attachment, caption=""):
        if not self.live:
            return SendResult(delivery="delivered")
        from apps.crm.services import signed_url

        kind = "image" if attachment.is_image else "document"
        base = getattr(settings, "PUBLIC_BASE_URL", "")
        body = {"link": base + signed_url(attachment)}
        if kind == "document":
            body["filename"] = attachment.name
        if caption:
            body["caption"] = caption
        return self._post({"to": self._to(conv), "type": kind, kind: body})


class LeadFormChannel(BaseChannel):
    """Google / Meta заявки: ответить можно только звонком или WhatsApp — сообщение фиксируется как исходящее."""


CHANNELS = {"wa": WhatsAppChannel(), "g": LeadFormChannel(), "meta": LeadFormChannel(), "ph": BaseChannel(), "manual": BaseChannel()}


def channel_for(conv):
    return CHANNELS.get(conv.channel, BaseChannel())


class Telephony:
    """Обёртка API провайдера IP-телефонии. Провайдер утверждается при старте (п. 8.1):
    реализуйте originate()/transfer() под его API — остальная CRM не меняется."""

    @property
    def live(self):
        return bool(settings.TELEPHONY_API_URL)

    def originate(self, user, phone):
        if not self.live:
            return {"ok": True, "call_id": "", "sandbox": True}
        r = requests.post(f"{settings.TELEPHONY_API_URL}/calls", json={"from_ext": user.phone or user.username, "to": phone}, headers={"Authorization": f"Bearer {settings.TELEPHONY_API_TOKEN}"}, timeout=10)
        return {"ok": r.ok, "call_id": r.json().get("id", "") if r.ok else ""}

    def transfer(self, call, user):
        if not self.live:
            return {"ok": True, "sandbox": True}
        r = requests.post(f"{settings.TELEPHONY_API_URL}/calls/{call.external_id}/transfer", json={"to_ext": user.phone or user.username}, headers={"Authorization": f"Bearer {settings.TELEPHONY_API_TOKEN}"}, timeout=10)
        return {"ok": r.ok}


telephony = Telephony()
