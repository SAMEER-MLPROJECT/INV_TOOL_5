from __future__ import annotations

from sakshya.adapters.base import AdapterContext, ParseResult, Record, get, read_rows, to_float
from sakshya.core.identifiers import canonical_phone


def _pair(a: str, b: str) -> str:
    return "|".join(sorted([a, b]))


def parse_cdr(ctx: AdapterContext) -> ParseResult:
    result = ParseResult()
    subjects: set[str] = set()
    for line_no, row, raw in read_rows(ctx):
        try:
            t = ctx.parse_time(get(ctx, row, "time"))
        except ValueError as exc:
            result.warnings.append(f"row {line_no}: {exc}")
            continue
        msisdn = canonical_phone(get(ctx, row, "msisdn"))
        other_raw = get(ctx, row, "other")
        other = canonical_phone(other_raw)
        call_type = get(ctx, row, "call_type").upper()
        family, _, leg = call_type.partition("-")
        if family == "VOICE":
            kind = "call"
        elif family == "SMS":
            kind = "sms"
        elif family == "NETWORK":
            kind = "network_event"
        else:
            kind = "presence"
        record = Record(row=line_no, kind=kind, t_raw=t, raw=raw, duration_s=to_float(get(ctx, row, "duration")))
        record.direction = "out" if leg == "MO" else "in" if leg == "MT" else ""
        subject_role = "from" if leg == "MO" else "to" if leg == "MT" else "subject"
        other_role = "to" if leg == "MO" else "from" if leg == "MT" else "other"
        if msisdn:
            subjects.add(msisdn)
            record.add_id(subject_role, "phone", msisdn)
        if other:
            record.add_id(other_role, "phone", other)
        elif other_raw and kind in {"sms", "call"}:
            record.add_id(other_role, "sender", other_raw)
        record.add_id("device", "imei", get(ctx, row, "imei"))
        record.add_id("sim", "imsi", get(ctx, row, "imsi"))
        cell = get(ctx, row, "cell")
        if cell:
            record.add_id("cell", "cell", cell)
            record.place = cell
        if kind in {"call", "sms"} and msisdn and (other or other_raw):
            record.anchors.append(f"{kind}:{_pair(msisdn, other or other_raw.lower())}")
        record.attrs = {
            "call_type": call_type,
            "record_id": get(ctx, row, "record_id"),
            "other_raw": other_raw,
            "subscriber": msisdn or "",
        }
        if kind == "network_event":
            record.attrs["event"] = other_raw
        result.records.append(record)
    result.meta["subject"] = [("phone", s) for s in sorted(subjects)]
    return result


def parse_tower_list(ctx: AdapterContext) -> ParseResult:
    result = ParseResult()
    for line_no, row, _ in read_rows(ctx):
        cell = get(ctx, row, "cell")
        lat, lon = to_float(get(ctx, row, "lat")), to_float(get(ctx, row, "lon"))
        if not cell or lat is None or lon is None:
            result.warnings.append(f"row {line_no}: incomplete cell site")
            continue
        result.towers[cell] = {
            "lat": lat,
            "lon": lon,
            "radius_m": to_float(get(ctx, row, "radius")) or 1000.0,
            "label": get(ctx, row, "address") or cell,
        }
    return result


def parse_tower_dump(ctx: AdapterContext) -> ParseResult:
    result = ParseResult()
    cells: set[str] = set()
    for line_no, row, raw in read_rows(ctx):
        try:
            t = ctx.parse_time(get(ctx, row, "time"))
        except ValueError as exc:
            result.warnings.append(f"row {line_no}: {exc}")
            continue
        cell = get(ctx, row, "cell")
        cells.add(cell)
        record = Record(row=line_no, kind="presence", t_raw=t, raw=raw, place=cell)
        record.add_id("subject", "phone", get(ctx, row, "msisdn"))
        record.add_id("device", "imei", get(ctx, row, "imei"))
        record.add_id("sim", "imsi", get(ctx, row, "imsi"))
        record.add_id("cell", "cell", cell)
        record.attrs = {
            "record_id": get(ctx, row, "record_id"),
            "dump": True,
            "subscriber": canonical_phone(get(ctx, row, "msisdn")) or "",
        }
        result.records.append(record)
    result.meta["dump_cells"] = sorted(cells)
    return result


def parse_kyc_subscriber(ctx: AdapterContext) -> ParseResult:
    result = ParseResult()
    for line_no, row, raw in read_rows(ctx):
        try:
            t = ctx.parse_time(get(ctx, row, "time"))
        except ValueError:
            t = None
        record = Record(row=line_no, kind="kyc", t_raw=t, raw=raw, sigma_t=86400.0)
        record.add_id("subject", "phone", get(ctx, row, "msisdn"))
        record.add_id("sim", "imsi", get(ctx, row, "imsi"))
        record.attrs = {
            "name": get(ctx, row, "name"),
            "address": get(ctx, row, "address"),
            "kyc": "subscriber",
            "document": get(ctx, row, "document"),
            "activated_on": get(ctx, row, "time"),
        }
        result.records.append(record)
    return result
