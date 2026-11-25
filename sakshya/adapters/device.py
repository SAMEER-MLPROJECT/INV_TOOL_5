from __future__ import annotations

import json
import re

from sakshya.adapters.base import AMOUNT_PATTERN, AdapterContext, ParseResult, Record, get, mentions, read_rows, to_float
from sakshya.core.identifiers import canonical_phone
from sakshya.core.timeutil import parse_local

ALERT_ACCOUNT = re.compile(r"A/c\s*(?:No\.?\s*)?[X*]+(\d{3,6})", re.IGNORECASE)
ALERT_REF = re.compile(r"(?:UPI\s*Ref(?:\s*No)?|Ref\s*No|RRN)[\s:.]*([0-9]{8,14})", re.IGNORECASE)
CHAT_LINE = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4}),\s*(\d{1,2}:\d{2}(?::\d{2})?\s*(?:[aApP]\.?\s?[mM]\.?)?)\s*-\s*([^:]+?):\s(.*)$"
)


def _owner(ctx: AdapterContext) -> str | None:
    return canonical_phone(ctx.entry.get("owner", ""))


def parse_call_log(ctx: AdapterContext) -> ParseResult:
    result = ParseResult()
    owner = _owner(ctx)
    for line_no, row, raw in read_rows(ctx):
        try:
            t = ctx.parse_time(get(ctx, row, "time"))
        except ValueError as exc:
            result.warnings.append(f"row {line_no}: {exc}")
            continue
        number = canonical_phone(get(ctx, row, "number"))
        kind = get(ctx, row, "type").lower()
        record = Record(row=line_no, kind="call", t_raw=t, raw=raw, duration_s=to_float(get(ctx, row, "duration")))
        record.direction = "out" if kind.startswith("out") else "in"
        if owner:
            record.add_id("from" if record.direction == "out" else "to", "phone", owner)
        if number:
            record.add_id("to" if record.direction == "out" else "from", "phone", number)
        if owner and number:
            record.anchors.append("call:" + "|".join(sorted([owner, number])))
        record.attrs = {"call_type": kind}
        result.records.append(record)
    if owner:
        result.meta["subject"] = [("phone", owner)]
    return result


def parse_sms(ctx: AdapterContext) -> ParseResult:
    result = ParseResult()
    owner = _owner(ctx)
    for line_no, row, raw in read_rows(ctx):
        try:
            t = ctx.parse_time(get(ctx, row, "time"))
        except ValueError as exc:
            result.warnings.append(f"row {line_no}: {exc}")
            continue
        sender_raw = get(ctx, row, "sender")
        body = get(ctx, row, "body")
        sender = canonical_phone(sender_raw)
        inbound = get(ctx, row, "direction").lower() in {"", "inbox", "in", "received"}
        record = Record(row=line_no, kind="sms", t_raw=t, raw=raw, text=body, direction="in" if inbound else "out")
        if owner:
            record.add_id("to" if inbound else "from", "phone", owner)
        if sender:
            record.add_id("from" if inbound else "to", "phone", sender)
        elif sender_raw:
            record.add_id("from", "sender", sender_raw)
        amount_match = AMOUNT_PATTERN.search(body)
        account_match = ALERT_ACCOUNT.search(body)
        ref_match = ALERT_REF.search(body)
        if amount_match and account_match and "debit" in body.lower():
            amount = float(amount_match.group(1).replace(",", ""))
            record.amount = amount
            record.anchors.append(f"amt:{amount:.2f}|a4:{account_match.group(1)[-4:]}")
            record.attrs["bank_alert"] = True
        if ref_match:
            record.anchors.append(f"ref:{ref_match.group(1)}")
        if "otp" in body.lower():
            record.attrs["otp"] = True
        if owner and (sender or sender_raw):
            record.anchors.append("sms:" + "|".join(sorted([owner, sender or sender_raw.lower()])))
        mentions(record, body)
        result.records.append(record)
    if owner:
        result.meta["subject"] = [("phone", owner)]
    return result


def _chat_time(ctx: AdapterContext, date: str, clock: str) -> float:
    clock = clock.replace(".", "").replace(" ", " ").strip().upper()
    for fmt in (ctx.time_format or "", "%d/%m/%y, %I:%M %p", "%d/%m/%Y, %I:%M %p", "%d/%m/%y, %H:%M", "%d/%m/%Y, %H:%M"):
        if not fmt:
            continue
        try:
            return parse_local(f"{date}, {clock}", fmt, ctx.tz)
        except ValueError:
            continue
    raise ValueError(f"unrecognised chat time '{date}, {clock}'")


def parse_chat(ctx: AdapterContext) -> ParseResult:
    result = ParseResult()
    owner = _owner(ctx)
    owner_name = str(ctx.entry.get("owner_name", "")).strip().lower()
    other_default = canonical_phone(ctx.entry.get("other", ""))
    lines = ctx.path.read_text(encoding="utf-8-sig").splitlines()
    current: Record | None = None
    for line_no, line in enumerate(lines, start=1):
        match = CHAT_LINE.match(line)
        if not match:
            if current is not None and line.strip():
                current.text += "\n" + line
                current.raw += "\n" + line
            continue
        date, clock, speaker, body = match.groups()
        try:
            t = _chat_time(ctx, date, clock)
        except ValueError as exc:
            result.warnings.append(f"line {line_no}: {exc}")
            continue
        speaker_phone = canonical_phone(speaker)
        from_owner = speaker.strip().lower() == owner_name or (owner is not None and speaker_phone == owner)
        other = speaker_phone if (speaker_phone and not from_owner) else other_default
        current = Record(row=line_no, kind="chat", t_raw=t, raw=line, text=body, direction="out" if from_owner else "in")
        if from_owner:
            if owner:
                current.add_id("from", "phone", owner)
            if other:
                current.add_id("to", "phone", other)
        else:
            if other:
                current.add_id("from", "phone", other)
            if owner:
                current.add_id("to", "phone", owner)
        lowered = body.lower()
        if "video call" in lowered or "voice call" in lowered:
            current.attrs["call_notice"] = True
        mentions(current, body)
        result.records.append(current)
    if owner:
        result.meta["subject"] = [("phone", owner)]
    return result


def parse_cloud_location(ctx: AdapterContext) -> ParseResult:
    result = ParseResult()
    payload = json.loads(ctx.path.read_text(encoding="utf-8"))
    account = payload.get("account", "")
    device_phone = (payload.get("device") or {}).get("phone", "")
    header = Record(row=0, kind="account_link", t_raw=None, raw=json.dumps({"account": account, "device": payload.get("device")}))
    header.add_id("subject", "cloud", account)
    header.add_id("device_phone", "phone", device_phone)
    result.records.append(header)
    for index, item in enumerate(payload.get("locations", []), start=1):
        stamp = item.get("timestamp") or item.get("timestampMs")
        if stamp is None:
            continue
        t = int(stamp) / 1000.0 if str(stamp).isdigit() else parse_local(str(stamp), None, ctx.tz)
        lat = item.get("latitudeE7", 0) / 1e7 if "latitudeE7" in item else item.get("lat")
        lon = item.get("longitudeE7", 0) / 1e7 if "longitudeE7" in item else item.get("lon")
        record = Record(
            row=index,
            kind="location",
            t_raw=t,
            raw=json.dumps(item, sort_keys=True),
            lat=lat,
            lon=lon,
            radius_m=float(item.get("accuracy", 50)),
            place="cloud location",
        )
        record.add_id("subject", "cloud", account)
        result.records.append(record)
    result.meta["subject"] = [("cloud", account)]
    return result
