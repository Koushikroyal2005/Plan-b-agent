"""Small, deterministic language helpers shared by the rules interpreter and slot filling."""

from __future__ import annotations

import re
from datetime import date, time, timedelta

WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
    "twenty": 20, "twenty five": 25, "thirty": 30, "forty": 40, "forty five": 45,
    "fifty": 50, "sixty": 60, "ninety": 90,
}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def normalize(text: str) -> str:
    value = text.replace("\u2019", "'").replace("\u2018", "'").lower()
    value = re.sub(r"\s+", " ", value).strip()
    return value.strip(" .!?,")


def _words_to_digits(text: str) -> str:
    value = text.replace("-", " ")
    for word, number in sorted(WORD_NUMBERS.items(), key=lambda item: -len(item[0])):
        value = re.sub(rf"\b{word}\b", str(number), value)
    return value


def duration_minutes(text: str) -> int | None:
    value = _words_to_digits(normalize(text))
    if re.search(r"\b(an|one|1) hour and (a )?half\b|\b(1|one) and a half hours?\b", value):
        return 90
    if re.search(r"\bhalf (an )?hour\b", value):
        return 30
    total = 0
    hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|hr|h)\b", value)
    if hours:
        total += round(float(hours.group(1)) * 60)
    elif re.search(r"\b(an|a) hour\b", value):
        total += 60
    minutes = re.search(r"(\d+)\s*(?:minutes?|mins?|min|m)\b", value)
    if minutes:
        total += int(minutes.group(1))
    return min(720, max(5, total)) if total else None


def _clock(hour: int, minute: int, meridiem: str | None) -> time | None:
    if meridiem:
        meridiem = meridiem.replace(".", "")
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
    elif 1 <= hour <= 7:
        hour += 12
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def clock_time(text: str) -> time | None:
    value = _words_to_digits(normalize(text))
    if re.search(r"\bnoon\b|\bmidday\b", value):
        return time(12)
    if re.search(r"\bend of (the )?day\b|\btonight\b", value) and not re.search(r"\d", value):
        return time(21)
    explicit = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\b\.?|p\.?m\b\.?)", value)
    if explicit:
        return _clock(int(explicit.group(1)), int(explicit.group(2) or 0), explicit.group(3))
    anchored = re.search(
        r"\b(?:at|by|before|until|till|around|after|from)\s+(\d{1,2})(?::(\d{2}))?(?:\s*o'?clock)?\b(?!\s*(?:min|minute|hour|hr|h\b))",
        value,
    )
    if anchored:
        return _clock(int(anchored.group(1)), int(anchored.group(2) or 0), None)
    military = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", value)
    if military:
        return time(int(military.group(1)), int(military.group(2)))
    return None


def day_reference(text: str, today: date) -> date | None:
    value = normalize(text)
    if "day after tomorrow" in value:
        return today + timedelta(days=2)
    if re.search(r"\btomorrow\b|\btmrw\b|\btmr\b", value):
        return today + timedelta(days=1)
    if re.search(r"\btoday\b|\btonight\b|\bthis (evening|afternoon|morning)\b", value):
        return today
    iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", value)
    if iso:
        try:
            return date.fromisoformat(iso.group(1))
        except ValueError:
            return None
    for index, name in enumerate(WEEKDAYS):
        if re.search(rf"\b{name}\b", value):
            ahead = (index - today.weekday()) % 7 or 7
            return today + timedelta(days=ahead)
    return None


def datetime_reference(text: str, today: date, default_clock: time = time(18)) -> str | None:
    """ISO local datetime for phrases such as 'tomorrow at 10 am' or 'before 6'."""
    day = day_reference(text, today)
    moment = clock_time(text)
    if not day and not moment:
        return None
    chosen = moment or default_clock
    return f"{(day or today).isoformat()}T{chosen.hour:02d}:{chosen.minute:02d}"


MERIDIEM = r"(?:\s*(?:a\.?m\b\.?|p\.?m\b\.?))?"
CLOCK = rf"\d{{1,2}}(?::\d{{2}})?{MERIDIEM}"
GENERIC_TITLES = {"", "task", "a task", "new task", "schedule", "a schedule", "something", "it", "event", "block", "slot", "time"}


def task_details(text: str, today: date) -> dict[str, object]:
    """Pull title, duration, fixed start and deadline out of one task request."""
    lower = normalize(text)
    if re.search(r"(?<!day )\bafter tomorrow\b", lower):
        lower = re.sub(r"(?<!day )\bafter tomorrow\b", "day after tomorrow", lower)
    day = day_reference(lower, today)
    fixed_start = deadline = None
    minutes = duration_minutes(lower)
    span = re.search(rf"\bfrom\s+({CLOCK})\s+(?:to|until|till|-)\s+({CLOCK})", lower)
    if span:
        start, end = clock_time(f"at {span.group(1)}"), clock_time(f"at {span.group(2)}")
        if start and end:
            gap = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
            minutes = minutes or (gap if gap > 0 else gap + 720 if gap + 720 > 0 else None)
            fixed_start = f"{(day or today).isoformat()}T{start.hour:02d}:{start.minute:02d}"
    if not fixed_start:
        at = re.search(rf"(?<!due )(?<!by )(?<!before )\bat\s+({CLOCK})", lower)
        if at and re.search(r"\d", at.group(1)):
            moment = clock_time(f"at {at.group(1)}")
            if moment:
                fixed_start = f"{(day or today).isoformat()}T{moment.hour:02d}:{moment.minute:02d}"
    due = re.search(rf"\b(?:due|by|before)\s+(.+)$", lower)
    if due:
        deadline = datetime_reference(due.group(1), day or today)
    elif day and not fixed_start:
        deadline = f"{day.isoformat()}T18:00"

    title = re.sub(r"^.*?\b(?:task|remind me to|i need to)\b\s*", "", lower, count=1) if re.search(
        r"\b(?:task|remind me to|i need to)\b", lower) else lower
    removals = [
        rf"\bfrom\s+{CLOCK}\s+(?:to|until|till|-)\s+{CLOCK}",
        rf"\b(?:due|by|before)\b.*$",
        rf"\b(?:at|around)\s+{CLOCK}",
        r"\b(?:for\s+)?(?:\d+(?:\.\d+)?|an?|half an?)\s*(?:hours?|hrs?|hr|h|minutes?|mins?|min)\b(?:\s+long)?",
        r"\b(?:on\s+)?(?:the\s+)?day after tomorrow\b|\btomorrow\b|\btoday\b|\btonight\b|\bthis (?:morning|afternoon|evening)\b",
        r"\b(?:on\s+)?(?:next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b(?:high|low|medium)\s+priority\b|\burgent\b",
        r"^(?:please\s+)?(?:can you\s+)?(?:create|add|make|schedule|book|block|put|new)\b",
        r"^\s*(?:a|an|the|new)\b",
        r"^\s*(?:schedule|block|slot|session|event)\b",
        r"^\s*(?:called|named|to|for|about|:)\b",
        r"\bto my (?:list|tasks|day|calendar)\b",
    ]
    for pattern in removals:
        title = re.sub(pattern, " ", title).strip()
    title = re.sub(r"\s+", " ", title).strip(" .,-:")
    title = re.sub(r"^(?:a|an|the|to|for|called|named)\s+", "", title)
    original = re.search(re.escape(title), text, re.I) if title else None
    title = original.group(0) if original else title
    return {
        "title": None if title.lower() in GENERIC_TITLES else title[:160],
        "duration_minutes": minutes,
        "fixed_start": fixed_start,
        "deadline": deadline,
    }


def ordinal(text: str) -> int | None:
    value = normalize(text)
    table = [
        (r"\b(second|2nd|option b)\b", 1),
        (r"\b(third|3rd|option c)\b", 2),
        (r"\b(fourth|4th)\b", 3),
        (r"\b(last)\b", -1),
        (r"\b(first|1st|option a|top)\b", 0),
        (r"\b(two|2)\b", 1),
        (r"\b(three|3)\b", 2),
        (r"\b(one|1)\b", 0),
    ]
    for pattern, index in table:
        if re.search(pattern, value):
            return index
    return None


def strip_filler(phrase: str) -> str:
    value = normalize(phrase)
    value = re.sub(r"^(?:the|my|a|an|that|this)\s+", "", value)
    value = re.sub(
        r"\s+(?:instead|please|today|then|as well|too|for now|for me|anymore|now|task|block|session)$",
        "",
        value,
    )
    value = re.sub(r"^(?:the|my)\s+", "", value)
    return value.strip(" .,'\"")
