import re
from datetime import timedelta
from difflib import SequenceMatcher

from django.utils import timezone

MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

_LAT2CYR = [
    ("shch", "щ"), ("sch", "щ"), ("yo", "е"), ("zh", "ж"), ("kh", "х"), ("ts", "ц"), ("ch", "ч"), ("sh", "ш"),
    ("yu", "ю"), ("ya", "я"), ("a", "а"), ("b", "б"), ("v", "в"), ("g", "г"), ("d", "д"), ("e", "е"), ("z", "з"),
    ("i", "и"), ("y", "ы"), ("k", "к"), ("l", "л"), ("m", "м"), ("n", "н"), ("o", "о"), ("p", "п"), ("r", "р"),
    ("s", "с"), ("t", "т"), ("u", "у"), ("f", "ф"), ("h", "х"), ("c", "к"), ("w", "в"), ("x", "кс"), ("q", "к"), ("j", "дж"),
]
_ORG_WORDS = {"осоо", "ооо", "оао", "зао", "ао", "ип", "чп", "llc", "ltd", "фирма", "компания"}


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0") and len(digits) == 10:  # 0555123456 → 996555123456
        digits = "996" + digits[1:]
    return digits[-12:] if digits else ""


def _translit(s: str) -> str:
    for lat, cyr in _LAT2CYR:
        s = s.replace(lat, cyr)
    return s


def normalize_name(name: str) -> str:
    """Нормализация ФИО / наименования для поиска конфликтов: регистр, ё/е, латиница→кириллица,
    кавычки и орг. формы, порядок слов (Садыков Тимур == Тимур Садыков)."""
    s = (name or "").lower().replace("ё", "е")
    s = re.sub(r"[«»\"'.,()\-]", " ", s)
    s = _translit(s)
    # кыргызские буквы к русским аналогам
    s = s.replace("ү", "у").replace("ө", "о").replace("ң", "н")
    tokens = [t for t in s.split() if t and t not in _ORG_WORDS]
    return " ".join(sorted(tokens))


def names_match(a_norm: str, b_norm: str) -> bool:
    if not a_norm or not b_norm:
        return False
    if a_norm == b_norm:
        return True
    a, b = set(a_norm.split()), set(b_norm.split())
    # «Садыков Тимур» ⊂ «Садыков Тимур Асанович»
    if len(a) >= 2 and len(b) >= 2 and (a <= b or b <= a):
        return True
    if min(len(a), len(b)) == 1 and (len(a_norm) < 4 or len(b_norm) < 4):
        return False
    return SequenceMatcher(None, a_norm, b_norm).ratio() >= 0.86


def mask_pii(text: str) -> str:
    """Маскирование перед передачей в языковую модель (п. 9.11.2)."""
    if not text:
        return text
    text = re.sub(r"\b\d{14}\b", "[ПИН]", text)  # ПИН КР — 14 цифр
    text = re.sub(r"\b(?:\d[ -]?){16,19}\b", "[КАРТА/СЧЁТ]", text)
    text = re.sub(r"\b[A-ZА-Я]{2}\s?\d{6,7}\b", "[ПАСПОРТ]", text)
    text = re.sub(r"\bKG\d{2}[A-Z0-9]{10,30}\b", "[СЧЁТ]", text)
    return text


def due_label(dt, with_time=True) -> str:
    if not dt:
        return "—"
    dt = timezone.localtime(dt)
    today = timezone.localdate()
    d = dt.date()
    t = dt.strftime("%H:%M")
    has_time = with_time and t != "00:00" and t != "23:59"
    if d == today:
        base = "Сегодня"
    elif d == today - timedelta(days=1):
        base = "Вчера"
    elif d == today + timedelta(days=1):
        base = "Завтра"
    else:
        base = f"{d.day} {MONTHS[d.month - 1]}"
        if d.year != today.year:
            base += f" {d.year}"
    return f"{base}, {t}" if has_time else base


def rel_label(dt) -> str:
    """«10:42», «Вчера», «Пн», «26 сен» — для списков."""
    if not dt:
        return ""
    dt = timezone.localtime(dt)
    today = timezone.localdate()
    d = dt.date()
    if d == today:
        return dt.strftime("%H:%M")
    if d == today - timedelta(days=1):
        return "Вчера"
    if (today - d).days < 7:
        return WEEKDAYS[d.weekday()]
    return f"{d.day} {MONTHS[d.month - 1]}"


def initials(name: str) -> str:
    parts = [p for p in re.sub(r"[«»\"]|ОсОО |ООО ", "", name or "").split() if p]
    return "".join(p[0] for p in parts[:2]).upper()
