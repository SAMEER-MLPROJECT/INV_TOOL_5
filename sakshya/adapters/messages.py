from __future__ import annotations

import re
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime

from sakshya.adapters.base import AMOUNT_PATTERN, AdapterContext, ParseResult, Record, mentions

IP_IN_HEADER = re.compile(r"\[?(\d{1,3}(?:\.\d{1,3}){3})\]?")
ACCOUNT_DIGITS = re.compile(r"(?<!\d)(\d{9,18})(?!\d)")


def parse_email(ctx: AdapterContext) -> ParseResult:
    result = ParseResult()
    raw_bytes = ctx.path.read_bytes()
    message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    date_header = message.get("Date")
    t = parsedate_to_datetime(str(date_header)).timestamp() if date_header else None
    if message.is_multipart():
        part = message.get_body(preferencelist=("plain", "html"))
        body = part.get_content() if part is not None else ""
    else:
        body = message.get_content()
    record = Record(row=1, kind="email", t_raw=t, raw=raw_bytes.decode("utf-8", errors="replace"), text=str(body).strip())
    for _, address in getaddresses([str(message.get("From", ""))]):
        record.add_id("from", "email", address)
    for _, address in getaddresses([str(message.get("To", "")), str(message.get("Cc", ""))]):
        record.add_id("to", "email", address)
    origin = message.get("X-Originating-IP")
    if origin:
        found = IP_IN_HEADER.search(str(origin))
        if found:
            record.add_id("sender_ip", "ip", found.group(1))
    else:
        received = message.get_all("Received") or []
        if received:
            found = IP_IN_HEADER.search(str(received[-1]))
            if found:
                record.add_id("sender_ip", "ip", found.group(1))
    record.attrs = {"subject": str(message.get("Subject", "")), "message_id": str(message.get("Message-ID", ""))}
    mentions(record, record.text)
    result.records.append(record)
    return result


def _narrative(ctx: AdapterContext, kind: str, header_key: str) -> ParseResult:
    result = ParseResult()
    lines = ctx.path.read_text(encoding="utf-8-sig").splitlines()
    filed = None
    fields = {}
    for line in lines:
        key, sep, value = line.partition(":")
        if sep and key.strip() and len(key) < 40 and not fields.get(key.strip().lower()):
            fields[key.strip().lower()] = value.strip()
    stamp = fields.get(header_key)
    if stamp:
        try:
            filed = ctx.parse_time(stamp)
        except ValueError as exc:
            result.warnings.append(str(exc))
    text = "\n".join(lines)
    record = Record(row=1, kind=kind, t_raw=filed, raw=text, text=text, sigma_t=float(ctx.colmap.get("sigma_s", 1800)))
    mentions(record, text)
    for line in lines:
        if line.lower().startswith(("mera account", "my account", "account:", "a/c")):
            for digits in ACCOUNT_DIGITS.findall(line):
                record.attrs.setdefault("account_digits", []).append(digits)
    amounts = [float(m.replace(",", "")) for m in AMOUNT_PATTERN.findall(text)]
    if amounts:
        record.attrs["amounts"] = amounts
    record.attrs.update({k: v for k, v in fields.items() if k in {"category", "acknowledgement no", "complainant"}})
    result.records.append(record)
    return result


def parse_complaint(ctx: AdapterContext) -> ParseResult:
    return _narrative(ctx, "complaint", "filed")


def parse_statement(ctx: AdapterContext) -> ParseResult:
    return _narrative(ctx, "testimony", "recorded")
