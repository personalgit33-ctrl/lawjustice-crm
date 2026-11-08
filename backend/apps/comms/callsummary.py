"""Транскрибация и резюме звонков (п. 9.4).

Распознавание речи — внешний сервис (выбирается Сторонами, п. 11). Подключение: реализовать transcribe(),
вернуть [{speaker, text}]. Резюме строится моделью Claude, без неё — по первым репликам клиента."""
from apps.assistant import llm
from apps.audit.services import audit


def transcribe(call):
    return call.transcript or []


def summarize_call(call):
    tr = transcribe(call)
    if tr and not call.transcript:
        call.transcript = tr
    if not tr:
        if call.record_url or call.recording_id:
            call.summary = call.summary or "Запись сохранена. Расшифровка появится после подключения сервиса распознавания речи."
        call.save(update_fields=["summary", "transcript"])
        return call
    text = "\n".join(f"{x.get('speaker')}: {x.get('text')}" for x in tr)
    out = llm.complete_json(
        "Сделай краткое резюме телефонного разговора юридической компании: суть, договорённости, следующие шаги. Без юридических оценок. Верни JSON {\"summary\": str}.",
        [{"role": "user", "content": llm.masked(text)}],
        max_tokens=400,
    )
    call.summary = (out or {}).get("summary") or " ".join(x["text"] for x in tr if x.get("speaker", "").lower().startswith("клиент"))[:400]
    call.save(update_fields=["summary", "transcript"])
    audit(None, "Сохранил расшифровку и резюме звонка", f"{call.client.name if call.client else call.phone}", is_ai=True, type="ai", client_id=call.client_id)
    return call
