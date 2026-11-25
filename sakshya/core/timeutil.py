from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")
UTC = UTC

_OFFSET = re.compile(r"^(?:UTC)?([+-])(\d{1,2}):?(\d{2})$")


def tz_from_spec(spec: str | None) -> timezone:
    if spec is None:
        return IST
    text = str(spec).strip()
    if text.upper() in {"UTC", "Z", "GMT"}:
        return UTC
    if text.upper() in {"IST", "ASIA/KOLKATA", "ASIA/CALCUTTA"}:
        return IST
    match = _OFFSET.match(text)
    if not match:
        raise ValueError(f"Unsupported time zone '{spec}'")
    sign, hours, minutes = match.groups()
    delta = timedelta(hours=int(hours), minutes=int(minutes))
    return timezone(delta if sign == "+" else -delta)


def parse_local(value: str, fmt: str | None, tz: timezone) -> float:
    text = str(value).strip()
    moment = datetime.strptime(text, fmt) if fmt else datetime.fromisoformat(text.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz)
    return moment.timestamp()


def fmt_ist(value: float | None, seconds: bool = True) -> str:
    if value is None:
        return ""
    moment = datetime.fromtimestamp(value, tz=IST)
    return moment.strftime("%Y-%m-%d %H:%M:%S" if seconds else "%Y-%m-%d %H:%M")


def describe_duration(seconds: float) -> str:
    total = int(round(abs(seconds)))
    sign = "-" if seconds < 0 else "+"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{sign}{hours} h {minutes:02d} min"
    if minutes:
        return f"{sign}{minutes} min {secs:02d} s"
    return f"{sign}{secs} s"
