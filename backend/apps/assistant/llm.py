"""AI Gateway: единственная точка доступа CRM к языковой модели (п. 2.4, 9.1, 9.11).

- модель меняется переменной окружения (ANTHROPIC_MODEL) или заменой этого модуля — CRM не меняется;
- перед отправкой текст маскируется (ПИН, паспорт, счета, карты);
- учёт расходов и лимит из настроек (п. 9.10);
- без ключа API возвращает None — вызывающий код работает по правилам (режим rules).
"""
import json
import logging

from django.conf import settings

from apps.audit.services import managers, notify
from apps.crm.services import get_settings, update_settings
from apps.crm.utils import mask_pii

log = logging.getLogger(__name__)
# Ориентировочная цена за 1M токенов (вход/выход), USD — для лимита расходов
PRICE_IN, PRICE_OUT = 3.0, 15.0


def available():
    if not settings.ANTHROPIC_API_KEY:
        return False
    s = get_settings()
    if not s["integrations"]["claude"]["enabled"]:
        return False
    return s["ai"]["spent_usd"] < s["ai"]["monthly_limit_usd"]


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def _track(usage):
    try:
        cost = (usage.input_tokens * PRICE_IN + usage.output_tokens * PRICE_OUT) / 1_000_000
        s = get_settings()["ai"]
        spent = round(s["spent_usd"] + cost, 4)
        update_settings({"ai": {"spent_usd": spent}})
        limit = s["monthly_limit_usd"]
        if s["spent_usd"] < 0.8 * limit <= spent:
            notify(managers(), "ai_limit", f"Расходы на AI API достигли 80 % лимита ({spent:.2f} из {limit} $)", "/settings", dedup_key=f"ai80-{limit}")
    except Exception:
        log.exception("usage tracking failed")


def masked(text):
    return mask_pii(text) if get_settings()["ai"]["masking"] else text


def complete_json(system, messages, max_tokens=800):
    """Ответ модели как JSON-объект. messages: [{role, content}] — уже замаскированные."""
    if not available():
        return None
    try:
        resp = _client().messages.create(model=settings.ANTHROPIC_MODEL, max_tokens=max_tokens, system=system, messages=messages)
        _track(resp.usage)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        start, end = text.find("{"), text.rfind("}")
        return json.loads(text[start : end + 1]) if start >= 0 else None
    except Exception:
        log.exception("Claude call failed")
        return None


def run_tools(system, user_text, tools, max_turns=8, on_tool=None):
    """Агентный цикл с инструментами CRM. on_tool(name, input) -> (result: dict, stop: bool)."""
    if not available():
        return None
    client = _client()
    messages = [{"role": "user", "content": masked(user_text)}]
    final_text = ""
    try:
        for _ in range(max_turns):
            resp = client.messages.create(model=settings.ANTHROPIC_MODEL, max_tokens=1200, system=system, tools=tools, messages=messages)
            _track(resp.usage)
            messages.append({"role": "assistant", "content": resp.content})
            uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
            final_text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
            if not uses:
                break
            results, stop = [], False
            for u in uses:
                res, st = on_tool(u.name, u.input)
                stop = stop or st
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": json.dumps(res, ensure_ascii=False, default=str)})
            messages.append({"role": "user", "content": results})
            if stop:
                break
        return final_text
    except Exception:
        log.exception("Claude tool loop failed")
        return None
