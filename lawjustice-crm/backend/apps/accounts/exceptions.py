from rest_framework.views import exception_handler


def _flatten(data):
    if isinstance(data, dict):
        if "detail" in data and isinstance(data["detail"], str):
            return data["detail"]
        parts = []
        for k, v in data.items():
            msg = _flatten(v)
            parts.append(msg if k in ("non_field_errors", "detail") else f"{k}: {msg}")
        return "; ".join(parts)
    if isinstance(data, list):
        return "; ".join(_flatten(x) for x in data)
    return str(data)


def handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None and isinstance(response.data, (dict, list)):
        data = response.data if isinstance(response.data, dict) else {}
        extra = {k: v for k, v in data.items() if k not in ("detail",) and not isinstance(v, list)}
        response.data = {"detail": _flatten(response.data), **({"fields": data} if data and "detail" not in data else {}), **{k: v for k, v in extra.items() if k == "otp_required"}}
    return response
