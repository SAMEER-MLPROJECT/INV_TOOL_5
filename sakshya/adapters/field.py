from __future__ import annotations

from sakshya.adapters.base import AdapterContext, ParseResult, Record, get, read_rows, to_float


def parse_cctv_log(ctx: AdapterContext) -> ParseResult:
    result = ParseResult()
    default_atm = ctx.entry.get("atm_id", "")
    for line_no, row, raw in read_rows(ctx):
        try:
            t = ctx.parse_time(get(ctx, row, "time"))
        except ValueError as exc:
            result.warnings.append(f"row {line_no}: {exc}")
            continue
        atm = get(ctx, row, "atm") or default_atm
        record = Record(row=line_no, kind="cctv_event", t_raw=t, raw=raw, place=atm)
        record.add_id("atm", "atm", atm)
        if atm:
            record.anchors.append(f"atmcam:{atm}")
        record.attrs = {
            "camera": get(ctx, row, "camera"),
            "event": get(ctx, row, "event"),
            "frame_file": get(ctx, row, "frame_file"),
            "frame_sha256": get(ctx, row, "frame_sha256").lower(),
        }
        result.records.append(record)
    return result


def parse_seizure_memo(ctx: AdapterContext) -> ParseResult:
    result = ParseResult()
    for line_no, row, raw in read_rows(ctx):
        try:
            t = ctx.parse_time(get(ctx, row, "time"))
        except ValueError as exc:
            result.warnings.append(f"row {line_no}: {exc}")
            continue
        lat, lon = to_float(get(ctx, row, "lat")), to_float(get(ctx, row, "lon"))
        record = Record(
            row=line_no,
            kind="seizure",
            t_raw=t,
            raw=raw,
            lat=lat,
            lon=lon,
            radius_m=30.0 if lat is not None else None,
            place=get(ctx, row, "premises"),
        )
        record.add_id("item", "imei", get(ctx, row, "imei"))
        record.add_id("item", "phone", get(ctx, row, "msisdn"))
        record.add_id("item", "imsi", get(ctx, row, "imsi"))
        record.add_id("item", "mac", get(ctx, row, "mac"))
        record.add_id("item", "host", get(ctx, row, "hostname"))
        record.attrs = {
            "item_id": get(ctx, row, "item"),
            "item_type": get(ctx, row, "item_type"),
            "description": get(ctx, row, "description"),
            "premises": get(ctx, row, "premises"),
            "officer": get(ctx, row, "officer"),
        }
        result.records.append(record)
    return result


def parse_media(ctx: AdapterContext) -> ParseResult:
    return ParseResult()
