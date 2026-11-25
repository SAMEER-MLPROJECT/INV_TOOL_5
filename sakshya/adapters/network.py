from __future__ import annotations

import json

from sakshya.adapters.base import AdapterContext, ParseResult, Record, get, read_rows, to_float
from sakshya.core.timeutil import parse_local


def parse_net_conn(ctx: AdapterContext) -> ParseResult:
    result = ParseResult()
    for line_no, row, raw in read_rows(ctx):
        stamp = get(ctx, row, "time")
        value = to_float(stamp)
        try:
            t = value if value is not None else parse_local(stamp, ctx.time_format, ctx.tz)
        except ValueError as exc:
            result.warnings.append(f"row {line_no}: {exc}")
            continue
        record = Record(row=line_no, kind="net_flow", t_raw=t, raw=raw)
        record.add_id("device", "mac", get(ctx, row, "src_mac"))
        record.add_id("lan_ip", "ip", get(ctx, row, "src_ip"))
        record.add_id("dst", "ip", get(ctx, row, "dst_ip"))
        host = get(ctx, row, "dst_host")
        if host:
            record.add_id("dst_host", "domain", host)
        record.attrs = {
            "dst_port": int(to_float(get(ctx, row, "dst_port")) or 0),
            "bytes_out": int(to_float(get(ctx, row, "bytes_out")) or 0),
            "bytes_in": int(to_float(get(ctx, row, "bytes_in")) or 0),
            "dst_host": host,
        }
        result.records.append(record)
    return result


def parse_uniaethel(ctx: AdapterContext) -> ParseResult:
    result = ParseResult()
    payload = json.loads(ctx.path.read_text(encoding="utf-8"))
    for index, incident in enumerate(payload.get("incidents", []), start=1):
        window = incident.get("window") or {}
        start = window.get("start")
        end = window.get("end")
        t = parse_local(start, None, ctx.tz) if start else None
        t_end = parse_local(end, None, ctx.tz) if end else None
        record = Record(row=index, kind="net_incident", t_raw=t, raw=json.dumps(incident, sort_keys=True, ensure_ascii=False))
        record.add_id("host", "ip", incident.get("host", ""))
        destination = (incident.get("counterparty") or {}).get("top_destination", "")
        record.add_id("dst", "ip", destination)
        record.text = "; ".join(incident.get("reasons", []))
        record.attrs = {
            "label": incident.get("label", ""),
            "scores": incident.get("scores", {}),
            "trajectory": incident.get("trajectory", ""),
            "t_end": t_end,
            "tool": payload.get("tool", "UniAethel"),
            "incident_id": incident.get("id", f"INC-{index:03d}"),
        }
        result.records.append(record)
    return result
