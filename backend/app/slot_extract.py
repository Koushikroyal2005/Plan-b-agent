"""Shared slot extraction for assistant + planner (dates, titles, duration)."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def normalize_meridiems(text: str) -> str:
    text = re.sub(r"\ba\.?\s*m\.?(?=\W|$)", "am", text, flags=re.I)
    text = re.sub(r"\bp\.?\s*m\.?(?=\W|$)", "pm", text, flags=re.I)
    return text


def has_explicit_clock(text: str) -> bool:
    return bool(re.search(r"\b(?:at|from)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", text, re.I))


def parse_duration(text: str) -> int | None:
    hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|hr)\b", text, re.I)
    minutes = re.search(r"(\d+)\s*(?:minutes?|mins?|min)\b", text, re.I)
    total = 0
    if hours:
        total += round(float(hours.group(1)) * 60)
    if minutes:
        total += int(minutes.group(1))
    return min(720, max(5, total)) if total else None


def parse_range_duration(text: str) -> int | None:
    text = normalize_meridiems(text)
    match = re.search(
        r"\bfrom\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s+(?:to|until|till)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
        text, re.I,
    )
    if not match:
        return None
    start_h, start_m = int(match.group(1)), int(match.group(2) or 0)
    end_h, end_m = int(match.group(4)), int(match.group(5) or 0)
    start_meridiem = (match.group(3) or match.group(6)).lower()
    end_meridiem = match.group(6).lower()
    if start_meridiem == "pm" and start_h < 12:
        start_h += 12
    if start_meridiem == "am" and start_h == 12:
        start_h = 0
    if end_meridiem == "pm" and end_h < 12:
        end_h += 12
    if end_meridiem == "am" and end_h == 12:
        end_h = 0
    minutes = end_h * 60 + end_m - (start_h * 60 + start_m)
    return minutes if 5 <= minutes <= 720 else None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_calendar_date(text: str, *, today: date | None = None) -> date | None:
    """Parse absolute dates like 25th Oct, October 25, 2026-10-25."""
    today = today or date.today()
    lower = text.lower()

    iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", lower)
    if iso:
        return _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))

    # 25th october / 25 oct 2026
    dmy = re.search(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_ALT})(?:\s+(\d{{4}}))?\b",
        lower,
    )
    if dmy:
        day_n, month_n = int(dmy.group(1)), MONTHS[dmy.group(2)]
        year = int(dmy.group(3)) if dmy.group(3) else today.year
        value = _safe_date(year, month_n, day_n)
        if value and value < today and not dmy.group(3):
            value = _safe_date(year + 1, month_n, day_n)
        return value

    # october 25th / oct 25, 2026
    mdy = re.search(
        rf"\b({_MONTH_ALT})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{{4}}))?\b",
        lower,
    )
    if mdy:
        month_n, day_n = MONTHS[mdy.group(1)], int(mdy.group(2))
        year = int(mdy.group(3)) if mdy.group(3) else today.year
        value = _safe_date(year, month_n, day_n)
        if value and value < today and not mdy.group(3):
            value = _safe_date(year + 1, month_n, day_n)
        return value

    # 25/10/2026 or 25-10-2026 (day-first)
    slash = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", lower)
    if slash:
        return _safe_date(int(slash.group(3)), int(slash.group(2)), int(slash.group(1)))

    return None


def mentions_unresolved_date(text: str) -> bool:
    """True when the user said a calendar-ish date we should not silently ignore."""
    lower = text.lower()
    if parse_calendar_date(lower):
        return False
    if re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_ALT})\b", lower):
        return True
    if re.search(rf"\b({_MONTH_ALT})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", lower):
        return True
    return False


def parse_when(text: str, *, today: date | None = None) -> str | None:
    """Return local ISO datetime YYYY-MM-DDTHH:MM or None."""
    today = today or date.today()
    lower = normalize_meridiems(text.lower())
    target: date | None = None

    if "day after tomorrow" in lower or "after tomorrow" in lower:
        target = today + timedelta(days=2)
    elif "tomorrow" in lower:
        target = today + timedelta(days=1)
    elif "today" in lower or "tonight" in lower:
        target = today
    else:
        target = parse_calendar_date(lower, today=today)

    if target is None:
        return None

    clock = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lower)
    if not clock:
        return f"{target.isoformat()}T18:00"
    hour, minute, meridiem = int(clock.group(1)), int(clock.group(2) or 0), clock.group(3)
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return f"{target.isoformat()}T{hour:02d}:{minute:02d}"


def parse_title(text: str) -> str | None:
    raw = normalize_meridiems(text)

    trailing = re.search(
        r"^\s*task\b.*?\bfor\s+\d+(?:\.\d+)?\s*(?:hours?|hrs?|minutes?|mins?)\s+(.+)$",
        raw, re.I,
    )
    if trailing:
        value = clean(re.sub(r"^(?:to|on)\s+", "", trailing.group(1), flags=re.I).strip(" .,-"))
        value = clean(_strip_timing_tail(value))
        if value:
            return value[:160]

    called = re.search(
        r"\b(?:task|schedule|block)\s+(?:called|named|of)\s+([a-zA-Z][\w\s-]{0,40})",
        raw, re.I,
    )
    if called:
        value = clean(_strip_timing_tail(called.group(1)))
        if value:
            return value[:160]

    create_noun_task = re.search(
        r"\b(?:create|add|make|build)\s+(?:a|an)\s+([a-zA-Z][\w-]{1,40})\s+task\b",
        raw, re.I,
    )
    if create_noun_task:
        value = clean(create_noun_task.group(1))
        if value.lower() not in {"new", "quick", "small", "big"}:
            return value[:160]

    known = re.search(
        r"\b((?:my\s+)?(?:homework|assignment|essay|project report|study(?:ing)?|gym|workout|meeting|doctor|dentist))\b",
        raw, re.I,
    )
    if known:
        return clean(known.group(1))[:160]

    body = re.sub(
        r"^\s*(?:(?:then|so|please|okay|ok)[, ]+)*(?:can you|could you|would you|i want you to|i want|i need)\s*",
        "", raw, flags=re.I,
    )
    body = re.sub(
        r"^\s*(?:please\s+)?(?:create|add|make|build)\s+(?:a\s+|an\s+)?(?:\d+(?:\.\d+)?\s*(?:hours?|hrs?|minutes?|mins?)\s+)?(?:task|schedule)\b",
        "", body, flags=re.I,
    )
    body = re.sub(r"^\s*(?:remind me to|i need to)\s+", "", body, flags=re.I)
    body = re.sub(r"^\s*(?:called|named|to|for|of)\b\s*", "", body, flags=re.I)
    body = re.sub(r"\b(?:a\s+|an\s+)?(?:task|schedule|block)\b", " ", body, flags=re.I)
    body = _strip_timing_tail(body)
    value = clean(body.strip(" .,-"))
    if re.search(r"\b(can you|create|schedule for|want you)\b", value, re.I):
        return None
    if re.fullmatch(
        r"(?:\d+(?:\.\d+)?\s*(?:hours?|hrs?|minutes?|mins?|min|hrs?)\s*)+",
        value,
        re.I,
    ):
        return None
    if re.fullmatch(rf"(?:\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH_ALT})|{_MONTH_ALT}\s+\d{{1,2}}(?:st|nd|rd|th)?)", value, re.I):
        return None
    return value[:160] if value and value.lower() not in {"a task", "task", "it", "schedule", "a schedule"} else None


def _strip_timing_tail(value: str) -> str:
    value = re.split(
        r"\b(?:for\s+\d|lasting\s+\d|due\b|by\b|on\s+\d|on\s+(?:"
        + _MONTH_ALT
        + r")|day after tomorrow\b|after tomorrow\b|today\b|tomorrow\b|tonight\b|at\s+\d|from\s+\d)",
        value,
        maxsplit=1,
        flags=re.I,
    )[0]
    value = re.sub(
        rf"\b(?:on\s+)?(?:\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH_ALT})|(?:{_MONTH_ALT})\s+\d{{1,2}}(?:st|nd|rd|th)?)(?:\s+\d{{4}})?\b",
        " ",
        value,
        flags=re.I,
    )
    return value


def pin_day_placement(slots: dict[str, Any], *, day_start: str = "09:00", text: str = "") -> dict[str, Any]:
    deadline = slots.get("deadline") or slots.get("fixed_start")
    if not deadline:
        return slots
    if has_explicit_clock(text):
        if slots.get("fixed_start"):
            slots["flexibility"] = "fixed"
        return slots
    day = str(deadline).split("T", 1)[0]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return slots
    hhmm = day_start if re.fullmatch(r"\d{1,2}:\d{2}", day_start or "") else "09:00"
    hour, minute = hhmm.split(":")
    pinned = f"{day}T{int(hour):02d}:{minute}"
    slots["deadline"] = pinned
    slots["fixed_start"] = pinned
    slots["flexibility"] = "fixed"
    return slots


def extract_task_slots(text: str, *, day_start: str = "09:00") -> dict[str, Any]:
    start = parse_when(text)
    fixed = bool(start and has_explicit_clock(text))
    slots = {
        "title": parse_title(text),
        "duration_minutes": parse_range_duration(text) or parse_duration(text),
        "deadline": start,
        "fixed_start": start if fixed else None,
        "flexibility": "fixed" if fixed else "flexible",
    }
    if start and not fixed:
        slots = pin_day_placement(slots, day_start=day_start, text=text)
    return slots
